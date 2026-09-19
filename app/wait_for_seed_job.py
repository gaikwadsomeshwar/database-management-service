"""Blocks until the seed-students Job finishes, so the API doesn't start too early."""

import logging
import os
import sys
import time

from state_populations import STATE_STUDENT_COUNTS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

JOB_NAME = os.getenv("SEED_JOB_NAME", "seed-students")
NAMESPACE = os.getenv("POD_NAMESPACE", "default")
POLL_INTERVAL_SECONDS = int(os.getenv("SEED_JOB_POLL_SECONDS", "5"))


def _compute_default_timeout_seconds():
    """Derive a timeout from the actual dataset size instead of a fixed constant.

    total_records / assumed sustained insert throughput, plus a fixed buffer
    for connection setup, schema creation, and index building.
    """
    total_records = sum(STATE_STUDENT_COUNTS.values())
    assumed_records_per_second = float(os.getenv("SEED_ASSUMED_RECORDS_PER_SECOND", "4000"))
    buffer_seconds = int(os.getenv("SEED_TIMEOUT_BUFFER_SECONDS", "1200"))
    return int(total_records / assumed_records_per_second) + buffer_seconds


TIMEOUT_SECONDS = int(os.getenv("SEED_JOB_TIMEOUT_SECONDS", str(_compute_default_timeout_seconds())))


def main():
    from kubernetes import client, config

    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()

    batch_api = client.BatchV1Api()
    deadline = time.monotonic() + TIMEOUT_SECONDS
    logger.info(
        "Waiting up to %ds for seed job %s (dataset=%d records)",
        TIMEOUT_SECONDS,
        JOB_NAME,
        sum(STATE_STUDENT_COUNTS.values()),
    )

    while time.monotonic() < deadline:
        job = batch_api.read_namespaced_job_status(JOB_NAME, NAMESPACE)
        status = job.status

        if status.succeeded:
            logger.info("Seed job %s completed successfully", JOB_NAME)
            return 0
        if status.failed:
            logger.error("Seed job %s failed", JOB_NAME)
            return 1

        logger.info("Waiting for seed job %s to complete...", JOB_NAME)
        time.sleep(POLL_INTERVAL_SECONDS)

    logger.error("Timed out after %ds waiting for seed job %s", TIMEOUT_SECONDS, JOB_NAME)
    return 1


if __name__ == "__main__":
    sys.exit(main())
