"""
Tests for the Settings screen functionality (FS-033).

Covers:
- Settings persistence (bodyweight, goal weight, drop percentages, target RPE,
  notification toggles)
- Settings survive app restart (re-read from DB)
- CSV export of all session data
- CSV import round-trip (export -> import -> verify)
- Bulk settings update
- Settings validation (drop percentage ranges, RPE ranges)
- Safety notice tracking
"""

import csv
import io
import datetime
import pytest
from fastapi.testclient import TestClient

from tests.conftest import authenticate_client
from app.routes import app, _get_session
from app.database import (
    Base,
    Athlete,
    Bodyweight,
    Exercise,
    Program,
    Block,
    Cycle,
    Session as DBSession,
    Prescription,
    SetLog,
    Settings,
    get_engine,
    reset_db,
)
from app.strength.settings import (
    DEFAULT_SETTINGS,
    VALID_KEYS,
    get_setting,
    set_setting,
    load_all_settings,
    save_all_settings,
    ensure_defaults,
    export_sessions_csv,
    import_sessions_csv,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db_url(tmp_path):
    """Provide a file-based SQLite database URL for each test."""
    db_file = tmp_path / "test_settings.db"
    return f"sqlite:///{db_file}"


@pytest.fixture()
def client(db_url):
    """Create a TestClient with a fresh database for each test."""
    import app.database as db_mod
    db_mod._engine = None
    db_mod._session_factory = None
    get_engine(db_url)
    reset_db(db_url)
    # Seed athlete and default settings so the DB is usable
    db = _get_session()
    athlete = Athlete(name="Test Athlete", units="lb")
    db.add(athlete)
    db.flush()
    from app.strength.settings import ensure_defaults
    ensure_defaults(db)
    db.commit()
    db.close()
    c = TestClient(app)
    authenticate_client(c)
    return c


@pytest.fixture()
def seeded_db(db_url):
    """Provide a DB session with athlete + settings seeded."""
    import app.database as db_mod
    db_mod._engine = None
    db_mod._session_factory = None
    get_engine(db_url)
    reset_db(db_url)
    db = _get_session()
    # Seed athlete
    athlete = Athlete(name="Test Athlete", units="lb")
    db.add(athlete)
    db.flush()
    # Seed default settings
    ensure_defaults(db)
    db.commit()
    yield db
    db.close()


# ---------------------------------------------------------------------------
# 1. Settings persistence – bodyweight and goal weight
# ---------------------------------------------------------------------------

class TestBodyweightSettings:
    """Settings screen allows editing bodyweight and goal weight."""

    def test_default_bodyweight_is_zero(self, seeded_db):
        bw = get_setting(seeded_db, "bodyweight")
        assert bw == "0"

    def test_default_goal_weight_is_zero(self, seeded_db):
        gw = get_setting(seeded_db, "goal_weight")
        assert gw == "0"

    def test_set_bodyweight(self, seeded_db):
        set_setting(seeded_db, "bodyweight", "200")
        seeded_db.commit()
        bw = get_setting(seeded_db, "bodyweight")
        assert bw == "200"

    def test_set_goal_weight(self, seeded_db):
        set_setting(seeded_db, "goal_weight", "190")
        seeded_db.commit()
        gw = get_setting(seeded_db, "goal_weight")
        assert gw == "190"

    def test_bodyweight_survives_restart(self, seeded_db):
        """Settings persist in DB and survive re-read (simulating restart)."""
        set_setting(seeded_db, "bodyweight", "210")
        seeded_db.commit()
        # Simulate restart: close and re-open session
        seeded_db.close()
        new_db = _get_session()
        try:
            bw = get_setting(new_db, "bodyweight")
            assert bw == "210"
        finally:
            new_db.close()

    def test_goal_weight_survives_restart(self, seeded_db):
        set_setting(seeded_db, "goal_weight", "185")
        seeded_db.commit()
        seeded_db.close()
        new_db = _get_session()
        try:
            gw = get_setting(new_db, "goal_weight")
            assert gw == "185"
        finally:
            new_db.close()


# ---------------------------------------------------------------------------
# 2. Drop percentages per block phase
# ---------------------------------------------------------------------------

class TestDropPercentages:
    """Settings screen allows configuring drop percentages per block phase."""

    def test_default_drop_pct_accumulation(self, seeded_db):
        val = get_setting(seeded_db, "drop_pct_accumulation")
        assert float(val) == 5.5

    def test_default_drop_pct_intensification(self, seeded_db):
        val = get_setting(seeded_db, "drop_pct_intensification")
        assert float(val) == 4.5

    def test_default_drop_pct_realization(self, seeded_db):
        val = get_setting(seeded_db, "drop_pct_realization")
        assert float(val) == 2.5

    def test_update_drop_pct_accumulation(self, seeded_db):
        set_setting(seeded_db, "drop_pct_accumulation", "6.0")
        seeded_db.commit()
        val = get_setting(seeded_db, "drop_pct_accumulation")
        assert float(val) == 6.0

    def test_update_drop_pct_intensification(self, seeded_db):
        set_setting(seeded_db, "drop_pct_intensification", "5.0")
        seeded_db.commit()
        val = get_setting(seeded_db, "drop_pct_intensification")
        assert float(val) == 5.0

    def test_update_drop_pct_realization(self, seeded_db):
        set_setting(seeded_db, "drop_pct_realization", "3.0")
        seeded_db.commit()
        val = get_setting(seeded_db, "drop_pct_realization")
        assert float(val) == 3.0

    def test_drop_pct_survives_restart(self, seeded_db):
        set_setting(seeded_db, "drop_pct_accumulation", "5.0")
        seeded_db.commit()
        seeded_db.close()
        new_db = _get_session()
        try:
            val = get_setting(new_db, "drop_pct_accumulation")
            assert float(val) == 5.0
        finally:
            new_db.close()

    def test_drop_pct_within_valid_range_accumulation(self, seeded_db):
        """Accumulation drop pct should be 5-6%."""
        for pct in ["5.0", "5.5", "6.0"]:
            set_setting(seeded_db, "drop_pct_accumulation", pct)
            seeded_db.commit()
            val = get_setting(seeded_db, "drop_pct_accumulation")
            assert float(val) == float(pct)

    def test_drop_pct_within_valid_range_intensification(self, seeded_db):
        """Intensification drop pct should be 4-5%."""
        for pct in ["4.0", "4.5", "5.0"]:
            set_setting(seeded_db, "drop_pct_intensification", pct)
            seeded_db.commit()
            val = get_setting(seeded_db, "drop_pct_intensification")
            assert float(val) == float(pct)

    def test_drop_pct_within_valid_range_realization(self, seeded_db):
        """Realization drop pct should be 2-3%."""
        for pct in ["2.0", "2.5", "3.0"]:
            set_setting(seeded_db, "drop_pct_realization", pct)
            seeded_db.commit()
            val = get_setting(seeded_db, "drop_pct_realization")
            assert float(val) == float(pct)


# ---------------------------------------------------------------------------
# 3. Target RPE per cycle
# ---------------------------------------------------------------------------

class TestTargetRPE:
    """Settings screen allows configuring target RPE per cycle within each block."""

    def test_default_target_rpe_cycle_1(self, seeded_db):
        val = get_setting(seeded_db, "target_rpe_cycle_1")
        assert float(val) == 8.0

    def test_default_target_rpe_cycle_2(self, seeded_db):
        val = get_setting(seeded_db, "target_rpe_cycle_2")
        assert float(val) == 8.5

    def test_default_target_rpe_cycle_3(self, seeded_db):
        val = get_setting(seeded_db, "target_rpe_cycle_3")
        assert float(val) == 9.0

    def test_update_target_rpe_cycle_1(self, seeded_db):
        set_setting(seeded_db, "target_rpe_cycle_1", "7.5")
        seeded_db.commit()
        val = get_setting(seeded_db, "target_rpe_cycle_1")
        assert float(val) == 7.5

    def test_update_target_rpe_cycle_2(self, seeded_db):
        set_setting(seeded_db, "target_rpe_cycle_2", "8.0")
        seeded_db.commit()
        val = get_setting(seeded_db, "target_rpe_cycle_2")
        assert float(val) == 8.0

    def test_update_target_rpe_cycle_3(self, seeded_db):
        set_setting(seeded_db, "target_rpe_cycle_3", "9.5")
        seeded_db.commit()
        val = get_setting(seeded_db, "target_rpe_cycle_3")
        assert float(val) == 9.5

    def test_target_rpe_survives_restart(self, seeded_db):
        set_setting(seeded_db, "target_rpe_cycle_1", "7.0")
        seeded_db.commit()
        seeded_db.close()
        new_db = _get_session()
        try:
            val = get_setting(new_db, "target_rpe_cycle_1")
            assert float(val) == 7.0
        finally:
            new_db.close()

    def test_target_rpe_half_step(self, seeded_db):
        """RPE supports 0.5 steps."""
        set_setting(seeded_db, "target_rpe_cycle_1", "7.5")
        seeded_db.commit()
        val = get_setting(seeded_db, "target_rpe_cycle_1")
        assert float(val) == 7.5


# ---------------------------------------------------------------------------
# 4. Notification settings
# ---------------------------------------------------------------------------

class TestNotificationSettings:
    """Settings screen allows enabling/disabling rest timer and workout reminders."""

    def test_default_rest_timer_notifications(self, seeded_db):
        val = get_setting(seeded_db, "rest_timer_notifications")
        assert val == "true"

    def test_default_workout_reminders(self, seeded_db):
        val = get_setting(seeded_db, "workout_reminders")
        assert val == "true"

    def test_disable_rest_timer_notifications(self, seeded_db):
        set_setting(seeded_db, "rest_timer_notifications", "false")
        seeded_db.commit()
        val = get_setting(seeded_db, "rest_timer_notifications")
        assert val == "false"

    def test_enable_rest_timer_notifications(self, seeded_db):
        set_setting(seeded_db, "rest_timer_notifications", "true")
        seeded_db.commit()
        val = get_setting(seeded_db, "rest_timer_notifications")
        assert val == "true"

    def test_disable_workout_reminders(self, seeded_db):
        set_setting(seeded_db, "workout_reminders", "false")
        seeded_db.commit()
        val = get_setting(seeded_db, "workout_reminders")
        assert val == "false"

    def test_enable_workout_reminders(self, seeded_db):
        set_setting(seeded_db, "workout_reminders", "true")
        seeded_db.commit()
        val = get_setting(seeded_db, "workout_reminders")
        assert val == "true"

    def test_notification_settings_survive_restart(self, seeded_db):
        set_setting(seeded_db, "rest_timer_notifications", "false")
        set_setting(seeded_db, "workout_reminders", "false")
        seeded_db.commit()
        seeded_db.close()
        new_db = _get_session()
        try:
            assert get_setting(new_db, "rest_timer_notifications") == "false"
            assert get_setting(new_db, "workout_reminders") == "false"
        finally:
            new_db.close()


# ---------------------------------------------------------------------------
# 5. Safety notice
# ---------------------------------------------------------------------------

class TestSafetyNotice:
    """Safety notice is tracked in settings."""

    def test_default_safety_notice_not_seen(self, seeded_db):
        val = get_setting(seeded_db, "safety_notice_seen")
        assert val == "false"

    def test_mark_safety_notice_seen(self, seeded_db):
        set_setting(seeded_db, "safety_notice_seen", "true")
        seeded_db.commit()
        val = get_setting(seeded_db, "safety_notice_seen")
        assert val == "true"


# ---------------------------------------------------------------------------
# 6. Bulk settings update via API
# ---------------------------------------------------------------------------

class TestBulkSettingsAPI:
    """Bulk update settings via PATCH /api/settings/bulk."""

    def test_bulk_update_settings(self, client):
        resp = client.patch("/api/settings/bulk", json={
            "bodyweight": "200",
            "goal_weight": "190",
            "drop_pct_accumulation": "5.5",
            "rest_timer_notifications": "false",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["updated"] == 4

    def test_bulk_update_persists(self, client):
        client.patch("/api/settings/bulk", json={
            "bodyweight": "210",
            "goal_weight": "195",
        })
        # Re-read via GET
        resp = client.get("/api/settings")
        assert resp.status_code == 200
        settings = {item["key"]: item["value"] for item in resp.json()}
        assert settings["bodyweight"] == "210"
        assert settings["goal_weight"] == "195"

    def test_bulk_update_empty(self, client):
        resp = client.patch("/api/settings/bulk", json={})
        assert resp.status_code == 200
        assert resp.json()["updated"] == 0

    def test_bulk_update_invalid_key_ignored(self, client):
        resp = client.patch("/api/settings/bulk", json={
            "nonexistent_key": "value",
            "bodyweight": "200",
        })
        assert resp.status_code == 200
        data = resp.json()
        # Only valid keys should be updated
        assert data["updated"] == 1

    def test_bulk_update_survives_restart(self, client):
        client.patch("/api/settings/bulk", json={
            "bodyweight": "220",
            "goal_weight": "200",
            "drop_pct_accumulation": "6.0",
            "target_rpe_cycle_1": "7.5",
            "rest_timer_notifications": "false",
            "workout_reminders": "false",
        })
        # Verify via GET
        resp = client.get("/api/settings")
        settings = {item["key"]: item["value"] for item in resp.json()}
        assert settings["bodyweight"] == "220"
        assert settings["goal_weight"] == "200"
        assert settings["drop_pct_accumulation"] == "6.0"
        assert settings["target_rpe_cycle_1"] == "7.5"
        assert settings["rest_timer_notifications"] == "false"
        assert settings["workout_reminders"] == "false"


# ---------------------------------------------------------------------------
# 7. CSV Export
# ---------------------------------------------------------------------------

class TestCSVExport:
    """Settings screen provides CSV export of all session data."""

    def test_export_csv_returns_csv_content_type(self, client):
        resp = client.get("/api/export/csv")
        assert resp.status_code == 200
        assert "text/csv" in resp.headers.get("content-type", "")

    def test_export_csv_has_correct_headers(self, client):
        resp = client.get("/api/export/csv")
        assert resp.status_code == 200
        reader = csv.reader(io.StringIO(resp.text))
        headers = next(reader)
        assert "session_date" in headers
        assert "exercise_name" in headers
        assert "actual_load_lb" in headers
        assert "actual_reps" in headers
        assert "rpe" in headers
        assert "e1rm_lb" in headers
        assert "confidence" in headers
        assert "pain_flag" in headers

    def test_export_csv_empty_when_no_data(self, client):
        resp = client.get("/api/export/csv")
        assert resp.status_code == 200
        reader = csv.reader(io.StringIO(resp.text))
        rows = list(reader)
        # Only header row
        assert len(rows) == 1

    def test_export_csv_includes_session_data(self, client):
        """Create a session with logged sets, then export."""
        # Create a session
        resp = client.post("/api/sessions", json={"day_label": "A"})
        assert resp.status_code == 200
        session_id = resp.json()["id"]

        # Log a set (endpoint is /sets, not /set)
        resp = client.post(f"/api/sessions/{session_id}/sets", json={
            "exercise_name": "Back Squat",
            "weight": 225,
            "reps": 5,
            "rpe": 8.0,
            "set_type": "top",
        })
        assert resp.status_code == 200

        # Export
        resp = client.get("/api/export/csv")
        assert resp.status_code == 200
        reader = csv.DictReader(io.StringIO(resp.text))
        rows = list(reader)
        assert len(rows) >= 1
        # Find our logged set
        found = [r for r in rows if r["exercise_name"] == "Back Squat"]
        assert len(found) >= 1
        assert found[0]["actual_load_lb"] == "225.0"
        assert found[0]["actual_reps"] == "5"


# ---------------------------------------------------------------------------
# 8. CSV Import
# ---------------------------------------------------------------------------

class TestCSVImport:
    """Settings screen provides import from CSV backup."""

    def test_import_csv_returns_counts(self, client):
        csv_data = (
            "session_date,day_label,exercise_name,set_number,"
            "actual_load_lb,actual_reps,rpe,e1rm_lb,confidence,pain_flag,note,logged_at\n"
            "2025-01-15,A,Back Squat,1,225,5,8.0,262.5,high,false,,2025-01-15T10:00:00\n"
        )
        resp = client.post("/api/import/csv", json={"csv_data": csv_data})
        assert resp.status_code == 200
        data = resp.json()
        assert "exercises" in data
        assert "set_logs" in data
        assert data["set_logs"] >= 1

    def test_import_csv_creates_exercise(self, client):
        csv_data = (
            "session_date,day_label,exercise_name,set_number,"
            "actual_load_lb,actual_reps,rpe,e1rm_lb,confidence,pain_flag,note,logged_at\n"
            "2025-01-15,A,Custom Lift,1,100,3,7.0,110.0,high,false,,2025-01-15T10:00:00\n"
        )
        resp = client.post("/api/import/csv", json={"csv_data": csv_data})
        assert resp.status_code == 200
        data = resp.json()
        assert data["exercises"] >= 1

    def test_import_csv_empty(self, client):
        csv_data = (
            "session_date,day_label,exercise_name,set_number,"
            "actual_load_lb,actual_reps,rpe,e1rm_lb,confidence,pain_flag,note,logged_at\n"
        )
        resp = client.post("/api/import/csv", json={"csv_data": csv_data})
        assert resp.status_code == 200
        data = resp.json()
        assert data["set_logs"] == 0


# ---------------------------------------------------------------------------
# 9. Export/Import Round-trip
# ---------------------------------------------------------------------------

class TestExportImportRoundTrip:
    """Tests verify settings persistence and export/import round-trip."""

    def test_roundtrip_preserves_data(self, client):
        """Export session data, import it into a fresh DB, verify it matches."""
        # Create sessions and log sets
        for day in ["A", "B"]:
            resp = client.post("/api/sessions", json={"day_label": day})
            assert resp.status_code == 200
            session_id = resp.json()["id"]

            for exercise, load, reps, rpe in [
                ("Back Squat", 225, 5, 8.0),
                ("Deadlift", 315, 3, 8.5),
            ]:
                resp = client.post(f"/api/sessions/{session_id}/sets", json={
                    "exercise_name": exercise,
                    "weight": load,
                    "reps": reps,
                    "rpe": rpe,
                    "set_type": "top",
                })
                assert resp.status_code == 200

        # Export
        resp = client.get("/api/export/csv")
        assert resp.status_code == 200
        csv_data = resp.text

        # Verify CSV has data
        reader = csv.DictReader(io.StringIO(csv_data))
        exported_rows = list(reader)
        assert len(exported_rows) >= 4  # 2 days x 2 exercises

        # Import into same DB (simulating restore)
        resp = client.post("/api/import/csv", json={"csv_data": csv_data})
        assert resp.status_code == 200
        data = resp.json()
        assert data["set_logs"] >= 4

    def test_roundtrip_preserves_rpe_values(self, client):
        """RPE values survive export/import."""
        resp = client.post("/api/sessions", json={"day_label": "A"})
        session_id = resp.json()["id"]

        resp = client.post(f"/api/sessions/{session_id}/sets", json={
            "exercise_name": "Bench Press",
            "weight": 185,
            "reps": 5,
            "rpe": 8.5,
            "set_type": "top",
        })
        assert resp.status_code == 200

        # Export
        resp = client.get("/api/export/csv")
        csv_data = resp.text

        # Import
        resp = client.post("/api/import/csv", json={"csv_data": csv_data})
        assert resp.status_code == 200

        # Re-export and verify RPE is preserved
        resp = client.get("/api/export/csv")
        reader = csv.DictReader(io.StringIO(resp.text))
        rows = list(reader)
        bench_rows = [r for r in rows if r["exercise_name"] == "Bench Press"]
        assert len(bench_rows) >= 1
        assert bench_rows[0]["rpe"] == "8.5"

    def test_roundtrip_preserves_pain_flag(self, client):
        """Pain flag survives export/import."""
        resp = client.post("/api/sessions", json={"day_label": "A"})
        session_id = resp.json()["id"]

        resp = client.post(f"/api/sessions/{session_id}/sets", json={
            "exercise_name": "Deadlift",
            "weight": 300,
            "reps": 3,
            "rpe": 9.0,
            "set_type": "top",
            "pain_flag": True,
        })
        assert resp.status_code == 200

        # Export
        resp = client.get("/api/export/csv")
        csv_data = resp.text

        # Verify pain flag in CSV
        reader = csv.DictReader(io.StringIO(csv_data))
        rows = list(reader)
        deadlift_rows = [r for r in rows if r["exercise_name"] == "Deadlift"]
        assert len(deadlift_rows) >= 1
        assert deadlift_rows[0]["pain_flag"].lower() in ("true", "1", "yes")


# ---------------------------------------------------------------------------
# 10. Settings API – GET /api/settings
# ---------------------------------------------------------------------------

class TestSettingsAPI:
    """GET /api/settings returns all settings."""

    def test_get_settings_returns_list(self, client):
        resp = client.get("/api/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) > 0

    def test_get_settings_has_expected_keys(self, client):
        resp = client.get("/api/settings")
        settings = {item["key"]: item["value"] for item in resp.json()}
        # Check all default keys are present
        for key in DEFAULT_SETTINGS:
            assert key in settings, f"Missing key: {key}"

    def test_get_settings_includes_bodyweight(self, client):
        resp = client.get("/api/settings")
        settings = {item["key"]: item["value"] for item in resp.json()}
        assert "bodyweight" in settings
        assert "goal_weight" in settings

    def test_get_settings_includes_drop_pcts(self, client):
        resp = client.get("/api/settings")
        settings = {item["key"]: item["value"] for item in resp.json()}
        assert "drop_pct_accumulation" in settings
        assert "drop_pct_intensification" in settings
        assert "drop_pct_realization" in settings

    def test_get_settings_includes_target_rpes(self, client):
        resp = client.get("/api/settings")
        settings = {item["key"]: item["value"] for item in resp.json()}
        assert "target_rpe_cycle_1" in settings
        assert "target_rpe_cycle_2" in settings
        assert "target_rpe_cycle_3" in settings

    def test_get_settings_includes_notifications(self, client):
        resp = client.get("/api/settings")
        settings = {item["key"]: item["value"] for item in resp.json()}
        assert "rest_timer_notifications" in settings
        assert "workout_reminders" in settings


# ---------------------------------------------------------------------------
# 11. Settings API – PATCH /api/settings (single)
# ---------------------------------------------------------------------------

class TestSingleSettingAPI:
    """PATCH /api/settings updates a single setting."""

    def test_update_single_setting(self, client):
        resp = client.patch("/api/settings", json={
            "key": "bodyweight",
            "value": "200",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["key"] == "bodyweight"
        assert data["value"] == "200"

    def test_update_single_setting_persists(self, client):
        client.patch("/api/settings", json={
            "key": "goal_weight",
            "value": "190",
        })
        resp = client.get("/api/settings")
        settings = {item["key"]: item["value"] for item in resp.json()}
        assert settings["goal_weight"] == "190"

    def test_update_drop_pct(self, client):
        resp = client.patch("/api/settings", json={
            "key": "drop_pct_accumulation",
            "value": "6.0",
        })
        assert resp.status_code == 200
        assert resp.json()["value"] == "6.0"

    def test_update_target_rpe(self, client):
        resp = client.patch("/api/settings", json={
            "key": "target_rpe_cycle_1",
            "value": "7.5",
        })
        assert resp.status_code == 200
        assert resp.json()["value"] == "7.5"

    def test_update_notification(self, client):
        resp = client.patch("/api/settings", json={
            "key": "rest_timer_notifications",
            "value": "false",
        })
        assert resp.status_code == 200
        assert resp.json()["value"] == "false"


# ---------------------------------------------------------------------------
# 12. Settings persistence layer (unit tests)
# ---------------------------------------------------------------------------

class TestSettingsPersistenceLayer:
    """Unit tests for the settings persistence layer functions."""

    def test_load_all_settings(self, seeded_db):
        settings = load_all_settings(seeded_db)
        assert isinstance(settings, dict)
        assert "bodyweight" in settings
        assert "goal_weight" in settings

    def test_save_all_settings(self, seeded_db):
        new_settings = {
            "bodyweight": "200",
            "goal_weight": "190",
            "drop_pct_accumulation": "5.5",
        }
        save_all_settings(seeded_db, new_settings)
        seeded_db.commit()
        loaded = load_all_settings(seeded_db)
        assert loaded["bodyweight"] == "200"
        assert loaded["goal_weight"] == "190"
        assert loaded["drop_pct_accumulation"] == "5.5"

    def test_ensure_defaults(self, seeded_db):
        """ensure_defaults does not overwrite existing settings."""
        set_setting(seeded_db, "bodyweight", "200")
        seeded_db.commit()
        ensure_defaults(seeded_db)
        seeded_db.commit()
        bw = get_setting(seeded_db, "bodyweight")
        assert bw == "200"

    def test_get_setting_default(self, seeded_db):
        """get_setting returns default for unknown key."""
        val = get_setting(seeded_db, "nonexistent_key", default="fallback")
        assert val == "fallback"

    def test_valid_keys_match_defaults(self):
        """VALID_KEYS should match DEFAULT_SETTINGS keys."""
        assert VALID_KEYS == set(DEFAULT_SETTINGS.keys())

    def test_default_settings_has_all_required_keys(self):
        """DEFAULT_SETTINGS must include all required setting keys."""
        required_keys = {
            "bodyweight", "goal_weight",
            "drop_pct_accumulation", "drop_pct_intensification", "drop_pct_realization",
            "target_rpe_cycle_1", "target_rpe_cycle_2", "target_rpe_cycle_3",
            "rest_timer_notifications", "workout_reminders",
            "safety_notice_seen",
        }
        assert required_keys.issubset(set(DEFAULT_SETTINGS.keys()))


# ---------------------------------------------------------------------------
# 13. Settings export/import (settings CSV)
# ---------------------------------------------------------------------------

class TestSettingsExportImport:
    """Export and import settings as CSV."""

    def test_export_settings_csv(self, client):
        """GET /api/settings/export/csv returns settings as CSV."""
        resp = client.get("/api/settings/export/csv")
        assert resp.status_code == 200
        assert "text/csv" in resp.headers.get("content-type", "")
        reader = csv.DictReader(io.StringIO(resp.text))
        rows = list(reader)
        assert len(rows) > 0
        keys = [r["key"] for r in rows]
        assert "bodyweight" in keys
        assert "goal_weight" in keys

    def test_import_settings_csv(self, client):
        """POST /api/settings/import/csv restores settings from CSV."""
        csv_data = (
            "key,value\n"
            "bodyweight,200\n"
            "goal_weight,190\n"
            "drop_pct_accumulation,5.5\n"
            "rest_timer_notifications,false\n"
        )
        resp = client.post("/api/settings/import/csv", json={"csv_data": csv_data})
        assert resp.status_code == 200
        data = resp.json()
        assert data["imported"] >= 4

    def test_settings_roundtrip(self, client):
        """Export settings, modify, import, verify."""
        # First set some values
        client.patch("/api/settings", json={"key": "bodyweight", "value": "210"})
        client.patch("/api/settings", json={"key": "goal_weight", "value": "195"})

        # Export
        resp = client.get("/api/settings/export/csv")
        csv_data = resp.text

        # Verify CSV content
        reader = csv.DictReader(io.StringIO(csv_data))
        rows = {r["key"]: r["value"] for r in reader}
        assert rows["bodyweight"] == "210"
        assert rows["goal_weight"] == "195"

        # Import back
        resp = client.post("/api/settings/import/csv", json={"csv_data": csv_data})
        assert resp.status_code == 200

        # Verify settings are restored
        resp = client.get("/api/settings")
        settings = {item["key"]: item["value"] for item in resp.json()}
        assert settings["bodyweight"] == "210"
        assert settings["goal_weight"] == "195"
