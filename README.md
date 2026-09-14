# Student Database Service

This project provides a MySQL database with 100,000 synthetic student records and a secured Flask REST API. It can run in either:

- Standalone Docker containers.
- Kubernetes using the manifests in `k8s/`.

The records contain first name, last name, date of birth, email, phone number, city, state, country, and enrollment date.

## Project structure

```text
├── app/
│   ├── api.py                  # Flask API and Swagger UI
│   └── main.py                 # SQL file runner
├── database/
│   ├── init/01_students_schema.sql
│   └── seed_students.py        # 100,000-record generator
├── k8s/
│   ├── api.yaml
│   ├── app-config.yaml
│   ├── kustomization.yaml
│   ├── mysql.yaml
│   ├── secret.example.yaml
│   └── secret.yaml             # local only; ignored by Git
├── Dockerfile
└── requirements.txt
```

## Configuration

The local `.env` file contains the Docker values and credentials. Use strong values for passwords and `JWT_SECRET_KEY`:

```dotenv
MYSQL_DATABASE=students_db
MYSQL_USER=root
MYSQL_PASSWORD=your-mysql-password
STUDENT_COUNT=100000
API_USERNAME=apiuser
API_PASSWORD=your-api-password
JWT_SECRET_KEY=your-long-random-secret
JWT_ACCESS_TOKEN_EXPIRES_MINUTES=60
API_PORT=5000
```

Never commit `.env` or `k8s/secret.yaml` with real credentials.

# Option 1: Run with Docker

This option uses two containers connected to a shared Docker network:

- `student-mysql` uses the official `mysql:lts-oracle` image.
- `student-api` uses the application image built from `Dockerfile`.

No Docker Compose is required.

## 1. Build the application image

```powershell
docker build -t student-api:1.0.0 .
```

## 2. Create a Docker network

```powershell
docker network create student-network
```

If the network already exists, Docker will report that it exists; continue to the next step.

## 3. Start the database container

Replace the password with the value used in `.env`:

```powershell
docker run -d --name student-mysql --network student-network `
  --env-file .env `
  -e MYSQL_ROOT_PASSWORD=your-mysql-password `
  -p 3306:3306 `
  -v student-mysql-data:/var/lib/mysql `
  mysql:lts-oracle
```

Wait for MySQL:

```powershell
docker exec student-mysql mysqladmin ping -h 127.0.0.1 -uroot -pyour-mysql-password --wait=60
```

## 4. Create the schema and seed 100,000 records

The application container connects to the database through the Docker service name `student-mysql`:

```powershell
docker run --rm --name student-seeder --network student-network `
  --env-file .env `
  -e MYSQL_HOST=student-mysql `
  -e MYSQL_USER=root `
  -e MYSQL_PASSWORD=your-mysql-password `
  student-api:1.0.0 `
  sh -c "python main.py /database/init/01_students_schema.sql && python /database/seed_students.py"
```

## 5. Start the API container

```powershell
docker run -d --name student-api --network student-network `
  --env-file .env `
  -e MYSQL_HOST=student-mysql `
  -e MYSQL_USER=root `
  -e MYSQL_PASSWORD=your-mysql-password `
  -p 5000:5000 `
  student-api:1.0.0 `
  python api.py
```

The Docker API is available at `http://localhost:5000`.

## Stop Docker containers

```powershell
docker rm -f student-api student-mysql
docker network rm student-network
docker volume rm student-mysql-data
```

# Option 2: Run with Kubernetes

The Kubernetes configuration creates two Services:

- `mysql`: ClusterIP Service backed by a persistent `mysql:lts-oracle` Deployment.
- `student-api`: ClusterIP Service backed by the Flask API Deployment.

The API pod has an init container that creates the schema and seeds 100,000 records before the API starts. Non-sensitive settings come from `student-app-config` (`ConfigMap`); credentials come from `student-app-secrets` (`Secret`).

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

For a remote cluster, push the image to a registry and update the image name in `k8s/api.yaml`.

## 2. Create the Kubernetes Secret

```powershell
Copy-Item k8s\secret.example.yaml k8s\secret.yaml
```

Edit `k8s/secret.yaml` and set:

- `MYSQL_PASSWORD`
- `API_USERNAME`
- `API_PASSWORD`
- `JWT_SECRET_KEY`

Apply it:

```powershell
kubectl apply -f k8s\secret.yaml
```

## 3. Deploy the database and application

```powershell
kubectl apply -k k8s
```

Check status:

```powershell
kubectl get pods,services
kubectl rollout status deployment/mysql
kubectl rollout status deployment/student-api
kubectl logs deployment/student-api -c seed-students
```

## 4. Access the Kubernetes API locally

The API Service is internal to the cluster. Forward it to localhost:

```powershell
kubectl port-forward service/student-api 5000:5000
```

The Kubernetes API is then available at `http://localhost:5000`.

## Remove the Kubernetes deployment

```powershell
kubectl delete -k k8s
```

Delete the database data only when required:

```powershell
kubectl delete pvc mysql-data
```

# API usage

Both Docker and Kubernetes expose the same Flask API.

## Swagger documentation

Swagger UI:

```text
http://localhost:5000/docs/
```

OpenAPI JSON:

```text
http://localhost:5000/swagger.json
```

## Authenticate

```powershell
$login = Invoke-RestMethod -Method Post `
  -Uri http://localhost:5000/api/auth/login `
  -ContentType 'application/json' `
  -Body '{"username":"apiuser","password":"your-api-password"}'
$headers = @{ Authorization = "Bearer $($login.access_token)" }
```

## Health check

```powershell
Invoke-RestMethod http://localhost:5000/health
```

## Filter and sort students

```powershell
Invoke-RestMethod `
  -Uri 'http://localhost:5000/api/students?page=1&per_page=25&city=London&sort_by=last_name&sort_order=asc' `
  -Headers $headers
```

Supported filters are `first_name`, `last_name`, `email`, `city`, `state`, and `country`. Sorting uses allow-listed fields and `asc` or `desc` order. Student endpoints require a JWT.

## Get one student

```powershell
Invoke-RestMethod `
  -Uri http://localhost:5000/api/students/1 `
  -Headers $headers
```
