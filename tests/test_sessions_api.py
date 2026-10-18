"""
Tests for the session API endpoints (POST /api/sessions, POST /api/sessions/{id}/sets,
PATCH /api/sessions/{id}/complete, GET /api/sessions).

Covers:
- Creating sessions with correct day type and block phase
- Logging sets with exercise, weight, reps, rpe, set_type
- Completing sessions and triggering adjustment rule checks
- Retrieving session history filtered by date range, day type, or block phase
"""

import datetime
import pytest
from fastapi.testclient import TestClient

from app.routes import app, _get_session
from app.database import (
    Base,
    Session as DBSession,
    Program,
    Block,
    Cycle,
    Exercise,
    Prescription,
    SetLog,
    get_engine,
    reset_db,
)


@pytest.fixture()
def db_url(tmp_path):
    """Provide a file-based SQLite database URL for each test."""
    db_file = tmp_path / "test_sessions.db"
    return f"sqlite:///{db_file}"


@pytest.fixture()
def client(db_url):
    """Create a TestClient with a fresh database for each test."""
    import app.database as db_mod
    db_mod._engine = None
    db_mod._session_factory = None
    get_engine(db_url)
    reset_db(db_url)
    return TestClient(app)


# ---------------------------------------------------------------------------
# POST /api/sessions – Create a new session
# ---------------------------------------------------------------------------

