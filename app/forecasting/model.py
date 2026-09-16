"""Ensemble time-series forecasting combining Holt-Winters and gradient boosting.

Holt-Winters (statsmodels) captures the trend and daily seasonality of request
load, while a gradient-boosted regressor (scikit-learn) learns non-linear
lag relationships that pick up sudden bursts the seasonal model smooths over.
The two forecasts are blended by weighted average to produce the final
multi-variate proactive-scaling signal.
"""

import logging

import numpy as np
from sklearn.ensemble import GradientBoostingRegressor
from statsmodels.tsa.holtwinters import ExponentialSmoothing

logger = logging.getLogger(__name__)

LAG_FEATURES = (1, 2, 3, 6, 12)


def _build_lag_features(series, lags=LAG_FEATURES):
    """Turn a 1-D series into a supervised (X, y) lag-feature dataset."""
    series = np.asarray(series, dtype=float)
    max_lag = max(lags)
    rows = [[series[i - lag] for lag in lags] for i in range(max_lag, len(series))]
    targets = series[max_lag:]
    return np.array(rows), np.array(targets)


class EnsembleForecaster:
    """Blends a seasonal Holt-Winters model with a gradient-boosted lag model."""

    def __init__(self, seasonal_periods=60, holt_winters_weight=0.5):
        self.seasonal_periods = seasonal_periods
        self.holt_winters_weight = holt_winters_weight
        self._hw_model = None
        self._gb_model = None
        self._last_window = None

    def fit(self, history):
        history = np.asarray(history, dtype=float)
        if len(history) < self.seasonal_periods * 2:
            # Not enough history for the configured seasonality; shrink it.
            self.seasonal_periods = max(2, len(history) // 3)

        try:
            self._hw_model = ExponentialSmoothing(
                history,
                trend="add",
                seasonal="add",
                seasonal_periods=self.seasonal_periods,
                initialization_method="estimated",
            ).fit(optimized=True)
        except Exception:
            logger.warning(
                "Seasonal Holt-Winters fit failed; falling back to trend-only model",
                exc_info=True,
            )
            self._hw_model = ExponentialSmoothing(
                history, trend="add", initialization_method="estimated"
            ).fit(optimized=True)

        X, y = _build_lag_features(history)
        self._gb_model = GradientBoostingRegressor(
            n_estimators=200, max_depth=3, learning_rate=0.05, random_state=42
        )
        self._gb_model.fit(X, y)
        self._last_window = history[-max(LAG_FEATURES):]
        return self

    def predict(self, horizon=5):
        """Return a blended forecast for the next `horizon` steps."""
        if self._hw_model is None or self._gb_model is None:
            raise RuntimeError("EnsembleForecaster must be fit() before predict()")

        hw_forecast = np.asarray(self._hw_model.forecast(horizon))

        window = list(self._last_window)
        gb_forecast = []
        for _ in range(horizon):
            features = np.array([[window[-lag] for lag in LAG_FEATURES]])
            next_value = float(self._gb_model.predict(features)[0])
            gb_forecast.append(next_value)
            window.append(next_value)

        blended = (
            self.holt_winters_weight * hw_forecast
            + (1 - self.holt_winters_weight) * np.asarray(gb_forecast)
        )
        return np.clip(blended, 0, None)
