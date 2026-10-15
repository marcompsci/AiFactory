"""Encryption at rest for financial secrets, and keyed hashing for account identifiers (THREAT_MODEL F11).

Key: AICIV_FINANCE_KEY (a Fernet key: 32 url-safe base64 bytes; generate with
`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`).
In dev mode only, a key is generated once into <data dir>/finance.key (mode 0600). With an API token or Supabase
auth configured, a missing AICIV_FINANCE_KEY is an error: secrets are never stored under a throwaway key.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import threading

from cryptography.fernet import Fernet, InvalidToken

from services.core.config import get_settings


class FinanceKeyMissing(RuntimeError):
    pass


_lock = threading.Lock()


def _key() -> bytes:
    env = os.environ.get("AICIV_FINANCE_KEY", "").strip()
    if env:
        return env.encode()
    s = get_settings()
    if not s.dev_auth:
        raise FinanceKeyMissing("AICIV_FINANCE_KEY must be set outside dev mode")
    path = s.data_dir / "finance.key"
    with _lock:
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as fh:
                fh.write(Fernet.generate_key())
        return path.read_bytes().strip()


def encrypt(plaintext: str) -> str:
    return Fernet(_key()).encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    try:
        return Fernet(_key()).decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise FinanceKeyMissing("could not decrypt: wrong AICIV_FINANCE_KEY or tampered ciphertext") from exc


def ref_hmac(value: str) -> str:
    """Stable, keyed fingerprint of an account/payee identifier: lets us match without storing the number."""
    return hmac.new(_key(), b"aiciv-ref:" + value.encode(), hashlib.sha256).hexdigest()


def mask(value: str) -> str:
    digits = "".join(c for c in value if c.isalnum())
    return digits[-4:] if digits else ""
