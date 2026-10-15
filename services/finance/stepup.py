"""Step-up authentication for sensitive financial actions (THREAT_MODEL F5).

Approving a financial action needs a *fresh* second factor on top of the normal session:
  * TOTP (RFC 6238: HMAC-SHA1, 30 s steps, 6 digits, ±1 step). Secrets are per user, Fernet-encrypted, and a code
    can be used once (replay protection by step counter). Enroll once with `enroll()`; the otpauth URI is shown once.
  * or a Supabase session at `aal2` whose MFA verification happened within the last 10 minutes.
Either yields a step-up token: HMAC-signed, bound to the user and to one purpose (the approval id), valid 5 minutes.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Connection

from services.core import db

from . import crypto

STEP = 30
DIGITS = 6
TOKEN_TTL = 300
AAL2_MAX_AGE = 600


class StepUpRequired(PermissionError):
    pass


def _hotp(secret_b32: str, counter: int) -> str:
    key = base64.b32decode(secret_b32 + "=" * (-len(secret_b32) % 8), casefold=True)
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    off = mac[-1] & 0x0F
    code = (struct.unpack(">I", mac[off:off + 4])[0] & 0x7FFFFFFF) % (10 ** DIGITS)
    return str(code).zfill(DIGITS)


def totp(secret_b32: str, at: float | None = None) -> str:
    return _hotp(secret_b32, int((at or time.time()) // STEP))


def enrolled(conn: Connection, user_id: str) -> bool:
    return conn.execute(select(db.stepup_secrets.c.user_id).where(db.stepup_secrets.c.user_id == user_id)).first() is not None


def enroll(conn: Connection, *, user_id: str, org_id: str, label: str = "AI Civilization") -> dict:
    """Creates the secret. Refused if one exists (re-enrolment goes through `reset` with a valid current code)."""
    if enrolled(conn, user_id):
        raise StepUpRequired("already enrolled")
    secret = base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")
    conn.execute(insert(db.stepup_secrets).values(user_id=user_id, organization_id=org_id, secret_ciphertext=crypto.encrypt(secret),
                                                  last_used_step=0))
    uri = f"otpauth://totp/{quote(label)}:owner?secret={secret}&issuer={quote(label)}&digits={DIGITS}&period={STEP}"
    return {"secret": secret, "otpauth_uri": uri}


def check_code(conn: Connection, user_id: str, code: str) -> None:
    row = conn.execute(select(db.stepup_secrets).where(db.stepup_secrets.c.user_id == user_id)).first()
    if row is None:
        raise StepUpRequired("enroll an authenticator first")
    code = (code or "").strip().replace(" ", "")
    if not (code.isdigit() and len(code) == DIGITS):
        raise StepUpRequired("enter the 6-digit code from your authenticator")
    secret = crypto.decrypt(row.secret_ciphertext)
    now_step = int(time.time() // STEP)
    for step in (now_step - 1, now_step, now_step + 1):
        if hmac.compare_digest(_hotp(secret, step), code):
            if step <= row.last_used_step:
                raise StepUpRequired("that code was already used; wait for the next one")
            conn.execute(update(db.stepup_secrets).where(db.stepup_secrets.c.user_id == user_id).values(last_used_step=step))
            return
    raise StepUpRequired("code did not match")


def aal2_fresh(claims: dict | None) -> bool:
    if not claims or claims.get("aal") != "aal2":
        return False
    now = time.time()
    return any(isinstance(a, dict) and a.get("method") in ("totp", "webauthn", "phone") and now - float(a.get("timestamp", 0)) <= AAL2_MAX_AGE
               for a in claims.get("amr") or [])


def _sign(body: str) -> str:
    key = hashlib.sha256(b"aiciv-stepup:" + crypto._key()).digest()
    return hmac.new(key, body.encode(), hashlib.sha256).hexdigest()


def issue_token(user_id: str, purpose: str, method: str) -> str:
    body = f"{user_id}|{purpose}|{int(time.time()) + TOKEN_TTL}|{method}|{secrets.token_hex(8)}"
    return base64.urlsafe_b64encode(f"{body}|{_sign(body)}".encode()).decode()


def check_token(token: str | None, *, user_id: str, purpose: str) -> str:
    """Returns the step-up method if the token is valid for this user and purpose; raises otherwise."""
    if not token:
        raise StepUpRequired("this action needs step-up verification")
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        uid, purp, exp, method, nonce, sig = raw.split("|")
    except Exception as exc:  # noqa: BLE001
        raise StepUpRequired("malformed step-up token") from exc
    if not hmac.compare_digest(sig, _sign(f"{uid}|{purp}|{exp}|{method}|{nonce}")):
        raise StepUpRequired("step-up token signature invalid")
    if uid != user_id:
        raise StepUpRequired("step-up token belongs to another user")
    if purp != purpose:
        raise StepUpRequired("step-up token was issued for a different action")
    if int(exp) < time.time():
        raise StepUpRequired("step-up token expired; verify again")
    return method
