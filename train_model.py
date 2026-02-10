"""
ML Model Training Script

Train/retrain the token scoring model with real trade data.
Reads trade history from a CSV file and retrains the GradientBoosting model.

CSV format:
  is_not_honeypot,buy_tax,sell_tax,ownership_renounced,no_proxy,
  holder_count,top_holder_pct,not_mintable,liquidity_locked,
  liquidity_usd,token_age_seconds,price_impact_pct,profitable

Usage:
  python train_model.py --data trades.csv
  python train_model.py  (uses synthetic data)
"""

import argparse
import logging
import os
import sys

import numpy as np
import pandas as pd

from src.ml_model import TokenScorer, FEATURE_NAMES
from src.utils import setup_logging

logger = logging.getLogger("sniper.train")


def load_csv_data(path: str) -> tuple[np.ndarray, np.ndarray]:
    logger.info("Loading training data from %s", path)
    df = pd.read_csv(path)

    if "profitable" in df.columns:
        expected_cols = FEATURE_NAMES + ["profitable"]
        missing = [c for c in expected_cols if c not in df.columns]
        if missing:
            logger.error("Missing columns: %s", missing)
            sys.exit(1)
        X = df[FEATURE_NAMES].values
        y = df["profitable"].values.astype(float)
    elif "price_5m_pct" in df.columns:
        logger.info("Detected market_data.csv format — using real price data")
        return load_market_csv(df)
    else:
        logger.error("CSV has neither 'profitable' nor 'price_5m_pct' column")
        sys.exit(1)

    logger.info("Loaded %d samples (%d profitable, %d not)",
                len(y), int(y.sum()), int(len(y) - y.sum()))
    return X, y


def load_market_csv(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    price_col = "price_5m_pct"
    df_valid = df[df[price_col].notna() & (df[price_col] != "") & (df[price_col] != "dead")].copy()
    df_dead = df[df[price_col] == "dead"].copy()

    features_list = []
    labels = []

    for _, row in df_valid.iterrows():
        feat = _extract_features(row)
        if feat is not None:
            features_list.append(feat)
            pct = float(row[price_col])
            labels.append(1.0 if pct > 5.0 else 0.0)

    for _, row in df_dead.iterrows():
        feat = _extract_features(row)
        if feat is not None:
            features_list.append(feat)
            labels.append(0.0)

    if not features_list:
        logger.error("No valid training samples found in market CSV")
        sys.exit(1)

    X = np.array(features_list)
    y = np.array(labels)
    logger.info(
        "Loaded %d samples from market CSV (%d profitable, %d not)",
        len(y), int(y.sum()), int(len(y) - y.sum()),
    )
    return X, y


def _extract_features(row) -> list[float] | None:
    try:
        hp = row.get("is_honeypot", "")
        is_not_hp = 0.0 if str(hp) == "True" else 1.0
        buy_tax = float(row.get("buy_tax", 0) or 0)
        sell_tax = float(row.get("sell_tax", 0) or 0)
        renounced = 1.0 if str(row.get("ownership_renounced", "")) == "True" else 0.0
        no_proxy = 0.0 if str(row.get("is_proxy", "")) == "True" else 1.0
        holder_count = float(row.get("holder_count", 0) or 0)
        top_holder = float(row.get("top_holder_pct", 0) or 0)
        not_mintable = 0.0 if str(row.get("is_mintable", "")) == "True" else 1.0
        liq_locked = 0.0
        liq_usd = float(row.get("liquidity_usd", 0) or 0)
        token_age = float(row.get("token_age_seconds", 0) or 0)
        price_impact = float(row.get("price_impact_pct", 0) or 0)
        return [
            is_not_hp, buy_tax, sell_tax, renounced, no_proxy,
            holder_count, top_holder, not_mintable, liq_locked,
            liq_usd, token_age, price_impact,
        ]
    except (ValueError, TypeError):
        return None


def generate_synthetic_data(n_samples: int = 5000) -> tuple[np.ndarray, np.ndarray]:
    logger.info("Generating %d synthetic training samples", n_samples)
    np.random.seed(42)

    n_good = n_samples // 2
    n_bad = n_samples - n_good

    X_good = np.column_stack([
        np.ones(n_good),
        np.random.uniform(0, 8, n_good),
        np.random.uniform(0, 8, n_good),
        np.random.choice([0, 1], n_good, p=[0.3, 0.7]),
        np.ones(n_good),
        np.random.uniform(10, 500, n_good),
        np.random.uniform(5, 40, n_good),
        np.random.choice([0, 1], n_good, p=[0.2, 0.8]),
        np.random.choice([0, 1], n_good, p=[0.4, 0.6]),
        np.random.uniform(1500, 50000, n_good),
        np.random.uniform(60, 3600, n_good),
        np.random.uniform(0.1, 3, n_good),
    ])

    X_bad = np.column_stack([
        np.random.choice([0, 1], n_bad, p=[0.7, 0.3]),
        np.random.uniform(10, 90, n_bad),
        np.random.uniform(10, 99, n_bad),
        np.random.choice([0, 1], n_bad, p=[0.9, 0.1]),
        np.random.choice([0, 1], n_bad, p=[0.5, 0.5]),
        np.random.uniform(1, 50, n_bad),
        np.random.uniform(40, 99, n_bad),
        np.random.choice([0, 1], n_bad, p=[0.5, 0.5]),
        np.random.choice([0, 1], n_bad, p=[0.9, 0.1]),
        np.random.uniform(0, 2000, n_bad),
        np.random.uniform(0, 60, n_bad),
        np.random.uniform(5, 50, n_bad),
    ])

    X = np.vstack([X_good, X_bad])
    y = np.concatenate([np.ones(n_good), np.zeros(n_bad)])

    shuffle = np.random.permutation(len(X))
    return X[shuffle], y[shuffle]


def main():
    parser = argparse.ArgumentParser(description="Train ML model for token scoring")
    parser.add_argument("--data", type=str, default=None, help="CSV file with trade data")
    parser.add_argument("--market-data", type=str, default=None, help="market_data.csv with price columns")
    parser.add_argument("--samples", type=int, default=5000, help="Synthetic data samples")
    parser.add_argument("--fresh", action="store_true", help="Delete old model before training")
    args = parser.parse_args()

    setup_logging()

    if args.fresh:
        for p in ["models/sniper_model.pkl", "models/scaler.pkl"]:
            if os.path.exists(p):
                os.remove(p)
                logger.info("Deleted old model: %s", p)

    if args.market_data and os.path.exists(args.market_data):
        X, y = load_csv_data(args.market_data)
    elif args.data and os.path.exists(args.data):
        X, y = load_csv_data(args.data)
    else:
        X, y = generate_synthetic_data(args.samples)

    scorer = TokenScorer()
    scorer.load()
    scorer.retrain(X, y)

    importance = scorer.get_feature_importance()
    logger.info("Feature importance:")
    for name, imp in sorted(importance.items(), key=lambda x: x[1], reverse=True):
        logger.info("  %-25s %.4f", name, imp)

    logger.info("Model training complete!")


if __name__ == "__main__":
    main()
