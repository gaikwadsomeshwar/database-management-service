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
    "active_requests": "sum(student_api_active_requests)",
    # Per-pod averages (not per-pod totals) so the resource forecaster predicts
    # what one replica needs, independent of how many replicas are running now.
    "cpu_usage": (
        'avg(rate(container_cpu_usage_seconds_total{pod=~"student-api-.*", '
        'container="api"}[5m]))'
    ),
    "memory_usage": (
        'avg(container_memory_working_set_bytes{pod=~"student-api-.*", '
        'container="api"})'
    ),
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


def _query_instant(promql):
    response = requests.get(
        f"{PROMETHEUS_URL}/api/v1/query", params={"query": promql}, timeout=5
    )
    response.raise_for_status()
    result = response.json().get("data", {}).get("result", [])
    return float(result[0]["value"][1]) if result else None


def fetch_latest(metric="active_requests"):
    """Return the current instant value for a metric (not a forecast).

    Used for reactive, low-latency signals like in-flight request queue depth
    that shouldn't wait for a full history-based ensemble forecast.
    """
    query = METRIC_QUERIES.get(metric, METRIC_QUERIES["request_rate"])
    if PROMETHEUS_URL:
        try:
            value = _query_instant(query)
            if value is not None:
                return value
        except Exception:
            logger.warning("Prometheus instant query failed for %s", metric, exc_info=True)

    profile = SYNTHETIC_PROFILES.get(metric, SYNTHETIC_PROFILES["request_rate"])
    return profile[0]


def _synthetic_series(length, seed, baseline=40.0, amplitude=30.0, noise_std=3.0, spike_scale=1.0):
    """Generate a daily-seasonal pattern with noise and occasional spikes.

    baseline/amplitude/noise_std/spike_scale let callers keep the synthetic
    fallback in a realistic range per metric (e.g. CPU cores vs. memory bytes)
    instead of always producing a 0-100-ish request-rate-shaped curve.
    """
    rng = np.random.default_rng(seed)
    steps_per_day = max(2, (24 * 3600) // STEP_SECONDS)
    t = np.arange(length)
    daily_cycle = baseline + amplitude * np.sin(2 * np.pi * t / steps_per_day)
    noise = rng.normal(0, noise_std, size=length)
    spikes = np.zeros(length)
    spike_positions = rng.choice(length, size=max(1, length // 200), replace=False)
    spikes[spike_positions] = (
        rng.uniform(amplitude, amplitude * 2.5, size=len(spike_positions)) * spike_scale
    )
    floor = max(baseline * 0.05, 0.01)
    return np.clip(daily_cycle + noise + spikes, floor, None).tolist()


# Per-metric synthetic fallback shape: (baseline, amplitude, noise_std, spike_scale).
SYNTHETIC_PROFILES = {
    "request_rate": (40.0, 30.0, 3.0, 1.0),
    "active_requests": (3.0, 3.0, 1.0, 1.0),
    "cpu_usage": (0.15, 0.1, 0.02, 0.5),  # cores per pod
    "memory_usage": (150_000_000.0, 60_000_000.0, 10_000_000.0, 0.5),  # bytes per pod
}


def fetch_history(metric="request_rate"):
    """Return a recent time-series for the given metric name."""
    length = HISTORY_WINDOW_SECONDS // STEP_SECONDS
    seed = abs(hash(metric)) % (2**32)
    profile = SYNTHETIC_PROFILES.get(metric, SYNTHETIC_PROFILES["request_rate"])

    if not PROMETHEUS_URL:
        logger.info("PROMETHEUS_URL not set; using synthetic history for %s", metric)
        return _synthetic_series(length, seed, *profile)

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
        return _synthetic_series(length, seed, *profile)
