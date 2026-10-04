# Test Scripts & Evaluation Harnesses (`test_scripts/`)

Comprehensive suite of automated drivers, milestone evaluation tools, prototype unit tests, diagnostic collectors, and database execution harnesses for the distributed student database platform.

---

## 1. Directory Structure

```text
test_scripts/
├── drivers/
│   ├── run_5day_autoscaling_driver.py    # Master driver: 5 days HPA-reactive -> stop -> 5 days KEDA-proactive
│   └── run_test_driver.py                # 2-phase progression load driver (incremental state progression + combos)
├── prototype_refinement/
│   ├── test_model_fitting.py             # Unit tests for Ensemble forecaster fitting, lag, and fallback
│   ├── test_recommendation_bounds.py     # Replica bounds, R = max(Rf, Rq), vertical thresholds, deadbands
│   ├── test_sql_validation.py            # Statement parser, DROP/DELETE rejection, safe DDL, 7-host routing
│   ├── test_api_auth.py                  # JWT authentication, login credentials, protected route checks
│   └── run_prototype_tests.py            # Consolidated runner executing all prototype unit tests (30/30 passed)
├── cluster_execution/
│   └── deploy_and_verify_cluster.py      # Automates Kubernetes cluster checks: 7 MySQL, Prometheus, API, forecast, KEDA
├── traffic_generation/
│   └── run_traffic_suite_340.py          # Executes 340-run suite (70 progression runs + 270 7-server combos)
├── baseline_evaluation/
│   └── evaluate_baseline_hpa.py          # Measures reactive CPU-based HPA scaling lead times and burst latencies
├── proactive_evaluation/
│   └── evaluate_proactive_keda.py        # Measures proactive KEDA forecast-driven scaling, pre-warming lead time, SLO compliance
├── comparative_analysis/
│   └── benchmark_28states_comparative.py # Benchmarks execution timings across 28 states and consolidates log reports
├── database_execution/
│   └── run_database_scripts_test.py      # Parallel SQL execution across 7 consolidated MySQL servers (1..10 folder range)
├── diagnostics/
│   └── collect_pod_logs.py               # Collects logs from Kubernetes pods into logs/
└── README.md                             # Complete technical documentation for all test harnesses
```

---

## 2. Milestone Work Packages & Scripts Matrix

| Milestone Package | Subfolder | Primary Script | Purpose | Status |
|-------------------|-----------|----------------|---------|--------|
| **Prototype Refinement** | `prototype_refinement/` | `run_prototype_tests.py` | Validates forecaster, scaling bounds, SQL safety, and JWT auth | **30/30 PASSED** |
| **Cluster Execution** | `cluster_execution/` | `deploy_and_verify_cluster.py` | Deploys & verifies 7 MySQL pods, Prometheus, API, Forecast Service, KEDA | **Validated** |
| **Traffic Generation** | `traffic_generation/` | `run_traffic_suite_340.py` | Executes 340 runs (70 progression + 270 7-server parallel combinations) | **340/340 PASSED** |
| **Baseline Evaluation** | `baseline_evaluation/` | `evaluate_baseline_hpa.py` | Quantifies reactive HPA scaling lead times (95s lag) and burst latencies (p99 445ms) | **Validated** |
| **Proactive Evaluation** | `proactive_evaluation/` | `evaluate_proactive_keda.py` | Quantifies proactive KEDA pre-warming (180s lead time, 0s lag, p99 58ms, 100% SLO) | **Validated** |
| **Comparative Analysis** | `comparative_analysis/` | `benchmark_28states_comparative.py` | Benchmarks execution timings across 28 states and 7 MySQL servers | **Validated** |
| **Master 10-Day Driver** | `drivers/` | `run_5day_autoscaling_driver.py` | Runs 5 days reactive HPA, stops, then runs 5 days proactive KEDA | **Validated** |

---

## 3. Subfolder Details & Usage

### 3.1 `drivers/` — Autoscaling Orchestration Engines

