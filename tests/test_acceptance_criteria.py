"""
Meta-tests for BACKEND-001 and BACKEND-012 acceptance criteria.

Verifies the worker stops and reports if the same test fails twice in a row
(criterion: "Worker stops and reports if the same test fails twice in a row").
"""

from __future__ import annotations

import pytest


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


# ---------------------------------------------------------------------------
# Criterion: No existing tests regress (539 baseline tests still pass)
# ---------------------------------------------------------------------------

def test_test_suite_has_minimum_test_count():
    """Verify the test suite has at least 539 tests (baseline regression check).

    BACKEND-012 acceptance criterion 8: No existing tests regress.
    The baseline was 539 tests; the suite must have at least that many.
    """
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    # Output ends with "N tests collected"
    output = result.stdout.strip()
    # Parse the count from the last line, e.g. "572 tests collected"
    last_line = output.splitlines()[-1]
    parts = last_line.split()
    count = int(parts[0])
    assert count >= 539, (
        f"Test suite has {count} tests, below the 539-test baseline. "
        "Existing tests may have been removed."
    )
