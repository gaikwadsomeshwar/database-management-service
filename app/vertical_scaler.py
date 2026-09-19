"""Vertical resource recommendation and safe, rate-limited actuation.

Predicts the CPU/memory a single student-api replica needs (via the same
Holt-Winters + gradient-boosting ensemble used for horizontal forecasting),
then patches the Deployment's container resources when the recommendation
drifts meaningfully from what's currently deployed. Designed to avoid cost
blowups from over-provisioning or thrashing:

- Recommendations are always clamped to configured MIN/MAX bounds.
- A patch is only applied if the change exceeds CHANGE_THRESHOLD_RATIO.
- A patch is only applied once per COOLDOWN_SECONDS, even if triggered again.
"""

import logging
import math
import os
import threading
import time

from forecasting.data_source import fetch_history
from forecasting.model import EnsembleForecaster

logger = logging.getLogger(__name__)

NAMESPACE = os.getenv("POD_NAMESPACE", "default")
DEPLOYMENT_NAME = os.getenv("SCALING_DEPLOYMENT_NAME", "student-api")
CONTAINER_NAME = os.getenv("SCALING_CONTAINER_NAME", "api")

CPU_HEADROOM_RATIO = float(os.getenv("VERTICAL_CPU_HEADROOM_RATIO", "1.3"))
MEMORY_HEADROOM_RATIO = float(os.getenv("VERTICAL_MEMORY_HEADROOM_RATIO", "1.3"))
CPU_LIMIT_MULTIPLIER = float(os.getenv("VERTICAL_CPU_LIMIT_MULTIPLIER", "2.0"))
MEMORY_LIMIT_MULTIPLIER = float(os.getenv("VERTICAL_MEMORY_LIMIT_MULTIPLIER", "2.0"))

MIN_CPU_MILLICORES = float(os.getenv("VERTICAL_MIN_CPU_MILLICORES", "50"))
MAX_CPU_MILLICORES = float(os.getenv("VERTICAL_MAX_CPU_MILLICORES", "1000"))
MIN_MEMORY_MIB = float(os.getenv("VERTICAL_MIN_MEMORY_MIB", "64"))
MAX_MEMORY_MIB = float(os.getenv("VERTICAL_MAX_MEMORY_MIB", "1024"))

CHANGE_THRESHOLD_RATIO = float(os.getenv("VERTICAL_CHANGE_THRESHOLD_RATIO", "0.2"))
COOLDOWN_SECONDS = int(os.getenv("VERTICAL_SCALE_COOLDOWN_SECONDS", "600"))
ENABLED = os.getenv("VERTICAL_SCALING_ENABLED", "true").lower() == "true"

_last_patch_lock = threading.Lock()
_last_patch_at = 0.0

_apps_api = None
_apps_api_attempted = False


def _get_apps_api():
    global _apps_api, _apps_api_attempted
    if _apps_api_attempted:
        return _apps_api
    _apps_api_attempted = True
    try:
        from kubernetes import client, config

        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()
        _apps_api = client.AppsV1Api()
    except Exception:
        logger.warning(
            "Kubernetes API client unavailable; vertical scaling is disabled",
            exc_info=True,
        )
    return _apps_api


def recommend_resources(horizon=5):
    """Forecast per-pod CPU/memory needs and return a bounded recommendation."""
    cpu_forecast = EnsembleForecaster().fit(fetch_history("cpu_usage")).predict(horizon=horizon)
    memory_forecast = (
        EnsembleForecaster().fit(fetch_history("memory_usage")).predict(horizon=horizon)
    )

    peak_cpu_cores = float(max(cpu_forecast))
    peak_memory_bytes = float(max(memory_forecast))

    cpu_millicores = peak_cpu_cores * 1000 * CPU_HEADROOM_RATIO
    memory_mib = (peak_memory_bytes / (1024 * 1024)) * MEMORY_HEADROOM_RATIO

    cpu_millicores = max(MIN_CPU_MILLICORES, min(MAX_CPU_MILLICORES, cpu_millicores))
    memory_mib = max(MIN_MEMORY_MIB, min(MAX_MEMORY_MIB, memory_mib))

    return {
        "recommended_cpu_millicores": math.ceil(cpu_millicores),
        "recommended_memory_mib": math.ceil(memory_mib),
    }


def _current_container_resources(apps_api):
    deployment = apps_api.read_namespaced_deployment(DEPLOYMENT_NAME, NAMESPACE)
    for container in deployment.spec.template.spec.containers:
        if container.name == CONTAINER_NAME:
            requests = (container.resources and container.resources.requests) or {}
            return requests
    return {}


def _parse_cpu_millicores(value):
    if value is None:
        return None
    if value.endswith("m"):
        return float(value[:-1])
    return float(value) * 1000


def _parse_memory_mib(value):
    if value is None:
        return None
    if value.endswith("Mi"):
        return float(value[:-2])
    if value.endswith("Gi"):
        return float(value[:-2]) * 1024
    return float(value) / (1024 * 1024)


def _ratio_changed(current, recommended):
    if not current or current == 0:
        return True
    return abs(recommended - current) / current >= CHANGE_THRESHOLD_RATIO


def maybe_apply_vertical_scaling(recommendation):
    """Patch the Deployment's container resources if recommendation drifted enough.

    Returns True if a patch was applied, False otherwise (disabled, within
    threshold, still cooling down, or the Kubernetes API is unavailable).
    """
    global _last_patch_at

    if not ENABLED:
        return False

    apps_api = _get_apps_api()
    if apps_api is None:
        return False

    with _last_patch_lock:
        if time.monotonic() - _last_patch_at < COOLDOWN_SECONDS:
            return False

        try:
            current_requests = _current_container_resources(apps_api)
            current_cpu = _parse_cpu_millicores(current_requests.get("cpu"))
            current_memory = _parse_memory_mib(current_requests.get("memory"))
        except Exception:
            logger.warning("Failed to read current Deployment resources", exc_info=True)
            return False

        target_cpu = recommendation["recommended_cpu_millicores"]
        target_memory = recommendation["recommended_memory_mib"]

        if not _ratio_changed(current_cpu, target_cpu) and not _ratio_changed(
            current_memory, target_memory
        ):
            return False

        patch = {
            "spec": {
                "template": {
                    "spec": {
                        "containers": [
                            {
                                "name": CONTAINER_NAME,
                                "resources": {
                                    "requests": {
                                        "cpu": f"{target_cpu}m",
                                        "memory": f"{target_memory}Mi",
                                    },
                                    "limits": {
                                        "cpu": f"{math.ceil(target_cpu * CPU_LIMIT_MULTIPLIER)}m",
                                        "memory": (
                                            f"{math.ceil(target_memory * MEMORY_LIMIT_MULTIPLIER)}Mi"
                                        ),
                                    },
                                },
                            }
                        ]
                    }
                }
            }
        }

        try:
            apps_api.patch_namespaced_deployment(DEPLOYMENT_NAME, NAMESPACE, patch)
            _last_patch_at = time.monotonic()
            logger.info(
                "Vertical scaling applied: cpu=%sm memory=%sMi (was cpu=%s memory=%s)",
                target_cpu,
                target_memory,
                current_cpu,
                current_memory,
            )
            return True
        except Exception:
            logger.warning("Failed to patch Deployment resources", exc_info=True)
            return False
