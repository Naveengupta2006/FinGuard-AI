import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # charts save karo, window mat kholo
import matplotlib.pyplot as plt
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(PROJECT_ROOT / "src" / "database"))
from connection import get_engine  # noqa: E402

OUT_DIR = PROJECT_ROOT / "docs" / "eda"
OUT_DIR.mkdir(parents=True, exist_ok=True)
SPIKE_START = pd.Timestamp("2026-10-01")


def load() -> pd.DataFrame:
    df = pd.read_sql("SELECT * FROM transactions", get_engine())
    df["txn_timestamp"] = pd.to_datetime(df["txn_timestamp"])
    df["amount"] = df["amount"].astype(float)
    df["date"] = df["txn_timestamp"].dt.date
    df["hour"] = df["txn_timestamp"].dt.hour
    df["period"] = (df["txn_timestamp"] >= SPIKE_START).map(
        {True: "Oct 1-7", False: "Before Oct 1"})
    return df


def fraud_rate_by(df, col):
    g = df.groupby(col)["is_fraud"].agg(["count", "sum", "mean"])
    g.columns = ["txns", "fraud", "fraud_rate_pct"]
    g["fraud_rate_pct"] = (g["fraud_rate_pct"] * 100).round(2)
    return g.sort_values("fraud_rate_pct", ascending=False)


def save(fig, name):
    fig.tight_layout()
    fig.savefig(OUT_DIR / name, dpi=120)
    plt.close(fig)


def main():
    df = load()
    print("Rows:", len(df), "| Overall fraud rate:",
          round(df.is_fraud.mean() * 100, 2), "%")

    print("\n--- Before vs Oct 1-7 ---")
    print(fraud_rate_by(df, "period"))

    for col in ["merchant_category", "country", "channel", "device_type"]:
        print(f"\n--- Fraud rate by {col} ---")
        print(fraud_rate_by(df, col).head(6))

    print("\n--- Amount (median) fraud vs genuine ---")
    print(df.groupby("is_fraud")["amount"].median().round(2))

    # Chart 1: daily fraud rate
    daily = df.groupby("date")["is_fraud"].mean() * 100
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(daily.index, daily.values, marker="o", markersize=3)
    ax.axvline(SPIKE_START.date(), color="red", linestyle="--", label="Oct 1")
    ax.set_title("Daily fraud rate (%)")
    ax.set_ylabel("Fraud rate %")
    ax.legend()
    save(fig, "01_daily_fraud_rate.png")

    # Chart 2: fraud rate by category, before vs spike
    cat = (df.groupby(["merchant_category", "period"])["is_fraud"]
             .mean().unstack() * 100).sort_values("Oct 1-7", ascending=False)
    fig, ax = plt.subplots(figsize=(10, 4))
    cat.plot(kind="bar", ax=ax)
    ax.set_title("Fraud rate % by merchant category")
    ax.set_ylabel("Fraud rate %")
    save(fig, "02_category_before_vs_spike.png")

    # Chart 3: fraud by hour
    hr = df.groupby("hour")["is_fraud"].sum()
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.bar(hr.index, hr.values)
    ax.set_title("Fraud transactions by hour of day")
    ax.set_xlabel("Hour")
    save(fig, "03_fraud_by_hour.png")

    # Chart 4: amount distribution
    fig, ax = plt.subplots(figsize=(10, 4))
    for label, grp in df.groupby("is_fraud"):
        ax.hist(grp["amount"].clip(upper=df["amount"].quantile(0.99)),
                bins=50, alpha=0.6, density=True,
                label="Fraud" if label else "Genuine")
    ax.set_title("Amount distribution (top 1% clipped)")
    ax.legend()
    save(fig, "04_amount_distribution.png")

    print("\nCharts saved in:", OUT_DIR)


if __name__ == "__main__":
    main()