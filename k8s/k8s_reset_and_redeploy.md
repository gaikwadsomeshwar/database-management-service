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

# Apply migration scripts across random state databases (1 per MySQL server, 7 total)
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
```
