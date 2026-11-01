import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import text

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(PROJECT_ROOT / "src" / "data"))
sys.path.append(str(PROJECT_ROOT / "src" / "database"))

from connection import get_engine          # noqa: E402
from ingestion import load_transactions, load_customers  # noqa: E402


def main():
    engine = get_engine()

    # 1. Create tables
    schema = (PROJECT_ROOT / "src" / "database" / "schema.sql").read_text()
    with engine.begin() as conn:
        conn.execute(text(schema))
    print("Schema created.")

    # 2. Load validated data (customers first: foreign key)
    customers = load_customers()
    txn = load_transactions().rename(columns={"timestamp": "txn_timestamp"})
    txn["txn_timestamp"] = pd.to_datetime(txn["txn_timestamp"])

    customers.to_sql("customers", engine, if_exists="append", index=False)
    txn.to_sql("transactions", engine, if_exists="append", index=False,
               chunksize=2000, method="multi")

    # 3. Verify
    with engine.connect() as conn:
        for table in ["customers", "transactions"]:
            n = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
            print(f"{table}: {n} rows")
        f = conn.execute(text("SELECT SUM(is_fraud) FROM transactions")).scalar()
        print("fraud rows:", f)


if __name__ == "__main__":
    main()