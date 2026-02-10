import logging
import os
from typing import Optional

import numpy as np
import joblib
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler

from src.safety import SafetyReport

logger = logging.getLogger("sniper.ml")

FEATURE_NAMES = [
    "is_not_honeypot",
    "buy_tax",
    "sell_tax",
    "ownership_renounced",
    "no_proxy",
    "holder_count",
    "top_holder_pct",
    "not_mintable",
    "liquidity_locked",
    "liquidity_usd",
    "token_age_seconds",
    "price_impact_pct",
]

MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "models", "sniper_model.pkl")
SCALER_PATH = os.path.join(os.path.dirname(__file__), "..", "models", "scaler.pkl")


class TokenScorer:
    def __init__(self):
        self.model: Optional[GradientBoostingClassifier] = None
        self.scaler: Optional[StandardScaler] = None
        self._loaded = False

    def load(self) -> bool:
        try:
            if os.path.exists(MODEL_PATH) and os.path.exists(SCALER_PATH):
                self.model = joblib.load(MODEL_PATH)
                self.scaler = joblib.load(SCALER_PATH)
                self._loaded = True
                logger.info("ML model loaded from disk")
                return True
        except Exception as e:
            logger.warning("Failed to load ML model: %s", e)

        self._init_default_model()
        return True

    def _init_default_model(self):
        logger.info("Initializing ML model with synthetic training data")
        np.random.seed(42)
        n_samples = 2000

        X_safe = np.column_stack([
            np.ones(n_samples // 2),
            np.random.uniform(0, 8, n_samples // 2),
            np.random.uniform(0, 8, n_samples // 2),
            np.random.choice([0, 1], n_samples // 2, p=[0.3, 0.7]),
            np.ones(n_samples // 2),
            np.random.uniform(10, 500, n_samples // 2),
            np.random.uniform(5, 40, n_samples // 2),
            np.random.choice([0, 1], n_samples // 2, p=[0.2, 0.8]),
            np.random.choice([0, 1], n_samples // 2, p=[0.4, 0.6]),
            np.random.uniform(1500, 50000, n_samples // 2),
            np.random.uniform(60, 3600, n_samples // 2),
            np.random.uniform(0.1, 3, n_samples // 2),
        ])
        y_safe = np.ones(n_samples // 2)

        X_scam = np.column_stack([
            np.random.choice([0, 1], n_samples // 2, p=[0.7, 0.3]),
            np.random.uniform(10, 90, n_samples // 2),
            np.random.uniform(10, 99, n_samples // 2),
            np.random.choice([0, 1], n_samples // 2, p=[0.9, 0.1]),
            np.random.choice([0, 1], n_samples // 2, p=[0.5, 0.5]),
            np.random.uniform(1, 50, n_samples // 2),
            np.random.uniform(40, 99, n_samples // 2),
            np.random.choice([0, 1], n_samples // 2, p=[0.5, 0.5]),
            np.random.choice([0, 1], n_samples // 2, p=[0.9, 0.1]),
            np.random.uniform(0, 2000, n_samples // 2),
            np.random.uniform(0, 60, n_samples // 2),
            np.random.uniform(5, 50, n_samples // 2),
        ])
        y_scam = np.zeros(n_samples // 2)

        X = np.vstack([X_safe, X_scam])
        y = np.concatenate([y_safe, y_scam])

        shuffle_idx = np.random.permutation(len(X))
        X = X[shuffle_idx]
        y = y[shuffle_idx]

        self.scaler = StandardScaler()
        X_scaled = self.scaler.fit_transform(X)

        self.model = GradientBoostingClassifier(
            n_estimators=200,
            max_depth=5,
            learning_rate=0.1,
            subsample=0.8,
            random_state=42,
        )
        self.model.fit(X_scaled, y)
        self._loaded = True

        self._save_model()
        logger.info("ML model trained on synthetic data (accuracy on train: %.3f)",
                     self.model.score(X_scaled, y))

    def _save_model(self):
        try:
            os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
            joblib.dump(self.model, MODEL_PATH)
            joblib.dump(self.scaler, SCALER_PATH)
            logger.info("ML model saved to disk")
        except Exception as e:
            logger.warning("Failed to save ML model: %s", e)

    def predict(
        self,
        safety: SafetyReport,
        liquidity_usd: float,
        token_age_seconds: float,
        price_impact_pct: float,
    ) -> tuple[float, bool, list[float]]:
        if not self._loaded:
            self.load()

        features = safety.to_features() + [
            liquidity_usd,
            token_age_seconds,
            price_impact_pct,
        ]

        X = np.array([features])
        X_scaled = self.scaler.transform(X)

        proba = self.model.predict_proba(X_scaled)[0][1]
        is_good = proba >= 0.5

        logger.info(
            "ML Score: %.3f | Prediction: %s | Features: %s",
            proba,
            "BUY" if is_good else "SKIP",
            dict(zip(FEATURE_NAMES, features)),
        )

        return proba, is_good, features

    def retrain(self, X: np.ndarray, y: np.ndarray) -> float:
        if len(X) < 10:
            logger.warning("Not enough data to retrain (%d samples)", len(X))
            return 0.0

        logger.info("Retraining ML model with %d real trade samples", len(X))
        wins = int(y.sum())
        losses = len(y) - wins
        logger.info("Training data: %d wins, %d losses", wins, losses)

        unique_classes = np.unique(y)
        if len(unique_classes) < 2:
            logger.warning(
                "Only one class in training data (class=%d). "
                "Adding minimal synthetic counter-examples.",
                int(unique_classes[0]),
            )
            n_synthetic = max(5, len(X) // 10)
            if unique_classes[0] == 0:
                X_syn = np.column_stack([
                    np.ones(n_synthetic),
                    np.random.uniform(0, 3, n_synthetic),
                    np.random.uniform(0, 3, n_synthetic),
                    np.ones(n_synthetic),
                    np.ones(n_synthetic),
                    np.random.uniform(50, 500, n_synthetic),
                    np.random.uniform(1, 15, n_synthetic),
                    np.ones(n_synthetic),
                    np.ones(n_synthetic),
                    np.random.uniform(5000, 100000, n_synthetic),
                    np.random.uniform(60, 600, n_synthetic),
                    np.random.uniform(0.1, 2, n_synthetic),
                ])
                y_syn = np.ones(n_synthetic)
            else:
                X_syn = np.column_stack([
                    np.zeros(n_synthetic),
                    np.random.uniform(20, 90, n_synthetic),
                    np.random.uniform(20, 99, n_synthetic),
                    np.zeros(n_synthetic),
                    np.zeros(n_synthetic),
                    np.random.uniform(0, 5, n_synthetic),
                    np.random.uniform(60, 99, n_synthetic),
                    np.zeros(n_synthetic),
                    np.zeros(n_synthetic),
                    np.random.uniform(0, 500, n_synthetic),
                    np.random.uniform(0, 30, n_synthetic),
                    np.random.uniform(10, 80, n_synthetic),
                ])
                y_syn = np.zeros(n_synthetic)
            X = np.vstack([X, X_syn])
            y = np.concatenate([y, y_syn])
            logger.info(
                "Added %d synthetic counter-examples. Total: %d samples",
                n_synthetic, len(X),
            )

        X_scaled = self.scaler.fit_transform(X)
        self.model.fit(X_scaled, y)
        accuracy = self.model.score(X_scaled, y)
        self._save_model()
        logger.info("Model retrained on REAL data (accuracy: %.3f)", accuracy)
        return accuracy

    def get_feature_importance(self) -> dict[str, float]:
        if self.model is None:
            return {}
        importances = self.model.feature_importances_
        return dict(zip(FEATURE_NAMES, importances))
