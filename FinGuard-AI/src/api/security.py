"""Password hashing (scrypt), JWT (HS256), role-based access, login throttling."""
import base64
import hashlib
import hmac
import os
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

ROLES = {"viewer": 1, "analyst": 2, "admin": 3}
ALGORITHM = "HS256"
ISSUER = "finguard-ai"
TOKEN_MINUTES = 60
_N, _R, _P = 2 ** 14, 8, 1

_bearer = HTTPBearer(auto_error=False, description="Login se mila JWT token")


# ---------------- passwords ----------------
def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${_b64(salt)}${_b64(dk)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, dk = stored.split("$")
        calc = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt),
                              n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(calc, base64.b64decode(dk))
    except Exception:  # noqa: BLE001
        return False


# Unknown user par bhi same time lage (user enumeration timing attack se bachao)
DUMMY_HASH = hash_password("dummy-password-for-timing")


# ---------------- JWT ----------------
def _secret() -> str:
    secret = os.getenv("JWT_SECRET", "")
    if len(secret) < 32:
        raise RuntimeError("JWT_SECRET must be set in .env and be at least 32 characters long")
    return secret


def create_token(username: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": username, "role": role, "iss": ISSUER, "iat": now,
                       "exp": now + timedelta(minutes=TOKEN_MINUTES)}, _secret(), algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        data = jwt.decode(token, _secret(), algorithms=[ALGORITHM], issuer=ISSUER,
                          options={"require": ["exp", "sub", "role", "iss"]})
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid or expired token", headers={"WWW-Authenticate": "Bearer"})
    if data["role"] not in ROLES:
        raise HTTPException(401, "Invalid or expired token", headers={"WWW-Authenticate": "Bearer"})
    return data


# ---------------- dependencies ----------------
def current_user(creds: HTTPAuthorizationCredentials = Depends(_bearer)) -> dict:
    if creds is None:
        raise HTTPException(401, "Not authenticated", headers={"WWW-Authenticate": "Bearer"})
    data = decode_token(creds.credentials)
    return {"username": data["sub"], "role": data["role"]}


def require_role(minimum: str):
    def dep(user: dict = Depends(current_user)) -> dict:
        if ROLES[user["role"]] < ROLES[minimum]:
            raise HTTPException(403, f"Requires role '{minimum}' or higher")
        return user
    return dep


# ---------------- login throttling (in-memory, per process) ----------------
class LoginThrottle:
    def __init__(self, max_failures: int = 5, window_seconds: int = 600):
        self.max, self.window = max_failures, window_seconds
        self._fails = defaultdict(deque)

    def _prune(self, key):
        q, cutoff = self._fails[key], time.time() - self.window
        while q and q[0] < cutoff:
            q.popleft()

    def check(self, key: str):
        self._prune(key)
        if len(self._fails[key]) >= self.max:
            raise HTTPException(429, "Too many failed login attempts. Try again later.")

    def fail(self, key: str):
        self._fails[key].append(time.time())

    def success(self, key: str):
        self._fails.pop(key, None)