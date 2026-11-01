import pandas as pd

TXN_REQUIRED = [
    "transaction_id", "customer_id", "timestamp", "amount",
    "merchant", "merchant_category", "country", "is_fraud",
]
CUSTOMER_REQUIRED = ["customer_id", "age_group", "home_country", "account_status"]


def _check_columns(df: pd.DataFrame, required: list, name: str):
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"{name}: missing columns {missing}")
    if df.empty:
        raise ValueError(f"{name}: dataset is empty")


def validate_transactions(df: pd.DataFrame) -> dict:
    _check_columns(df, TXN_REQUIRED, "transactions")

    if df["transaction_id"].duplicated().any():
        raise ValueError("Duplicate transaction_id found")
    if df["is_fraud"].isna().any():
        raise ValueError("Missing fraud labels")
    if not set(df["is_fraud"].unique()).issubset({0, 1}):
        raise ValueError("Invalid fraud labels (only 0/1 allowed)")
    if (df["amount"] < 0).any():
        raise ValueError("Negative transaction amount")
    if pd.to_datetime(df["timestamp"], errors="coerce").isna().any():
        raise ValueError("Invalid timestamp values")

    return {
        "status": "valid",
        "rows": len(df),
        "columns": len(df.columns),
        "missing_values": int(df.isna().sum().sum()),
    }


def validate_customers(df: pd.DataFrame) -> dict:
    _check_columns(df, CUSTOMER_REQUIRED, "customers")

    if df["customer_id"].duplicated().any():
        raise ValueError("Duplicate customer_id found")

    return {"status": "valid", "rows": len(df), "columns": len(df.columns)}