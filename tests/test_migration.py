"""
Tests for database migration from TrainingEntry to new schema.

Covers:
- All 13 tables are created
- Migration is idempotent
- TrainingEntry rows are migrated to set_log with correct field mapping
- No data loss: count of migrated rows >= original count
- Spot-check values match
- Existing /log, /history, /edit, /delete endpoints still work
"""

import datetime
import os
import tempfile

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.database import (
    Athlete,
    Base,
    Block,
    Bodyweight,
    Cycle,
    Equipment,
    Exercise,
    ExerciseSubstitute,
    EventLog,
    PR,
    Prescription,
    Program,
    Settings,
    SetLog,
    Session as DBSession,
    get_engine,
    init_db,
    migrate_from_training_entry,
    reset_db,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db_url():
    """Provide an in-memory SQLite database URL for each test."""
    return "sqlite:///:memory:"


@pytest.fixture()
def engine(db_url):
    """Create a fresh engine for each test."""
    from app.database import _engine, _session_factory
    # Reset module-level state
    import app.database as db_mod
    db_mod._engine = None
    db_mod._session_factory = None
    eng = get_engine(db_url)
    return eng


@pytest.fixture()
def session_factory(engine):
    return sessionmaker(bind=engine)


@pytest.fixture()
def session(session_factory):
    s = session_factory()
    yield s
    s.close()


@pytest.fixture()
def seeded_db(session, db_url):
    """
    Create a TrainingEntry table with sample data, then run migration.
    Returns (session, stats).
    """
    # Create the legacy TrainingEntry table
    session.execute(text("""
        CREATE TABLE IF NOT EXISTS TrainingEntry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date DATE,
            exercise_name TEXT,
            weight REAL,
            reps INTEGER,
            sets INTEGER,
            notes TEXT
        )
    """))

    # Insert sample data
    sample_data = [
        ("2024-01-15", "Bench Press", 225.0, 5, 3, "Felt strong"),
        ("2024-01-15", "Squat", 315.0, 5, 3, None),
        ("2024-01-15", "Deadlift", 405.0, 3, 2, "Heavy day"),
        ("2024-01-16", "Bench Press", 185.0, 8, 4, "Volume day"),
        ("2024-01-16", "Overhead Press", 135.0, 5, 3, None),
        ("2024-01-17", "Squat", 275.0, 8, 3, "Back off"),
        ("2024-01-17", "Deadlift", 315.0, 5, 3, None),
        ("2024-01-18", "Bench Press", 225.0, 5, 3, "Test day"),
        ("2024-01-18", "Pull Ups", 0.0, 10, 3, "Bodyweight"),
        ("2024-01-19", "Squat", 335.0, 3, 2, "PR attempt"),
    ]

    for date, exercise, weight, reps, sets, notes in sample_data:
        session.execute(text("""
            INSERT INTO TrainingEntry (date, exercise_name, weight, reps, sets, notes)
            VALUES (:date, :exercise, :weight, :reps, :sets, :notes)
        """), {
            "date": date,
            "exercise": exercise,
            "weight": weight,
            "reps": reps,
            "sets": sets,
            "notes": notes,
        })

    session.commit()

    # Run migration
    stats = migrate_from_training_entry(db_url)

    # Get a fresh session
    from app.database import get_session_factory
    factory = get_session_factory(db_url)
    new_session = factory()

    return new_session, stats


# ---------------------------------------------------------------------------
# Test: All 13 tables created
# ---------------------------------------------------------------------------

class TestTableCreation:
    def test_all_tables_exist(self, engine, session):
        """All 13 new tables should be created."""
        init_db(engine.url.render_as_string())
        from sqlalchemy import inspect
        inspector = inspect(engine)
        tables = inspector.get_table_names()

        expected_tables = [
            "athlete", "bodyweight", "equipment", "exercise",
            "program", "block", "cycle", "session",
            "prescription", "set_log", "event_log", "pr", "settings",
        ]
        for table in expected_tables:
            assert table in tables, f"Table '{table}' not found. Tables: {tables}"

    def test_exercise_substitute_table_exists(self, engine, session):
        """exercise_substitute table should also exist."""
        init_db(engine.url.render_as_string())
        from sqlalchemy import inspect
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        assert "exercise_substitute" in tables


# ---------------------------------------------------------------------------
# Test: Migration correctness
# ---------------------------------------------------------------------------

class TestMigration:
    def test_migration_creates_athlete(self, seeded_db):
        session, stats = seeded_db
        athlete = session.query(Athlete).first()
        assert athlete is not None
        assert athlete.units == "lb"
        assert athlete.plate_increment_lb == 2.5

    def test_migration_creates_exercises(self, seeded_db):
        session, stats = seeded_db
        exercises = session.query(Exercise).all()
        assert len(exercises) >= 5  # Bench Press, Squat, Deadlift, Overhead Press, Pull Ups
        names = {e.name for e in exercises}
        assert "Bench Press" in names
        assert "Squat" in names
        assert "Deadlift" in names

    def test_migration_creates_program(self, seeded_db):
        session, stats = seeded_db
        program = session.query(Program).filter_by(name="Imported History").first()
        assert program is not None

    def test_migration_creates_block_and_cycle(self, seeded_db):
        session, stats = seeded_db
        program = session.query(Program).filter_by(name="Imported History").first()
        assert program is not None
        block = session.query(Block).filter_by(program_id=program.id).first()
        assert block is not None
        cycle = session.query(Cycle).filter_by(block_id=block.id).first()
        assert cycle is not None

    def test_migration_creates_sessions(self, seeded_db):
        session, stats = seeded_db
        # We have 5 distinct dates in sample data
        assert stats["session_count"] >= 5

    def test_migration_creates_set_logs(self, seeded_db):
        session, stats = seeded_db
        # Total sets: 3+3+2+4+3+3+3+3+3+2 = 29
        assert stats["set_log_count"] == 29

    def test_no_data_loss_row_count(self, seeded_db):
        """Total set_log rows >= total sets from TrainingEntry."""
        session, stats = seeded_db
        # Original TrainingEntry had 10 rows, but with multiple sets each
        # Total sets = 3+3+2+4+3+3+3+3+3+2 = 29
        assert stats["set_log_count"] >= 10  # at least one per entry
        assert stats["set_log_count"] == 29  # exact match

    def test_spot_check_bench_press_values(self, seeded_db):
        """First Bench Press entry: 225 lb × 5 reps × 3 sets."""
        session, stats = seeded_db
        bench_ex = session.query(Exercise).filter_by(name="Bench Press").first()
        assert bench_ex is not None

        bench_prescriptions = session.query(Prescription).filter_by(
            exercise_id=bench_ex.id
        ).all()
        # 3 sets on Jan 15 + 4 sets on Jan 16 + 3 sets on Jan 18 = 10
        assert len(bench_prescriptions) == 10

        # Check first prescription's set_log
        first_pres = bench_prescriptions[0]
        slog = session.query(SetLog).filter_by(
            prescription_id=first_pres.id
        ).first()
        assert slog is not None
        assert slog.actual_load_lb == 225.0
        assert slog.actual_reps == 5
        assert slog.confidence == "low"  # RPE unknown

    def test_spot_check_squat_values(self, seeded_db):
        """Squat entry: 315 lb × 5 reps × 3 sets."""
        session, stats = seeded_db
        squat_ex = session.query(Exercise).filter_by(name="Squat").first()
        assert squat_ex is not None

        squat_prescriptions = session.query(Prescription).filter_by(
            exercise_id=squat_ex.id
        ).all()
        # 3 sets on Jan 15 + 3 sets on Jan 17 + 2 sets on Jan 19 = 8
        assert len(squat_prescriptions) == 8

    def test_e1rm_computed_via_epley(self, seeded_db):
        """e1RM should be computed via Epley: weight * (1 + reps/30)."""
        session, stats = seeded_db
        bench_ex = session.query(Exercise).filter_by(name="Bench Press").first()
        pres = session.query(Prescription).filter_by(exercise_id=bench_ex.id).first()
        slog = session.query(SetLog).filter_by(prescription_id=pres.id).first()

        expected_e1rm = 225.0 * (1 + 5 / 30.0)  # 225 * 1.1667 = 262.5
        assert slog.e1rm_lb is not None
        assert abs(slog.e1rm_lb - expected_e1rm) < 0.1

    def test_prs_backfilled(self, seeded_db):
        """PRs should be backfilled for each exercise."""
        session, stats = seeded_db
        prs = session.query(PR).all()
        assert len(prs) > 0
        assert stats["pr_count"] > 0
        # All PRs should be category 'e1rm'
        for pr in prs:
            assert pr.category == "e1rm"

    def test_training_entry_renamed_to_archive(self, seeded_db):
        """TrainingEntry should be renamed to TrainingEntry_archive."""
        session, stats = seeded_db
        from sqlalchemy import inspect
        inspector = inspect(session.bind)
        tables = inspector.get_table_names()
        assert "TrainingEntry_archive" in tables
        assert "TrainingEntry" not in tables

    def test_archive_preserves_original_data(self, seeded_db):
        """TrainingEntry_archive should still have the original data."""
        session, stats = seeded_db
        count = session.execute(text(
            "SELECT COUNT(*) FROM TrainingEntry_archive"
        )).scalar()
        assert count == 10

    def test_migration_is_idempotent(self, seeded_db):
        """Running migration again should not duplicate data."""
        session, stats = seeded_db
        first_count = stats["set_log_count"]

        # Run migration again
        import app.database as db_mod
        db_mod._engine = None
        db_mod._session_factory = None
        stats2 = migrate_from_training_entry(session.bind.url.render_as_string())

        # Should report same counts (no duplication)
        assert stats2["migrated"] is True
        # set_log count should not have doubled
        current_count = session.query(SetLog).count()
        assert current_count == first_count

    def test_migration_flag_set(self, seeded_db):
        """migration_version setting should be set to '1'."""
        session, stats = seeded_db
        setting = session.query(Settings).filter_by(key="migration_version").first()
        assert setting is not None
        assert setting.value == "1"

    def test_equipment_seeded(self, seeded_db):
        """Default equipment should be seeded."""
        session, stats = seeded_db
        equipment = session.query(Equipment).all()
        assert len(equipment) > 0
        names = {e.name for e in equipment}
        assert "barbell" in names

    def test_settings_seeded(self, seeded_db):
        """Default settings should be seeded."""
        session, stats = seeded_db
        settings = session.query(Settings).all()
        keys = {s.key for s in settings}
        assert "units" in keys
        assert "safety_notice_seen" in keys

    def test_migration_empty_training_entry(self, engine, db_url):
        """Migration with no TrainingEntry data should succeed."""
        import app.database as db_mod
        db_mod._engine = None
        db_mod._session_factory = None

        init_db(db_url)
        factory = sessionmaker(bind=get_engine(db_url))
        session = factory()

        # Create empty TrainingEntry table
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS TrainingEntry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date DATE,
                exercise_name TEXT,
                weight REAL,
                reps INTEGER,
                sets INTEGER,
                notes TEXT
            )
        """))
        session.commit()

        stats = migrate_from_training_entry(db_url)
        assert stats["migrated"] is True
        assert stats["training_entry_count"] == 0
        session.close()

    def test_migration_no_training_entry_table(self, engine, db_url):
        """Migration with no TrainingEntry table should succeed."""
        import app.database as db_mod
        db_mod._engine = None
        db_mod._session_factory = None

        init_db(db_url)
        stats = migrate_from_training_entry(db_url)
        assert stats["migrated"] is True


# ---------------------------------------------------------------------------
# Test: Backward-compatible endpoints
# ---------------------------------------------------------------------------

class TestEndpoints:
    @pytest.fixture(autouse=True)
    def setup(self, db_url):
        """Set up a fresh DB with migration for each endpoint test."""
        import app.database as db_mod
        db_mod._engine = None
        db_mod._session_factory = None

        init_db(db_url)
        factory = sessionmaker(bind=get_engine(db_url))
        session = factory()

        # Create TrainingEntry and migrate
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS TrainingEntry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date DATE,
                exercise_name TEXT,
                weight REAL,
                reps INTEGER,
                sets INTEGER,
                notes TEXT
            )
        """))
        session.execute(text("""
            INSERT INTO TrainingEntry (date, exercise_name, weight, reps, sets, notes)
            VALUES ('2024-01-15', 'Bench Press', 225.0, 5, 3, 'Test notes')
        """))
        session.commit()
        session.close()

        migrate_from_training_entry(db_url)

        # Import and configure the app
        from app.routes import app
        self.app = app
        self.db_url = db_url

    def test_log_endpoint(self, client):
        """POST /log should create new entries."""
        response = client.post("/log", json={
            "exercise_name": "Deadlift",
            "weight": 315.0,
            "reps": 5,
            "sets": 3,
            "notes": "New entry",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["logged"] is True
        assert len(data["set_log_ids"]) == 3

    def test_history_endpoint(self, client):
        """GET /history should return migrated data."""
        response = client.get("/history")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 3  # 3 sets from migrated Bench Press

    def test_history_filter_by_exercise(self, client):
        """GET /history?exercise=Bench should filter correctly."""
        response = client.get("/history", params={"exercise": "Bench"})
        assert response.status_code == 200
        data = response.json()
        for entry in data:
            assert "Bench" in entry["exercise_name"]

    def test_edit_endpoint(self, client):
        """PATCH /edit/{id} should update an entry."""
        # Get an entry ID from history
        history = client.get("/history").json()
        entry_id = history[0]["id"]

        response = client.patch(f"/edit/{entry_id}", json={
            "weight": 235.0,
            "reps": 6,
        })
        assert response.status_code == 200
        assert response.json()["updated"] is True

    def test_delete_endpoint(self, client):
        """DELETE /delete/{id} should remove an entry."""
        history = client.get("/history").json()
        entry_id = history[0]["id"]

        response = client.delete(f"/delete/{entry_id}")
        assert response.status_code == 200
        assert response.json()["deleted"] is True

        # Verify it's gone
        history_after = client.get("/history").json()
        ids_after = {e["id"] for e in history_after}
        assert entry_id not in ids_after

    def test_delete_nonexistent(self, client):
        """DELETE /delete/{id} for non-existent entry returns 404."""
        response = client.delete("/delete/99999")
        assert response.status_code == 404

    def test_edit_nonexistent(self, client):
        """PATCH /edit/{id} for non-existent entry returns 404."""
        response = client.patch("/edit/99999", json={"weight": 100.0})
        assert response.status_code == 404


@pytest.fixture
def client(db_url):
    """Create a test client for the FastAPI app."""
    import app.database as db_mod
    db_mod._engine = None
    db_mod._session_factory = None

    init_db(db_url)

    # Seed TrainingEntry and migrate
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    engine = create_engine(db_url)
    factory = sessionmaker(bind=engine)
    session = factory()

    session.execute(text("""
        CREATE TABLE IF NOT EXISTS TrainingEntry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date DATE,
            exercise_name TEXT,
            weight REAL,
            reps INTEGER,
            sets INTEGER,
            notes TEXT
        )
    """))
    session.execute(text("""
        INSERT INTO TrainingEntry (date, exercise_name, weight, reps, sets, notes)
        VALUES ('2024-01-15', 'Bench Press', 225.0, 5, 3, 'Test notes')
    """))
    session.execute(text("""
        INSERT INTO TrainingEntry (date, exercise_name, weight, reps, sets, notes)
        VALUES ('2024-01-16', 'Squat', 315.0, 5, 3, NULL)
    """))
    session.commit()
    session.close()

    migrate_from_training_entry(db_url)

    from app.routes import app
    from fastapi.testclient import TestClient
    with TestClient(app) as c:
        yield c
