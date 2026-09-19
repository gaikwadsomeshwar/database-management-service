"""Collects logs from the running Kubernetes pods into separate text files.

A plain Python script for manual/local debugging - it is not deployed as a
container, Job, or Pod. Wraps `kubectl logs` (current and, where available,
`--previous` for crashed containers) for each known component and writes one
file per component under `logs/`, so `student-api`'s errors, `mysql`'s
errors, etc. can be inspected without re-running `kubectl` by hand.

Usage:
    python test_scripts/collect_pod_logs.py
    python test_scripts/collect_pod_logs.py --namespace default --tail 500
"""

import argparse
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = PROJECT_ROOT / "logs"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# One log file per component; label selector matches k8s/*.yaml Deployment/Job labels.
COMPONENTS = {
    "student-api": "app=student-api",
    "forecast-service": "app=forecast-service",
    "mysql": "app=mysql",
    "prometheus": "app=prometheus",
    "seed-students": "app=seed-students",
}


def run_kubectl(args):
    """Run a kubectl command, returning (success, stdout_or_stderr)."""
    try:
        result = subprocess.run(
            ["kubectl", *args], capture_output=True, text=True, timeout=60, check=False
        )
    except FileNotFoundError:
        return False, "kubectl was not found on PATH."
    except subprocess.TimeoutExpired:
        return False, f"kubectl {' '.join(args)} timed out."

    if result.returncode != 0:
        return False, result.stderr.strip() or f"kubectl {' '.join(args)} failed."
    return True, result.stdout


def list_pods(namespace, selector):
    ok, output = run_kubectl(
        ["get", "pods", "-n", namespace, "-l", selector, "-o", "jsonpath={.items[*].metadata.name}"]
    )
    if not ok:
        return [], output
    return [name for name in output.split() if name], None


def fetch_pod_logs(namespace, pod_name, tail, previous=False):
    args = ["logs", pod_name, "-n", namespace, "--all-containers=true", "--timestamps", f"--tail={tail}"]
    if previous:
        args.append("--previous")
    return run_kubectl(args)


def collect_component(namespace, component, selector, tail):
    """Write one logs/<component>.txt with sections for every matching pod."""
    pod_names, list_error = list_pods(namespace, selector)
    lines = [
        f"# Collected at {datetime.now(timezone.utc).isoformat()} "
        f"(namespace={namespace}, selector={selector})",
    ]

    if list_error:
        lines.append(f"# Failed to list pods: {list_error}")
    elif not pod_names:
        lines.append("# No matching pods found.")

    for pod_name in pod_names:
        lines.append(f"\n===== Pod: {pod_name} (current logs) =====")
        ok, output = fetch_pod_logs(namespace, pod_name, tail)
        lines.append(output if ok else f"[error fetching current logs: {output}]")

        lines.append(f"\n===== Pod: {pod_name} (previous / crashed container logs) =====")
        ok, output = fetch_pod_logs(namespace, pod_name, tail, previous=True)
        lines.append(output if ok else f"[no previous logs available: {output}]")

    output_path = LOGS_DIR / f"{component}.txt"
    output_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Wrote %s (%d pod(s))", output_path, len(pod_names))


def parse_args():
    parser = argparse.ArgumentParser(description="Collect logs for known pods into logs/<component>.txt")
    parser.add_argument("--namespace", default="default", help="Kubernetes namespace (default: default)")
    parser.add_argument("--tail", type=int, default=1000, help="Lines per pod to fetch (default: 1000)")
    parser.add_argument(
        "--components", nargs="+", choices=sorted(COMPONENTS), default=sorted(COMPONENTS),
        help="Subset of components to collect (default: all)",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    LOGS_DIR.mkdir(exist_ok=True)

    for component in args.components:
        collect_component(args.namespace, component, COMPONENTS[component], args.tail)

    logger.info("Done. Logs written to %s", LOGS_DIR)
    return 0


if __name__ == "__main__":
    sys.exit(main())
