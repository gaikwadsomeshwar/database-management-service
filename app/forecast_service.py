"""Proactive-autoscaling forecast service.

Periodically forecasts near-future request load with an ensemble time-series
model (see ``forecasting/model.py``) and exposes the predicted load and a
recommended replica count as Prometheus metrics. KEDA (or a custom metrics
adapter) can then scale the ``student-api`` Deployment ahead of demand,
instead of waiting for CPU thresholds to be breached.

The horizontal recommendation blends two signals so neither over- nor
under-provisions: the forecasted request-rate trend (proactive) and the
*current* in-flight request queue depth (reactive safety net for sudden
bursts the forecast hasn't seen yet). A separate vertical-scaling loop
predicts each replica's own CPU/memory needs and right-sizes the Deployment's
container resources within configured bounds, so horizontal scale-out never
compounds with over-provisioned per-pod resources.
"""

import logging
import json
import math
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify
from prometheus_client import Gauge, generate_latest

from forecasting.data_source import fetch_history, fetch_latest
from forecasting.model import EnsembleForecaster
from vertical_scaler import maybe_apply_vertical_scaling, recommend_resources

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Read-only metrics/prediction endpoints only; no forms or state-changing routes.
app = Flask(__name__)

FORECAST_HORIZON_STEPS = int(os.getenv("FORECAST_HORIZON_STEPS", "5"))
REFRESH_INTERVAL_SECONDS = int(os.getenv("FORECAST_REFRESH_SECONDS", "60"))
MIN_REPLICAS = int(os.getenv("FORECAST_MIN_REPLICAS", "1"))
MAX_REPLICAS = int(os.getenv("FORECAST_MAX_REPLICAS", "10"))
TARGET_REQUESTS_PER_REPLICA = float(os.getenv("FORECAST_TARGET_RPS_PER_REPLICA", "20"))
# Queue-depth (in-flight requests) safety net: how many concurrent in-flight
# requests one replica should absorb before the queue-based signal kicks in.
TARGET_ACTIVE_REQUESTS_PER_REPLICA = float(
    os.getenv("FORECAST_TARGET_ACTIVE_REQUESTS_PER_REPLICA", "5")
)
VERTICAL_SCALING_ENABLED = os.getenv("VERTICAL_SCALING_ENABLED", "true").lower() == "true"
REPORT_DATA_ENABLED = os.getenv("REPORT_DATA_ENABLED", "true").lower() == "true"
REPORT_DATA_DIR = Path(
    os.getenv(
        "REPORT_DATA_DIR",
        str(Path(__file__).resolve().parent.parent / "reports_and_documents" / "runtime_data"),
    )
)
REPORT_DATA_FILE = REPORT_DATA_DIR / os.getenv("REPORT_DATA_FILENAME", "forecast_metrics.jsonl")

PREDICTED_REQUEST_RATE = Gauge(
    "predicted_request_rate",
    "Forecasted peak request rate (requests/sec) over the next horizon.",
)
PREDICTED_REPLICAS = Gauge(
    "predicted_replicas",
    "Recommended pod replica count blending the forecast and queue depth.",
)
REPLICAS_FROM_FORECAST = Gauge(
    "predicted_replicas_from_forecast",
    "Replica recommendation derived only from the request-rate forecast.",
)
REPLICAS_FROM_QUEUE = Gauge(
    "predicted_replicas_from_queue",
    "Replica recommendation derived only from current in-flight queue depth.",
)
CURRENT_ACTIVE_REQUESTS = Gauge(
    "observed_active_requests",
    "Current in-flight request count observed at forecast time.",
)
RECOMMENDED_CPU_MILLICORES = Gauge(
    "recommended_cpu_millicores",
    "Predicted per-replica CPU request (millicores) from the vertical-scaling model.",
)
RECOMMENDED_MEMORY_MIB = Gauge(
    "recommended_memory_mib",
    "Predicted per-replica memory request (MiB) from the vertical-scaling model.",
)
VERTICAL_SCALE_APPLIED_TOTAL = Gauge(
    "vertical_scale_applied_total",
    "Count of vertical-scaling patches applied to the Deployment.",
)
FORECAST_MODEL_ERRORS = Gauge(
    "forecast_model_errors_total",
    "Count of forecasting cycles that failed and fell back to the last known value.",
)

_state_lock = threading.Lock()
_latest = {"predicted_request_rate": 0.0, "predicted_replicas": MIN_REPLICAS}
_vertical_scale_applied_count = 0
_report_data_lock = threading.Lock()


