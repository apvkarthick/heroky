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
import time
import urllib.request
import uuid
import guard
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).parent
CONFIG_PATH = Path(os.environ.get("TRIAGE_CONFIG", HERE / "routes.json"))
STATE_PATH = Path(os.environ.get("TRIAGE_STATE", HERE / "state.json"))
TG = "https://api.telegram.org/bot{}/{}"
TRIAGE_MODEL = os.environ.get("TRIAGE_MODEL", "claude-haiku-5-5")

_state_lock = threading.Lock()
_lane_locks = {}
STATUS = {}  # lane -> {"busy": bool, "since": ts, "last_ok": ts}


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
        "max_tokens": 40,
        "system": ("You are the orchestrator triaging team messages. Reply with the lane name that should "
                   "handle it. Only if the message clearly contains separate tasks for different lanes, "
                   "reply with up to 3 lane names separated by commas. Nothing else.\n" + lanes),
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
    picked = []
    for name in (p.strip(" #/.") for p in out.split(",")):
        if name in cfg["lanes"] and name not in picked:
            picked.append(name)
    return picked[:3] or None


def triage(text, cfg):
    """Returns ([lanes], cleaned_text, method)."""
    lane, rest = explicit_lane(text, cfg)
    if lane:
        return [lane], rest, "explicit"
    lanes = llm_lane(text, cfg)
    if lanes:
        return lanes, text, "llm"
    return [keyword_lane(text, cfg)], text, "keywords"


# ---------- dispatch to Claude Code ----------
def run_claude(lane, lane_cfg, prompt, state):
    lock = _lane_locks.setdefault(lane, threading.Lock())
    with lock:  # one turn at a time per session
        STATUS[lane] = {**STATUS.get(lane, {}), "busy": True, "since": time.time()}
        try:
            return _run_claude_locked(lane, lane_cfg, prompt, state)
        finally:
            STATUS[lane]["busy"] = False
            STATUS[lane]["last_ok"] = time.time()


def _run_claude_locked(lane, lane_cfg, prompt, state):
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
    cmd += ["--append-system-prompt",
            (lane_cfg.get("system", "") + "\n\n" + guard.RULE_FOR_SESSIONS).strip()]
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
WITHHELD_DIR = HERE / "withheld"
BLOCKED_TERMS = []  # set from config in main()


def tg(token, method, **params):
    if method in ("sendMessage", "sendDocument", "sendPhoto", "editMessageText"):
        # Single chokepoint: hard global rule, fail-closed, not configurable off.
        try:
            hit = guard.check(str(params.get("text") or params.get("caption") or ""), BLOCKED_TERMS)
            if method in ("sendDocument", "sendPhoto"):
                hit = hit or "attachments not allowed"
        except Exception:
            hit = "guard error"
        if hit:
            WITHHELD_DIR.mkdir(exist_ok=True)
            (WITHHELD_DIR / f"{int(time.time())}.txt").write_text(str(params.get("text", "")))
            print(f"BLOCKED outbound telegram message ({hit})", file=sys.stderr)
            if method != "sendMessage":
                return {}
            params = {**params, "text": f"Withheld: reply contained {hit}. Commercial data is never sent to "
                                        "Telegram. Read the full answer in the local session."}
        req = urllib.request.Request(TG.format(token, method), json.dumps(params).encode(),
                                 {"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=params.get("timeout", 10) + 10) as r:
        return json.load(r)["result"]


def reply(token, chat_id, msg_id, text):
    for i in range(0, max(len(text), 1), 4000):
        tg(token, "sendMessage", chat_id=chat_id, text=text[i:i + 4000],
           reply_to_message_id=msg_id)


def handle(token, cfg, state, msg, pool):
    try:
        _handle(token, cfg, state, msg, pool)
    except Exception as e:  # never let a worker thread die silently
        print("handler error:", e, file=sys.stderr)


def _handle(token, cfg, state, msg, pool):
    chat_id, user_id = msg["chat"]["id"], msg.get("from", {}).get("id")
    text = (msg.get("text") or msg.get("caption") or "").strip()
    if not text:
        return
    cmd = text.split()[0].split("@")[0]
    if cmd == "/id":  # open to anyone: lets you find the id to allowlist
        reply(token, chat_id, msg["message_id"], f"chat_id: {chat_id}\nuser_id: {user_id}")
        return
    if chat_id not in cfg.get("allowed_chat_ids", []) and user_id not in cfg.get("allowed_user_ids", []):
        print(f"ignored message from chat {chat_id} user {user_id} (not allowlisted)", file=sys.stderr)
        return
    if cmd in ("/lanes", "/start"):
        reply(token, chat_id, msg["message_id"], "Lanes:\n" + "\n".join(
            f"#{n} - {l['description']}" for n, l in cfg["lanes"].items()))
        return
    if cmd == "/status":
        now = time.time()
        rows = []
        for n in cfg["lanes"]:
            st = STATUS.get(n, {})
            sid = state["sessions"].get(n, "no session yet")
            busy = f"busy {int(now - st['since'])}s" if st.get("busy") else "idle"
            rows.append(f"{n}: {busy} | session {sid[:8]}")
        reply(token, chat_id, msg["message_id"], "\n".join(rows))
        return
    who = msg.get("from", {}).get("first_name", "team")
    lanes, body, how = triage(text, cfg)
    reply(token, chat_id, msg["message_id"], f"-> {', '.join(lanes)} ({how}). Working on it...")
    tg(token, "sendChatAction", chat_id=chat_id, action="typing")

    def work(lane):
        prompt = f"[Telegram message from {who}]\n{body}"
        if len(lanes) > 1:
            prompt += f"\n\n(Orchestrator: this message was split across lanes {lanes}; handle only the part that belongs to '{lane}'.)"
        try:
            out = run_claude(lane, cfg["lanes"][lane], prompt, state)
        except Exception as e:
            out = f"dispatch failed: {e}"
        reply(token, chat_id, msg["message_id"], f"[{lane}] {out}")

    for lane in lanes:  # fan out; per-lane locks keep each session serial
        pool.submit(work, lane)


def preflight(token, cfg):
    me = tg(token, "getMe")
    print(f"connected as @{me['username']}")
    hook = tg(token, "getWebhookInfo")
    if hook.get("url"):
        print("webhook was set, removing so polling works:", hook["url"])
        tg(token, "deleteWebhook")
    if not me.get("can_read_all_group_messages"):
        print("WARNING: privacy mode ON - bot only sees /commands in groups. "
              "BotFather -> /setprivacy -> Disable, then re-add bot to the group.")
    print("allowed_chat_ids:", cfg.get("allowed_chat_ids"), "allowed_user_ids:", cfg.get("allowed_user_ids"))
    for n, l in cfg["lanes"].items():
        if not os.path.isdir(os.path.expanduser(l["cwd"])):
            print(f"WARNING: lane '{n}' cwd missing: {l['cwd']}")
    if subprocess.run(["which", "claude"], capture_output=True).returncode:
        print("WARNING: `claude` CLI not found on PATH")


def main():
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    cfg, state = load_config(), load_state()
    BLOCKED_TERMS[:] = cfg.get("blocked_terms", [])
    if not cfg.get("allowed_chat_ids") and not cfg.get("allowed_user_ids"):
        sys.exit("Set allowed_chat_ids or allowed_user_ids in routes.json (bot ignores everyone otherwise).")
    pool = ThreadPoolExecutor(max_workers=16)
    preflight(token, cfg)
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
                pool.submit(handle, token, cfg, state, u["message"], pool)


if __name__ == "__main__":
    main()
