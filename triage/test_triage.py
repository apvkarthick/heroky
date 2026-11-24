import os
import unittest

os.environ.pop("ANTHROPIC_API_KEY", None)
import bot

CFG = bot.load_config(os.path.join(os.path.dirname(__file__), "routes.example.json"))


class TriageTests(unittest.TestCase):
    def test_explicit_hash_and_slash(self):
        self.assertEqual(bot.triage("#infra restart it", CFG)[:2], (["infra"], "restart it"))
        self.assertEqual(bot.triage("/bug@mybot login 500", CFG)[:2], (["bug"], "login 500"))

    def test_unknown_prefix_not_forced(self):
        self.assertEqual(bot.triage("#nope hello", CFG)[2], "keywords")

    def test_keywords(self):
        self.assertEqual(bot.triage("app crash with a traceback", CFG)[0], ["bug"])
        self.assertEqual(bot.triage("heroku deploy is down", CFG)[0], ["infra"])

    def test_default(self):
        self.assertEqual(bot.triage("what's our release date?", CFG)[0], ["general"])




class GuardTests(unittest.TestCase):
    def test_blocks(self):
        import guard
        for t in ["total is $5,000", "Rs. 40000 pending", "send the invoice", "mail me a@b.com",
                  "call +91 98765 43210", "api_key=abc123", "sk-ant-abcdefghijklmnop1234"]:
            self.assertIsNotNone(guard.check(t), t)
        self.assertEqual(guard.check("Acme deal", ["acme"]), "blocked term")

    def test_allows_technical(self):
        import guard
        self.assertIsNone(guard.check("Fixed null check in app.py; 4 tests pass, deployed to staging"))

    def test_tg_chokepoint(self):
        import guard
        sent = []
        orig = bot.urllib.request.urlopen
        class R:
            def __enter__(s): return s
            def __exit__(s,*a): pass
            def read(s): return b'{"ok":true,"result":{}}'
        def fake(req, timeout=0):
            sent.append(req.data.decode()); return R()
        bot.urllib.request.urlopen = fake
        try:
            bot.tg("T", "sendMessage", chat_id=1, text="invoice total $900")
            bot.tg("T", "sendMessage", chat_id=1, text="build green")
        finally:
            bot.urllib.request.urlopen = orig
        self.assertNotIn("900", sent[0]); self.assertIn("Withheld", sent[0])
        self.assertIn("build green", sent[1])


if __name__ == "__main__":
    unittest.main()
