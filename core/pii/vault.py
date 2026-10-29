"""Local reversible PII tokenisation. Secrets are supplied only by environment."""
from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass
from typing import Callable

try:
    import phonenumbers
except ImportError:  # Dependency is required in the supported runtime.
    phonenumbers = None

EMAIL_RE = re.compile(r"(?<![\w.+-])[\w.!#$%&'*+/=?^`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+")
PHONE_CANDIDATE_RE = re.compile(r"(?<!\w)(?:\+?\d[\d ().-]{7,}\d)(?!\w)")
TOKEN_RE = re.compile(r"\[(EMAIL|PHONE)_([0-9a-f]{6,64})\]")


@dataclass
class PIIVault:
    hmac_secret: bytes
    fernet_key: bytes
    default_region: str = "IN"
    persist: Callable[[str, str, bytes], None] | None = None
    lookup: Callable[[str], tuple[str, bytes] | None] | None = None

    def __post_init__(self) -> None:
        from cryptography.fernet import Fernet
        self._fernet = Fernet(self.fernet_key)
        self._values: dict[str, tuple[str, bytes]] = {}

    @classmethod
    def from_env(cls) -> "PIIVault":
        import os
        secret = os.environ.get("PII_HMAC_SECRET", "").encode()
        key = os.environ.get("PII_FERNET_KEY", "").encode()
        if not secret or not key:
            raise RuntimeError("PII_HMAC_SECRET and PII_FERNET_KEY are required")
        return cls(secret, key)

    def _normalise_phone(self, value: str) -> str | None:
        if phonenumbers is None:
            return None
        try:
            number = phonenumbers.parse(value, self.default_region)
            if phonenumbers.is_valid_number(number):
                return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)
        except phonenumbers.NumberParseException:
            pass
        return None

    def _store(self, kind: str, normal: str) -> str:
        digest = hmac.new(self.hmac_secret, normal.encode(), hashlib.sha256).hexdigest()
        length = 6
        while True:
            token = f"[{kind}_{digest[:length]}]"
            existing = self._values.get(token)
            if existing is None and self.lookup:
                existing = self.lookup(token)
            if existing is None or self._fernet.decrypt(existing[1]).decode() == normal:
                break
            length += 2
            if length > 64:
                raise RuntimeError("HMAC collision could not be resolved")
        if token not in self._values and (not self.lookup or not self.lookup(token)):
            encrypted = self._fernet.encrypt(normal.encode())
            self._values[token] = (kind.lower(), encrypted)
            if self.persist:
                self.persist(token, kind.lower(), encrypted)
        return token

    def tokenise(self, text: str) -> str:
        def email_sub(m: re.Match[str]) -> str:
            return self._store("EMAIL", m.group(0).lower())
        text = EMAIL_RE.sub(email_sub, text)
        def phone_sub(m: re.Match[str]) -> str:
            normal = self._normalise_phone(m.group(0))
            return self._store("PHONE", normal) if normal else m.group(0)
        return PHONE_CANDIDATE_RE.sub(phone_sub, text)

    def detokenise(self, text: str) -> str:
        def replace(m: re.Match[str]) -> str:
            token = m.group(0)
            item = self._values.get(token) or (self.lookup(token) if self.lookup else None)
            if not item:
                return token
            return self._fernet.decrypt(item[1]).decode()
        return TOKEN_RE.sub(replace, text)

    def detokenise_args(self, value):
        if isinstance(value, str):
            def replace(m: re.Match[str]) -> str:
                token=m.group(0)
                item=self._values.get(token) or (self.lookup(token) if self.lookup else None)
                if not item:
                    raise ValueError("unknown token")
                return self._fernet.decrypt(item[1]).decode()
            return TOKEN_RE.sub(replace, value)
        if isinstance(value, list):
            return [self.detokenise_args(v) for v in value]
        if isinstance(value, dict):
            return {k:self.detokenise_args(v) for k,v in value.items()}
        return value


class StreamingDetokenizer:
    """Buffers possible token fragments, including tokens split over SSE chunks."""
    def __init__(self, vault: PIIVault):
        self.vault = vault
        self.pending = ""

    def feed(self, chunk: str, final: bool = False) -> str:
        data = self.pending + chunk
        self.pending = ""
        if not final:
            start = data.rfind("[")
            if start >= 0 and "]" not in data[start:] and len(data) - start <= 72:
                self.pending = data[start:]
                data = data[:start]
        out = self.vault.detokenise(data)
        if final and self.pending:
            out += self.vault.detokenise(self.pending)
            self.pending = ""
        return out