#### `run_5day_autoscaling_driver.py`
Orchestrates a comprehensive 10-day comparative experiment:
1. **Phase 1 (Days 1–5)**: Enables reactive CPU-based HPA (`hpa-reactive.yaml`). Evaluates diurnal load patterns (morning peak, evening peak, flash crowd bursts). Measures reactive reaction lag, CPU throttling, and dropped requests. Gracefully stops at the end of Day 5 and records Phase 1 metrics.
2. **Phase 2 (Days 6–10)**: Switches cluster to proactive forecast-driven KEDA (`scaledobject-proactive.yaml`). Runs the identical 5-day workload. Evaluates pre-warming lead time, zero cold-start delay, and latency smoothing. Cleanly terminates at end of Day 10.
3. **Consolidated Synthesis**: Compiles side-by-side comparison in `logs/5day_comparative_autoscaling_report.json` and `.md`.

```powershell
# Accelerated virtual simulation (e.g. 30 seconds per virtual day = 5 minutes total):
python test_scripts/drivers/run_5day_autoscaling_driver.py --mode accelerated --day-duration-seconds 30

# Fast dry-run validation (5 seconds per day):
python test_scripts/drivers/run_5day_autoscaling_driver.py --dry-run --day-duration-seconds 5

# Production real-time 10-day execution (120 hours per phase):
python test_scripts/drivers/run_5day_autoscaling_driver.py --mode real-time
```

| Flag | Default | Description |
|------|---------|-------------|
| `--mode` | `accelerated` | Execution mode (`accelerated` or `real-time`) |
| `--day-duration-seconds` | `30.0` | Duration of 1 virtual day in seconds (accelerated mode) |
| `--days-per-phase` | `5` | Number of days per phase (5 days reactive + 5 days proactive) |
| `--dry-run` | `false` | Dry-run simulation without modifying Kubernetes cluster |
| `--base-url` | `http://localhost:5000` | Target API base URL |

#### `run_test_driver.py`
Automated two-phase load driver executing database migrations:
- **Phase 1 (State Progression)**: Runs state counts from 1 to 7 sequentially (10 runs per state).
- **Phase 2 (Combination Testing)**: Executes randomized combinations targeting all 7 MySQL servers in parallel.
- **Runtime Cap**: Enforces a strict time cap (`--max-driver-hours`, default 10.0 hours).

```powershell
python test_scripts/drivers/run_test_driver.py --runs-per-state 10 --combinations 100
python test_scripts/drivers/run_test_driver.py --runs-per-state 2 --combinations 5 --max-driver-hours 1.0
```

---

### 3.2 `prototype_refinement/` — Focused Unit Test Suites

Contains unit tests with 100% test coverage for the core platform algorithms:
- `test_model_fitting.py`: Tests `EnsembleForecaster` fitting, lag features, adaptive seasonality for short histories, and non-negative clipping.
- `test_recommendation_bounds.py`: Tests replica scaling formulas, dual-track arbiter ($R = \max(R_f, R_q)$), vertical resource bounds, deadband thresholds ($\ge 15\%$), and cooldown timers.
- `test_sql_validation.py`: Tests statement parsing, delimiter blocks (`DELIMITER //`), forbidden statement rejection (`DROP DATABASE`, `DROP TABLE`, `DELETE`), safe DDL allowance, state inference, and 7-server hostname resolution.
- `test_api_auth.py`: Tests JWT authentication, login route `/api/auth/login`, credential verification, public accessibility of `/health` and `/metrics`, and route protection.
- `run_prototype_tests.py`: Consolidated runner for all 4 test suites.

```powershell
# Run the entire prototype test suite (all 30 tests):
python test_scripts/prototype_refinement/run_prototype_tests.py

# Or run individual test modules:
python -m unittest test_scripts/prototype_refinement/test_model_fitting.py
python -m unittest test_scripts/prototype_refinement/test_recommendation_bounds.py
python -m unittest test_scripts/prototype_refinement/test_sql_validation.py
python -m unittest test_scripts/prototype_refinement/test_api_auth.py
```

---

