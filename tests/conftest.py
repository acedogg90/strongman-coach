"""Shared pytest configuration for strongman-coach tests.

Sets required environment variables before any test imports occur.
"""

import os

# Ensure SESSION_SECRET is set before app.routes is imported
if "SESSION_SECRET" not in os.environ:
    os.environ["SESSION_SECRET"] = "test-secret-key-for-testing-only"


def authenticate_client(client):
    """Log in a test user and store the session cookie on the client.

    Creates a user via signup, logs in, and ensures the client carries
    the session cookie for subsequent authenticated requests.
    """
    # Signup
    client.post(
        "/auth/signup",
        json={"email": "test@example.com", "password": "testpass123"},
    )
    # Login
    resp = client.post(
        "/auth/login",
        json={"email": "test@example.com", "password": "testpass123"},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
