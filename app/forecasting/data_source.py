"""Historical metric retrieval for the proactive forecasting service.

Queries Prometheus for recent request-rate and CPU-usage history. When
Prometheus is not configured or unreachable, a synthetic seasonal series is
generated instead so the forecasting pipeline can be developed and tested
without live cluster infrastructure.
"""

import logging
import os
import time

import numpy as np
import requests

logger = logging.getLogger(__name__)

PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "").rstrip("/")
HISTORY_WINDOW_SECONDS = int(os.getenv("FORECAST_HISTORY_SECONDS", str(6 * 3600)))
STEP_SECONDS = int(os.getenv("FORECAST_STEP_SECONDS", "60"))

METRIC_QUERIES = {
    "request_rate": "sum(rate(student_api_requests_total[5m]))",
    "cpu_usage": 'sum(rate(container_cpu_usage_seconds_total{pod=~"student-api.*"}[5m]))',
}


def _query_range(promql, start, end, step):
    response = requests.get(
        f"{PROMETHEUS_URL}/api/v1/query_range",
        params={"query": promql, "start": start, "end": end, "step": step},
        timeout=10,
    )
    response.raise_for_status()
    result = response.json().get("data", {}).get("result", [])
    if not result:
        return []
    return [float(value) for _, value in result[0]["values"]]


def _synthetic_series(length, seed):
    """Generate a daily-seasonal traffic pattern with noise and occasional spikes."""
    rng = np.random.default_rng(seed)
    steps_per_day = max(2, (24 * 3600) // STEP_SECONDS)
    t = np.arange(length)
    daily_cycle = 40 + 30 * np.sin(2 * np.pi * t / steps_per_day)
    noise = rng.normal(0, 3, size=length)
    spikes = np.zeros(length)
    spike_positions = rng.choice(length, size=max(1, length // 200), replace=False)
    spikes[spike_positions] = rng.uniform(30, 80, size=len(spike_positions))
    return np.clip(daily_cycle + noise + spikes, 1, None).tolist()


def fetch_history(metric="request_rate"):
    """Return a recent time-series for the given metric name."""
    length = HISTORY_WINDOW_SECONDS // STEP_SECONDS
    seed = abs(hash(metric)) % (2**32)

    if not PROMETHEUS_URL:
        logger.info("PROMETHEUS_URL not set; using synthetic history for %s", metric)
        return _synthetic_series(length, seed)

    query = METRIC_QUERIES.get(metric, METRIC_QUERIES["request_rate"])
    end = time.time()
    start = end - HISTORY_WINDOW_SECONDS
    try:
        values = _query_range(query, start, end, STEP_SECONDS)
        if len(values) < 20:
            raise ValueError("insufficient history returned by Prometheus")
        return values
    except Exception:
        logger.warning(
            "Prometheus query failed for %s; using synthetic history", metric, exc_info=True
        )
        return _synthetic_series(length, seed)
