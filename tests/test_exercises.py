"""
Tests for exercise library seed data, equipment filtering, and substitute logic.

Covers:
- Exercise table seeded with exercises covering all roles and movement patterns
- Each exercise has required equipment listed
- get_available_exercises(equipment_ids) returns only exercises whose equipment is checked
- get_substitutes(event_name) returns the substitute exercises from the plan's table
- Substitute table covers all 8 events
- Filtering hides exercises with unavailable equipment
- Each event returns at least one substitute
"""

import json
import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.database import (
    Athlete,
    Base,
    Equipment,
    Exercise,
    ExerciseSubstitute,
    get_engine,
)
from app.strength.exercises import (
    EVENT_SUBSTITUTES,
    SEED_EXERCISES,
    get_available_exercises,
    get_substitutes,
    seed_exercises,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db_url(tmp_path):
    """Provide a file-based SQLite database URL for each test."""
    db_file = tmp_path / "test_exercises.db"
    return f"sqlite:///{db_file}"


@pytest.fixture()
def engine(db_url):
    """Create a fresh engine for each test."""
    import app.database as db_mod
    db_mod._engine = None
    db_mod._session_factory = None
    eng = get_engine(db_url)
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture()
def session(engine):
    factory = sessionmaker(bind=engine)
    s = factory()
    yield s
    s.close()


@pytest.fixture()
def seeded_session(session: Session):
    """Session with exercises and equipment seeded."""
    # Create an athlete first (required for equipment FK)
    athlete = Athlete(name="Test Athlete", units="lb")
    session.add(athlete)
    session.flush()

    # Seed some equipment with known IDs
    equipment_list = [
        Equipment(athlete_id=athlete.id, name="barbell", available=True, category="gym"),
        Equipment(athlete_id=athlete.id, name="plates_2.5lb", available=True, category="gym"),
        Equipment(athlete_id=athlete.id, name="plates_5lb", available=True, category="gym"),
        Equipment(athlete_id=athlete.id, name="plates_10lb", available=True, category="gym"),
        Equipment(athlete_id=athlete.id, name="plates_25lb", available=True, category="gym"),
        Equipment(athlete_id=athlete.id, name="plates_35lb", available=True, category="gym"),
        Equipment(athlete_id=athlete.id, name="bench", available=True, category="gym"),
        Equipment(athlete_id=athlete.id, name="squat_rack", available=True, category="gym"),
        Equipment(athlete_id=athlete.id, name="dumbbells", available=True, category="gym"),
        Equipment(athlete_id=athlete.id, name="pull_up_bar", available=True, category="gym"),
        Equipment(athlete_id=athlete.id, name="cable_machine", available=True, category="gym"),
        Equipment(athlete_id=athlete.id, name="leg_press", available=True, category="gym"),
        Equipment(athlete_id=athlete.id, name="lat_machine", available=True, category="gym"),
        Equipment(athlete_id=athlete.id, name="chest_press_machine", available=True, category="gym"),
        Equipment(athlete_id=athlete.id, name="sandbag", available=True, category="personal"),
        Equipment(athlete_id=athlete.id, name="kettlebells", available=True, category="club"),
        Equipment(athlete_id=athlete.id, name="medicine_balls", available=True, category="club"),
        Equipment(athlete_id=athlete.id, name="sled", available=True, category="club"),
        Equipment(athlete_id=athlete.id, name="turf_sled", available=True, category="club"),
        Equipment(athlete_id=athlete.id, name="tires", available=True, category="club"),
        Equipment(athlete_id=athlete.id, name="landmines", available=True, category="club"),
        Equipment(athlete_id=athlete.id, name="rowing_machine", available=True, category="gym"),
    ]
    session.add_all(equipment_list)
    session.flush()

    # Seed exercises
    seed_exercises(session)
    session.commit()
    return session


# ---------------------------------------------------------------------------
# Test: Seed data completeness
# ---------------------------------------------------------------------------

class TestSeedData:

    def test_all_roles_present(self, seeded_session: Session):
        """Exercises cover all five roles."""
        roles = {ex.role for ex in seeded_session.query(Exercise).all()}
        expected_roles = {"main", "secondary", "accessory", "event", "event_substitute"}
        assert expected_roles.issubset(roles), f"Missing roles: {expected_roles - roles}"

    def test_all_movement_patterns_present(self, seeded_session: Session):
        """Exercises cover all movement patterns."""
        patterns = {ex.movement_pattern for ex in seeded_session.query(Exercise).all()}
        expected_patterns = {"hinge", "squat", "press", "carry", "load", "pull", "core"}
        assert expected_patterns.issubset(patterns), f"Missing patterns: {expected_patterns - patterns}"

    def test_each_exercise_has_equipment(self, seeded_session: Session):
        """Every exercise has a required_equipment field (may be empty list)."""
        for ex in seeded_session.query(Exercise).all():
            equip = json.loads(ex.required_equipment) if ex.required_equipment else []
            assert isinstance(equip, list), f"{ex.name}: required_equipment is not a list"

    def test_seed_is_idempotent(self, seeded_session: Session):
        """Calling seed_exercises twice does not duplicate rows."""
        count_before = seeded_session.query(Exercise).count()
        seed_exercises(seeded_session)
        seeded_session.commit()
        count_after = seeded_session.query(Exercise).count()
        assert count_before == count_after

    def test_seed_exercise_count(self, seeded_session: Session):
        """All seed exercises are present."""
        names = {ex.name for ex in seeded_session.query(Exercise).all()}
        for seed in SEED_EXERCISES:
            assert seed["name"] in names, f"Missing seed exercise: {seed['name']}"


# ---------------------------------------------------------------------------
# Test: Equipment filtering
# ---------------------------------------------------------------------------

class TestEquipmentFiltering:

    def test_full_equipment_returns_all(self, seeded_session: Session):
        """With all equipment available, all exercises are returned."""
        all_ids = [eq.id for eq in seeded_session.query(Equipment).all()]
        available = get_available_exercises(seeded_session, all_ids)
        # All non-hidden exercises should be returned
        all_exercises = seeded_session.query(Exercise).filter_by(is_hidden=False).all()
        assert len(available) == len(all_exercises)

    def test_no_equipment_returns_only_bodyweight(self, seeded_session: Session):
        """With no equipment, only exercises requiring no equipment are returned."""
        available = get_available_exercises(seeded_session, [])
        names = {ex.name for ex in available}
        # Plank and Ab Wheel Rollout require no equipment
        assert "Plank" in names
        assert "Ab Wheel Rollout" in names
        # Exercises requiring equipment should NOT be present
        assert "Back Squat" not in names
        assert "Overhead Press" not in names

    def test_filtering_hides_exercises_with_unavailable_equipment(self, seeded_session: Session):
        """Exercises needing unavailable equipment are excluded."""
        # Only give access to dumbbells
        db_equipment = seeded_session.query(Equipment).filter_by(name="dumbbells").first()
        assert db_equipment is not None
        available = get_available_exercises(seeded_session, [db_equipment.id])
        names = {ex.name for ex in available}
        # Dumbbell exercises should be present
        assert "Dumbbell Bench Press" in names
        assert "Dumbbell Curl" in names
        assert "Dumbbell Shoulder Press" in names
        # Barbell exercises should NOT be present
        assert "Back Squat" not in names
        assert "Overhead Press" not in names
        assert "Conventional Deadlift" not in names

    def test_filtering_with_partial_equipment(self, seeded_session: Session):
        """Only exercises whose equipment is fully available are returned."""
        # Give barbell + plates but no squat rack
        equip_names = ["barbell", "plates_2.5lb", "plates_5lb", "plates_10lb",
                       "plates_25lb", "plates_35lb"]
        equip_ids = [
            eq.id for eq in seeded_session.query(Equipment)
            .filter(Equipment.name.in_(equip_names)).all()
        ]
        available = get_available_exercises(seeded_session, equip_ids)
        names = {ex.name for ex in available}
        # Overhead Press needs barbell + plates (no rack) -> should be present
        assert "Overhead Press" in names
        # Back Squat needs squat_rack -> should NOT be present
        assert "Back Squat" not in names
        # Conventional Deadlift needs barbell + plates -> should be present
        assert "Conventional Deadlift" in names

    def test_empty_equipment_ids(self, seeded_session: Session):
        """Passing empty list returns only no-equipment exercises."""
        available = get_available_exercises(seeded_session, [])
        for ex in available:
            equip = json.loads(ex.required_equipment) if ex.required_equipment else []
            assert len(equip) == 0, f"{ex.name} requires equipment but was returned with no equipment"


# ---------------------------------------------------------------------------
# Test: Substitute logic
# ---------------------------------------------------------------------------

class TestSubstitutes:

    def test_all_events_have_substitutes(self, seeded_session: Session):
        """Each of the 8 events returns at least one substitute."""
        events = [
            "Log Press", "Axle Press", "Strongman Deadlift", "Farmers Walk",
            "Yoke Walk", "Atlas Stone", "Loading Medley", "Truck Pull",
        ]
        for event in events:
            subs = get_substitutes(seeded_session, event)
            assert len(subs) >= 1, f"{event} has no substitutes"

    def test_log_press_substitutes(self, seeded_session: Session):
        """Log Press returns press-style substitutes."""
        subs = get_substitutes(seeded_session, "Log Press")
        names = {ex.name for ex in subs}
        assert "Dumbbell Shoulder Press" in names

    def test_axle_press_substitutes(self, seeded_session: Session):
        """Axle Press returns press-style substitutes."""
        subs = get_substitutes(seeded_session, "Axle Press")
        names = {ex.name for ex in subs}
        assert "Dumbbell Shoulder Press" in names

    def test_deadlift_substitutes(self, seeded_session: Session):
        """Strongman Deadlift returns hinge-style substitutes."""
        subs = get_substitutes(seeded_session, "Strongman Deadlift")
        names = {ex.name for ex in subs}
        assert "Trap Bar Deadlift" in names

    def test_farmers_walk_substitutes(self, seeded_session: Session):
        """Farmers Walk returns carry-style substitutes."""
        subs = get_substitutes(seeded_session, "Farmers Walk")
        names = {ex.name for ex in subs}
        assert "Kettlebell Farmers Walk" in names

    def test_yoke_walk_substitutes(self, seeded_session: Session):
        """Yoke Walk returns load/carry substitutes."""
        subs = get_substitutes(seeded_session, "Yoke Walk")
        names = {ex.name for ex in subs}
        assert "Sandbag Shouldering" in names

    def test_atlas_stone_substitutes(self, seeded_session: Session):
        """Atlas Stone returns load-style substitutes."""
        subs = get_substitutes(seeded_session, "Atlas Stone")
        names = {ex.name for ex in subs}
        assert "Sandbag Shouldering" in names

    def test_loading_medley_substitutes(self, seeded_session: Session):
        """Loading Medley returns mixed substitutes."""
        subs = get_substitutes(seeded_session, "Loading Medley")
        names = {ex.name for ex in subs}
        assert "Sandbag Shouldering" in names

    def test_truck_pull_substitutes(self, seeded_session: Session):
        """Truck Pull returns pull-style substitutes."""
        subs = get_substitutes(seeded_session, "Truck Pull")
        names = {ex.name for ex in subs}
        assert "Turf Sled Drag" in names

    def test_unknown_event_returns_empty(self, seeded_session: Session):
        """An event name that doesn't exist returns an empty list."""
        subs = get_substitutes(seeded_session, "Nonexistent Event")
        assert subs == []

    def test_substitutes_ordered_by_priority(self, seeded_session: Session):
        """Substitutes are returned in priority order."""
        subs = get_substitutes(seeded_session, "Log Press")
        names = [ex.name for ex in subs]
        # First substitute should be the highest priority (priority=1)
        assert names[0] == "Dumbbell Shoulder Press"

    def test_substitute_table_covers_all_8_events(self, seeded_session: Session):
        """The exercise_substitute table has entries for all 8 events."""
        events = [
            "Log Press", "Axle Press", "Strongman Deadlift", "Farmers Walk",
            "Yoke Walk", "Atlas Stone", "Loading Medley", "Truck Pull",
        ]
        for event_name in events:
            primary = seeded_session.query(Exercise).filter_by(name=event_name).first()
            assert primary is not None, f"Event '{event_name}' not found in exercise table"
            sub_count = (
                seeded_session.query(ExerciseSubstitute)
                .filter_by(primary_exercise_id=primary.id)
                .count()
            )
            assert sub_count >= 1, f"Event '{event_name}' has no substitute entries"
