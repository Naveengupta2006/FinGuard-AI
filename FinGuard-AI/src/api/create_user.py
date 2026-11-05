"""API user banao: python src/api/create_user.py analyst1 --role analyst"""
import argparse
import getpass
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for sub in ("api", "database"):
    sys.path.append(str(ROOT / "src" / sub))

from connection import get_engine   # noqa: E402
from users import upsert_user       # noqa: E402

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("username")
    p.add_argument("--role", choices=["viewer", "analyst", "admin"], default="analyst")
    a = p.parse_args()
    pw = getpass.getpass("Password (min 10 chars): ")
    if pw != getpass.getpass("Repeat password: "):
        raise SystemExit("Passwords do not match")
    upsert_user(get_engine(), a.username, pw, a.role)
    print(f"User '{a.username}' saved with role '{a.role}'.")