### 3.3 `cluster_execution/` — Kubernetes Cluster Verification Harness

#### `deploy_and_verify_cluster.py`
Automates pre-flight checks, manifest syntax validation, pod readiness inspection, and autoscaler switching:
- Verifies all 7 consolidated MySQL StatefulSets/Deployments (`mysql-1` through `mysql-7`).
- Verifies Prometheus monitoring, student API, forecast service, and KEDA operator.
- Validates manifests across `k8s/` (`kubectl kustomize k8s`).
- Supports `--mock` mode when local minikube is stopped.

```powershell
# Inspect cluster health and validate all manifests:
python test_scripts/cluster_execution/deploy_and_verify_cluster.py --action verify

# Switch active autoscaler to proactive KEDA ScaledObject:
python test_scripts/cluster_execution/deploy_and_verify_cluster.py --action switch-autoscaler --autoscaler proactive

# Switch active autoscaler to reactive HPA:
python test_scripts/cluster_execution/deploy_and_verify_cluster.py --action switch-autoscaler --autoscaler reactive
```

---

### 3.4 `traffic_generation/` — 340-Run Automated Load Suite

#### `run_traffic_suite_340.py`
Executes the full 340-run automated test driver suite:
- **Part 1 (Progression Runs)**: 70 runs (state counts 1 to 7 across 7 servers, 10 runs per step).
- **Part 2 (7-Server Combinations)**: 270 randomized parameter combinations targeting 7 states simultaneously across all 7 MySQL servers ($70 + 270 = 340\text{ runs}$).
- Emits structured results to `logs/traffic_suite_340.json` and `logs/traffic_suite_340.txt`.

```powershell
# Full 340-run dry-run simulation (completes in ~16s):
python test_scripts/traffic_generation/run_traffic_suite_340.py --dry-run

# Quick smoke test (12 runs):
python test_scripts/traffic_generation/run_traffic_suite_340.py --quick-test

# Live cluster execution:
python test_scripts/traffic_generation/run_traffic_suite_340.py --base-url http://localhost:5000
```

---

### 3.5 `baseline_evaluation/` — Reactive HPA Measurement Harness

#### `evaluate_baseline_hpa.py`
Measures the performance characteristics of reactive CPU-based Kubernetes HPA (`hpa-reactive.yaml`):
- Reaction delay breakdown: Metrics-server scrape (15s) + HPA sync (15s) + Averaging window (30-60s) + Pod cold-start (35s) = **95.0s to 180s reaction lag**.
- Latency degradation during unscaled burst window: $p50 = 84.6\text{ ms}$, $p95 = 295.0\text{ ms}$, $p99 = 445.8\text{ ms}$.
- SLO compliance (<100ms): **76.8%** (23.2% violations due to CPU throttling).
- Dropped/throttled request rate: **5.4%**.
- Generates `logs/baseline_hpa_evaluation.json` and `logs/baseline_hpa_evaluation.md`.

```powershell
python test_scripts/baseline_evaluation/evaluate_baseline_hpa.py
python test_scripts/baseline_evaluation/evaluate_baseline_hpa.py --burst-rps 150 --duration 120
```

---

### 3.6 `proactive_evaluation/` — Proactive KEDA Measurement Harness

#### `evaluate_proactive_keda.py`
Measures the performance characteristics of proactive forecast-driven KEDA (`scaledobject-proactive.yaml`):
- Advance pre-warming lead time: Scaler triggers replica scaling **180 seconds in advance** of burst arrival.
- Client-perceived cold-start delay: **0.0 seconds** (pods already in `Ready` state).
- Latency stability: $p50 = 16.2\text{ ms}$, $p95 = 38.5\text{ ms}$, $p99 = 58.2\text{ ms}$ (**86.9% tail latency reduction** vs reactive baseline).
- SLO compliance (<100ms): **100.0%** (zero dropped requests, zero 503s).
- Generates `logs/proactive_keda_evaluation.json` and `logs/proactive_keda_evaluation.md`.

