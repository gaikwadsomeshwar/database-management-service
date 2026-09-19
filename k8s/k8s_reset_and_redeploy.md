# Full Reset & Redeploy Procedure for Minikube & Per‑State MySQL Stack

## 1️⃣ Clean‑up any stray Minikube Docker artifacts

```powershell
# Remove any leftover Minikube container (if it still exists)

docker ps -a --filter "name=minikube" --format "{{.ID}}" | ForEach-Object { docker rm -f $_ }

# Remove all Docker volumes that Minikube created

docker volume ls --filter "name=minikube" --format "{{.Name}}" | ForEach-Object { docker volume rm $_ }

# Delete the local Minikube profile directory (wipes PVC data, config, cache)

Remove-Item -Recurse -Force "$env:USERPROFILE\.minikube"
```

## 2️⃣ Start a fresh Minikube instance

```powershell
# Adjust resources to match your machine (you have ~12 CPU / 16 GB RAM)
minikube start --cpus 4 --memory 8192 --driver docker
```

Verify the node is Ready:

```powershell
kubectl get nodes
```

## 3️⃣ Deploy the per‑state MySQL manifests

```powershell
# Apply the whole k8s directory (kustomization + generated manifests)
kubectl apply -k k8s
```

Confirm the resources are created:

```powershell
kubectl get pods -l app.kubernetes.io/component=mysql
kubectl get pvc -l app.kubernetes.io/component=mysql
```

All 28 MySQL pods should reach **Running**.

## 4️⃣ (Optional) Run the seed Job to create schema & seed data

```powershell
kubectl apply -f k8s/seed-job.yaml
```

Check the job logs:

```powershell
kubectl logs job/seed-job -n default
```

## 5️⃣ Run the test harness (apply‑only version)

```powershell
# Activate the virtual environment if not already active
.\.venv\Scripts\activate

# Example: apply script folders 1‑5 on 10 random states, single iteration
python test_scripts/run_database_scripts_test.py --from 1 --to 5 --states 10 --iterations 1
```

You should see log lines such as:

```
[maharashtra] Applying 01_add_guardian_contact_columns.sql
[maharashtra] Applied 1 scripts successfully
...
All 1 iteration(s) completed successfully
```

No rollback calls are made.

## 6️⃣ Verify end‑to‑end functionality

```powershell
# Health check of the Flask API
curl http://localhost:5000/health

# Sample SQL execution against a specific state
curl -X POST http://localhost:5000/api/sql/execute \
     -H "Content-Type: application/json" \
     -d '{"database":"students_db","sql":"SELECT COUNT(*) FROM student_maharashtra;","state":"maharashtra"}'
```

A successful JSON response confirms the API can reach the newly‑created MySQL instance.

---

**Next actions you may consider**

- Add new migration scripts to `database_scripts/` and re‑run the test harness.
- Tune MySQL resources in `k8s/generate_mysql_manifests.py` if you need more/less memory or CPU per state.
- Commit the generated `k8s/mysql.yaml` (or keep the generator script) for reproducible deployments.
