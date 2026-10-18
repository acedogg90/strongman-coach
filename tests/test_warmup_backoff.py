"""Tests for warm-up set generation and back-off set logging.

Covers:
- Warm-up progression generation for various top-set weights
- Back-off weight calculations matching the RTS fatigue-percent table
- Drop percentage defaults per block phase
- Edge cases (low weights, deload phase, series generation)
- Integration: API endpoints store warm-up and back-off prescriptions in DB
"""

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.database import (
    Base,
    Prescription,
    get_engine,
    init_db,
    migrate_from_training_entry,
)
from app.strength.warmup_backoff import (
    BAR_WEIGHT_LB,
    RTS_DROP_TABLE,
    BackoffSet,
    WarmupSet,
    calculate_backoff,
    calculate_backoff_series,
    generate_warmups,
    get_default_drop_pct,
)


# ---------------------------------------------------------------------------
# Fixtures for integration tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_url(tmp_path):
    """Provide a file-based SQLite database URL for each test."""
    db_file = tmp_path / "test_wb.db"
    return f"sqlite:///{db_file}"


@pytest.fixture()
def warmup_client(db_url):
    """Create a test client with a seeded DB for warm-up/back-off integration tests."""
    import app.database as db_mod

    db_mod._engine = None
    db_mod._session_factory = None

    init_db(db_url)

    # Seed TrainingEntry and migrate
    factory = sessionmaker(bind=get_engine(db_url))
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
    session.commit()
    session.close()

    migrate_from_training_entry(db_url)

    from app.routes import app
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Warm-up generation tests
# ---------------------------------------------------------------------------


class TestGenerateWarmups:
    """Test warm-up progression generation."""

    def test_warmup_starts_with_empty_bar(self):
        warmups = generate_warmups(300.0)
        assert warmups[0].load_lb == BAR_WEIGHT_LB
        assert warmups[0].is_empty_bar is True

    def test_warmup_progression_300_lb(self):
        """300 lb top set: bar → 40% → 60% → 80%."""
        warmups = generate_warmups(300.0, plate_increment=2.5)
        # 40% of 300 = 120, 60% = 180, 80% = 240
        loads = [w.load_lb for w in warmups]
        assert loads[0] == 45.0  # empty bar
        assert loads[1] == 120.0  # 40%
        assert loads[2] == 180.0  # 60%
        assert loads[3] == 240.0  # 80%

    def test_warmup_progression_405_lb(self):
        """405 lb top set with 2.5 lb plates."""
        warmups = generate_warmups(405.0, plate_increment=2.5)
        loads = [w.load_lb for w in warmups]
        assert loads[0] == 45.0  # empty bar
        # 40% of 405 = 162.0, floor(162/2.5)*2.5 = 160.0
        assert loads[1] == 160.0
        # 60% of 405 = 243.0, floor(243/2.5)*2.5 = 242.5
        assert loads[2] == 242.5
        # 80% of 405 = 324.0, floor(324/2.5)*2.5 = 322.5
        assert loads[3] == 322.5

    def test_warmup_progression_225_lb(self):
        """225 lb top set: some steps may be skipped if ≤ bar weight."""
        warmups = generate_warmups(225.0, plate_increment=2.5)
        loads = [w.load_lb for w in warmups]
        assert loads[0] == 45.0  # empty bar
        # 40% of 225 = 90.0
        assert loads[1] == 90.0
        # 60% of 225 = 135.0
        assert loads[2] == 135.0
        # 80% of 225 = 180.0
        assert loads[3] == 180.0

    def test_warmup_low_weight_skips_steps(self):
        """When top set is low, percentage steps ≤ bar weight are skipped."""
        warmups = generate_warmups(100.0, plate_increment=2.5)
        loads = [w.load_lb for w in warmups]
        assert loads[0] == 45.0  # empty bar
        # 40% of 100 = 40 → ≤ 45, skipped
        # 60% of 100 = 60
        assert loads[1] == 60.0
        # 80% of 100 = 80
        assert loads[2] == 80.0

    def test_warmup_very_low_weight_only_bar(self):
        """When top set is very low, only the empty bar remains."""
        warmups = generate_warmups(50.0, plate_increment=2.5)
        loads = [w.load_lb for w in warmups]
        # 40% of 50 = 20 ≤ 45, 60% = 30 ≤ 45, 80% = 40 ≤ 45
        assert loads == [45.0]

    def test_warmup_plate_increment_rounding(self):
        """Warm-up loads are rounded down to plate increment."""
        warmups = generate_warmups(310.0, plate_increment=5.0)
        loads = [w.load_lb for w in warmups]
        # 40% of 310 = 124 → floor to 5 = 120
        assert loads[1] == 120.0
        # 60% of 310 = 186 → floor to 5 = 185
        assert loads[2] == 185.0
        # 80% of 310 = 248 → floor to 5 = 245
        assert loads[3] == 245.0

    def test_warmup_reps_default(self):
        warmups = generate_warmups(300.0)
        for w in warmups:
            assert w.reps == 3

    def test_warmup_custom_reps(self):
        warmups = generate_warmups(300.0, reps=5)
        for w in warmups:
            assert w.reps == 5

    def test_warmup_negative_weight_raises(self):
        with pytest.raises(ValueError, match="positive"):
            generate_warmups(-100.0)

    def test_warmup_zero_weight_raises(self):
        with pytest.raises(ValueError, match="positive"):
            generate_warmups(0.0)

    def test_warmup_custom_bar_weight(self):
        """Allow a different bar weight (e.g. 35 lb women's bar)."""
        warmups = generate_warmups(200.0, bar_weight=35.0)
        assert warmups[0].load_lb == 35.0


