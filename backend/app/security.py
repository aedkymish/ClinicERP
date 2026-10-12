"""Password hashing (Argon2id) and JWT helpers — AUTH-01, AUTH-04."""
import secrets
import string
from datetime import timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from .config import get_settings
from .db import utcnow

_hasher = PasswordHasher()  # argon2-cffi defaults to Argon2id
ALGORITHM = "HS256"
MIN_PASSWORD = 8


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def one_time_password() -> str:
    """Random 12-character password handed out by Admin; must be changed at first sign-in (AUTH-02)."""
    alphabet = string.ascii_letters + string.digits
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(12))
        if any(c.isdigit() for c in pw) and any(c.isalpha() for c in pw):
            return pw


def password_problem(password: str) -> str | None:
    if len(password) < MIN_PASSWORD:
        return f"Password must be at least {MIN_PASSWORD} characters"
    return None


def make_token(user_id: int, session_id: int, kind: str) -> str:
    s = get_settings()
    ttl = timedelta(minutes=s.access_minutes) if kind == "access" else timedelta(hours=s.refresh_hours)
    now = utcnow()
    payload = {"sub": str(user_id), "sid": session_id, "typ": kind, "iat": now, "exp": now + ttl}
    return jwt.encode(payload, s.secret_key, algorithm=ALGORITHM)


def decode_token(token: str, kind: str) -> dict | None:
    try:
        data = jwt.decode(token, get_settings().secret_key, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    return data if data.get("typ") == kind else None
