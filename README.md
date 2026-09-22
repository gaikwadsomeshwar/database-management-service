# Student Database Service

This project provides a distributed, sharded database platform with **7 consolidated MySQL servers** (`mysql-1` through `mysql-7`), hosting **4 dedicated state databases per server** (covering all 28 Indian states) and a secured Flask REST API with proactive autoscaling. It can run in either:

- Standalone Docker containers.
- Kubernetes (Minikube, Kind, or cloud clusters) using the manifests in `k8s/`.

Each state has its own dedicated MySQL database instance (e.g. `students_db_maharashtra`, `students_db_karnataka`) hosted across 7 SQL servers (`mysql-1` .. `mysql-7`), containing that state's dedicated table, such as `student_maharashtra` and `student_uttar_pradesh`, alongside its metadata schema. This eliminates cross-state lock contention and InnoDB redo-log bottlenecks while keeping state data strictly isolated.

State allocations use Census 2011 population figures. The generator assumes
2% of each state's population are students and creates
`round(population × 0.02)` records for that state. There is no maximum cap;
therefore Uttar Pradesh, the most populous state, receives the largest table.

## Project structure

```text
├── app/
│   ├── api.py                  # Flask API with dynamic per-state database routing and Swagger UI
│   ├── main.py                 # Safe SQL script runner (supports --state and --all-states)
│   ├── sql_executor.py         # State-aware SQL execution and auto-detection
│   ├── forecast_service.py     # Proactive-autoscaling forecast microservice
│   └── forecasting/
│       ├── data_source.py      # Prometheus history fetch (with synthetic fallback)
│       └── model.py            # Holt-Winters + gradient boosting ensemble
├── database/
│   ├── init/01_students_schema.sql  # State metadata schema initialized on each SQL server
│   └── seed_students.py        # Parallel population-proportional per-state seeder
├── k8s/
│   ├── generate_mysql_manifests.py # Manifest generator for the 7 consolidated SQL servers
│   ├── mysql.yaml              # 7 Deployments, Services, and PVCs (mysql-1 through mysql-7)
│   ├── api.yaml                # student-api Deployment and Service
│   ├── app-config.yaml         # ConfigMap with MYSQL_HOST_TEMPLATE="mysql-{state}"
│   ├── forecast-config.yaml
│   ├── forecast-service.yaml
│   ├── monitoring.yaml         # In-cluster Prometheus scraping forecast-service/student-api
│   ├── hpa-reactive.yaml       # Reactive CPU-based HPA (baseline)
│   ├── scaledobject-proactive.yaml  # KEDA ScaledObject driven by the forecast (enabled by default)
│   ├── kustomization.yaml
│   ├── secret.example.yaml
│   └── secret.yaml             # local only; ignored by Git
├── test_scripts/
│   ├── run_database_scripts_test.py # Parallel test harness routing SQL across state servers (max 7 states)
│   ├── run_test_driver.py      # Automated 340-run test driver (140 state progression runs + 200 parallel 7-server combos)
│   └── collect_pod_logs.py     # Collects pod logs across student-api, mysql-1..mysql-7, forecast-service, prometheus
├── Dockerfile
└── requirements.txt
```

## Distributed Consolidated SQL Architecture

Instead of hosting 28 separate standalone MySQL containers or a single monolithic pod, the architecture consolidates database workloads into **7 dedicated MySQL servers** (`mysql-1` through `mysql-7`):