# ---------------------------------------------------------------------------
# Back-off calculation tests
# ---------------------------------------------------------------------------


class TestCalculateBackoff:
    """Test back-off weight calculations."""

    def test_backoff_5_percent_drop(self):
        """300 lb top set with 5% drop → 285 lb."""
        result = calculate_backoff(300.0, 5.0)
        assert result.weight_lb == 285.0
        assert result.drop_pct == 5.0

    def test_backoff_6_percent_drop(self):
        """300 lb top set with 6% drop → 282 lb."""
        result = calculate_backoff(300.0, 6.0)
        assert result.weight_lb == 282.0
        assert result.drop_pct == 6.0

    def test_backoff_4_percent_drop(self):
        """405 lb top set with 4% drop → 388.8 lb."""
        result = calculate_backoff(405.0, 4.0)
        assert result.weight_lb == 388.8
        assert result.drop_pct == 4.0

    def test_backoff_2_percent_drop(self):
        """500 lb top set with 2% drop → 490 lb."""
        result = calculate_backoff(500.0, 2.0)
        assert result.weight_lb == 490.0

    def test_backoff_7_percent_drop(self):
        """RTS table max drop: 7%."""
        result = calculate_backoff(315.0, 7.0)
        # 315 * 0.93 = 292.95, rounded to 1 decimal = 292.9
        assert result.weight_lb == 292.9
        assert result.drop_pct == 7.0

    def test_backoff_zero_drop(self):
        """Deload phase: 0% drop means same weight."""
        result = calculate_backoff(300.0, 0.0)
        assert result.weight_lb == 300.0

    def test_backoff_stores_exercise_and_reps(self):
        result = calculate_backoff(300.0, 5.0, exercise="Back Squat", reps=5)
        assert result.exercise == "Back Squat"
        assert result.reps == 5

    def test_backoff_stores_rpe_and_notes(self):
        result = calculate_backoff(
            300.0, 5.0, exercise="Deadlift", reps=3, rpe=7.5, notes="felt good"
        )
        assert result.rpe == 7.5
        assert result.notes == "felt good"

    def test_backoff_negative_weight_raises(self):
        with pytest.raises(ValueError, match="positive"):
            calculate_backoff(-100.0, 5.0)

    def test_backoff_zero_weight_raises(self):
        with pytest.raises(ValueError, match="positive"):
            calculate_backoff(0.0, 5.0)

    def test_backoff_negative_drop_raises(self):
        with pytest.raises(ValueError, match="between 0 and 100"):
            calculate_backoff(300.0, -5.0)

    def test_backoff_drop_over_100_raises(self):
        with pytest.raises(ValueError, match="between 0 and 100"):
            calculate_backoff(300.0, 101.0)


