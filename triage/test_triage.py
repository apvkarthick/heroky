import os
import unittest

os.environ.pop("ANTHROPIC_API_KEY", None)
import bot

CFG = bot.load_config(os.path.join(os.path.dirname(__file__), "routes.example.json"))


class TriageTests(unittest.TestCase):
    def test_explicit_hash_and_slash(self):
        self.assertEqual(bot.triage("#infra restart it", CFG)[:2], ("infra", "restart it"))
        self.assertEqual(bot.triage("/bug@mybot login 500", CFG)[:2], ("bug", "login 500"))

    def test_unknown_prefix_not_forced(self):
        self.assertEqual(bot.triage("#nope hello", CFG)[2], "keywords")

    def test_keywords(self):
        self.assertEqual(bot.triage("app crash with a traceback", CFG)[0], "bug")
        self.assertEqual(bot.triage("heroku deploy is down", CFG)[0], "infra")

    def test_default(self):
        self.assertEqual(bot.triage("what's our release date?", CFG)[0], "general")


if __name__ == "__main__":
    unittest.main()
