"""Telegram -> triage -> Claude Code session router (stdlib only).

Runs on the machine where Claude Code is installed. Long-polls Telegram (no
inbound port needed), classifies each team message into a lane, and sends it
to that lane's Claude Code session via `claude -p --resume`.
"""
import json
import os
import subprocess
import sys
import threading
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).parent
CONFIG_PATH = Path(os.environ.get("TRIAGE_CONFIG", HERE / "routes.json"))
STATE_PATH = Path(os.environ.get("TRIAGE_STATE", HERE / "state.json"))
TG = "https://api.telegram.org/bot{}/{}"
TRIAGE_MODEL = os.environ.get("TRIAGE_MODEL", "claude-haiku-5-5")

_state_lock = threading.Lock()
_lane_locks = {}


# ---------- config / state ----------
def load_config(path=CONFIG_PATH):
    cfg = json.loads(Path(path).read_text())
    if cfg["default_lane"] not in cfg["lanes"]:
        raise ValueError("default_lane must be one of the lanes")
    return cfg


def load_state():
    try:
        return json.loads(STATE_PATH.read_text())
    except (FileNotFoundError, ValueError):
        return {"offset": 0, "sessions": {}}


def save_state(state):
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(STATE_PATH)


# ---------- triage ----------
def explicit_lane(text, cfg):
    """`#bug ...` or `/bug ...` forces a lane."""
    first = text.split(None, 1)[0] if text.strip() else ""
    if first[:1] in "#/":
        name = first[1:].split("@")[0].lower()
        if name in cfg["lanes"]:
            return name, text[len(first):].strip()
    return None, text


def keyword_lane(text, cfg):
    low = text.lower()
    scores = {n: sum(k.lower() in low for k in l.get("keywords", [])) for n, l in cfg["lanes"].items()}
    best = max(scores, key=scores.get)
    return best if scores[best] else cfg["default_lane"]


def llm_lane(text, cfg):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    lanes = "\n".join(f"- {n}: {l['description']}" for n, l in cfg["lanes"].items())
    body = {
        "model": TRIAGE_MODEL,
        "max_tokens": 20,
        "system": "You triage team messages. Reply with exactly one lane name from the list, nothing else.\n" + lanes,
        "messages": [{"role": "user", "content": text[:4000]}],
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", json.dumps(body).encode(),
        {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            out = json.load(r)["content"][0]["text"].strip().lower()
    except Exception as e:  # network/API failure -> fall back to keywords
        print("llm triage failed:", e, file=sys.stderr)
        return None
    return out if out in cfg["lanes"] else None


def triage(text, cfg):
    """Returns (lane, cleaned_text, method)."""
    lane, rest = explicit_lane(text, cfg)
    if lane:
        return lane, rest, "explicit"
    lane = llm_lane(text, cfg)
    if lane:
        return lane, text, "llm"
    return keyword_lane(text, cfg), text, "keywords"


# ---------- dispatch to Claude Code ----------
def run_claude(lane, lane_cfg, prompt, state):
    lock = _lane_locks.setdefault(lane, threading.Lock())
    with lock:  # one turn at a time per session
        with _state_lock:
            sid = state["sessions"].get(lane)
        cmd = ["claude", "-p", prompt, "--output-format", "json",
               "--permission-mode", lane_cfg.get("permission_mode", "acceptEdits")]
        if sid:
            cmd += ["--resume", sid]
        else:
            sid = str(uuid.uuid4())
            cmd += ["--session-id", sid]
        if lane_cfg.get("allowed_tools"):
            cmd += ["--allowedTools", ",".join(lane_cfg["allowed_tools"])]
        if lane_cfg.get("system"):
            cmd += ["--append-system-prompt", lane_cfg["system"]]
        proc = subprocess.run(cmd, cwd=os.path.expanduser(lane_cfg["cwd"]),
                              capture_output=True, text=True,
                              timeout=lane_cfg.get("timeout", 900))
        if proc.returncode != 0:
            return f"claude exited {proc.returncode}: {proc.stderr.strip()[-500:]}"
        try:
            data = json.loads(proc.stdout)
        except ValueError:
            return proc.stdout.strip()[-3500:]
        with _state_lock:
            state["sessions"][lane] = data.get("session_id", sid)
            save_state(state)
        return data.get("result") or "(no output)"


# ---------- telegram ----------
def tg(token, method, **params):
    req = urllib.request.Request(TG.format(token, method), json.dumps(params).encode(),
                                 {"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=params.get("timeout", 10) + 10) as r:
        return json.load(r)["result"]


def reply(token, chat_id, msg_id, text):
    for i in range(0, max(len(text), 1), 4000):
        tg(token, "sendMessage", chat_id=chat_id, text=text[i:i + 4000],
           reply_to_message_id=msg_id)


def handle(token, cfg, state, msg):
    chat_id, user_id = msg["chat"]["id"], msg.get("from", {}).get("id")
    text = msg.get("text") or msg.get("caption") or ""
    allowed = cfg.get("allowed_chat_ids", [])
    if not text or (chat_id not in allowed and user_id not in cfg.get("allowed_user_ids", [])):
        return  # fail closed: ignore strangers silently
    if text.strip() in ("/lanes", "/start"):
        reply(token, chat_id, msg["message_id"], "Lanes:\n" + "\n".join(
            f"#{n} - {l['description']}" for n, l in cfg["lanes"].items()))
        return
    who = msg.get("from", {}).get("first_name", "team")
    lane, body, how = triage(text, cfg)
    reply(token, chat_id, msg["message_id"], f"-> {lane} ({how}). Working on it...")
    prompt = f"[Telegram message from {who}]\n{body}"
    try:
        out = run_claude(lane, cfg["lanes"][lane], prompt, state)
    except Exception as e:
        out = f"dispatch failed: {e}"
    reply(token, chat_id, msg["message_id"], f"[{lane}] {out}")


def main():
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    cfg, state = load_config(), load_state()
    if not cfg.get("allowed_chat_ids") and not cfg.get("allowed_user_ids"):
        sys.exit("Set allowed_chat_ids or allowed_user_ids in routes.json (bot ignores everyone otherwise).")
    pool = ThreadPoolExecutor(max_workers=8)
    print("triage bot running; lanes:", ", ".join(cfg["lanes"]))
    while True:
        try:
            updates = tg(token, "getUpdates", offset=state["offset"], timeout=50)
        except Exception as e:
            print("poll error:", e, file=sys.stderr)
            threading.Event().wait(5)
            continue
        for u in updates:
            with _state_lock:
                state["offset"] = u["update_id"] + 1
                save_state(state)
            if "message" in u:
                pool.submit(handle, token, cfg, state, u["message"])


if __name__ == "__main__":
    main()
