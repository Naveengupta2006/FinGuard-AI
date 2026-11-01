"""Read-only database user banata hai (idempotent: dobara chalana safe hai).

Admin credentials (.env ke DB_USER/DB_PASSWORD) se chalta hai.
NOTE: load_data.py tables drop karta hai, jisse grants chale jaate hain.
      Isliye load_data.py ke baad ye script dobara chalao.
"""
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg import sql

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env", override=True)

# Agent ke tools sirf in tables ko padh sakte hain.
# audit_logs, agent_runs, investigations jaise tables ye user nahi dekh sakta.
READABLE_TABLES = ["customers", "transactions", "risk_predictions", "anomaly_events"]


def main():
    user = os.getenv("DB_READONLY_USER", "finguard_readonly")
    password = os.getenv("DB_READONLY_PASSWORD")
    db = os.getenv("DB_NAME")
    if not password:
        raise SystemExit("DB_READONLY_PASSWORD .env mein set karo (admin password se alag).")

    with psycopg.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=db,
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        autocommit=True,
    ) as conn:
        role = sql.Identifier(user)
        exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (user,)).fetchone()
        if exists:
            conn.execute(sql.SQL("ALTER ROLE {} LOGIN PASSWORD {}").format(role, sql.Literal(password)))
        else:
            conn.execute(sql.SQL(
                "CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE"
            ).format(role, sql.Literal(password)))

        # Extra guards (asli suraksha neeche wale limited GRANTs se aati hai)
        conn.execute(sql.SQL("ALTER ROLE {} SET default_transaction_read_only = on").format(role))
        conn.execute(sql.SQL("ALTER ROLE {} SET statement_timeout = '10s'").format(role))

        conn.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(db), role))
        conn.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
        conn.execute(sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {}").format(role))
        for table in READABLE_TABLES:
            conn.execute(sql.SQL("GRANT SELECT ON TABLE {} TO {}").format(sql.Identifier(table), role))

    print(f"Read-only user '{user}' ready. SELECT allowed on: {', '.join(READABLE_TABLES)}")


if __name__ == "__main__":
    main()