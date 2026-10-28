"""
Tests for the phone logging screen API endpoints.

Covers:
- POST /api/sync – batch sync of offline-queued sets
- Idempotent set submission (same idempotency_key sent twice does not duplicate)
- Offline queue sync behavior
- Set logging with RPE, pain flag, notes
- e1RM calculation in sync responses
- Session auto-creation when no session_id provided
"""

import datetime
import pytest
from fastapi.testclient import TestClient

from tests.conftest import authenticate_client
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
    db_file = tmp_path / "test_logging.db"
    return f"sqlite:///{db_file}"


@pytest.fixture()
def client(db_url):
    """Create a TestClient with a fresh database for each test."""
    import app.database as db_mod
    db_mod._engine = None
    db_mod._session_factory = None
    get_engine(db_url)
    reset_db(db_url)
    c = TestClient(app)
    authenticate_client(c)
    return c


# ---------------------------------------------------------------------------
# Helper: create a session and return its id
# ---------------------------------------------------------------------------

def create_session(client, day_label="A"):
    """Create a session and return its id."""
    resp = client.post("/api/sessions", json={"day_label": day_label})
    assert resp.status_code == 200, f"Failed to create session: {resp.text}"
    return resp.json()["id"]


# ---------------------------------------------------------------------------
# POST /api/sync – basic set logging
# ---------------------------------------------------------------------------

