"""Hash de contraseñas (Argon2id), sesiones JWT, tokens de nodo y limitador de login."""

from __future__ import annotations

import hashlib
import secrets
import string
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from .config import Settings

_ph = PasswordHasher()
_DUMMY_HASH = _ph.hash("snackdrop-dummy-password-for-timing")

MIN_PASSWORD_LENGTH = 10
JWT_ALG = "HS256"


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def dummy_verify(password: str) -> None:
    """Gasta el mismo tiempo que una verificación real para no revelar si el usuario existe."""
    verify_password(_DUMMY_HASH, password)


def password_problem(password: str, username: str = "") -> str | None:
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"La contraseña debe tener al menos {MIN_PASSWORD_LENGTH} caracteres."
    if len(password) > 256:
        return "La contraseña es demasiado larga."
    if username and username.lower() in password.lower():
        return "La contraseña no puede contener el nombre de usuario."
    classes = sum(
        [
            any(c.islower() for c in password),
            any(c.isupper() for c in password),
            any(c.isdigit() for c in password),
            any(not c.isalnum() for c in password),
        ]
    )
    if classes < 3:
        return "Usa al menos tres de: minúsculas, mayúsculas, números y símbolos."
    return None


def generate_password(length: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits
    while True:
        pwd = "".join(secrets.choice(alphabet) for _ in range(length))
        if password_problem(pwd) is None:
            return pwd


def create_session_token(user_id: int, token_version: int, settings: Settings) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "ver": token_version,
        "typ": "session",
        "iat": now,
        "exp": now + timedelta(minutes=settings.session_ttl_minutes),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=JWT_ALG)


def decode_session_token(token: str, settings: Settings) -> dict | None:
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[JWT_ALG],
            options={"require": ["exp", "sub", "ver", "typ"]},
        )
    except jwt.PyJWTError:
        return None
    if payload.get("typ") != "session":
        return None
    return payload


def generate_node_token() -> str:
    return "sdn_" + secrets.token_urlsafe(32)


def hash_node_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class LoginLimiter:
    """Bloqueo temporal tras demasiados intentos fallidos (por usuario y por IP)."""

    def __init__(self, max_per_user: int = 5, max_per_ip: int = 20, window_seconds: int = 900):
        self.max_per_user = max_per_user
        self.max_per_ip = max_per_ip
        self.window = window_seconds
        self._fails: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        q = self._fails.setdefault(key, deque())
        while q and now - q[0] > self.window:
            q.popleft()
        return q

    def is_blocked(self, username: str, ip: str) -> bool:
        now = time.monotonic()
        with self._lock:
            return (
                len(self._prune(f"u:{username.lower()}", now)) >= self.max_per_user
                or len(self._prune(f"i:{ip}", now)) >= self.max_per_ip
            )

    def record_failure(self, username: str, ip: str) -> None:
        now = time.monotonic()
        with self._lock:
            self._prune(f"u:{username.lower()}", now).append(now)
            self._prune(f"i:{ip}", now).append(now)

    def reset(self, username: str) -> None:
        with self._lock:
            self._fails.pop(f"u:{username.lower()}", None)
