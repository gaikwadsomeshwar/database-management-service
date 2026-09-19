"""Read-only Kubernetes and Prometheus lookups for the scaling comparison dashboard."""

import logging
import os

import requests

logger = logging.getLogger(__name__)

PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "").rstrip("/")
FORECAST_SERVICE_URL = os.getenv("FORECAST_SERVICE_URL", "http://forecast-service:5100").rstrip("/")
NAMESPACE = os.getenv("POD_NAMESPACE", "default")
DEPLOYMENT_NAME = os.getenv("SCALING_DEPLOYMENT_NAME", "student-api")
HPA_NAME = os.getenv("SCALING_HPA_NAME", "student-api-hpa-reactive")
SCALEDOBJECT_NAME = os.getenv("SCALING_SCALEDOBJECT_NAME", "student-api-scaledobject-proactive")

_k8s_apps_api = None
_k8s_autoscaling_api = None
_k8s_custom_api = None
_k8s_available = False
_k8s_attempted = False


def _init_kubernetes_clients():
    """Lazily load the Kubernetes client, preferring in-cluster credentials."""
    global _k8s_apps_api, _k8s_autoscaling_api, _k8s_custom_api, _k8s_available, _k8s_attempted
    if _k8s_attempted:
        return
    _k8s_attempted = True
    try:
        from kubernetes import client, config

        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()

        _k8s_apps_api = client.AppsV1Api()
        _k8s_autoscaling_api = client.AutoscalingV2Api()
        _k8s_custom_api = client.CustomObjectsApi()
        _k8s_available = True
    except Exception:
        logger.warning(
            "Kubernetes API client unavailable; dashboard will omit live cluster state",
            exc_info=True,
        )


def get_deployment_replicas():
    """Return desired/current/ready replica counts for the tracked Deployment, or None."""
    _init_kubernetes_clients()
    if not _k8s_available:
        return None
    try:
        deployment = _k8s_apps_api.read_namespaced_deployment(DEPLOYMENT_NAME, NAMESPACE)
        status = deployment.status
        return {
            "desired": deployment.spec.replicas,
            "current": status.replicas or 0,
            "ready": status.ready_replicas or 0,
        }
    except Exception:
        logger.warning("Failed to read Deployment %s", DEPLOYMENT_NAME, exc_info=True)
        return None


def get_reactive_hpa_status():
    """Return the reactive CPU-based HPA's status, or {'active': False} if not present."""
    _init_kubernetes_clients()
    if not _k8s_available:
        return None
    try:
        hpa = _k8s_autoscaling_api.read_namespaced_horizontal_pod_autoscaler(HPA_NAME, NAMESPACE)
        current_utilization = None
        if hpa.status.current_metrics:
            resource_metric = hpa.status.current_metrics[0].resource
            if resource_metric:
                current_utilization = resource_metric.current.average_utilization
        return {
            "active": True,
            "current_replicas": hpa.status.current_replicas,
            "desired_replicas": hpa.status.desired_replicas,
            "current_cpu_utilization": current_utilization,
        }
    except Exception:
        return {"active": False}


def get_proactive_scaledobject_status():
    """Return the proactive KEDA ScaledObject's status, or {'active': False} if not present."""
    _init_kubernetes_clients()
    if not _k8s_available:
        return None
    try:
        scaled_object = _k8s_custom_api.get_namespaced_custom_object(
            group="keda.sh",
            version="v1alpha1",
            namespace=NAMESPACE,
            plural="scaledobjects",
            name=SCALEDOBJECT_NAME,
        )
        conditions = {
            condition["type"]: condition["status"]
            for condition in scaled_object.get("status", {}).get("conditions", [])
        }
        return {
            "active": True,
            "ready": conditions.get("Ready") == "True",
            "scaling_active": conditions.get("Active") == "True",
        }
    except Exception:
        return {"active": False}


def _query_prometheus_instant(promql):
    if not PROMETHEUS_URL:
        return None
    try:
        response = requests.get(
            f"{PROMETHEUS_URL}/api/v1/query", params={"query": promql}, timeout=5
        )
        response.raise_for_status()
        result = response.json().get("data", {}).get("result", [])
        return float(result[0]["value"][1]) if result else None
    except Exception:
        logger.warning("Prometheus instant query failed: %s", promql, exc_info=True)
        return None


def get_forecast_snapshot():
    """Return forecast-service's latest predicted request rate and replica count."""
    try:
        response = requests.get(f"{FORECAST_SERVICE_URL}/predict", timeout=5)
        response.raise_for_status()
        return response.json()
    except Exception:
        logger.warning("Failed to reach forecast-service", exc_info=True)
        return None


def get_actual_request_rate():
    """Return the current actual request rate (requests/sec) from Prometheus."""
    return _query_prometheus_instant("sum(rate(student_api_requests_total[1m]))")


def get_scaling_snapshot():
    """Assemble one combined snapshot comparing reactive vs. proactive scaling."""
    return {
        "deployment": get_deployment_replicas(),
        "reactive_hpa": get_reactive_hpa_status(),
        "proactive_scaledobject": get_proactive_scaledobject_status(),
        "forecast": get_forecast_snapshot(),
        "actual_request_rate": get_actual_request_rate(),
    }