class TestSyncBasic:
    """Test basic set logging via the sync endpoint."""

    def test_sync_single_set(self, client):
        """Sync a single set returns 200 with results."""
        sid = create_session(client)
        payload = [{
            "exercise_name": "Deadlift",
            "weight": 315,
            "reps": 5,
            "rpe": 8.0,
            "set_type": "top",
            "pain_flag": False,
            "note": "Felt strong",
            "idempotency_key": "test-key-001",
            "session_id": sid,
        }]
        resp = client.post("/api/sync", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["synced"] == 1
        assert len(data["results"]) == 1
        result = data["results"][0]
        assert result["exercise_name"] == "Deadlift"
        assert result["actual_load_lb"] == 315
        assert result["actual_reps"] == 5
        assert result["rpe"] == 8.0
        assert result["set_type"] == "top"
        assert result["duplicate"] is False

    def test_sync_multiple_sets(self, client):
        """Sync multiple sets in one batch."""
        sid = create_session(client)
        payload = [
            {
                "exercise_name": "Deadlift",
                "weight": 315,
                "reps": 5,
                "rpe": 8.0,
                "set_type": "top",
                "idempotency_key": "test-key-multi-1",
                "session_id": sid,
            },
            {
                "exercise_name": "Deadlift",
                "weight": 335,
                "reps": 3,
                "rpe": 9.0,
                "set_type": "backoff",
                "idempotency_key": "test-key-multi-2",
                "session_id": sid,
            },
        ]
        resp = client.post("/api/sync", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["synced"] == 2
        assert len(data["results"]) == 2

    def test_sync_set_without_rpe(self, client):
        """Sync a set without RPE (warm-up set)."""
        sid = create_session(client)
        payload = [{
            "exercise_name": "Deadlift",
            "weight": 135,
            "reps": 10,
            "rpe": None,
            "set_type": "warmup",
            "idempotency_key": "test-key-warmup",
            "session_id": sid,
        }]
        resp = client.post("/api/sync", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["synced"] == 1
        assert data["results"][0]["set_type"] == "warmup"

    def test_sync_set_with_pain_flag(self, client):
        """Sync a set with pain flag set."""
        sid = create_session(client)
        payload = [{
            "exercise_name": "Squat",
            "weight": 225,
            "reps": 5,
            "rpe": 7.0,
            "set_type": "top",
            "pain_flag": True,
            "idempotency_key": "test-key-pain",
            "session_id": sid,
        }]
        resp = client.post("/api/sync", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["synced"] == 1
        # Verify the set was stored with pain_flag
        db = _get_session()
        slog = db.query(SetLog).filter_by(idempotency_key="test-key-pain").first()
        assert slog is not None
        assert slog.pain_flag is True
        db.close()

    def test_sync_set_with_note(self, client):
        """Sync a set with a note."""
        sid = create_session(client)
        payload = [{
            "exercise_name": "Bench Press",
            "weight": 225,
            "reps": 5,
            "rpe": 8.5,
            "set_type": "top",
            "note": "Good lockout",
            "idempotency_key": "test-key-note",
            "session_id": sid,
        }]
        resp = client.post("/api/sync", json=payload)
        assert resp.status_code == 200
        db = _get_session()
        slog = db.query(SetLog).filter_by(idempotency_key="test-key-note").first()
        assert slog is not None
        assert slog.note == "Good lockout"
        db.close()


# ---------------------------------------------------------------------------
# Idempotency: same set logged twice does not duplicate
# ---------------------------------------------------------------------------

class TestIdempotency:
    """Test that duplicate submissions with the same idempotency_key are rejected."""

    def test_duplicate_set_same_key_returns_duplicate(self, client):
        """Sending the same idempotency_key twice returns duplicate=True on second call."""
        sid = create_session(client)
        payload = [{
            "exercise_name": "Deadlift",
            "weight": 315,
            "reps": 5,
            "rpe": 8.0,
            "set_type": "top",
            "idempotency_key": "idem-dup-001",
            "session_id": sid,
        }]
        # First submission
        resp1 = client.post("/api/sync", json=payload)
        assert resp1.status_code == 200
        data1 = resp1.json()
        assert data1["results"][0]["duplicate"] is False

        # Second submission with same key
        resp2 = client.post("/api/sync", json=payload)
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["results"][0]["duplicate"] is True

    def test_duplicate_set_does_not_create_extra_row(self, client):
        """Duplicate submission does not create a second row in the database."""
        sid = create_session(client)
        payload = [{
            "exercise_name": "Squat",
            "weight": 275,
            "reps": 5,
            "rpe": 8.0,
            "set_type": "top",
            "idempotency_key": "idem-row-001",
            "session_id": sid,
        }]
        # Submit twice
        client.post("/api/sync", json=payload)
        client.post("/api/sync", json=payload)

        # Only one row should exist
        db = _get_session()
        count = db.query(SetLog).filter_by(
            idempotency_key="idem-row-001"
        ).count()
        assert count == 1
        db.close()

    def test_duplicate_set_returns_existing_data(self, client):
        """Duplicate response includes the original set's data."""
        sid = create_session(client)
        payload = [{
            "exercise_name": "Bench Press",
            "weight": 225,
            "reps": 5,
            "rpe": 7.5,
            "set_type": "top",
            "idempotency_key": "idem-data-001",
            "session_id": sid,
        }]
        client.post("/api/sync", json=payload)
        resp2 = client.post("/api/sync", json=payload)
        data = resp2.json()
        result = data["results"][0]
        assert result["duplicate"] is True
        assert result["actual_load_lb"] == 225
        assert result["actual_reps"] == 5
        assert result["rpe"] == 7.5

    def test_mixed_batch_with_duplicates(self, client):
        """A batch with some new and some duplicate sets processes correctly."""
        sid = create_session(client)
        # First batch: two new sets
        batch1 = [
            {
                "exercise_name": "Deadlift",
                "weight": 315,
                "reps": 5,
                "rpe": 8.0,
                "set_type": "top",
                "idempotency_key": "idem-mix-1",
                "session_id": sid,
            },
            {
                "exercise_name": "Deadlift",
                "weight": 335,
                "reps": 3,
                "rpe": 9.0,
                "set_type": "backoff",
                "idempotency_key": "idem-mix-2",
                "session_id": sid,
            },
        ]
        resp1 = client.post("/api/sync", json=batch1)
        assert resp1.status_code == 200
        assert resp1.json()["synced"] == 2

        # Second batch: first is duplicate, second is new
        batch2 = [
            {
                "exercise_name": "Deadlift",
                "weight": 315,
                "reps": 5,
                "rpe": 8.0,
                "set_type": "top",
                "idempotency_key": "idem-mix-1",  # duplicate
                "session_id": sid,
            },
            {
                "exercise_name": "Deadlift",
                "weight": 345,
                "reps": 2,
                "rpe": 9.5,
                "set_type": "backoff",
                "idempotency_key": "idem-mix-3",  # new
                "session_id": sid,
            },
        ]
        resp2 = client.post("/api/sync", json=batch2)
        assert resp2.status_code == 200
        data = resp2.json()
        assert data["synced"] == 2
        assert data["results"][0]["duplicate"] is True
        assert data["results"][1]["duplicate"] is False

    def test_no_idempotency_key_allows_duplicate(self, client):
        """Sets without idempotency_key can be submitted multiple times (no dedup)."""
        sid = create_session(client)
        payload = [{
            "exercise_name": "Deadlift",
            "weight": 315,
            "reps": 5,
            "rpe": 8.0,
            "set_type": "top",
            "idempotency_key": None,
            "session_id": sid,
        }]
        client.post("/api/sync", json=payload)
        client.post("/api/sync", json=payload)

        db = _get_session()
        count = db.query(SetLog).filter_by(
            session_id=sid,
            actual_load_lb=315,
            actual_reps=5,
        ).count()
        assert count == 2
        db.close()


# ---------------------------------------------------------------------------
# Session auto-creation
# ---------------------------------------------------------------------------

class TestSessionAutoCreation:
    """Test that sync creates a session when none is provided."""

    def test_sync_creates_session_when_none_exists(self, client):
        """Sync without session_id creates a session for today."""
        payload = [{
            "exercise_name": "Deadlift",
            "weight": 315,
            "reps": 5,
            "rpe": 8.0,
            "set_type": "top",
            "idempotency_key": "auto-sess-001",
            "session_id": None,
        }]
        resp = client.post("/api/sync", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["synced"] == 1

    def test_sync_reuses_existing_in_progress_session(self, client):
        """Sync without session_id reuses an existing in-progress session."""
        sid = create_session(client)
        payload = [{
            "exercise_name": "Squat",
            "weight": 225,
            "reps": 5,
            "rpe": 7.0,
            "set_type": "top",
            "idempotency_key": "auto-sess-002",
            "session_id": None,
        }]
        resp = client.post("/api/sync", json=payload)
        assert resp.status_code == 200
        # Verify the set was logged to the existing session
        db = _get_session()
        slog = db.query(SetLog).filter_by(idempotency_key="auto-sess-002").first()
        assert slog is not None
        assert slog.session_id == sid
        db.close()


# ---------------------------------------------------------------------------
# e1RM calculation
# ---------------------------------------------------------------------------

class TestE1RMCalculation:
    """Test that e1RM is calculated and stored for logged sets."""

    def test_e1rm_stored_for_high_confidence_set(self, client):
        """Sets with RPE >= 7 and reps <= 8 get high-confidence e1RM."""
        sid = create_session(client)
        payload = [{
            "exercise_name": "Deadlift",
            "weight": 315,
            "reps": 5,
            "rpe": 8.0,
            "set_type": "top",
            "idempotency_key": "e1rm-hc-001",
            "session_id": sid,
        }]
        resp = client.post("/api/sync", json=payload)
        assert resp.status_code == 200
        db = _get_session()
        slog = db.query(SetLog).filter_by(idempotency_key="e1rm-hc-001").first()
        assert slog is not None
        assert slog.e1rm_lb is not None
        assert slog.e1rm_lb > 315  # e1RM should be higher than the set weight
        assert slog.confidence == "high"
        db.close()

    def test_e1rm_low_confidence_for_warmup(self, client):
        """Warm-up sets without RPE get low-confidence e1RM (Epley fallback)."""
        sid = create_session(client)
        payload = [{
            "exercise_name": "Deadlift",
            "weight": 135,
            "reps": 10,
            "rpe": None,
            "set_type": "warmup",
            "idempotency_key": "e1rm-lc-001",
            "session_id": sid,
        }]
        resp = client.post("/api/sync", json=payload)
        assert resp.status_code == 200
        db = _get_session()
        slog = db.query(SetLog).filter_by(idempotency_key="e1rm-lc-001").first()
        assert slog is not None
        assert slog.e1rm_lb is not None
        assert slog.confidence == "low"
        db.close()

    def test_e1rm_low_confidence_for_low_rpe(self, client):
        """Sets with RPE < 7 get low confidence."""
        sid = create_session(client)
        payload = [{
            "exercise_name": "Squat",
            "weight": 185,
            "reps": 5,
            "rpe": 6.0,
            "set_type": "warmup",
            "idempotency_key": "e1rm-lc-002",
            "session_id": sid,
        }]
        resp = client.post("/api/sync", json=payload)
        assert resp.status_code == 200
        db = _get_session()
        slog = db.query(SetLog).filter_by(idempotency_key="e1rm-lc-002").first()
        assert slog is not None
        assert slog.confidence == "low"
        db.close()

    def test_e1rm_low_confidence_for_high_reps(self, client):
        """Sets with reps > 8 get low confidence even with high RPE."""
        sid = create_session(client)
        payload = [{
            "exercise_name": "Bench Press",
            "weight": 135,
            "reps": 12,
            "rpe": 9.0,
            "set_type": "top",
            "idempotency_key": "e1rm-lc-003",
            "session_id": sid,
        }]
        resp = client.post("/api/sync", json=payload)
        assert resp.status_code == 200
        db = _get_session()
        slog = db.query(SetLog).filter_by(idempotency_key="e1rm-lc-003").first()
        assert slog is not None
        assert slog.confidence == "low"
        db.close()


# ---------------------------------------------------------------------------
# Exercise auto-creation
# ---------------------------------------------------------------------------

class TestExerciseAutoCreation:
    """Test that unknown exercises are auto-created during sync."""

    def test_sync_creates_unknown_exercise(self, client):
        """Syncing a set for an unknown exercise creates it."""
        sid = create_session(client)
        payload = [{
            "exercise_name": "Atlas Stone",
            "weight": 200,
            "reps": 5,
            "rpe": 9.0,
            "set_type": "top",
            "idempotency_key": "ex-auto-001",
            "session_id": sid,
        }]
        resp = client.post("/api/sync", json=payload)
        assert resp.status_code == 200
        db = _get_session()
        ex = db.query(Exercise).filter_by(name="Atlas Stone").first()
        assert ex is not None
        db.close()


# ---------------------------------------------------------------------------
# Response shape
# ---------------------------------------------------------------------------

class TestResponseShape:
    """Test the shape of sync responses."""

    def test_sync_response_has_synced_count(self, client):
        """Response includes 'synced' count."""
        sid = create_session(client)
        payload = [{
            "exercise_name": "Deadlift",
            "weight": 315,
            "reps": 5,
            "rpe": 8.0,
            "set_type": "top",
            "idempotency_key": "shape-001",
            "session_id": sid,
        }]
        resp = client.post("/api/sync", json=payload)
        data = resp.json()
        assert "synced" in data
        assert "results" in data
        assert isinstance(data["synced"], int)
        assert isinstance(data["results"], list)

    def test_result_has_required_fields(self, client):
        """Each result has id, exercise_name, actual_load_lb, actual_reps, rpe, set_type, duplicate."""
        sid = create_session(client)
        payload = [{
            "exercise_name": "Deadlift",
            "weight": 315,
            "reps": 5,
            "rpe": 8.0,
            "set_type": "top",
            "idempotency_key": "shape-002",
            "session_id": sid,
        }]
        resp = client.post("/api/sync", json=payload)
        data = resp.json()
        result = data["results"][0]
        assert "id" in result
        assert "exercise_name" in result
        assert "actual_load_lb" in result
        assert "actual_reps" in result
        assert "rpe" in result
        assert "set_type" in result
        assert "duplicate" in result

    def test_duplicate_result_has_id(self, client):
        """Duplicate results include the original set's id."""
        sid = create_session(client)
        payload = [{
            "exercise_name": "Squat",
            "weight": 225,
            "reps": 5,
            "rpe": 7.5,
            "set_type": "top",
            "idempotency_key": "shape-dup-001",
            "session_id": sid,
        }]
        resp1 = client.post("/api/sync", json=payload)
        first_id = resp1.json()["results"][0]["id"]

        resp2 = client.post("/api/sync", json=payload)
        data = resp2.json()
        assert data["results"][0]["id"] == first_id
        assert data["results"][0]["duplicate"] is True


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestSyncErrors:
    """Test error handling in the sync endpoint."""

    def test_sync_invalid_session_returns_error(self, client):
        """Sync with a non-existent session_id returns an error in results."""
        payload = [{
            "exercise_name": "Deadlift",
            "weight": 315,
            "reps": 5,
            "rpe": 8.0,
            "set_type": "top",
            "idempotency_key": "err-sess-001",
            "session_id": 99999,
        }]
        resp = client.post("/api/sync", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        # The result should contain an error
        assert "error" in data["results"][0]

    def test_sync_empty_batch(self, client):
        """Sync with an empty batch returns 200 with zero results."""
        resp = client.post("/api/sync", json=[])
        assert resp.status_code == 200
        data = resp.json()
        assert data["synced"] == 0
        assert data["results"] == []
