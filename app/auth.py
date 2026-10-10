"""One password unlocks editing; a signed cookie remembers it for 30 days.

The cookie holds only an expiry and an HMAC over it. The signing key comes
from SESSION_SECRET, or from the password itself when that's unset, so
changing the password also logs every device out.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time

from . import config

COOKIE = "md_session"
MAX_AGE = 30 * 24 * 3600


def _key() -> bytes | None:
    secret = config.session_secret()
    if secret:
        return hashlib.sha256(b"md-session:" + secret.encode()).digest()
    password = config.dashboard_password()
    if password:
        return hashlib.sha256(b"md-session-pw:" + password.encode()).digest()
    return None


def _sign(payload: str, key: bytes) -> str:
    mac = hmac.new(key, payload.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode().rstrip("=")


def editing_enabled() -> bool:
    return config.dashboard_password() is not None


def check_password(attempt: str) -> bool:
    password = config.dashboard_password()
    if not password:
        return False
    return hmac.compare_digest(attempt.encode(), password.encode())


def make_token(now: float | None = None) -> str:
    key = _key()
    if key is None:
        raise RuntimeError("editing is not configured")
    payload = f"v1.{int((now or time.time()) + MAX_AGE)}"
    return f"{payload}.{_sign(payload, key)}"


def valid_token(token: str | None, now: float | None = None) -> bool:
    key = _key()
    if not token or key is None:
        return False
    try:
        version, expires, sig = token.split(".")
        expires_at = int(expires)
    except ValueError:
        return False
    if version != "v1" or expires_at < (now or time.time()):
        return False
    return hmac.compare_digest(sig, _sign(f"{version}.{expires}", key))
