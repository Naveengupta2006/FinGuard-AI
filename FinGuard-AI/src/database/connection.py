import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import URL

# Project root = FinGuard-AI/ (is file se do level upar)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = PROJECT_ROOT / ".env"
load_dotenv(ENV_PATH, override=True)

REQUIRED = ["DB_USER", "DB_PASSWORD", "DB_NAME"]


def get_engine():
    missing = [k for k in REQUIRED if not os.getenv(k)]
    if missing:
        raise ValueError(
            f"Missing in .env: {missing}\n"
            f"Looked for .env at: {ENV_PATH} (exists: {ENV_PATH.exists()})"
        )
    # URL.create password ke special characters (@ # / etc.) sahi handle karta hai
    url = URL.create(
        "postgresql+psycopg",
        username=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        database=os.getenv("DB_NAME"),
    )
    return create_engine(url)


def get_readonly_engine():
    user = os.getenv("DB_READONLY_USER", "finguard_readonly")
    password = os.getenv("DB_READONLY_PASSWORD")
    if not password:
        raise ValueError(
            f"Missing DB_READONLY_PASSWORD in .env\n"
            f"Looked for .env at: {ENV_PATH} (exists: {ENV_PATH.exists()})"
        )
    url = URL.create(
        "postgresql+psycopg",
        username=user,
        password=password,
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        database=os.getenv("DB_NAME"),
    )
    return create_engine(url)
