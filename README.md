# Student Database Service

This project provides MySQL tables for synthetic student records across all 28 Indian states and a secured Flask REST API. It can run in either:

- Standalone Docker containers.
- Kubernetes using the manifests in `k8s/`.

The records contain first name, last name, date of birth, email, phone number, city, state, and enrollment date. Each state has its own table, such as `student_maharashtra` and `student_uttar_pradesh`.

State allocations use Census 2011 population figures. The generator assumes
30% of each state's population are students and creates
`round(population × 0.30)` records for that state. There is no maximum cap;
therefore Uttar Pradesh, the most populous state, receives the largest table.

## Project structure

```text
├── app/
│   ├── api.py                  # Flask API and Swagger UI
│   └── main.py                 # SQL file runner
├── database/
│   ├── init/01_students_schema.sql
│   └── seed_students.py        # Census-proportional state-table generator
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
API_USERNAME=apiuser
API_PASSWORD=your-api-password
JWT_SECRET_KEY=your-long-random-secret
JWT_ACCESS_TOKEN_EXPIRES_MINUTES=60
API_PORT=5000
```

Never commit `.env` or `k8s/secret.yaml` with real credentials.

### Configuration variables

| Variable                           | Used by          | Purpose                                                                                              |
| ---------------------------------- | ---------------- | ---------------------------------------------------------------------------------------------------- |
| `MYSQL_HOST`                       | API/seeder       | MySQL hostname; use `student-mysql` in Docker and `mysql` in Kubernetes.                             |
| `MYSQL_PORT`                       | API/seeder       | MySQL port, normally `3306`.                                                                         |
| `MYSQL_DATABASE`                   | API/seeder/MySQL | Database containing metadata and state tables.                                                       |
| `MYSQL_USER`                       | API/seeder       | MySQL account used by the application.                                                               |
| `MYSQL_PASSWORD`                   | API/seeder       | Password for `MYSQL_USER`; the MySQL container receives it as `MYSQL_ROOT_PASSWORD` when using root. |
| `STUDENT_BATCH_SIZE`               | Seeder           | Number of records inserted per transaction batch.                                                    |
| `STUDENT_SEED_WORKERS`             | Seeder           | Number of state tables seeded concurrently; default is `4`.                                          |
| `API_USERNAME`                     | API              | Login username for JWT issuance.                                                                     |
| `API_PASSWORD`                     | API              | Login password for JWT issuance.                                                                     |
| `JWT_SECRET_KEY`                   | API              | Private signing key; never send it as a bearer token.                                                |
| `JWT_ACCESS_TOKEN_EXPIRES_MINUTES` | API              | Lifetime of issued access tokens.                                                                    |
| `API_HOST` / `API_PORT`            | API              | Flask bind address and listening port.                                                               |

## Prometheus metrics

The API exposes Prometheus-compatible metrics at:

```text
http://localhost:5000/metrics
```

The metrics include:

- `student_api_requests_total` — request count labeled by HTTP method, endpoint, and status code.
- `student_api_response_duration_seconds` — response-time histogram labeled by HTTP method and endpoint.

Prometheus can scrape the endpoint with:

```yaml
scrape_configs:
  - job_name: student-api
    static_configs:
      - targets: ["localhost:5000"]
```

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

Do not pass the full `.env` file to MySQL. It contains `MYSQL_USER=root`,
which the MySQL image rejects because `MYSQL_USER` is reserved for creating a
non-root user. Configure the root password with `MYSQL_ROOT_PASSWORD` instead:

```powershell
docker run -d --name student-mysql --network student-network `
  -e MYSQL_DATABASE=students_db `
  -e MYSQL_ROOT_PASSWORD=your-mysql-password `
  -p 3306:3306 `
  -v student-mysql-data:/var/lib/mysql `
  mysql:lts-oracle
