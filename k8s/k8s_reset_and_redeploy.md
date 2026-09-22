# Reset & Redeploy Procedure for Minikube & Per‑State MySQL Stack

## 1️⃣ Reset Minikube Cluster

```powershell
# Delete existing minikube profile and purge local cluster state
minikube delete --purge

# Start a fresh Minikube cluster
minikube start --cpus 4 --memory 8192 --driver docker

# Verify the node is Ready
kubectl get nodes
```

## 2️⃣ Deploy the per‑state MySQL manifests & Seed Databases

### Option A: All-in-One Deployment

```powershell
# Apply all manifests at once using Kustomize
kubectl apply -k k8s
```

_(Note: `api.yaml` contains an initContainer `wait-for-seed-job` that automatically holds the API pod until the seed job completes)._

### Option B: Phased Deployment (Seeding BEFORE Deploying API)

```powershell
# 1. Apply config, secret, and MySQL instances
kubectl apply -f k8s/app-config.yaml
kubectl apply -f k8s/secret.yaml
kubectl apply -f k8s/mysql.yaml

# 2. Wait until all 7 MySQL pods reach Running
kubectl rollout status deployment -l app.kubernetes.io/component=mysql --timeout=180s

# 3. Apply the seed Job and wait for it to complete
kubectl apply -f k8s/seed-job.yaml
kubectl wait --for=condition=complete job/seed-students --timeout=7200s

# 4. Deploy the API, Forecast service, Monitoring, and Autoscaler
kubectl apply -f k8s/rbac.yaml
kubectl apply -f k8s/api.yaml
kubectl apply -f k8s/forecast-config.yaml
kubectl apply -f k8s/forecast-service.yaml
kubectl apply -f k8s/monitoring.yaml
kubectl apply -f k8s/hpa-reactive.yaml
```

## 3️⃣ Verify Deployment

```powershell
# Confirm MySQL pods and PVCs are created and Running
kubectl get pods -l app.kubernetes.io/component=mysql
kubectl get pvc -l app.kubernetes.io/component=mysql
```

## 4️⃣ Run the test harness

```powershell
# Activate virtual environment
.\.venv\Scripts\activate

# Apply migration scripts across random state databases (1 per MySQL server, max 7, parallel state execution)
python test_scripts/run_database_scripts_test.py --from 1 --to 5 --states 7 --iterations 1
```

## 5️⃣ Verify API Functionality

```powershell
# Health check of the Flask API
curl http://localhost:5000/health

# Sample SQL execution against a specific state
curl -X POST http://localhost:5000/api/sql/execute \
     -H "Content-Type: application/json" \
     -d '{"database":"students_db","sql":"SELECT COUNT(*) FROM student_maharashtra;","state":"maharashtra"}'

# Verify active autoscaling mode (Reactive vs Proactive)
kubectl get hpa,scaledobject
```

## 6️⃣ Updating & Rolling Out Code Changes

When Python application code or dependencies in `app/` are updated, rebuild the image and trigger a rolling restart without resetting the database cluster.

> **Important**: Always use `--no-cache` when rebuilding. Docker's layer cache preserves stale `.py` files from earlier builds — skipping this causes the old code to remain active even after a rollout restart.

> **Important**: `minikube image load` does **not** replace an existing image with the same tag. You must force-remove the old image from Minikube first, then reload.

### Step 1 — Rebuild with no cache

```powershell
docker build --no-cache -t student-api:1.0.0 .
```

### Step 2 — Force-replace the image in Minikube

```powershell
# Remove the old image from Minikube's internal Docker daemon
minikube ssh -- "docker rmi student-api:1.0.0 --force"

# Load the freshly built image
minikube image load student-api:1.0.0
```

### Step 3 — Verify the image digest matches

```powershell
# Local image digest (source of truth)
docker inspect student-api:1.0.0 --format "{{.Id}} {{.Created}}"

# Minikube image digest (must match local)
minikube ssh -- "docker inspect student-api:1.0.0 --format '{{.Id}} {{.Created}}'"
```

Both digests must be identical before proceeding. If they differ, repeat Step 2.

### Step 4 — Trigger rolling restart

```powershell
kubectl rollout restart deployment student-api
kubectl rollout status deployment student-api

# Optional For all deployments
kubectl get deployments -o name | ForEach-Object { kubectl rollout restart $_ }
```

### Step 5 — Confirm the new code is live

```powershell
# Get the new pod name
kubectl get pods -l app=student-api

# Verify a module-level change (replace with any check relevant to your edit)
$pod = kubectl get pods -l app=student-api -o jsonpath="{.items[0].metadata.name}"
kubectl exec $pod -- python -c "import sql_executor; print(sql_executor.FORBIDDEN_PATTERN.pattern)"
```

### Common pitfalls

| Symptom                                           | Cause                                          | Fix                                                      |
| ------------------------------------------------- | ---------------------------------------------- | -------------------------------------------------------- |
| `deployment unchanged` after apply                | Manifest YAML hasn't changed, K8s skips update | Use `kubectl rollout restart` instead of `kubectl apply` |
| Old code still running after rollout              | Docker used cached layers with stale files     | Rebuild with `--no-cache`                                |
| Old code still running after `--no-cache` rebuild | Minikube has old image cached under same tag   | `minikube ssh -- "docker rmi ... --force"` then reload   |
| Swagger `/static/swagger.json` 404                | Stale pod; code fix not deployed yet           | Follow this rollout procedure                            |