# ---------------------------------------------------------------------------
# RTS drop table tests
# ---------------------------------------------------------------------------


class TestRTSDropTable:
    """Test that drop percentages match the RTS fatigue-percent table."""

    def test_accumulation_range(self):
        lo, hi = RTS_DROP_TABLE["accumulation"]
        assert lo == 5.0
        assert hi == 6.0

    def test_intensification_range(self):
        lo, hi = RTS_DROP_TABLE["intensification"]
        assert lo == 4.0
        assert hi == 5.0

    def test_realization_range(self):
        lo, hi = RTS_DROP_TABLE["realization"]
        assert lo == 2.0
        assert hi == 3.0

    def test_deload_range(self):
        lo, hi = RTS_DROP_TABLE["deload"]
        assert lo == 0.0
        assert hi == 0.0

    def test_default_drop_accumulation(self):
        assert get_default_drop_pct("accumulation") == 5.5

    def test_default_drop_intensification(self):
        assert get_default_drop_pct("intensification") == 4.5

    def test_default_drop_realization(self):
        assert get_default_drop_pct("realization") == 2.5

    def test_default_drop_deload(self):
        assert get_default_drop_pct("deload") == 0.0

    def test_default_drop_case_insensitive(self):
        assert get_default_drop_pct("Accumulation") == 5.5
        assert get_default_drop_pct("INTENSIFICATION") == 4.5

    def test_default_drop_unknown_phase_raises(self):
        with pytest.raises(ValueError, match="Unknown block phase"):
            get_default_drop_pct("unknown")


# ---------------------------------------------------------------------------
# Back-off series tests
# ---------------------------------------------------------------------------


class TestCalculateBackoffSeries:
    """Test generation of multiple back-off sets."""

    def test_series_length(self):
        series = calculate_backoff_series(300.0, 5.0, max_sets=4)
        assert len(series) == 4

    def test_series_increasing_drop(self):
        series = calculate_backoff_series(300.0, 5.0, max_sets=3)
        # Drops: 5%, 10%, 15%
        assert series[0].drop_pct == 5.0
        assert series[1].drop_pct == 10.0
        assert series[2].drop_pct == 15.0

    def test_series_weights_decrease(self):
        series = calculate_backoff_series(300.0, 5.0, max_sets=3)
        assert series[0].weight_lb > series[1].weight_lb > series[2].weight_lb

    def test_series_max_sets_default(self):
        series = calculate_backoff_series(300.0, 5.0)
        assert len(series) == 6

    def test_series_stops_before_100_drop(self):
        """If cumulative drop would reach 100%, stop early."""
        series = calculate_backoff_series(300.0, 50.0, max_sets=10)
        # 50, 100 → stops at 1 set (100% would be excluded)
        assert len(series) == 1
        assert series[0].drop_pct == 50.0

    def test_series_exercise_propagated(self):
        series = calculate_backoff_series(
            300.0, 5.0, exercise="Bench Press", max_sets=2
        )
        for s in series:
            assert s.exercise == "Bench Press"


# ---------------------------------------------------------------------------
# Integration tests: API endpoints store warm-up and back-off prescriptions
# ---------------------------------------------------------------------------


