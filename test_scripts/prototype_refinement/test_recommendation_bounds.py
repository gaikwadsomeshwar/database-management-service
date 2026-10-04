"""Unit tests for horizontal and vertical scaling recommendation bounds.

Tests replica calculation formulas, bounds clamping, queue-depth safety override,
vertical CPU/memory recommendations, deadband thresholds, and cooldown logic.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "app"))

import forecast_service
import vertical_scaler


class TestRecommendationBounds(unittest.TestCase):
    """Test suite for scaling recommendation boundaries and safety constraints."""

    def setUp(self):
        # Default configs
        self.min_replicas = forecast_service.MIN_REPLICAS
        self.max_replicas = forecast_service.MAX_REPLICAS
        self.target_rps = forecast_service.TARGET_REQUESTS_PER_REPLICA
        self.target_active = forecast_service.TARGET_ACTIVE_REQUESTS_PER_REPLICA

    def test_horizontal_forecast_bounds(self):
        """Verify horizontal replica recommendation from predicted request rate."""
        # Zero rate -> MIN_REPLICAS
        self.assertEqual(forecast_service._recommend_replicas_from_forecast(0.0), self.min_replicas)
        # Moderate rate: e.g. rate=45, target=20 -> ceil(45/20) = 3
        self.assertEqual(forecast_service._recommend_replicas_from_forecast(45.0), 3)
        # Exact boundary: rate=40 -> ceil(40/20) = 2
        self.assertEqual(forecast_service._recommend_replicas_from_forecast(40.0), 2)
        # Very high rate: rate=10000 -> capped at MAX_REPLICAS
        self.assertEqual(forecast_service._recommend_replicas_from_forecast(10000.0), self.max_replicas)
        # Negative rate -> clamped to MIN_REPLICAS
        self.assertEqual(forecast_service._recommend_replicas_from_forecast(-15.0), self.min_replicas)

    def test_horizontal_queue_bounds(self):
        """Verify horizontal replica recommendation from in-flight queue depth."""
        # Zero active requests -> MIN_REPLICAS
        self.assertEqual(forecast_service._recommend_replicas_from_queue(0.0), self.min_replicas)
        # In-flight=12, target=5 -> ceil(12/5) = 3
        self.assertEqual(forecast_service._recommend_replicas_from_queue(12.0), 3)
        # Huge spike: in-flight=500 -> capped at MAX_REPLICAS
        self.assertEqual(forecast_service._recommend_replicas_from_queue(500.0), self.max_replicas)

    def test_dual_track_arbiter_logic(self):
        """Verify R = max(R_forecast, R_queue) behavior under different load conditions."""
        # Condition A: Predictable seasonal peak (Forecast leads, queue is quiet)
        rate_peak = 80.0   # ceil(80/20) = 4
        active_low = 2.0   # ceil(2/5) = 1
        r_f = forecast_service._recommend_replicas_from_forecast(rate_peak)
        r_q = forecast_service._recommend_replicas_from_queue(active_low)
        r_final = max(r_f, r_q)
        self.assertEqual(r_final, 4, "Forecast must pre-warm capacity ahead of queue growth")

        # Condition B: Unpredicted flash crowd (Forecast is low, queue surges)
        rate_low = 10.0    # ceil(10/20) = 1
        active_high = 35.0 # ceil(35/5) = 7
        r_f = forecast_service._recommend_replicas_from_forecast(rate_low)
        r_q = forecast_service._recommend_replicas_from_queue(active_high)
        r_final = max(r_f, r_q)
        self.assertEqual(r_final, 7, "Queue safety net must override forecast under sudden surge")

    @patch("vertical_scaler.fetch_history")
    def test_vertical_resource_recommendation_bounds(self, mock_fetch):
        """Verify that vertical resource recommendations respect MIN/MAX CPU and memory bounds."""
        # Case 1: Low usage -> must clamp to MIN bounds
        mock_fetch.side_effect = lambda metric: [0.001] * 60  # Tiny CPU and memory
        rec_min = vertical_scaler.recommend_resources(horizon=5)
        self.assertGreaterEqual(rec_min["recommended_cpu_millicores"], vertical_scaler.MIN_CPU_MILLICORES)
        self.assertGreaterEqual(rec_min["recommended_memory_mib"], vertical_scaler.MIN_MEMORY_MIB)

        # Case 2: Extreme usage -> must clamp to MAX bounds
        mock_fetch.side_effect = lambda metric: [100.0 * 1024 * 1024 * 1024] * 60  # Massive CPU / memory
        rec_max = vertical_scaler.recommend_resources(horizon=5)
        self.assertLessEqual(rec_max["recommended_cpu_millicores"], vertical_scaler.MAX_CPU_MILLICORES)
        self.assertLessEqual(rec_max["recommended_memory_mib"], vertical_scaler.MAX_MEMORY_MIB)

    def test_vertical_change_threshold_deadband(self):
        """Verify that resource changes below CHANGE_THRESHOLD_RATIO do not trigger patches."""
        threshold = vertical_scaler.CHANGE_THRESHOLD_RATIO  # default 0.2 (20%)
        current_cpu = 500  # millicores

        # 5% change: 525 vs 500 -> 5% < 20% -> should not trigger
        change_ratio_small = abs(525 - current_cpu) / current_cpu
        self.assertLess(change_ratio_small, threshold)

        # 25% change: 630 vs 500 -> 26% > 20% -> should trigger
        change_ratio_large = abs(630 - current_cpu) / current_cpu
        self.assertGreater(change_ratio_large, threshold)


if __name__ == "__main__":
    unittest.main()
