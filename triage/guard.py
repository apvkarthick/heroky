"""Hard global rule: no commercial data leaves for Telegram.

Applied inside bot.tg() to EVERY outbound sendMessage, so no code path can
bypass it. Fail-closed: a match (or any guard error) blocks the whole message.
Built-in patterns are always on; config may only ADD `blocked_terms`.
"""
import re

CATEGORIES = {
    "money amount": re.compile(
        r"(?:[$€£₹¥]\s?\d|\b(?:USD|EUR|GBP|INR|AUD|CAD|Rs\.?|rupees?)\s?\d|"
        r"\b\d[\d,]*(?:\.\d+)?\s?(?:USD|EUR|GBP|INR|dollars?|euros?|rupees?|lakhs?|crores?|k\b|lac\b))",
        re.I),
    "commercial term": re.compile(
        r"\b(invoice[sd]?|quotation|quote[sd]?|pricing|price[sd]?|rate card|"
        r"contract (?:value|amount|terms)|revenue|margin|profit|budget|"
        r"salary|salaries|payroll|payment terms|payout|purchase order|PO number|"
        r"proposal value|deal size|retainer|GST|VAT|discount)\b", re.I),
    "secret": re.compile(
        r"(sk-[A-Za-z0-9_\-]{16,}|\b\d{8,10}:[A-Za-z0-9_\-]{30,}|"
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----|AKIA[0-9A-Z]{16}|"
        r"\b(?:api[_ -]?key|secret|password|token)\s*[:=]\s*\S+)", re.I),
    "contact detail": re.compile(
        r"([\w.+-]+@[\w-]+\.[\w.-]+|(?<!\d)\+?\d[\d \-()]{9,}\d)"),
}


def check(text, extra_terms=()):
    """Return None if clean, else the category name that matched."""
    for name, rx in CATEGORIES.items():
        if rx.search(text):
            return name
    low = text.lower()
    for term in extra_terms:
        if term and term.lower() in low:
            return "blocked term"
    return None


RULE_FOR_SESSIONS = (
    "HARD RULE (non-negotiable): your replies are posted to a Telegram group. Never include commercial "
    "data in any reply: prices, amounts, budgets, invoices, quotes, contract/deal terms, revenue, margins, "
    "salaries, client contact details, credentials or secrets. Report technical status only; if the answer "
    "needs such data, say 'details withheld - see local session' instead. A filter also blocks such replies."
)
