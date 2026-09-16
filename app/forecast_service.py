"""Proactive-autoscaling forecast service.

Periodically forecasts near-future request load with an ensemble time-series
model (see ``forecasting/model.py``) and exposes the predicted load and a
recommended replica count as Prometheus metrics. KEDA (or a custom metrics
adapter) can then scale the ``student-api`` Deployment ahead of demand,
instead of waiting for CPU thresholds to be breached.
"""

import logging
import math
import os
import threading
import time

from flask import Flask, jsonify
from prometheus_client import Gauge, generate_latest

from forecasting.data_source import fetch_history
from forecasting.model import EnsembleForecaster

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Read-only metrics/prediction endpoints only; no forms or state-changing routes.
app = Flask(__name__)

FORECAST_HORIZON_STEPS = int(os.getenv("FORECAST_HORIZON_STEPS", "5"))
REFRESH_INTERVAL_SECONDS = int(os.getenv("FORECAST_REFRESH_SECONDS", "60"))
MIN_REPLICAS = int(os.getenv("FORECAST_MIN_REPLICAS", "1"))
MAX_REPLICAS = int(os.getenv("FORECAST_MAX_REPLICAS", "10"))
TARGET_REQUESTS_PER_REPLICA = float(os.getenv("FORECAST_TARGET_RPS_PER_REPLICA", "20"))

PREDICTED_REQUEST_RATE = Gauge(
    "predicted_request_rate",
    "Forecasted peak request rate (requests/sec) over the next horizon.",
)
PREDICTED_REPLICAS = Gauge(
    "predicted_replicas",
    "Recommended pod replica count derived from the forecasted request rate.",
)
FORECAST_MODEL_ERRORS = Gauge(
    "forecast_model_errors_total",
    "Count of forecasting cycles that failed and fell back to the last known value.",
)

_state_lock = threading.Lock()
_latest = {"predicted_request_rate": 0.0, "predicted_replicas": MIN_REPLICAS}


def _recommend_replicas(predicted_rate):
    """Convert a forecasted request rate into a bounded replica recommendation."""
    replicas = math.ceil(predicted_rate / TARGET_REQUESTS_PER_REPLICA)
    return max(MIN_REPLICAS, min(MAX_REPLICAS, replicas))


def run_forecast_cycle():
    """Fetch history, retrain the ensemble, and publish the latest forecast."""
    history = fetch_history("request_rate")
    forecaster = EnsembleForecaster().fit(history)
    forecast = forecaster.predict(horizon=FORECAST_HORIZON_STEPS)
    peak_rate = float(max(forecast))
    replicas = _recommend_replicas(peak_rate)

    with _state_lock:
        _latest["predicted_request_rate"] = peak_rate
        _latest["predicted_replicas"] = replicas

    PREDICTED_REQUEST_RATE.set(peak_rate)
    PREDICTED_REPLICAS.set(replicas)
    logger.info("Forecast cycle: peak_rate=%.2f replicas=%d", peak_rate, replicas)


def _background_loop():
    while True:
        try:
            run_forecast_cycle()
        except Exception:
            FORECAST_MODEL_ERRORS.inc()
            logger.exception("Forecast cycle failed; retaining last known prediction")
        time.sleep(REFRESH_INTERVAL_SECONDS)


@app.get("/metrics")
def metrics():
    """Expose Prometheus metrics, including the proactive scaling forecast."""
    return generate_latest(), 200, {"Content-Type": "text/plain; version=0.0.4; charset=utf-8"}


@app.get("/predict")
def predict():
    """Return the latest forecast as JSON for debugging or direct integration."""
    with _state_lock:
        return jsonify(dict(_latest)), 200


@app.get("/health")
def health():
    return {"status": "ok"}, 200


if __name__ == "__main__":
    run_forecast_cycle()  # populate an initial prediction before serving traffic
    threading.Thread(target=_background_loop, daemon=True).start()
    app.run(host=os.getenv("API_HOST", "0.0.0.0"), port=int(os.getenv("FORECAST_PORT", "5100")))
