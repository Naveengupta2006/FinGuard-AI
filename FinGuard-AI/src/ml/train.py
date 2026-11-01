import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (average_precision_score, confusion_matrix,
                             f1_score, precision_score, recall_score,
                             roc_auc_score)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(PROJECT_ROOT / "src" / "database"))
from connection import get_engine  # noqa: E402

MODEL_DIR = PROJECT_ROOT / "models"
MODEL_DIR.mkdir(exist_ok=True)

# Time-based split (random split mat karna: future ka data leak ho jata hai)
TRAIN_END = pd.Timestamp("2026-09-24")   # train: Aug 9 -> Sep 23
VALID_END = pd.Timestamp("2026-10-01")   # valid: Sep 24 -> Sep 30
                                         # test : Oct 1 -> Oct 7

NUM_FEATURES = ["amount_log", "hour", "is_night", "is_international"]
CAT_FEATURES = ["merchant_category", "country", "channel", "device_type"]
TARGET = "is_fraud"
MODEL_VERSION = "fraud_v1"


def load_data() -> pd.DataFrame:
    df = pd.read_sql("SELECT * FROM transactions", get_engine())
    df["txn_timestamp"] = pd.to_datetime(df["txn_timestamp"])
    df["amount"] = df["amount"].astype(float)
    return df.sort_values("txn_timestamp").reset_index(drop=True)


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["amount_log"] = np.log1p(df["amount"])
    df["hour"] = df["txn_timestamp"].dt.hour
    df["is_night"] = df["hour"].isin([23, 0, 1, 2, 3, 4]).astype(int)
    return df


def split(df: pd.DataFrame):
    t = df["txn_timestamp"]
    return (df[t < TRAIN_END],
            df[(t >= TRAIN_END) & (t < VALID_END)],
            df[t >= VALID_END])


def build_pipeline(model) -> Pipeline:
    pre = ColumnTransformer([
        ("num", StandardScaler(), NUM_FEATURES),
        ("cat", OneHotEncoder(handle_unknown="ignore"), CAT_FEATURES),
    ])
    return Pipeline([("prep", pre), ("model", model)])


def evaluate(pipe, X, y, threshold=0.5) -> dict:
    proba = pipe.predict_proba(X)[:, 1]
    pred = (proba >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y, pred, labels=[0, 1]).ravel()

    # Alert budget: analyst sirf top 2% risky transactions review kar sakta hai
    k = max(1, int(len(y) * 0.02))
    top_idx = np.argsort(proba)[::-1][:k]
    y_arr = np.asarray(y)
    top_hits = int(y_arr[top_idx].sum())
    return {
        "rows": int(len(y)), "fraud": int(y.sum()),
        "precision": round(precision_score(y, pred, zero_division=0), 4),
        "recall": round(recall_score(y, pred, zero_division=0), 4),
        "f1": round(f1_score(y, pred, zero_division=0), 4),
        "precision_top2pct": round(top_hits / k, 4),
        "recall_top2pct": round(top_hits / max(1, int(y_arr.sum())), 4),
        "pr_auc": round(average_precision_score(y, proba), 4),
        "roc_auc": round(roc_auc_score(y, proba), 4),
        "confusion_matrix": {"tn": int(tn), "fp": int(fp),
                             "fn": int(fn), "tp": int(tp)},
    }


def main():
    df = add_features(load_data())
    train, valid, test = split(df)
    feats = NUM_FEATURES + CAT_FEATURES
    print(f"Train {len(train)} | Valid {len(valid)} | Test {len(test)}")
    print(f"Fraud %  train={train[TARGET].mean()*100:.2f}  "
          f"valid={valid[TARGET].mean()*100:.2f}  "
          f"test={test[TARGET].mean()*100:.2f}")

    models = {
        "logistic_regression": LogisticRegression(
            max_iter=1000, class_weight="balanced"),
        "random_forest": RandomForestClassifier(
            n_estimators=200, min_samples_leaf=5, n_jobs=-1,
            class_weight="balanced_subsample", random_state=42),
    }

    results, fitted = {}, {}
    for name, model in models.items():
        pipe = build_pipeline(model).fit(train[feats], train[TARGET])
        fitted[name] = pipe
        results[name] = {
            "valid": evaluate(pipe, valid[feats], valid[TARGET]),
            "test": evaluate(pipe, test[feats], test[TARGET]),
        }

    for name, res in results.items():
        for part in ["valid", "test"]:
            r = res[part]
            print(f"\n[{name}] {part}: P={r['precision']} R={r['recall']} "
                  f"F1={r['f1']} PR-AUC={r['pr_auc']} ROC-AUC={r['roc_auc']}")
            print(f"   top-2% alerts: precision={r['precision_top2pct']} "
                  f"recall={r['recall_top2pct']}")
            print("   confusion:", r["confusion_matrix"])

    best = max(results, key=lambda n: results[n]["valid"]["pr_auc"])
    print(f"\nBest model (by validation PR-AUC): {best}")

    joblib.dump({"pipeline": fitted[best], "features": feats,
                 "model_version": MODEL_VERSION, "model_name": best},
                MODEL_DIR / f"{MODEL_VERSION}.joblib")
    (MODEL_DIR / f"metrics_{MODEL_VERSION}.json").write_text(
        json.dumps({"best_model": best, "results": results}, indent=2))
    print("Saved:", MODEL_DIR / f"{MODEL_VERSION}.joblib")


if __name__ == "__main__":
    main()