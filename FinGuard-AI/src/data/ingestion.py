from pathlib import Path

import pandas as pd

from validation import validate_transactions, validate_customers

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = PROJECT_ROOT / "data" / "raw"


def _load(filename: str) -> pd.DataFrame:
    path = RAW_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    return pd.read_csv(path)


def load_transactions() -> pd.DataFrame:
    df = _load("transactions.csv")
    print("Transactions validation:", validate_transactions(df))
    return df


def load_customers() -> pd.DataFrame:
    df = _load("customers.csv")
    print("Customers validation:", validate_customers(df))
    return df


if __name__ == "__main__":
    txn = load_transactions()
    cust = load_customers()

    print("\nTransactions shape:", txn.shape)
    print("Customers shape:", cust.shape)
    print("\nColumns:", txn.columns.tolist())
    print("\nDuplicate rows:", int(txn.duplicated().sum()))
    print("\nFraud distribution:")
    print(txn["is_fraud"].value_counts())
    print("\nFraud percentage:", round(txn["is_fraud"].mean() * 100, 2), "%")
    print("\nDate range:", txn["timestamp"].min(), "->", txn["timestamp"].max())
    