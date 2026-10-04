"""Unit tests for the time-series forecasting model (app/forecasting/model.py).

Tests model fitting, lag feature creation, short history adaptation,
fallback mechanisms, and non-negative prediction clipping.
"""

import sys
import unittest
from pathlib import Path
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "app"))

from forecasting.model import EnsembleForecaster, _build_lag_features, LAG_FEATURES


class TestForecastingModel(unittest.TestCase):
    """Test suite for EnsembleForecaster and lag feature engineering."""

    def setUp(self):
        np.random.seed(42)
        # Generate synthetic seasonal history: base + trend + sine seasonality + noise
        t = np.arange(180)
        self.history = 20.0 + 0.05 * t + 5.0 * np.sin(2 * np.pi * t / 30) + np.random.normal(0, 0.5, len(t))

    def test_build_lag_features_shape(self):
        """Verify lag feature matrix has expected rows and columns."""
        lags = (1, 2, 3, 6, 12)
        X, y = _build_lag_features(self.history, lags=lags)
        max_lag = max(lags)
        expected_rows = len(self.history) - max_lag
        self.assertEqual(X.shape, (expected_rows, len(lags)))
        self.assertEqual(y.shape, (expected_rows,))
        # Verify specific lag values for the first row
        for idx, lag in enumerate(lags):
            self.assertAlmostEqual(X[0, idx], self.history[max_lag - lag])
        self.assertAlmostEqual(y[0], self.history[max_lag])

    def test_predict_before_fit_raises_error(self):
        """Calling predict() before fit() must raise a RuntimeError."""
        forecaster = EnsembleForecaster()
        with self.assertRaises(RuntimeError):
            forecaster.predict(horizon=5)

    def test_model_fitting_and_prediction(self):
        """Verify model fits cleanly and produces positive horizon predictions."""
        forecaster = EnsembleForecaster(seasonal_periods=30, holt_winters_weight=0.5)
        fitted = forecaster.fit(self.history)
        self.assertIs(fitted, forecaster)
        self.assertIsNotNone(forecaster._hw_model)
        self.assertIsNotNone(forecaster._gb_model)

        horizon = 7
        preds = forecaster.predict(horizon=horizon)
        self.assertEqual(len(preds), horizon)
        self.assertTrue(all(p >= 0 for p in preds), "Predictions must be non-negative")
        # Reasonable range check
        self.assertTrue(all(5.0 <= p <= 50.0 for p in preds), f"Predictions out of expected range: {preds}")

    def test_short_history_adaptation(self):
        """Verify model adapts gracefully when history has fewer points than seasonal period."""
        short_history = [12.0, 15.0, 14.0, 18.0, 19.0, 22.0, 21.0, 25.0]
        forecaster = EnsembleForecaster(seasonal_periods=30)
        forecaster.fit(short_history)
        # When history < 2 * seasonal_periods, seasonal component should be None or adapted
        self.assertIsNotNone(forecaster._hw_model)
        preds = forecaster.predict(horizon=3)
        self.assertEqual(len(preds), 3)
        self.assertTrue(all(p > 0 for p in preds))

    def test_fallback_on_extremely_short_series(self):
        """Verify robust fallback when history is minimal (e.g. 2 points)."""
        minimal_history = [10.0, 12.0]
        forecaster = EnsembleForecaster()
        forecaster.fit(minimal_history)
        preds = forecaster.predict(horizon=4)
        self.assertEqual(len(preds), 4)
        # Should fall back to mean/last value
        self.assertTrue(all(p > 0 for p in preds))

    def test_clipping_negative_predictions(self):
        """Verify negative model artifacts are clipped to 0.0 or positive."""
        declining_history = [50.0, 40.0, 30.0, 20.0, 10.0, 5.0, 2.0, 1.0, 0.5, 0.2]
        forecaster = EnsembleForecaster()
        forecaster.fit(declining_history)
        preds = forecaster.predict(horizon=10)
        self.assertTrue(all(p >= 0.0 for p in preds), "Predictions must never be negative")


if __name__ == "__main__":
    unittest.main()