```

The named volume is the database's persistent storage. Existing state tables
and rows are not stored in the application image; they are stored in
`student-mysql-data`. Keep using the same volume and do not run
`docker volume rm student-mysql-data` if existing data must be preserved.

Use the same password as `MYSQL_PASSWORD` in `.env`. `MYSQL_PASSWORD` is used
by the application to connect as `MYSQL_USER`; for the current setup that user
is `root`, so the application receives the root password through its own
container environment.

Wait for MySQL:

```powershell
docker exec student-mysql mysqladmin ping -h 127.0.0.1 -uroot -pyour-mysql-password --wait=60
```

## 4. Create the schema and seed all state tables

The application container connects to the database through the Docker service name `student-mysql`:

```powershell
docker run --rm --name student-seeder --network student-network `
  --env-file .env `
  -e MYSQL_HOST=student-mysql `
  -e MYSQL_USER=root `
  -e MYSQL_PASSWORD=your-mysql-password `
  student-api:1.0.0 `
  sh -c "python main.py /database/init/01_students_schema.sql && python /database/seed_students.py --workers 4"
```

The seeder uses bounded parallelism: each worker owns its own SQLAlchemy
connection and seeds a different state table. Increase `--workers` or set
`STUDENT_SEED_WORKERS` only when the MySQL server has enough CPU, memory, and
connections. `--batch-size` controls rows per insert batch independently.

Seeding is additive. Existing state tables are preserved, and existing rows
are counted before insertion. If a table already has the target number of
records, it is skipped; if it has fewer, only the missing records are added.

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
```

Only remove the volume when intentionally deleting all database data:

```powershell
docker volume rm student-mysql-data
```

# Option 2: Run with Kubernetes

The Kubernetes configuration creates two Services:

- `mysql`: ClusterIP Service backed by a persistent `mysql:lts-oracle` Deployment.
- `student-api`: ClusterIP Service backed by the Flask API Deployment.

The API pod has an init container that creates the metadata schema and seeds one table per Indian state before the API starts. Non-sensitive settings come from `student-app-config` (`ConfigMap`); credentials come from `student-app-secrets` (`Secret`).

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

## API usage

Both Docker and Kubernetes expose the same Flask API.

### Step 1: Start the API

Choose one environment first:

- Docker: complete the Docker steps above and confirm the API container is running with `docker ps`.
- Kubernetes: run `kubectl port-forward service/student-api 5000:5000` and keep that terminal open.

All examples below use the base URL `http://localhost:5000`.

## Swagger documentation

Swagger UI:

```text
http://localhost:5000/docs/
```

OpenAPI JSON:

```text
http://localhost:5000/swagger.json
```

Swagger provides an interactive way to call every endpoint. Open `/docs/`, use
`POST /api/auth/login` to obtain a token, click **Authorize**, enter `Bearer`
followed by the token, and then try the protected student endpoints.

### Step 2: Authenticate and save the JWT

Use the same username and password configured in `.env` for Docker or in
`k8s/secret.yaml` for Kubernetes:

```powershell
$login = Invoke-RestMethod -Method Post `
  -Uri http://localhost:5000/api/auth/login `
  -ContentType 'application/json' `
  -Body '{"username":"apiuser","password":"your-api-password"}'
$headers = @{ Authorization = "Bearer $($login.access_token)" }
```

The token is valid for the number of minutes configured by
`JWT_ACCESS_TOKEN_EXPIRES_MINUTES`. Send it on protected requests using the
`Authorization` header. Use the value returned in `access_token`; do not use
the `JWT_SECRET_KEY` value as a bearer token. The secret signs tokens and is
never sent to the API in a request.

If you receive `401 A valid Bearer JWT is required`, request a fresh token and
make sure the header has exactly this format:

```powershell
$headers = @{ Authorization = "Bearer $($login.access_token)" }
```

Do not send an empty token, the word `Bearer` by itself, or the JWT secret.

### Step 3: Check API and database health

```powershell
Invoke-RestMethod http://localhost:5000/health
```

Expected response:

```json
{ "status": "ok" }
```

### Step 4: List students

The student list endpoint is paginated. The default page size is 50 and the
maximum page size is 1,000:

```powershell
Invoke-RestMethod `
  -Uri 'http://localhost:5000/api/students?page=1&per_page=10' `
  -Headers $headers
```

The response contains a `data` array and pagination metadata:

```json
{
  "data": [],
  "pagination": {
    "page": 1,
    "per_page": 10,
    "total": "sum of all state-table records",
    "pages": "calculated from total and per_page"
  }
}
```

### Step 5: Filter and sort students

Use `state=maharashtra` to query one state table. If omitted, the API queries
all state tables. Supported filters are case-insensitive partial matches:

- `first_name`
- `last_name`
- `email`
- `city`

The supported state codes include `maharashtra`, `uttar_pradesh`, `karnataka`,
and all other Indian states defined in `app/state_populations.py`.

Supported sorting parameters are:

- `sort_by`: an allow-listed student field such as `student_id`, `last_name`, `city`, or `enrollment_date`.
- `sort_order`: `asc` or `desc`.

Example filtering and sorting one state's table:

```powershell
Invoke-RestMethod `
  -Uri 'http://localhost:5000/api/students?state=maharashtra&page=1&per_page=25&sort_by=last_name&sort_order=asc' `
  -Headers $headers
```

Student endpoints require a JWT. Invalid or missing tokens return `401`; an
invalid sort field or request parameter returns `400`.

### Step 7: Execute a SQL script

The authenticated SQL endpoint accepts the target database in the request, so
the API can work with multiple MySQL databases:

```powershell
$sqlBody = @{
  database = "students_db"
  sql = "CREATE TABLE IF NOT EXISTS student_maharashtra_notes (note_id INT PRIMARY KEY, note_text VARCHAR(255));"
  rollback = $false
} | ConvertTo-Json

Invoke-RestMethod -Method Post `
  -Uri http://localhost:5000/api/sql/execute `
  -Headers $headers `
  -ContentType "application/json" `
  -Body $sqlBody
```

The request fields are:

- `database` — required MySQL database/schema name. Only letters, numbers, and underscores are accepted.
- `sql` — required SQL script. Multiple statements and MySQL `DELIMITER` blocks are supported.
- `rollback` — optional boolean, default `false`.
- `rollback_sql` — required when `rollback=true` is used with `ALTER TABLE`; provide the inverse ALTER statement.

`DROP` and `DELETE` are rejected before execution. `CREATE`, `ALTER`, `INSERT`,
`UPDATE`, and other non-destructive statements are allowed. ALTER operations
are queued per table so concurrent changes to the same table execute one at a
time. The response includes `status`, `statement_count`, `started_at`,
`finished_at`, `duration_ms`, and queued table names.

Example ALTER with an explicit inverse:

```powershell
$alterBody = @{
  database = "students_db"
  sql = "ALTER TABLE student_maharashtra RENAME COLUMN city TO city_name;"
  rollback = $true
  rollback_sql = "ALTER TABLE student_maharashtra RENAME COLUMN city_name TO city;"
} | ConvertTo-Json

Invoke-RestMethod -Method Post `
  -Uri http://localhost:5000/api/sql/execute `
  -Headers $headers `
  -ContentType "application/json" `
  -Body $alterBody
```

MySQL implicitly commits most DDL statements. Therefore an ALTER cannot be
rolled back by a normal transaction; the optional `rollback_sql` is an explicit
inverse script that the service executes after the requested ALTER. Do not put
`DROP` or `DELETE` in the inverse script because the same safety policy applies.

### Step 6: Get one student

```powershell
Invoke-RestMethod `
  -Uri 'http://localhost:5000/api/students/1?state=maharashtra' `
  -Headers $headers
```

This returns the student with the requested numeric ID from the selected state
table. Include `?state=maharashtra` because IDs are local to each state table.
If the ID does not exist, the API returns `404`.

### API endpoint summary

| Method | Endpoint                     | Authentication    | Purpose                                   |
| ------ | ---------------------------- | ----------------- | ----------------------------------------- |
| `GET`  | `/health`                    | None              | Check API/database availability           |
| `POST` | `/api/auth/login`            | Username/password | Issue a JWT                               |
| `GET`  | `/api/students`              | Bearer JWT        | List, filter, sort, and paginate students |
| `GET`  | `/api/students/{student_id}` | Bearer JWT        | Get one student                           |
| `POST` | `/api/sql/execute`           | Bearer JWT        | Execute a validated SQL script            |