class TestWarmupIntegration:
    """Integration tests: POST /warmups stores prescriptions in the database."""

    def test_warmup_endpoint_returns_200(self, warmup_client):
        """POST /warmups should succeed and return generated warm-ups."""
        resp = warmup_client.post("/warmups", json={
            "exercise_name": "Back Squat",
            "top_set_weight": 300.0,
            "reps": 3,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["generated"] is True
        assert data["warmup_count"] >= 1

    def test_warmup_creates_prescriptions_in_db(self, warmup_client, db_url):
        """Warm-up prescriptions are stored with is_warmup=True."""
        warmup_client.post("/warmups", json={
            "exercise_name": "Deadlift",
            "top_set_weight": 405.0,
            "reps": 3,
        })

        # Verify prescriptions exist in DB
        factory = sessionmaker(bind=get_engine(db_url))
        session = factory()
        warmup_pres = session.query(Prescription).filter_by(
            is_warmup=True, is_backoff=False
        ).all()
        session.close()

        assert len(warmup_pres) >= 1
        for pres in warmup_pres:
            assert pres.is_warmup is True
            assert pres.is_backoff is False
            assert pres.prescribed_load_lb > 0

    def test_warmup_prescription_loads_match_progression(self, warmup_client, db_url):
        """Warm-up prescription loads follow bar → 40% → 60% → 80% progression."""
        warmup_client.post("/warmups", json={
            "exercise_name": "Bench Press",
            "top_set_weight": 300.0,
            "reps": 3,
            "plate_increment": 2.5,
        })

        factory = sessionmaker(bind=get_engine(db_url))
        session = factory()
        warmup_pres = session.query(Prescription).filter_by(
            is_warmup=True, is_backoff=False
        ).order_by(Prescription.set_number).all()
        session.close()

        loads = [p.prescribed_load_lb for p in warmup_pres]
        # First should be bar weight
        assert loads[0] == 45.0
        # Should be ascending
        for i in range(1, len(loads)):
            assert loads[i] > loads[i - 1]

    def test_warmup_prescription_reps_stored(self, warmup_client, db_url):
        """Warm-up prescriptions store the correct rep count."""
        warmup_client.post("/warmups", json={
            "exercise_name": "Overhead Press",
            "top_set_weight": 185.0,
            "reps": 5,
        })

        factory = sessionmaker(bind=get_engine(db_url))
        session = factory()
        warmup_pres = session.query(Prescription).filter_by(
            is_warmup=True, is_backoff=False
        ).all()
        session.close()

        for pres in warmup_pres:
            assert pres.prescribed_reps == 5


class TestBackoffIntegration:
    """Integration tests: POST /backoffs stores prescriptions in the database."""

    def test_backoff_endpoint_returns_200(self, warmup_client):
        """POST /backoffs should succeed and return generated back-offs."""
        resp = warmup_client.post("/backoffs", json={
            "exercise_name": "Back Squat",
            "top_set_weight": 300.0,
            "reps": 5,
            "drop_pct": 5.0,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["generated"] is True
        assert data["backoff_count"] >= 1

    def test_backoff_creates_prescriptions_in_db(self, warmup_client, db_url):
        """Back-off prescriptions are stored with is_backoff=True."""
        warmup_client.post("/backoffs", json={
            "exercise_name": "Deadlift",
            "top_set_weight": 405.0,
            "reps": 5,
            "drop_pct": 5.0,
        })

        factory = sessionmaker(bind=get_engine(db_url))
        session = factory()
        backoff_pres = session.query(Prescription).filter_by(
            is_warmup=False, is_backoff=True
        ).all()
        session.close()

        assert len(backoff_pres) >= 1
        for pres in backoff_pres:
            assert pres.is_backoff is True
            assert pres.is_warmup is False
            assert pres.fatigue_drop_pct > 0

    def test_backoff_prescription_weight_calculation(self, warmup_client, db_url):
        """Back-off prescription weights match top_set × (1 - drop_pct/100)."""
        warmup_client.post("/backoffs", json={
            "exercise_name": "Bench Press",
            "top_set_weight": 300.0,
            "reps": 5,
            "drop_pct": 5.0,
            "max_sets": 3,
        })

        factory = sessionmaker(bind=get_engine(db_url))
        session = factory()
        backoff_pres = session.query(Prescription).filter_by(
            is_warmup=False, is_backoff=True
        ).order_by(Prescription.set_number).all()
        session.close()

        # First back-off: 300 × (1 - 0.05) = 285
        assert backoff_pres[0].prescribed_load_lb == pytest.approx(285.0, abs=0.5)
        # Second back-off: 300 × (1 - 0.10) = 270
        assert backoff_pres[1].prescribed_load_lb == pytest.approx(270.0, abs=0.5)
        # Third back-off: 300 × (1 - 0.15) = 255
        assert backoff_pres[2].prescribed_load_lb == pytest.approx(255.0, abs=0.5)

    def test_backoff_fatigue_drop_pct_stored(self, warmup_client, db_url):
        """Back-off prescriptions store the correct fatigue_drop_pct."""
        warmup_client.post("/backoffs", json={
            "exercise_name": "Squat",
            "top_set_weight": 315.0,
            "reps": 5,
            "drop_pct": 6.0,
            "max_sets": 2,
        })

        factory = sessionmaker(bind=get_engine(db_url))
        session = factory()
        backoff_pres = session.query(Prescription).filter_by(
            is_warmup=False, is_backoff=True
        ).order_by(Prescription.set_number).all()
        session.close()

        # First: 6%, second: 12%
        assert backoff_pres[0].fatigue_drop_pct == pytest.approx(6.0, abs=0.1)
        assert backoff_pres[1].fatigue_drop_pct == pytest.approx(12.0, abs=0.1)

    def test_backoff_with_phase_uses_default_drop(self, warmup_client, db_url):
        """When phase is provided, default drop percentage is used."""
        warmup_client.post("/backoffs", json={
            "exercise_name": "Deadlift",
            "top_set_weight": 405.0,
            "reps": 5,
            "phase": "intensification",
            "max_sets": 1,
        })

        factory = sessionmaker(bind=get_engine(db_url))
        session = factory()
        backoff_pres = session.query(Prescription).filter_by(
            is_warmup=False, is_backoff=True
        ).all()
        session.close()

        # Intensification default drop is 4.5%
        assert backoff_pres[0].fatigue_drop_pct == pytest.approx(4.5, abs=0.1)
        # 405 × (1 - 0.045) = 387.225
        assert backoff_pres[0].prescribed_load_lb == pytest.approx(387.2, abs=0.5)

    def test_backoff_stores_reps(self, warmup_client, db_url):
        """Back-off prescriptions store the correct rep count."""
        warmup_client.post("/backoffs", json={
            "exercise_name": "Bench Press",
            "top_set_weight": 225.0,
            "reps": 8,
            "drop_pct": 5.0,
            "max_sets": 1,
        })

        factory = sessionmaker(bind=get_engine(db_url))
        session = factory()
        backoff_pres = session.query(Prescription).filter_by(
            is_warmup=False, is_backoff=True
        ).all()
        session.close()

        assert backoff_pres[0].prescribed_reps == 8

    def test_warmup_and_backoff_coexist(self, warmup_client, db_url):
        """Warm-up and back-off prescriptions can coexist in the same session."""
        warmup_client.post("/warmups", json={
            "exercise_name": "Squat",
            "top_set_weight": 300.0,
            "reps": 3,
        })
        warmup_client.post("/backoffs", json={
            "exercise_name": "Squat",
            "top_set_weight": 300.0,
            "reps": 5,
            "drop_pct": 5.0,
            "max_sets": 2,
        })

        factory = sessionmaker(bind=get_engine(db_url))
        session = factory()
        warmup_count = session.query(Prescription).filter_by(
            is_warmup=True, is_backoff=False
        ).count()
        backoff_count = session.query(Prescription).filter_by(
            is_warmup=False, is_backoff=True
        ).count()
        session.close()

        assert warmup_count >= 1
        assert backoff_count >= 1
