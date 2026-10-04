"""Unit tests for REST API authentication, JWT handling, and endpoint protection.

Tests /api/auth/login with valid and invalid credentials, token verification,
unauthorized access rejection on protected routes (/api/students, /api/sql/execute),
and public accessibility of /health and /metrics.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "app"))

# Ensure environment variables for testing
os.environ["API_USERNAME"] = "testuser"
os.environ["API_PASSWORD"] = "testpassword123"
os.environ["JWT_SECRET_KEY"] = "super-secret-test-key-for-jwt-verification-minimum-32bytes"

from api import app


class TestApiAuthentication(unittest.TestCase):
    """Test suite for JWT authentication and protected REST API endpoints."""

    def setUp(self):
        self.app = app
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()
        self.username = "testuser"
        self.password = "testpassword123"

    @patch("api.get_engine_for_state")
    def test_health_endpoint_is_public(self, mock_get_engine):
        """GET /health must be accessible without any JWT token."""
        mock_conn = MagicMock()
        mock_get_engine.return_value.connect.return_value.__enter__.return_value = mock_conn
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn("status", data)
        self.assertEqual(data["status"], "ok")

    def test_metrics_endpoint_is_public(self):
        """GET /metrics must return Prometheus text format without authentication."""
        response = self.client.get("/metrics")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"student_api_requests_total", response.data)

    def test_login_success(self):
        """POST /api/auth/login with correct credentials must return 200 and access_token."""
        response = self.client.post(
            "/api/auth/login",
            json={"username": self.username, "password": self.password}
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn("access_token", data)
        self.assertTrue(len(data["access_token"]) > 20)

    def test_login_invalid_password(self):
        """POST /api/auth/login with incorrect password must return 401."""
        response = self.client.post(
            "/api/auth/login",
            json={"username": self.username, "password": "wrong-password"}
        )
        self.assertEqual(response.status_code, 401)
        data = response.get_json()
        self.assertIn("message", data)
        self.assertEqual(data["message"], "Invalid credentials")

    def test_login_invalid_username(self):
        """POST /api/auth/login with incorrect username must return 401."""
        response = self.client.post(
            "/api/auth/login",
            json={"username": "unknown_user", "password": self.password}
        )
        self.assertEqual(response.status_code, 401)

    def test_login_empty_body(self):
        """POST /api/auth/login with empty or missing payload must return 401."""
        response = self.client.post("/api/auth/login", json={})
        self.assertEqual(response.status_code, 401)

    def test_protected_students_route_without_token(self):
        """GET /api/students without Authorization header must return 401."""
        response = self.client.get("/api/students")
        self.assertEqual(response.status_code, 401)
        data = response.get_json()
        self.assertIn("message", data)
        self.assertIn("valid Bearer JWT is required", data["message"])

    def test_protected_students_route_with_malformed_token(self):
        """GET /api/students with invalid/malformed token must return 401."""
        headers = {"Authorization": "Bearer not-a-valid-jwt-token"}
        response = self.client.get("/api/students", headers=headers)
        self.assertEqual(response.status_code, 401)

    def test_protected_sql_execute_route_without_token(self):
        """POST /api/sql/execute without Authorization header must return 401."""
        response = self.client.post("/api/sql/execute", json={"sql": "SELECT 1;"})
        self.assertEqual(response.status_code, 401)

    @patch("api.get_engine_for_state")
    def test_protected_route_with_valid_token(self, mock_get_engine):
        """GET /api/students?state=goa with valid JWT token must be authorized and processed."""
        # 1. Obtain token
        login_res = self.client.post(
            "/api/auth/login",
            json={"username": self.username, "password": self.password}
        )
        token = login_res.get_json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Mock database response
        mock_conn = MagicMock()
        mock_conn.execute.return_value.scalar_one.return_value = 0
        mock_conn.execute.return_value.fetchall.return_value = []
        mock_get_engine.return_value.connect.return_value.__enter__.return_value = mock_conn

        # 2. Call protected route
        response = self.client.get("/api/students?state=goa", headers=headers)
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn("data", data)
        self.assertEqual(data["pagination"]["total"], 0)


if __name__ == "__main__":
    unittest.main()
