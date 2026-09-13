# SQL Script Runner

This project provides a simple Python application that reads and executes a SQL script in a MySQL database. The application takes only the SQL file location as input. Database credentials are loaded from `.env` or from environment variables.

## Project Structure

```
sql-script-runner
├── app
│   ├── __init__.py
│   └── main.py
├── requirements.txt
├── Dockerfile
└── README.md
```

## Requirements

The application requires the following Python packages:

- `sqlalchemy`: For database interaction.
- `pymysql`: MySQL driver integration.
- `python-dotenv`: Loads local `.env` configuration.

## Getting Started

### Prerequisites

- Docker installed on your machine.
- A database server running and accessible with the appropriate credentials.

### Building the Docker Image

To build the Docker image for the application, navigate to the project directory and run:

```bash
docker build -t sql-script-runner .
```

### Configuring the Database

Create or update `.env` in the project root:

```dotenv
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_DATABASE=MyDatabase
MYSQL_USER=root
MYSQL_PASSWORD=your-password
```

Start the MySQL container with matching values:

```powershell
docker run --name mysql-db -e MYSQL_ROOT_PASSWORD=your-password -e MYSQL_DATABASE=MyDatabase -p 3306:3306 -d mysql:lts-oracle
```

### Running the Application

To run the application, use the following command:

```bash
python app\main.py path\to\script.sql
```

The script accepts exactly one argument: the SQL file path. MySQL statements ending in `;` are executed in one transaction. `DELIMITER` blocks are supported.

For Docker, pass the environment file and mount the SQL file:

```bash
docker run --rm --env-file .env -v "${PWD}:/scripts" sql-script-runner /scripts/script.sql
```

### Error Handling

The application is designed to handle exceptions gracefully. If there are issues with the SQL scripts or database connection, meaningful error messages will be returned.

### License

This project is licensed under the MIT License. See the LICENSE file for more details.
