import argparse
import sys
from pathlib import Path

import joblib
import pandas as pd
from sqlalchemy import text

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(PROJECT_ROOT / "src" / "database"))
sys.path.append(str(PROJECT_ROOT / "src" / "ml"))

from connection import get_engine           # noqa: E402
from train import add_features, load_data   # noqa: E402

MODEL_PATH = PROJECT_ROOT / "models" / "fraud_v1.joblib"

# Thresholds validation/test data dekhkar chune gaye:
#   >=0.90 -> ~4% transactions, ~68% fraud
#   0.70-0.90 -> ~9% transactions, ~6% fraud
HIGH_THRESHOLD = 0.90
MEDIUM_THRESHOLD = 0.70


def risk_band(score: float) -> str:
    if score >= HIGH_THRESHOLD:
        return "HIGH"
    if score >= MEDIUM_THRESHOLD:
        return "MEDIUM"
    return "LOW"


def score_transactions(df: pd.DataFrame, artifact: dict) -> pd.DataFrame:
    """df: add_features() ke baad ka dataframe. Returns risk_predictions rows."""
    proba = artifact["pipeline"].predict_proba(df[artifact["features"]])[:, 1]
    out = pd.DataFrame({
        "transaction_id": df["transaction_id"].values,
        "fraud_probability": proba.round(4),
    })
    out["risk_band"] = out["fraud_probability"].map(risk_band)
    out["model_version"] = artifact["model_version"]
    return out


def main(from_date: str):
    artifact = joblib.load(MODEL_PATH)
    df = add_features(load_data())

    # Sirf out-of-sample transactions score karo (training data par score
    # optimistic hota hai). Default: validation period ke baad se.
    df = df[df["txn_timestamp"] >= pd.Timestamp(from_date)]
    preds = score_transactions(df, artifact)

    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE risk_predictions RESTART IDENTITY"))
    preds.to_sql("risk_predictions", engine, if_exists="append",
                 index=False, chunksize=2000, method="multi")

    print(f"Scored {len(preds)} transactions from {from_date} "
          f"(model {artifact['model_version']})")
    check = pd.read_sql(
        """SELECT p.risk_band,
                  COUNT(*) AS txns,
                  SUM(t.is_fraud) AS fraud,
                  ROUND(100.0 * SUM(t.is_fraud) / COUNT(*), 1) AS fraud_pct
           FROM risk_predictions p
           JOIN transactions t USING (transaction_id)
           GROUP BY p.risk_band ORDER BY fraud_pct DESC""", engine)
    print(check.to_string(index=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-date", default="2026-09-24")
    main(parser.parse_args().from_date)