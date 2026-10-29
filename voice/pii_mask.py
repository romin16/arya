import re

EMAIL = re.compile(r"[\w.!#$%&'*+/=?^`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE = re.compile(r"(?<!\w)(?:\+?\d[\d ().-]{7,}\d)(?!\w)")


def mask_for_tts(text: str) -> str:
    text = EMAIL.sub("their email address", text)
    def phone(m):
        digits = re.sub(r"\D", "", m.group(0))
        return f"the number ending in {digits[-2:]}" if len(digits) >= 8 else m.group(0)
    return PHONE.sub(phone, text)
