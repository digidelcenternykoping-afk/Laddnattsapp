"""Kvantilmodeller (p10/p50/p90) med gradient boosting."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from .features import feature_columns

QUANTILES = {"p10": 0.1, "p50": 0.5, "p90": 0.9}


class PriceModel:
    def __init__(self, quantiles: dict[str, float] | None = None, max_iter: int = 300):
        self.quantiles = quantiles or QUANTILES
        self.max_iter = max_iter
        self.models: dict[str, HistGradientBoostingRegressor] = {}
        self.cols: list[str] = []

    def fit(self, train: pd.DataFrame) -> "PriceModel":
        self.cols = feature_columns(train)
        for name, q in self.quantiles.items():
            m = HistGradientBoostingRegressor(
                loss="quantile", quantile=q, max_iter=self.max_iter, learning_rate=0.05,
                max_leaf_nodes=31, min_samples_leaf=40, l2_regularization=1.0, random_state=0)
            self.models[name] = m.fit(train[self.cols], train["y"])
        return self

    def predict(self, rows: pd.DataFrame) -> pd.DataFrame:
        out = rows[["origin", "target_date", "hour", "lead"]].copy()
        for name, m in self.models.items():
            out[name] = m.predict(rows[self.cols]) + rows["level_hour"].to_numpy()
        # Kvantilerna tränas var för sig och kan korsa varandra; sortera dem.
        q = sorted(self.models, key=lambda n: self.quantiles[n])
        out[q] = np.sort(out[q].to_numpy(), axis=1)
        return out
