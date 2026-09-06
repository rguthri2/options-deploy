"""Single-admin authentication: PBKDF2 password hashing + HMAC-signed
session cookies.

Deliberately dependency-light (stdlib `hashlib`/`hmac` only, no bcrypt/JWT
library) so it can't be broken by the same kind of dependency-resolution
surprises seen deploying this app's other pieces. There is exactly one
account, configured via ADMIN_USERNAME/ADMIN_PASSWORD_HASH env vars -- see
scripts/create_admin.py to generate the hash.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from typing import Optional

from fastapi import Cookie, HTTPException, Response

from .config import get_settings

_PBKDF2_ITERATIONS = 600_000
_ALGO = "pbkdf2_sha256"
SESSION_COOKIE_NAME = "session"


def hash_password(password: str, *, salt: Optional[bytes] = None) -> str:
    salt = salt or secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"{_ALGO}${_PBKDF2_ITERATIONS}${salt.hex()}${derived.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algo, iterations_str, salt_hex, hash_hex = stored_hash.split("$")
        if algo != _ALGO:
            return False
        iterations = int(iterations_str)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except (ValueError, AttributeError):
        return False
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(derived, expected)


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def create_session_token(username: str, *, secret_key: str, max_age_seconds: int) -> str:
    expires_at = int(time.time()) + max_age_seconds
    payload = f"{username}:{expires_at}".encode("utf-8")
    signature = hmac.new(secret_key.encode("utf-8"), payload, hashlib.sha256).digest()
    return f"{_b64url_encode(payload)}.{_b64url_encode(signature)}"


def verify_session_token(token: str, *, secret_key: str) -> Optional[str]:
    """Return the username if `token` is a valid, unexpired session token."""
    try:
        payload_b64, signature_b64 = token.split(".")
        payload = _b64url_decode(payload_b64)
        signature = _b64url_decode(signature_b64)
    except Exception:  # noqa: BLE001 - any malformed token is just "invalid"
        return None

    expected_signature = hmac.new(secret_key.encode("utf-8"), payload, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected_signature):
        return None

    try:
        username, expires_at_str = payload.decode("utf-8").split(":")
        expires_at = int(expires_at_str)
    except (ValueError, UnicodeDecodeError):
        return None

    if time.time() > expires_at:
        return None
    return username


def set_session_cookie(response: Response, username: str) -> None:
    settings = get_settings()
    token = create_session_token(
        username, secret_key=settings.secret_key, max_age_seconds=settings.session_max_age_seconds
    )
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=settings.session_max_age_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE_NAME)


def require_auth(session: Optional[str] = Cookie(default=None)) -> str:
    """FastAPI dependency: returns the logged-in username, or raises 401."""
    settings = get_settings()
    if not settings.secret_key or not settings.admin_username or not settings.admin_password_hash:
        raise HTTPException(
            status_code=503,
            detail=(
                "Auth is not configured. Set SECRET_KEY, ADMIN_USERNAME, and ADMIN_PASSWORD_HASH "
                "(see scripts/create_admin.py) before this app can be used."
            ),
        )
    if session is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    username = verify_session_token(session, secret_key=settings.secret_key)
    if username is None:
        raise HTTPException(status_code=401, detail="Session expired or invalid")
    return username
