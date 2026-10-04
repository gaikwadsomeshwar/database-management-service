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
        self._active_lags = LAG_FEATURES
        self._fallback_value = None
        self._fitted = False

    def fit(self, history):
        history = np.asarray(history, dtype=float)
        self._fitted = True
        self._fallback_value = float(history[-1]) if len(history) else 1.0

        # Adjust seasonal periods if history is shorter than 2 full cycles
        if len(history) < self.seasonal_periods * 2:
            self.seasonal_periods = max(2, len(history) // 3)

        # 1. Fit Holt-Winters model
        if len(history) >= 4:
            try:
                self._hw_model = ExponentialSmoothing(
                    history,
                    trend="add",
                    seasonal="add",
                    seasonal_periods=self.seasonal_periods,
                    initialization_method="estimated",
                ).fit(optimized=True)
            except Exception:
                try:
                    self._hw_model = ExponentialSmoothing(
                        history, trend="add", initialization_method="estimated"
                    ).fit(optimized=True)
                except Exception:
                    logger.warning("Holt-Winters fit failed; falling back to lag-only/mean", exc_info=True)
                    self._hw_model = None
        else:
            self._hw_model = None

        # 2. Fit Gradient Boosting with adaptive lag features
        valid_lags = tuple(l for l in LAG_FEATURES if l < len(history))
        if valid_lags and (len(history) - max(valid_lags)) >= 1:
            self._active_lags = valid_lags
            X, y = _build_lag_features(history, lags=self._active_lags)
            if len(X) > 0:
                self._gb_model = GradientBoostingRegressor(
                    n_estimators=min(200, max(20, len(X) * 10)),
                    max_depth=min(3, max(1, len(X) // 2)),
                    learning_rate=0.05,
                    random_state=42,
                )
                self._gb_model.fit(X, y)
                self._last_window = history[-max(self._active_lags):]
            else:
                self._gb_model = None
        else:
            self._gb_model = None

        return self

    def predict(self, horizon=5):
        """Return a blended forecast for the next `horizon` steps."""
        if not self._fitted:
            raise RuntimeError("EnsembleForecaster must be fit() before predict()")

        hw_forecast = None
        if self._hw_model is not None:
            try:
                hw_forecast = np.asarray(self._hw_model.forecast(horizon))
            except Exception:
                hw_forecast = None

        gb_forecast = None
        if self._gb_model is not None and self._last_window is not None:
            try:
                window = list(self._last_window)
                gb_vals = []
                for _ in range(horizon):
                    features = np.array([[window[-lag] for lag in self._active_lags]])
                    next_value = float(self._gb_model.predict(features)[0])
                    gb_vals.append(next_value)
                    window.append(next_value)
                gb_forecast = np.asarray(gb_vals)
            except Exception:
                gb_forecast = None

        if hw_forecast is not None and gb_forecast is not None:
            blended = (
                self.holt_winters_weight * hw_forecast
                + (1 - self.holt_winters_weight) * gb_forecast
            )
        elif hw_forecast is not None:
            blended = hw_forecast
        elif gb_forecast is not None:
            blended = gb_forecast
        else:
            fallback = self._fallback_value if self._fallback_value is not None else 1.0
            blended = np.full(horizon, max(0.0, fallback))

        return np.clip(blended, 0, None)

