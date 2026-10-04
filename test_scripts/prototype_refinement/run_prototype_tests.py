"""Consolidated test runner for prototype refinement milestone tests.

Executes:
1. test_model_fitting.py (Ensemble forecaster, lag features, fallback)
2. test_recommendation_bounds.py (Horizontal max(Rf,Rq), vertical bounds, deadbands)
3. test_sql_validation.py (Statement parser, DROP/DELETE rejection, safe DDL, 7-host routing)
4. test_api_auth.py (JWT authentication, login, endpoint protection)
"""

import sys
import unittest
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = MODULE_DIR.parents[1]

# Ensure app directory is importable
sys.path.insert(0, str(PROJECT_ROOT / "app"))
sys.path.insert(0, str(MODULE_DIR))


def run_prototype_suite():
    """Discover and execute all prototype refinement unit tests."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    test_modules = [
        "test_model_fitting",
        "test_recommendation_bounds",
        "test_sql_validation",
        "test_api_auth",
    ]

    print("=" * 70)
    print("PROTOTYPE REFINEMENT - FOCUSED UNIT TEST SUITE")
    print("=" * 70)

    for mod_name in test_modules:
        try:
            mod = __import__(mod_name)
            loaded_suite = loader.loadTestsFromModule(mod)
            suite.addTests(loaded_suite)
            print(f"  [DISCOVERED] {mod_name} ({loaded_suite.countTestCases()} test cases)")
        except Exception as e:
            print(f"  [ERROR] Failed to load {mod_name}: {e}")

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("-" * 70)
    print(f"Total Tests Run: {result.testsRun}")
    print(f"Passed: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print("=" * 70)

    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_prototype_suite())