class TestCreateSession:
    def test_create_session_day_a(self, client):
        """Creating a session with day_label A returns 200."""
        resp = client.post("/api/sessions", json={
            "day_label": "A",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["day_label"] == "A"
        assert data["status"] == "in_progress"
        assert "id" in data
        assert data["block_phase"] is not None

    def test_create_session_day_b(self, client):
        resp = client.post("/api/sessions", json={"day_label": "B"})
        assert resp.status_code == 200
        assert resp.json()["day_label"] == "B"

    def test_create_session_day_c(self, client):
        resp = client.post("/api/sessions", json={"day_label": "C"})
        assert resp.status_code == 200
        assert resp.json()["day_label"] == "C"

    def test_create_session_day_d(self, client):
        resp = client.post("/api/sessions", json={"day_label": "D"})
        assert resp.status_code == 200
        assert resp.json()["day_label"] == "D"

    def test_create_session_invalid_day(self, client):
        resp = client.post("/api/sessions", json={"day_label": "X"})
        assert resp.status_code == 400

    def test_create_session_with_scheduled_date(self, client):
        future = (datetime.date.today() + datetime.timedelta(days=7)).isoformat()
        resp = client.post("/api/sessions", json={
            "day_label": "A",
            "scheduled_date": future,
        })
        assert resp.status_code == 200
        assert resp.json()["scheduled_date"] == future

    def test_create_session_with_readiness(self, client):
        resp = client.post("/api/sessions", json={
            "day_label": "A",
            "readiness_sleep": 4,
            "readiness_soreness": 3,
            "readiness_stress": 2,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["readiness_sleep"] == 4
        assert data["readiness_soreness"] == 3
        assert data["readiness_stress"] == 2

    def test_create_session_returns_block_phase(self, client):
        resp = client.post("/api/sessions", json={"day_label": "A"})
        assert resp.status_code == 200
        assert resp.json()["block_phase"] in ("accumulation", "intensification", "realization")

    def test_create_session_response_shape(self, client):
        resp = client.post("/api/sessions", json={"day_label": "A"})
        data = resp.json()
        assert "id" in data
        assert "cycle_id" in data
        assert "day_label" in data
        assert "scheduled_date" in data
        assert "status" in data
        assert "block_phase" in data


# ---------------------------------------------------------------------------
# POST /api/sessions/{id}/sets – Log a set
# ---------------------------------------------------------------------------

class TestLogSet:
    def _create_session(self, client, day_label="A"):
        resp = client.post("/api/sessions", json={"day_label": day_label})
        assert resp.status_code == 200
        return resp.json()["id"]

    def test_log_top_set(self, client):
        sid = self._create_session(client)
        resp = client.post(f"/api/sessions/{sid}/sets", json={
            "exercise_name": "Deadlift",
            "weight": 315,
            "reps": 5,
            "rpe": 8.0,
            "set_type": "top",
        })
        if resp.status_code != 200:
            print(f"ERROR: {resp.status_code} - {resp.text}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["exercise_name"] == "Deadlift"
        assert data["actual_load_lb"] == 315
        assert data["actual_reps"] == 5
        assert data["rpe"] == 8.0
        assert data["set_type"] == "top"
        assert data["e1rm_lb"] is not None

    def test_log_warmup_set(self, client):
        sid = self._create_session(client)
        resp = client.post(f"/api/sessions/{sid}/sets", json={
            "exercise_name": "Squat",
            "weight": 135,
            "reps": 10,
            "rpe": None,
            "set_type": "warmup",
        })
        assert resp.status_code == 200
        assert resp.json()["set_type"] == "warmup"

    def test_log_backoff_set(self, client):
        sid = self._create_session(client)
        resp = client.post(f"/api/sessions/{sid}/sets", json={
            "exercise_name": "Bench Press",
            "weight": 185,
            "reps": 5,
            "rpe": 7.5,
            "set_type": "backoff",
        })
        assert resp.status_code == 200
        assert resp.json()["set_type"] == "backoff"

    def test_log_apre_set(self, client):
        sid = self._create_session(client)
        resp = client.post(f"/api/sessions/{sid}/sets", json={
            "exercise_name": "Overhead Press",
            "weight": 95,
            "reps": 8,
            "rpe": 9.0,
            "set_type": "apre",
        })
        assert resp.status_code == 200
        assert resp.json()["set_type"] == "apre"

    def test_log_set_with_pain_flag(self, client):
        sid = self._create_session(client)
        resp = client.post(f"/api/sessions/{sid}/sets", json={
            "exercise_name": "Deadlift",
            "weight": 315,
            "reps": 5,
            "rpe": 8.0,
            "set_type": "top",
            "pain_flag": True,
        })
        assert resp.status_code == 200
        assert resp.json()["pain_flag"] is True

    def test_log_set_invalid_set_type(self, client):
        sid = self._create_session(client)
        resp = client.post(f"/api/sessions/{sid}/sets", json={
            "exercise_name": "Deadlift",
            "weight": 315,
            "reps": 5,
            "rpe": 8.0,
            "set_type": "invalid",
        })
        assert resp.status_code == 400

    def test_log_set_nonexistent_session(self, client):
        resp = client.post("/api/sessions/99999/sets", json={
            "exercise_name": "Deadlift",
            "weight": 315,
            "reps": 5,
            "rpe": 8.0,
            "set_type": "top",
        })
        assert resp.status_code == 404

    def test_log_set_completed_session(self, client):
        sid = self._create_session(client)
        # Complete the session first
        client.patch(f"/api/sessions/{sid}/complete")
        # Now try to log a set
        resp = client.post(f"/api/sessions/{sid}/sets", json={
            "exercise_name": "Deadlift",
            "weight": 315,
            "reps": 5,
            "rpe": 8.0,
            "set_type": "top",
        })
        assert resp.status_code == 400

    def test_log_set_creates_exercise(self, client):
        """Logging a set with a new exercise name should create it."""
        sid = self._create_session(client)
        resp = client.post(f"/api/sessions/{sid}/sets", json={
            "exercise_name": "Atlas Stone",
            "weight": 200,
            "reps": 5,
            "rpe": 8.0,
            "set_type": "top",
        })
        assert resp.status_code == 200
        assert resp.json()["exercise_name"] == "Atlas Stone"

    def test_log_set_response_shape(self, client):
        sid = self._create_session(client)
        resp = client.post(f"/api/sessions/{sid}/sets", json={
            "exercise_name": "Deadlift",
            "weight": 315,
            "reps": 5,
            "rpe": 8.0,
            "set_type": "top",
        })
        data = resp.json()
        assert "id" in data
        assert "exercise_name" in data
        assert "actual_load_lb" in data
        assert "actual_reps" in data
        assert "rpe" in data
        assert "e1rm_lb" in data
        assert "confidence" in data
        assert "set_type" in data


# ---------------------------------------------------------------------------
# PATCH /api/sessions/{id}/complete – Complete a session
# ---------------------------------------------------------------------------

class TestCompleteSession:
    def _create_session(self, client, day_label="A"):
        resp = client.post("/api/sessions", json={"day_label": day_label})
        assert resp.status_code == 200
        return resp.json()["id"]

    def _create_session_with_sets(self, client, day_label="A"):
        sid = self._create_session(client, day_label)
        # Log a top set
        client.post(f"/api/sessions/{sid}/sets", json={
            "exercise_name": "Deadlift",
            "weight": 315,
            "reps": 5,
            "rpe": 8.0,
            "set_type": "top",
        })
        return sid

    def test_complete_session(self, client):
        sid = self._create_session(client)
        resp = client.patch(f"/api/sessions/{sid}/complete")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert "adjustments" in data

    def test_complete_session_already_completed(self, client):
        sid = self._create_session(client)
        client.patch(f"/api/sessions/{sid}/complete")
        resp = client.patch(f"/api/sessions/{sid}/complete")
        assert resp.status_code == 400

    def test_complete_nonexistent_session(self, client):
        resp = client.patch("/api/sessions/99999/complete")
        assert resp.status_code == 404

    def test_complete_session_response_shape(self, client):
        sid = self._create_session(client)
        resp = client.patch(f"/api/sessions/{sid}/complete")
        data = resp.json()
        assert "session_id" in data
        assert "status" in data
        assert "adjustments" in data
        assert "skip_backoffs" in data
        assert "allow_extra_set" in data
        assert "early_deload" in data
        assert "pain_flags" in data

    def test_complete_triggers_adjustment_rpe_too_high(self, client):
        """If top-set RPE >= target + 1.0, skip back-offs."""
        sid = self._create_session(client)
        # Log a top set with RPE 9.5 (target is 8.0 from prescription)
        client.post(f"/api/sessions/{sid}/sets", json={
            "exercise_name": "Deadlift",
            "weight": 315,
            "reps": 5,
            "rpe": 9.5,
            "set_type": "top",
        })
        # Set prescribed_rpe on the prescription
        db = _get_session()
        try:
            pres = db.query(Prescription).filter_by(session_id=sid).first()
            if pres:
                pres.prescribed_rpe = 8.0
            db.commit()
        finally:
            db.close()

        resp = client.patch(f"/api/sessions/{sid}/complete")
        assert resp.status_code == 200
        data = resp.json()
        assert data["skip_backoffs"] is True

    def test_complete_triggers_pain_flag(self, client):
        """Pain flag on any set should show in adjustments."""
        sid = self._create_session(client)
        client.post(f"/api/sessions/{sid}/sets", json={
            "exercise_name": "Deadlift",
            "weight": 315,
            "reps": 5,
            "rpe": 8.0,
            "set_type": "top",
            "pain_flag": True,
        })
        resp = client.patch(f"/api/sessions/{sid}/complete")
        assert resp.status_code == 200
        data = resp.json()
        # pain_flags should contain the exercise name
        assert len(data["pain_flags"]) > 0
        # pain_flags is a list of dicts with "exercise" key
        exercise_names = [pf["exercise"] for pf in data["pain_flags"]]
        assert "Deadlift" in exercise_names


# ---------------------------------------------------------------------------
# GET /api/sessions – Get session history
# ---------------------------------------------------------------------------

class TestGetSessions:
    def _create_session(self, client, day_label="A", scheduled_date=None):
        payload = {"day_label": day_label}
        if scheduled_date:
            payload["scheduled_date"] = scheduled_date
        resp = client.post("/api/sessions", json=payload)
        assert resp.status_code == 200
        return resp.json()["id"]

    def test_get_all_sessions(self, client):
        self._create_session(client, "A")
        self._create_session(client, "B")
        resp = client.get("/api/sessions")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 2

    def test_filter_by_day_type(self, client):
        self._create_session(client, "A")
        self._create_session(client, "B")
        self._create_session(client, "A")
        resp = client.get("/api/sessions", params={"day_type": "A"})
        assert resp.status_code == 200
        data = resp.json()
        for s in data:
            assert s["day_label"] == "A"

    def test_filter_by_date_from(self, client):
        today = datetime.date.today().isoformat()
        tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
        self._create_session(client, "A", scheduled_date=today)
        self._create_session(client, "B", scheduled_date=tomorrow)
        resp = client.get("/api/sessions", params={"date_from": tomorrow})
        assert resp.status_code == 200
        data = resp.json()
        for s in data:
            assert s["scheduled_date"] == tomorrow

    def test_filter_by_date_to(self, client):
        yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        today = datetime.date.today().isoformat()
        self._create_session(client, "A", scheduled_date=yesterday)
        self._create_session(client, "B", scheduled_date=today)
        resp = client.get("/api/sessions", params={"date_to": yesterday})
        assert resp.status_code == 200
        data = resp.json()
        for s in data:
            assert s["scheduled_date"] == yesterday

    def test_filter_by_block_phase(self, client):
        # All sessions should be in the default program (accumulation phase)
        self._create_session(client, "A")
        resp = client.get("/api/sessions", params={"block_phase": "accumulation"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1

    def test_empty_result(self, client):
        resp = client.get("/api/sessions", params={"day_type": "Z"})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_sessions_ordered_by_date_desc(self, client):
        yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        today = datetime.date.today().isoformat()
        self._create_session(client, "A", scheduled_date=yesterday)
        self._create_session(client, "B", scheduled_date=today)
        resp = client.get("/api/sessions")
        data = resp.json()
        assert len(data) >= 2
        # First result should be the most recent
        assert data[0]["scheduled_date"] == today
