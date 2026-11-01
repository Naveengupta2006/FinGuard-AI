"""Anomaly detection: Isolation Forest + customer-level baseline.

Supervised model (fraud_v1) wahi pakadta hai jo usne pehle dekha hai.
Ye module "unusual" cheezein pakadta hai, bina labels ke use kiye.
Baseline (training period) sirf < TRAIN_END data se banta hai: leakage nahi.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import IsolationForest
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sqlalchemy import text

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(PROJECT_ROOT / "src" / "database"))
sys.path.append(str(PROJECT_ROOT / "src" / "ml"))
from connection import get_engine           # noqa: E402
from train import add_features, load_data   # noqa: E402

TRAIN_END = pd.Timestamp("2026-09-24")   # baseline: Aug 9 -> Sep 23
SPIKE_START = pd.Timestamp("2026-10-01")
THRESHOLD_QUANTILE = 0.99   # baseline ke top 1% scores = anomaly threshold

NUM = ["amount_log", "amount_z", "hour", "is_night", "is_international"]
CAT = ["merchant_category", "country", "channel", "device_type"]
RARE_SHARE = 0.03           # <3% baseline transactions = "rare" value


def build_customer_baseline(train: pd.DataFrame) -> pd.DataFrame:
    g = train.groupby("customer_id")["amount_log"].agg(["mean", "std", "count"])
    glob_mean, glob_std = train["amount_log"].mean(), train["amount_log"].std()
    g["std"] = g["std"].fillna(glob_std).clip(lower=0.3)
    small = g["count"] < 5   # kam history: global baseline use karo
    g.loc[small, "mean"] = glob_mean
    g.loc[small, "std"] = glob_std
    return g[["mean", "std"]].rename(columns={"mean": "cust_mean", "std": "cust_std"})


def add_baseline_features(df, baseline, glob_mean, glob_std):
    df = df.join(baseline, on="customer_id")
    df["cust_mean"] = df["cust_mean"].fillna(glob_mean)
    df["cust_std"] = df["cust_std"].fillna(glob_std)
    df["amount_z"] = ((df["amount_log"] - df["cust_mean"]) / df["cust_std"]).clip(-5, 8)
    return df


def build_reasons(df: pd.DataFrame, freq: dict) -> pd.Series:
    """Har anomaly ke liye evidence-based, human-readable reasons."""
    def reasons(row):
        out = []
        for col, label in [("country", "country"), ("merchant_category", "category"),
                           ("channel", "channel"), ("device_type", "device")]:
            share = freq[col].get(row[col], 0.0)
            if share < RARE_SHARE:
                out.append(f"rare {label} '{row[col]}' ({share*100:.1f}% of baseline txns)")
        if row["is_night"]:
            out.append(f"night-time ({int(row['hour']):02d}:00)")
        if row["amount_z"] > 3:
            ratio = np.exp(row["amount_log"] - row["cust_mean"])
            out.append(f"amount {ratio:.1f}x customer's typical")
        return "; ".join(out) if out else "unusual combination of features"
    return df.apply(reasons, axis=1)


def main():
    df = add_features(load_data())
    train = df[df["txn_timestamp"] < TRAIN_END].copy()
    score_df = df[df["txn_timestamp"] >= TRAIN_END].copy()

    baseline = build_customer_baseline(train)
    glob_mean, glob_std = train["amount_log"].mean(), train["amount_log"].std()
    train = add_baseline_features(train, baseline, glob_mean, glob_std)
    score_df = add_baseline_features(score_df, baseline, glob_mean, glob_std)

    pre = ColumnTransformer([
        ("num", StandardScaler(), NUM),
        ("cat", OneHotEncoder(handle_unknown="ignore"), CAT),
    ])
    pipe = Pipeline([("prep", pre),
                     ("iforest", IsolationForest(n_estimators=200, random_state=42, n_jobs=-1))])
    pipe.fit(train[NUM + CAT])   # labels use nahi hote (unsupervised)

    def anomaly_score(d):  # higher = more anomalous
        return -pipe.decision_function(d[NUM + CAT])

    threshold = float(np.quantile(anomaly_score(train), THRESHOLD_QUANTILE))
    score_df["anomaly_score"] = anomaly_score(score_df)
    score_df["is_anomaly"] = score_df["anomaly_score"] >= threshold
    print(f"Baseline: {len(train)} txns | threshold (p{int(THRESHOLD_QUANTILE*100)}) = {threshold:.4f}")

    # ---- Weekly comparison ----
    score_df["period"] = np.where(score_df["txn_timestamp"] >= SPIKE_START,
                                  "Oct 1-7", "Sep 24-30")
    summary = score_df.groupby("period").agg(
        txns=("is_anomaly", "size"), anomalies=("is_anomaly", "sum"),
        fraud=("is_fraud", "sum"))
    summary["anomaly_rate_pct"] = (summary["anomalies"] / summary["txns"] * 100).round(2)
    print("\n--- Anomaly rate by period ---")
    print(summary)

    flagged = score_df[score_df["is_anomaly"]].copy()
    prec = flagged["is_fraud"].mean() * 100
    rec = flagged["is_fraud"].sum() / score_df["is_fraud"].sum() * 100
    print(f"\nFlagged {len(flagged)} anomalies | fraud among flagged: {prec:.1f}% "
          f"| share of all fraud caught: {rec:.1f}%")
    print(f"(Baseline fraud rate in scored data: {score_df['is_fraud'].mean()*100:.2f}%)")

    # ---- Reasons ----
    freq = {c: train[c].value_counts(normalize=True).to_dict() for c in CAT}
    flagged["reason"] = build_reasons(flagged, freq)

    # ---- Save ----
    out = flagged[["transaction_id", "anomaly_score", "reason"]].copy()
    out["anomaly_score"] = out["anomaly_score"].round(4)
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE anomaly_events RESTART IDENTITY"))
    out.to_sql("anomaly_events", engine, if_exists="append", index=False,
               chunksize=1000, method="multi")
    print(f"\nSaved {len(out)} rows to anomaly_events")

    print("\n--- Top anomalies ---")
    top = flagged.sort_values("anomaly_score", ascending=False).head(5)
    for _, r in top.iterrows():
        print(f"{r['transaction_id']} score={r['anomaly_score']:.3f} fraud={r['is_fraud']} | {r['reason']}")


if __name__ == "__main__":
    main()