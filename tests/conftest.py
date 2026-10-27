"""Shared pytest configuration for strongman-coach tests.

Sets required environment variables before any test imports occur.
"""

import os

# Ensure SESSION_SECRET is set before app.routes is imported
if "SESSION_SECRET" not in os.environ:
    os.environ["SESSION_SECRET"] = "test-secret-key-for-testing-only"
