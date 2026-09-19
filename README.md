# Student Database Service

This project provides a distributed, sharded database platform with **one dedicated MySQL server per Indian state** (28 independent SQL servers) and a secured Flask REST API with proactive autoscaling. It can run in either:

- Standalone Docker containers.
- Kubernetes (Minikube, Kind, or cloud clusters) using the manifests in `k8s/`.

Each state has its own dedicated SQL server instance and Service (e.g. `mysql-maharashtra`, `mysql-andhra-pradesh`), hosting that state's dedicated table, such as `student_maharashtra` and `student_uttar_pradesh`, alongside its metadata schema. This eliminates cross-state lock contention and InnoDB redo-log bottlenecks while keeping state data strictly isolated.

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
│   ├── generate_mysql_manifests.py # Manifest generator for all 28 per-state SQL servers
│   ├── mysql.yaml              # 28 Deployments, Services, and PVCs (one per Indian state)
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
│   ├── run_database_scripts_test.py # Randomized test harness routing SQL across state servers
│   └── collect_pod_logs.py     # Collects pod logs (including all 28 state MySQL pods)
├── Dockerfile
└── requirements.txt
```

## Distributed Per-State SQL Architecture

Instead of hosting multiple state tables within a single monolithic MySQL pod, the architecture provides **one SQL server per state**:

1. **State Isolation**: Each Indian state has a dedicated MySQL pod and ClusterIP Service named `mysql-<state>` (e.g. `mysql-maharashtra`, `mysql-karnataka`).
2. **Resource Right-Sizing**: Each MySQL pod requests `30m CPU` and `120Mi RAM` (limits: `300m CPU`, `512Mi RAM`) with `--innodb-buffer-pool-size=64M`. All 28 pods collectively reserve ~0.84 CPU cores and ~3.3 GB RAM, running comfortably on standard developer machines and Minikube.
3. **Independent Storage**: Each state server has its own 1Gi `PersistentVolumeClaim` (`mysql-data-<state>`).
4. **Dynamic Routing**:
   - The Flask API (`app/api.py`) routes single-state queries (`/api/students?state=maharashtra`) directly to `mysql-maharashtra`.
   - Global queries (`/api/students` without `state`) execute parallel fan-out queries across all 28 state servers via `ThreadPoolExecutor` and aggregate the paginated results.
   - The SQL executor (`app/sql_executor.py`) automatically detects table references like `student_maharashtra` to target the corresponding SQL server.

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
| `STUDENT_BATCH_SIZE`               | Seeder           | Number of records inserted per transaction batch (default: `1000`, tuned to `10000` in k8s).        |
| `STUDENT_SEED_WORKERS`             | Seeder           | Number of worker threads per batch (default: `5`, tuned to `5` in k8s).                             |
| `STUDENT_STATE_BATCH_SIZE`         | Seeder           | Number of state SQL servers seeded per batch (default: `5`, tuned to `5` in k8s).                   |
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

```powershell
kubectl apply -k k8s
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
