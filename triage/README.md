# Telegram triage -> Claude Code sessions

Team posts in a Telegram group. The bot classifies each message into a **lane**
and forwards it to that lane's own persistent Claude Code session, then posts
the answer back in the thread.

```
Telegram group -> bot.py (long-poll) -> triage -> claude -p --resume <lane session> (cwd per lane)
                                          |
        1. "#bug ..." / "/infra ..."  (explicit override)
        2. Claude Haiku picks a lane   (needs ANTHROPIC_API_KEY)
        3. keyword scoring             (fallback)
        4. default_lane
```

## Setup (on the machine running Claude Code)

1. Create a bot with @BotFather, add it to the team group. In BotFather
   `/setprivacy` -> Disable so it sees group messages.
2. `cp routes.example.json routes.json` and edit: lanes, `cwd` per lane, and
   `allowed_chat_ids` (the group id, negative number; get it from
   `https://api.telegram.org/bot<TOKEN>/getUpdates`). The bot ignores everyone
   not on the allowlist, and refuses to start with an empty one.
3. `export TELEGRAM_BOT_TOKEN=...` and optionally `ANTHROPIC_API_KEY=...`
4. `python3 bot.py`  (needs `claude` CLI on PATH and logged in)
5. Tests: `python3 test_triage.py`

Chat commands: `/lanes` lists lanes; `#lane text` forces a lane.

## Notes

- Each lane keeps one session id in `state.json`, so context persists across
  messages; turns within a lane are serialized, lanes run in parallel.
- Sessions are driven headlessly via the CLI. They share Claude Code's
  transcript store (resume with `claude --resume <id>` from the lane's `cwd`),
  but may not appear as live tabs in the Desktop app UI.
- Headless runs can't answer permission prompts: set `permission_mode` and
  `allowed_tools` per lane (e.g. `plan` or read-only tools for risky lanes).
- This runs on your desktop, not Heroku (Heroku can't reach your local
  Claude). To use the existing Flask app instead, you'd need a queue between
  them; not built.
