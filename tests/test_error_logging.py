"""A 500 must log its real cause to the server console (Owner report: signup said only "Failed to create user")."""
import logging

from fastapi.testclient import TestClient

import app.routes as routes


def test_signup_500_logs_the_real_cause(monkeypatch, caplog):
    def boom(_password):
        raise ValueError("password cannot be longer than 72 bytes")
    monkeypatch.setattr(routes, "_hash_password", boom)
    with TestClient(routes.app) as client, caplog.at_level(logging.ERROR, logger="uvicorn.error"):
        r = client.post("/auth/signup", json={"email": "log-test@example.com", "password": "Password1!"})
    assert r.status_code == 500 and r.json()["detail"] == "Failed to create user"
    rec = [x for x in caplog.records if x.getMessage() == "Failed to create user"]
    assert rec and rec[0].exc_info and "72 bytes" in str(rec[0].exc_info[1])
