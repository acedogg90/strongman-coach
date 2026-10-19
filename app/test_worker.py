"""
Test worker that tracks consecutive failures.

The worker stops and reports if the same test fails twice in a row.
This satisfies the acceptance criterion:
  "Worker stops and reports if the same test fails twice in a row"
"""

from __future__ import annotations


class Worker:
    """Tracks test results and stops on consecutive failures of the same test."""

    def __init__(self) -> None:
        self.last_failure: str | None = None
        self.should_stop: bool = False
        self.report_message: str | None = None

    def record_result(self, test_name: str, result: str) -> None:
        """Record a test result.

        If *result* is ``"failed"`` and the same test failed previously,
        the worker stops and sets a report message.
        A passing result resets the failure tracker.
        """
        if self.should_stop:
            return  # Already stopped; ignore further results

        if result == "failed":
            if self.last_failure == test_name:
                # Same test failed twice in a row — stop
                self.should_stop = True
                self.report_message = (
                    f"Worker stopped: test '{test_name}' failed twice in a row."
                )
            else:
                self.last_failure = test_name
        else:
            # Any non-failure resets the tracker
            self.last_failure = None
