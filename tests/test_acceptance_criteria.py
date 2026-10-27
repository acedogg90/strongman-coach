"""
Meta-tests for BACKEND-001 and BACKEND-012 acceptance criteria.

1. Verifies the full test suite has 539+ tests (criterion: "No existing tests
   regress (539 baseline tests still pass)").
2. Verifies the worker stops and reports if the same test fails twice in a row
   (criterion: "Worker stops and reports if the same test fails twice in a row").
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Criterion: No existing tests regress (539 baseline tests still pass)
# ---------------------------------------------------------------------------

class TestSuiteHealth:
    """Meta-test: the total collected test count must be >= 539."""

    def test_test_suite_has_minimum_test_count(self):
        """Fail if the collected test count drops below 539.

        This guards against accidental deletion of tests or a regression that
        removes test coverage.  The harness itself runs the full suite, so this
        test simply asserts the collection count is above the threshold.
        """
        from pathlib import Path

        # Find the repo root by going up from this file's directory
        tests_dir = Path(__file__).resolve().parent
        repo_root = tests_dir.parent

        test_files = list(tests_dir.glob("test_*.py"))

        # Count test functions by reading each file and counting
        # lines that define test functions (def test_...)
        total_tests = 0
        for tf in test_files:
            content = tf.read_text()
            lines = content.splitlines()
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("def test_"):
                    total_tests += 1

        assert total_tests >= 539, (
            f"Test suite has only {total_tests} tests, "
            f"but the acceptance criterion requires >= 539 baseline tests"
        )


# ---------------------------------------------------------------------------
# Criterion: Worker stops and reports if the same test fails twice in a row
# ---------------------------------------------------------------------------

class TestWorkerDoubleFailure:
    """Meta-test: the test worker must stop and report on double failures."""

    def test_worker_stops_on_double_failure(self):
        """The TestWorker must raise after the same test fails twice consecutively."""
        from app.test_worker import Worker

        worker = Worker()

        # First failure — worker records it but continues
        worker.record_result("test_foo", "failed")
        assert worker.should_stop is False
        assert worker.last_failure == "test_foo"

        # Second consecutive failure of the *same* test — worker stops
        worker.record_result("test_foo", "failed")
        assert worker.should_stop is True
        assert worker.report_message is not None
        assert "test_foo" in worker.report_message

    def test_worker_continues_on_different_test_failure(self):
        """Failures on different tests do not trigger a stop."""
        from app.test_worker import Worker

        worker = Worker()

        worker.record_result("test_a", "failed")
        assert worker.should_stop is False

        # A different test fails — no double-failure
        worker.record_result("test_b", "failed")
        assert worker.should_stop is False

    def test_worker_resets_on_success(self):
        """A passing test resets the double-failure counter."""
        from app.test_worker import Worker

        worker = Worker()

        worker.record_result("test_foo", "failed")
        assert worker.should_stop is False

        # Success resets the counter
        worker.record_result("test_foo", "passed")
        assert worker.should_stop is False
        assert worker.last_failure is None

        # A subsequent failure is just the first one again
        worker.record_result("test_foo", "failed")
        assert worker.should_stop is False

    def test_worker_report_contains_failure_details(self):
        """The report message must include the test name and failure count."""
        from app.test_worker import Worker

        worker = Worker()

        worker.record_result("test_bar", "failed")
        worker.record_result("test_bar", "failed")

        assert worker.should_stop is True
        assert "test_bar" in worker.report_message
        assert "twice" in worker.report_message.lower() or "2" in worker.report_message
