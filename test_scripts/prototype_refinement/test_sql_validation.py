"""Unit tests for SQL statement parsing, safety validation, and dynamic routing.

Tests parse_sql_statements (including DELIMITER blocks), validate_statements
(rejecting destructive DROP/DELETE), state inference from SQL, and multi-server routing.
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "app"))

from sql_executor import (
    parse_sql_statements,
    validate_statements,
    infer_state_from_sql,
    resolve_mysql_host,
    resolve_mysql_database,
)
from state_populations import STATE_SERVER_MAP


class TestSqlValidation(unittest.TestCase):
    """Test suite for SQL parsing, security validation, and host resolution."""

    def test_parse_simple_statements(self):
        """Parse multiple statements delimited by semicolons."""
        sql = """
        ALTER TABLE student_maharashtra ADD COLUMN middle_name VARCHAR(80);
        CREATE INDEX idx_student_city ON student_maharashtra (city);
        """
        stmts = parse_sql_statements(sql)
        self.assertEqual(len(stmts), 2)
        self.assertIn("ALTER TABLE student_maharashtra", stmts[0])
        self.assertIn("CREATE INDEX idx_student_city", stmts[1])

    def test_parse_delimiter_block(self):
        """Parse stored procedure definitions enclosed in DELIMITER blocks."""
        sql = """
        DELIMITER //
        CREATE PROCEDURE GetStudentCount(OUT total INT)
        BEGIN
            SELECT COUNT(*) INTO total FROM student_karnataka;
        END //
        DELIMITER ;

        CREATE VIEW view_karnataka_summary AS SELECT city, COUNT(*) FROM student_karnataka GROUP BY city;
        """
        stmts = parse_sql_statements(sql)
        self.assertEqual(len(stmts), 2)
        self.assertIn("CREATE PROCEDURE GetStudentCount", stmts[0])
        self.assertIn("SELECT COUNT(*) INTO total", stmts[0])
        self.assertIn("CREATE VIEW view_karnataka_summary", stmts[1])

    def test_validate_statements_rejects_drop_database(self):
        """Forbidden statement 'DROP DATABASE' must be rejected."""
        stmts = ["DROP DATABASE students_db_maharashtra;"]
        with self.assertRaises(ValueError) as ctx:
            validate_statements(stmts)
        self.assertIn("forbidden DROP or DELETE", str(ctx.exception))

    def test_validate_statements_rejects_drop_table(self):
        """Forbidden statement 'DROP TABLE' must be rejected."""
        stmts = ["DROP TABLE student_bihar;"]
        with self.assertRaises(ValueError) as ctx:
            validate_statements(stmts)
        self.assertIn("forbidden DROP or DELETE", str(ctx.exception))

    def test_validate_statements_rejects_delete(self):
        """Forbidden statement 'DELETE' must be rejected."""
        stmts = ["DELETE FROM student_delhi WHERE student_id = 1;"]
        with self.assertRaises(ValueError) as ctx:
            validate_statements(stmts)
        self.assertIn("forbidden DROP or DELETE", str(ctx.exception))

    def test_validate_statements_allows_safe_ddl(self):
        """Safe DDL operations (ALTER, CREATE INDEX, CREATE VIEW) must pass validation."""
        safe_stmts = [
            "ALTER TABLE student_goa ADD COLUMN is_active TINYINT(1) DEFAULT 1;",
            "CREATE INDEX idx_email_hash ON student_goa (email(20));",
            "CREATE VIEW student_goa_active AS SELECT * FROM student_goa WHERE is_active = 1;",
        ]
        # Should execute without raising ValueError
        validate_statements(safe_stmts)

    def test_infer_state_from_sql(self):
        """Infer target Indian state code from table reference in SQL."""
        self.assertEqual(
            infer_state_from_sql("ALTER TABLE student_maharashtra ADD COLUMN test VARCHAR(10);"),
            "maharashtra"
        )
        self.assertEqual(
            infer_state_from_sql("CREATE INDEX idx_name ON student_uttar_pradesh (last_name);"),
            "uttar_pradesh"
        )
        self.assertEqual(
            infer_state_from_sql("SELECT * FROM student_andhra_pradesh LIMIT 10;"),
            "andhra_pradesh"
        )
        self.assertIsNone(
            infer_state_from_sql("SELECT 1;"),
            "Non-state query must return None"
        )

    def test_resolve_mysql_host_mapping(self):
        """Verify state mapping routes states to mysql-1 through mysql-7."""
        # Check all 28 states map deterministically to mysql-1 .. mysql-7
        for state_code, expected_server in STATE_SERVER_MAP.items():
            self.assertEqual(resolve_mysql_host(state_code), expected_server)

        # Check key states
        self.assertEqual(resolve_mysql_host("andhra_pradesh"), "mysql-1")
        self.assertEqual(resolve_mysql_host("maharashtra"), "mysql-4")
        self.assertEqual(resolve_mysql_host("uttar_pradesh"), "mysql-7")

        # Fallback when state is None
        self.assertEqual(resolve_mysql_host(None), "127.0.0.1")

    def test_resolve_mysql_database(self):
        """Verify per-state database suffix resolution."""
        self.assertEqual(resolve_mysql_database("students_db", "maharashtra"), "students_db_maharashtra")
        self.assertEqual(resolve_mysql_database("students_db", "bihar"), "students_db_bihar")
        self.assertEqual(resolve_mysql_database("students_db", None), "students_db")


if __name__ == "__main__":
    unittest.main()