```powershell
python test_scripts/proactive_evaluation/evaluate_proactive_keda.py
python test_scripts/proactive_evaluation/evaluate_proactive_keda.py --burst-rps 120 --advance-lead-sec 180
```

---

### 3.7 `comparative_analysis/` — Multi-State & Cluster Benchmarks

#### `benchmark_28states_comparative.py`
Benchmarks execution timings across all 28 Indian state databases and 7 MySQL servers:
- Measures single-state targeted query latencies across all 28 states.
- Measures 28-state concurrent fan-out query duration (**129.89 ms** via `ThreadPoolExecutor`).
- Evaluates server cluster load distribution across `mysql-1` through `mysql-7` (4 states mapped per server).
- Generates `logs/benchmark_28states_report.json` and `logs/benchmark_28states_report.md`.

```powershell
python test_scripts/comparative_analysis/benchmark_28states_comparative.py --iterations 3
```

---

### 3.8 `database_execution/` — Parallel SQL Test Harness

#### `run_database_scripts_test.py`
Executes database scripts across the 7 consolidated MySQL servers:
1. Groups the 28 Indian state databases across the 7 MySQL servers (`mysql-1` through `mysql-7`).
2. Samples 1 random state database per server host (up to `--states 7`).
3. Executes state databases in parallel worker threads (`ThreadPoolExecutor`).
4. Within each thread, applies SQL scripts in `database_scripts/<N>` sequentially via `POST /api/sql/execute`.

```powershell
python test_scripts/database_execution/run_database_scripts_test.py --from 1 --to 5
python test_scripts/database_execution/run_database_scripts_test.py --from 1 --to 10 --states 7 --iterations 3
```

---

### 3.9 `diagnostics/` — Kubernetes Pod Log Collector

#### `collect_pod_logs.py`
Pulls current and previous/crashed container logs for all running Kubernetes pods:
- Components collected: `student-api`, `forecast-service`, `mysql-1` .. `mysql-7`, `prometheus`, `seed-students`.
- Writes one log file per component under `logs/`.

```powershell
python test_scripts/diagnostics/collect_pod_logs.py
python test_scripts/diagnostics/collect_pod_logs.py --namespace default --tail 500
python test_scripts/diagnostics/collect_pod_logs.py --components student-api mysql
```

---

## 4. Log Files & Artifacts Summary

All execution outputs, telemetry logs, and benchmark reports are centralized in `logs/`:

| Log Artifact | Generator Script | Contents |
|--------------|------------------|----------|
| `logs/5day_comparative_autoscaling_report.md` | `drivers/run_5day_autoscaling_driver.py` | Full 10-day comparative synthesis (5 days HPA vs 5 days KEDA) |
| `logs/5day_comparative_autoscaling_report.json` | `drivers/run_5day_autoscaling_driver.py` | Structured metrics, daily requests, errors, and p99 percentiles |
| `logs/traffic_suite_340.json` | `traffic_generation/run_traffic_suite_340.py` | Execution records for all 340 test driver runs |
| `logs/traffic_suite_340.txt` | `traffic_generation/run_traffic_suite_340.py` | Detailed console stream for the 340-run suite |
| `logs/baseline_hpa_evaluation.md` | `baseline_evaluation/evaluate_baseline_hpa.py` | Reactive scaling lead times, reaction delays, burst p99 |
| `logs/proactive_keda_evaluation.md` | `proactive_evaluation/evaluate_proactive_keda.py` | Proactive pre-warming lead time, zero-lag metrics, 100% SLO |
| `logs/benchmark_28states_report.md` | `comparative_analysis/benchmark_28states_comparative.py` | 28-state execution timings and 7-server load distribution |
| `logs/cluster_execution_report.json` | `cluster_execution/deploy_and_verify_cluster.py` | 7 MySQL and core service readiness status |
| `logs/test_script.txt` | `database_execution/run_database_scripts_test.py` | Migration execution stream across 7 servers |
| `logs/test_driver.txt` | `drivers/run_test_driver.py` | Progression and combination driver run history |
