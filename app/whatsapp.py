"""Click-to-chat links for a personal WhatsApp account.

No automation of personal WhatsApp: tools that drive a personal account
(whatsapp-web.js, Baileys, ...) break WhatsApp's terms and risk a ban.
Instead the admin taps a wa.me link, which opens WhatsApp with the message
already written, and presses Send. The app records that the link was opened.
"""
import re
from urllib.parse import quote


def normalize_phone(raw: str) -> str:
    """Return digits only, international format without '+' or leading 00."""
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("00"):
        digits = digits[2:]
    return digits


def message_text(trainee_name: str, module_titles: list[str], link: str, due: str | None) -> str:
    lines = [f"Hello {trainee_name},", "",
             "You have been assigned the following training:"]
    lines += [f"• {t}" for t in module_titles]
    lines += ["", "Watch each short video in your language, then complete the quiz and acknowledgment:", link]
    if due:
        lines += ["", f"Please complete by {due}."]
    lines += ["", "This link is personal to you. Do not forward it."]
    return "\n".join(lines)


def wa_link(phone: str, text: str) -> str:
    return f"https://wa.me/{normalize_phone(phone)}?text={quote(text)}"