1. **State Isolation**: Each Indian state has a dedicated database (`students_db_<state>`) distributed across 7 MySQL pods and ClusterIP Services (`mysql-1` through `mysql-7`, 4 state databases per server).
2. **Resource Right-Sizing**: Each MySQL pod requests `60m CPU` and `240Mi RAM` (limits: `800m CPU`, `896Mi RAM`) with `--innodb-buffer-pool-size=96M`. All 7 pods reserve a total footprint of ~6.2 GB RAM and run smoothly on developer machines and Minikube.
3. **Independent Storage**: Each MySQL server has its own 2Gi `PersistentVolumeClaim` (`mysql-data-1` through `mysql-data-7`).
4. **Dynamic Routing**:
   - The Flask API (`app/api.py`) routes single-state queries (`/api/students?state=maharashtra`) directly to `mysql-4/students_db_maharashtra`.
   - Global queries (`/api/students` without `state`) execute parallel fan-out queries across all 28 state databases via `ThreadPoolExecutor` and aggregate the paginated results.
   - The SQL executor (`app/sql_executor.py`) automatically detects table references like `student_maharashtra` to target the corresponding SQL server (`mysql-4`) and database (`students_db_maharashtra`).

## Proactive autoscaling forecast service

`app/forecast_service.py` implements the forecasting model: it periodically pulls recent request-rate history (from Prometheus, or a synthetic seasonal series when `PROMETHEUS_URL` is unset) and fits an **ensemble** of two models:

- **Holt-Winters exponential smoothing** (`statsmodels`) — captures trend and daily seasonality in request load.
- **Gradient-boosted regression** (`scikit-learn`) — learns non-linear lag relationships that pick up sudden bursts the seasonal model smooths over.

The two forecasts are blended by weighted average into a single predicted peak request rate, which is converted into a recommended replica count and exposed as Prometheus gauges:

- `predicted_request_rate` — forecasted peak requests/sec over the next horizon.
- `predicted_replicas` — recommended pod count (bounded by min/max replicas).

Run it locally:

```powershell
$env:PROMETHEUS_URL = ""  # unset -> synthetic history for local testing
python app/forecast_service.py
```

Then check `http://localhost:5100/predict` (JSON) or `http://localhost:5100/metrics` (Prometheus format).

### Comparing reactive vs. proactive scaling in Kubernetes

Two autoscalers target the same `student-api` Deployment so they can be benchmarked against each other, but **only one may be active at a time** — KEDA's admission webhook rejects a `ScaledObject` if an HPA already manages the Deployment, and vice versa:

