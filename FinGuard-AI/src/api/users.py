"""app_users table (API login ke liye). schema.sql ke bahar hai, isliye load_data.py ise delete nahi karta."""
import re

from sqlalchemy import text

from security import ROLES, hash_password

USERNAME_RE = re.compile(r"[A-Za-z0-9_.-]{3,50}")


def ensure_users_table(engine):
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS app_users (
                username      VARCHAR(50) PRIMARY KEY,
                password_hash TEXT NOT NULL,
                role          VARCHAR(10) NOT NULL CHECK (role IN ('viewer','analyst','admin')),
                is_active     BOOLEAN NOT NULL DEFAULT TRUE,
                created_at    TIMESTAMP DEFAULT NOW()
            )"""))


def upsert_user(engine, username: str, password: str, role: str):
    if not USERNAME_RE.fullmatch(username):
        raise ValueError("username must be 3-50 chars: letters, digits, _ . -")
    if role not in ROLES:
        raise ValueError(f"role must be one of {sorted(ROLES)}")
    if len(password) < 10:
        raise ValueError("password must be at least 10 characters")
    ensure_users_table(engine)
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO app_users (username, password_hash, role) VALUES (:u, :h, :r)
            ON CONFLICT (username) DO UPDATE SET password_hash = :h, role = :r, is_active = TRUE"""),
            {"u": username, "h": hash_password(password), "r": role})


def get_user(engine, username: str):
    with engine.connect() as conn:
        row = conn.execute(text("SELECT username, password_hash, role, is_active FROM app_users "
                                "WHERE username = :u"), {"u": username}).mappings().first()
    return dict(row) if row else None