def _write_report_snapshot(status, **values):
    """Append one machine-readable forecast-cycle snapshot for later analysis."""
    if not REPORT_DATA_ENABLED:
        return

    snapshot = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "refresh_interval_seconds": REFRESH_INTERVAL_SECONDS,
        **values,
    }
    try:
        REPORT_DATA_DIR.mkdir(parents=True, exist_ok=True)
        with _report_data_lock:
            with REPORT_DATA_FILE.open("a", encoding="utf-8") as output:
                output.write(json.dumps(snapshot, sort_keys=True) + "\n")
    except Exception:
        # Report-data persistence must never stop autoscaling or the metrics API.
        logger.warning("Unable to persist report metrics snapshot", exc_info=True)


def _recommend_replicas_from_forecast(predicted_rate):
    """Convert a forecasted request rate into a bounded replica recommendation."""
    replicas = math.ceil(predicted_rate / TARGET_REQUESTS_PER_REPLICA)
    return max(MIN_REPLICAS, min(MAX_REPLICAS, replicas))


def _recommend_replicas_from_queue(active_requests):
    """Convert the current in-flight request count into a replica recommendation."""
    replicas = math.ceil(active_requests / TARGET_ACTIVE_REQUESTS_PER_REPLICA)
    return max(MIN_REPLICAS, min(MAX_REPLICAS, replicas))


def run_forecast_cycle():
    """Fetch history, retrain the ensembles, and publish the latest recommendations."""
    global _vertical_scale_applied_count

    history = fetch_history("request_rate")
    forecaster = EnsembleForecaster().fit(history)
    forecast = forecaster.predict(horizon=FORECAST_HORIZON_STEPS)
    peak_rate = float(max(forecast))
    replicas_from_forecast = _recommend_replicas_from_forecast(peak_rate)

    active_requests = fetch_latest("active_requests")
    replicas_from_queue = _recommend_replicas_from_queue(active_requests)

    # Horizontal: take whichever signal wants more capacity right now, so a
    # queue spike the forecast hasn't learned yet still triggers scale-out,
    # while a quiet queue doesn't undercut a forecasted upcoming peak.
    replicas = max(replicas_from_forecast, replicas_from_queue)

    with _state_lock:
        _latest["predicted_request_rate"] = peak_rate
        _latest["predicted_replicas"] = replicas
        _latest["predicted_replicas_from_forecast"] = replicas_from_forecast
        _latest["predicted_replicas_from_queue"] = replicas_from_queue
        _latest["observed_active_requests"] = active_requests

    PREDICTED_REQUEST_RATE.set(peak_rate)
    PREDICTED_REPLICAS.set(replicas)
    REPLICAS_FROM_FORECAST.set(replicas_from_forecast)
    REPLICAS_FROM_QUEUE.set(replicas_from_queue)
    CURRENT_ACTIVE_REQUESTS.set(active_requests)
    logger.info(
        "Forecast cycle: peak_rate=%.2f replicas=%d (forecast=%d, queue=%d, active=%.1f)",
        peak_rate,
        replicas,
        replicas_from_forecast,
        replicas_from_queue,
        active_requests,
    )

    if VERTICAL_SCALING_ENABLED:
        resource_recommendation = recommend_resources(horizon=FORECAST_HORIZON_STEPS)
        with _state_lock:
            _latest.update(resource_recommendation)
        RECOMMENDED_CPU_MILLICORES.set(resource_recommendation["recommended_cpu_millicores"])
        RECOMMENDED_MEMORY_MIB.set(resource_recommendation["recommended_memory_mib"])
        if maybe_apply_vertical_scaling(resource_recommendation):
            _vertical_scale_applied_count += 1
            VERTICAL_SCALE_APPLIED_TOTAL.set(_vertical_scale_applied_count)

    _write_report_snapshot(
        "success",
        predicted_request_rate=peak_rate,
        predicted_replicas=replicas,
        predicted_replicas_from_forecast=replicas_from_forecast,
        predicted_replicas_from_queue=replicas_from_queue,
        observed_active_requests=active_requests,
        recommended_cpu_millicores=_latest.get("recommended_cpu_millicores"),
        recommended_memory_mib=_latest.get("recommended_memory_mib"),
        vertical_scale_applied_total=_vertical_scale_applied_count,
    )


def _background_loop():
    while True:
        try:
            run_forecast_cycle()
        except Exception:
            FORECAST_MODEL_ERRORS.inc()
            _write_report_snapshot("failed", error="forecast_cycle_failed")
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