- `k8s/hpa-reactive.yaml` — standard CPU-utilization `HorizontalPodAutoscaler` (the reactive baseline).
- `k8s/scaledobject-proactive.yaml` — a [KEDA](https://keda.sh) `ScaledObject` that scales on the `predicted_replicas` metric from `forecast-service`, scraped by the in-cluster Prometheus in `k8s/monitoring.yaml`.

`k8s/kustomization.yaml` includes `scaledobject-proactive.yaml` by default.

#### Install KEDA (one-time, required for the proactive ScaledObject)

```powershell
helm repo add kedacore https://kedacore.github.io/charts
helm repo update
kubectl create namespace keda
helm install keda kedacore/keda --namespace keda
```

#### Switching between reactive and proactive scaling

```powershell
# Switch to reactive (CPU-based) scaling
kubectl delete -f k8s/scaledobject-proactive.yaml --ignore-not-found
kubectl apply -f k8s/hpa-reactive.yaml

# Switch back to proactive (forecast-driven) scaling
kubectl delete -f k8s/hpa-reactive.yaml --ignore-not-found
kubectl apply -f k8s/scaledobject-proactive.yaml
```

## Configuration

The local `.env` file contains configuration values and credentials. Use strong values for passwords and `JWT_SECRET_KEY`:

```dotenv
MYSQL_HOST_TEMPLATE=mysql-{state}
MYSQL_HOST=127.0.0.1
MYSQL_DATABASE=students_db
MYSQL_USER=root
MYSQL_PASSWORD=your-mysql-password
API_USERNAME=apiuser
API_PASSWORD=your-api-password
JWT_SECRET_KEY=your-long-random-secret
JWT_ACCESS_TOKEN_EXPIRES_MINUTES=60
API_PORT=5000
```

Never commit `.env` or `k8s/secret.yaml` with real credentials.

### Configuration variables

| Variable                           | Used by          | Purpose                                                                                             |
| ---------------------------------- | ---------------- | --------------------------------------------------------------------------------------------------- |
| `MYSQL_HOST_TEMPLATE`              | API/seeder/CLI   | Template for per-state SQL server hostname; defaults to `mysql-{state}` (e.g. `mysql-maharashtra`). |
| `MYSQL_HOST`                       | API/seeder       | Fallback MySQL hostname when `MYSQL_HOST_TEMPLATE` is not used.                                     |
| `MYSQL_PORT`                       | API/seeder       | MySQL port, normally `3306`.                                                                        |
| `MYSQL_DATABASE`                   | API/seeder/MySQL | Database name on each state's SQL server (default: `students_db`).                                  |
| `MYSQL_USER`                       | API/seeder       | MySQL account used by the application (default: `root`).                                            |
| `MYSQL_PASSWORD`                   | API/seeder       | Password for `MYSQL_USER`.                                                                          |
| `STUDENT_BATCH_SIZE`               | Seeder           | Number of records inserted per transaction batch (default: `1000`, tuned to `2000` in k8s).         |
| `STUDENT_SEED_WORKERS`             | Seeder           | Number of worker threads per batch (default: `4`, tuned to `4` in k8s).                             |
| `STUDENT_STATE_BATCH_SIZE`         | Seeder           | Number of state databases seeded per batch (default: `4`, tuned to `4` in k8s; 1 server at a time). |
| `API_USERNAME`                     | API              | Login username for JWT issuance.                                                                    |
| `API_PASSWORD`                     | API              | Login password for JWT issuance.                                                                    |
| `JWT_SECRET_KEY`                   | API              | Private signing key; never send it as a bearer token.                                               |
| `JWT_ACCESS_TOKEN_EXPIRES_MINUTES` | API              | Lifetime of issued access tokens.                                                                   |
| `API_HOST` / `API_PORT`            | API              | Flask bind address and listening port.                                                              |

## Prometheus metrics

The API exposes Prometheus-compatible metrics at:

```text
http://localhost:5000/metrics
```

The metrics include:

- `student_api_requests_total` — request count labeled by HTTP method, endpoint, and status code.
- `student_api_response_duration_seconds` — response-time histogram labeled by HTTP method and endpoint.
- `student_api_active_requests` — current in-flight requests on the API pod.

---

# Running with Kubernetes

In Kubernetes, each Indian state runs its own MySQL server (`mysql-<state>`), and the Flask API routes requests to the appropriate state server.

## 1. Build and load the application image

```powershell
docker build -t student-api:1.0.0 .
```

For `kind`:

```powershell
kind load docker-image student-api:1.0.0
```

For Minikube:

```powershell
minikube image load student-api:1.0.0
```

### Rolling out API code updates without cluster reset

To apply Python code changes (`app/api.py`, `app/sql_executor.py`, etc.) to a running cluster follow these steps exactly — skipping steps leads to stale code staying active.

> **Important**: Always use `--no-cache`. Docker's layer cache preserves old `.py` files, so a cached rebuild silently keeps the old code.

> **Important**: `minikube image load` does **not** overwrite an existing image with the same tag. Force-remove it first.

**Step 1 — Rebuild with no cache**

```powershell
docker build --no-cache -t student-api:1.0.0 .
```

**Step 2 — Force-replace the image in Minikube**

```powershell
minikube ssh -- "docker rmi student-api:1.0.0 --force"
minikube image load student-api:1.0.0
```

**Step 3 — Verify image digests match**

```powershell
# Both lines must print the same sha256 hash
docker inspect student-api:1.0.0 --format "{{.Id}} {{.Created}}"
minikube ssh -- "docker inspect student-api:1.0.0 --format '{{.Id}} {{.Created}}'"
```

If digests differ, repeat Step 2.

**Step 4 — Rolling restart**

```powershell
kubectl rollout restart deployment student-api
kubectl rollout status deployment student-api
```

**Step 5 — Confirm new code is live**

```powershell
$pod = kubectl get pods -l app=student-api -o jsonpath="{.items[0].metadata.name}"
kubectl exec $pod -- python -c "import sql_executor; print(sql_executor.FORBIDDEN_PATTERN.pattern)"
```

**Common pitfalls**

| Symptom                                      | Cause                                      | Fix                                                    |
| -------------------------------------------- | ------------------------------------------ | ------------------------------------------------------ |
| `deployment unchanged` after apply           | Manifest YAML unchanged, K8s skips it      | Use `kubectl rollout restart`                          |
| Old code still running after rollout         | Docker used cached layers with stale files | Rebuild with `--no-cache`                              |
| Old code persists after `--no-cache` rebuild | Minikube cached old image under same tag   | `minikube ssh -- "docker rmi ... --force"` then reload |

> For a full step-by-step guide including cluster reset see [`k8s/k8s_reset_and_redeploy.md`](k8s/k8s_reset_and_redeploy.md).

## 2. Create the Kubernetes Secret

```powershell
Copy-Item k8s\secret.example.yaml k8s\secret.yaml
```

Edit `k8s/secret.yaml` with your credentials and apply:

```powershell
kubectl apply -f k8s\secret.yaml
```

## 3. (Optional) Re-generate MySQL manifests

If state definitions or resource tuning change, regenerate `k8s/mysql.yaml`:

```powershell
python k8s/generate_mysql_manifests.py
```

## 4. Deploy the distributed platform

### Option A: All-in-One Deployment

```powershell
kubectl apply -k k8s
```

_(Note: `student-api` uses an `initContainer` named `wait-for-seed-job` that automatically blocks the API until `seed-students` Job finishes)._

### Option B: Phased Deployment (Seed DB Before Deploying API)

```powershell
# 1. Apply MySQL instances and secrets
kubectl apply -f k8s/app-config.yaml
kubectl apply -f k8s/secret.yaml
kubectl apply -f k8s/mysql.yaml

# 2. Wait until MySQL pods reach Running
kubectl rollout status deployment -l app.kubernetes.io/component=mysql --timeout=180s

# 3. Apply seed Job and wait for completion
kubectl apply -f k8s/seed-job.yaml
kubectl wait --for=condition=complete job/seed-students --timeout=7200s

# 4. Deploy API and services once seeding is complete
kubectl apply -f k8s/rbac.yaml
kubectl apply -f k8s/api.yaml
kubectl apply -f k8s/forecast-config.yaml
kubectl apply -f k8s/forecast-service.yaml
kubectl apply -f k8s/monitoring.yaml
kubectl apply -f k8s/hpa-reactive.yaml
```

Check status across all 28 state servers:

```powershell
# View all 28 state MySQL pods
kubectl get pods -l app=mysql

# Monitor the parallel seeding Job
kubectl logs -f job/seed-students

# Verify API and forecast service
kubectl get deployment student-api forecast-service
```

## 5. Access the API locally

Forward the API service to localhost:

```powershell
kubectl port-forward service/student-api 5000:5000
```

The API is now available at `http://localhost:5000`.

## Checking Active Autoscaling Mode (Reactive vs. Proactive)

To verify which autoscaling mode is currently active in your cluster:

```powershell
kubectl get hpa,scaledobject
```

- **Proactive Scaling (KEDA)**: `scaledobject.keda.sh/student-api-scaledobject-proactive` will show `READY = True` and `ACTIVE = True`. Pods scale based on `forecast-service` ML predictions.
- **Reactive Scaling (HPA)**: `horizontalpodautoscaler.autoscaling/student-api-hpa-reactive` will list CPU targets (e.g., `15%/80%`). Pods scale when CPU crosses 80%.

To switch scaling modes:

```powershell
# Switch to Proactive (KEDA)
kubectl delete -f k8s/hpa-reactive.yaml
kubectl apply -f k8s/scaledobject-proactive.yaml

# Switch to Reactive (HPA Baseline)
kubectl delete -f k8s/scaledobject-proactive.yaml
kubectl apply -f k8s/hpa-reactive.yaml
```

Alternatively, open the real-time autoscaling comparison dashboard at `http://localhost:5000/dashboard`.

## Clean up Kubernetes deployment

```powershell
kubectl delete -k k8s
```

To delete all per-state database storage:

```powershell
kubectl delete pvc -l app=mysql
```

---

# API usage

All examples below assume the API is available at `http://localhost:5000`.

## Swagger documentation

- Swagger UI: `http://localhost:5000/docs/`
- OpenAPI JSON: `http://localhost:5000/swagger.json`

## Step 1: Authenticate and obtain JWT

```powershell
$login = Invoke-RestMethod -Method Post `
  -Uri http://localhost:5000/api/auth/login `
  -ContentType 'application/json' `
  -Body '{"username":"apiuser","password":"your-api-password"}'
$headers = @{ Authorization = "Bearer $($login.access_token)" }
```

## Step 2: Health check

```powershell
Invoke-RestMethod http://localhost:5000/health
```

Response:

```json
{ "status": "ok" }
```

## Step 3: Query students from a specific state's SQL server

To query a specific state's dedicated SQL server (e.g. Maharashtra), include `state=maharashtra`. This routes directly to `mysql-maharashtra`:

```powershell
Invoke-RestMethod `
  -Uri 'http://localhost:5000/api/students?state=maharashtra&page=1&per_page=10&sort_by=last_name&sort_order=asc' `
  -Headers $headers
```

## Step 4: Query across all 28 state SQL servers (parallel fan-out)

Omit the `state` parameter to run a global query across all 28 state SQL servers:

```powershell
Invoke-RestMethod `
  -Uri 'http://localhost:5000/api/students?page=1&per_page=20' `
  -Headers $headers
```

## Step 5: Get one student from a state SQL server

```powershell
Invoke-RestMethod `
  -Uri 'http://localhost:5000/api/students/1?state=maharashtra' `
  -Headers $headers
```

## Step 6: Execute SQL script against a state SQL server

The SQL execution endpoint automatically routes the script to the target state's dedicated SQL server:

```powershell
$sqlBody = @{
  database = "students_db"
  state = "maharashtra"
  sql = "ALTER TABLE student_maharashtra RENAME COLUMN city TO city_name;"
  rollback = $true
  rollback_sql = "ALTER TABLE student_maharashtra RENAME COLUMN city_name TO city;"
} | ConvertTo-Json

Invoke-RestMethod -Method Post `
  -Uri http://localhost:5000/api/sql/execute `
  -Headers $headers `
  -ContentType "application/json" `
  -Body $sqlBody
```

If `state` is omitted in the request body, the service automatically inspects the SQL script for `student_<state>` table references and routes to the matching state SQL server (`mysql-<state>`).

### API endpoint summary

| Method | Endpoint                     | Authentication    | Routing Behavior                                                       |
| ------ | ---------------------------- | ----------------- | ---------------------------------------------------------------------- |
| `GET`  | `/health`                    | None              | Pings database connectivity                                            |
| `POST` | `/api/auth/login`            | Username/password | Issues JWT access token                                                |
| `GET`  | `/api/students`              | Bearer JWT        | Routes to `mysql-<state>` if `?state=` is set; parallel fan-out if not |
| `GET`  | `/api/students/{student_id}` | Bearer JWT        | Direct lookup on `mysql-<state>` (requires `?state=`)                  |
| `POST` | `/api/sql/execute`           | Bearer JWT        | Auto-routes to `mysql-<state>` by `state` parameter or table name      |
