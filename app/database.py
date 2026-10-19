"""
Strongman Coach – Database models and migration.

All 13 tables defined as SQLAlchemy 2.0 declarative models.
Migration from TrainingEntry (legacy) to set_log is idempotent.
"""

from __future__ import annotations

import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    REAL,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    inspect,
    text,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Session,
    relationship,
    sessionmaker,
)

# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# 4.1 athlete
# ---------------------------------------------------------------------------

class Athlete(Base):
    __tablename__ = "athlete"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    height_cm = Column(REAL)
    age = Column(Integer)
    training_age_months = Column(Integer)
    units = Column(String(4), default="lb")
    plate_increment_lb = Column(REAL, default=2.5)
    dumbbell_max_lb = Column(Integer, default=120)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))

    # relationships
    bodyweights = relationship("Bodyweight", back_populates="athlete")
    equipments = relationship("Equipment", back_populates="athlete")
    programs = relationship("Program", back_populates="athlete")
    prs = relationship("PR", back_populates="athlete")
    settings = relationship("Settings", back_populates="athlete")


# ---------------------------------------------------------------------------
# 4.2 bodyweight
# ---------------------------------------------------------------------------

class Bodyweight(Base):
    __tablename__ = "bodyweight"

    id = Column(Integer, primary_key=True, autoincrement=True)
    athlete_id = Column(Integer, ForeignKey("athlete.id"), nullable=False)
    weight_lb = Column(REAL, nullable=False)
    date = Column(Date, nullable=False)
    notes = Column(Text)

    athlete = relationship("Athlete", back_populates="bodyweights")


# ---------------------------------------------------------------------------
# 4.3 equipment
# ---------------------------------------------------------------------------

class Equipment(Base):
    __tablename__ = "equipment"

    id = Column(Integer, primary_key=True, autoincrement=True)
    athlete_id = Column(Integer, ForeignKey("athlete.id"), nullable=False)
    name = Column(String(100), nullable=False)
    available = Column(Boolean, default=True)
    category = Column(String(30))

    athlete = relationship("Athlete", back_populates="equipments")


# ---------------------------------------------------------------------------
# 4.4 exercise
# ---------------------------------------------------------------------------

class Exercise(Base):
    __tablename__ = "exercise"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True)
    role = Column(String(20))
    movement_pattern = Column(String(20))
    required_equipment = Column(Text)  # JSON array
    metric_type = Column(String(20), default="load_reps")
    is_hidden = Column(Boolean, default=False)

    prescriptions = relationship("Prescription", back_populates="exercise")
    prs = relationship("PR", back_populates="exercise")
    set_logs = relationship("SetLog", back_populates="exercise")


# ---------------------------------------------------------------------------
# 4.5 exercise_substitute
# ---------------------------------------------------------------------------

class ExerciseSubstitute(Base):
    __tablename__ = "exercise_substitute"

    id = Column(Integer, primary_key=True, autoincrement=True)
    primary_exercise_id = Column(Integer, ForeignKey("exercise.id"), nullable=False)
    substitute_exercise_id = Column(Integer, ForeignKey("exercise.id"), nullable=False)
    priority = Column(Integer, default=1)


# ---------------------------------------------------------------------------
# 4.6 program
# ---------------------------------------------------------------------------

class Program(Base):
    __tablename__ = "program"

    id = Column(Integer, primary_key=True, autoincrement=True)
    athlete_id = Column(Integer, ForeignKey("athlete.id"), nullable=False)
    name = Column(String(100), nullable=False)
    phase = Column(String(20))
    start_date = Column(Date, nullable=False)
    end_date = Column(Date)
    is_active = Column(Boolean, default=False)

    athlete = relationship("Athlete", back_populates="programs")
    blocks = relationship("Block", back_populates="program")


# ---------------------------------------------------------------------------
# 4.7 block
# ---------------------------------------------------------------------------

class Block(Base):
    __tablename__ = "block"

    id = Column(Integer, primary_key=True, autoincrement=True)
    program_id = Column(Integer, ForeignKey("program.id"), nullable=False)
    block_number = Column(Integer, nullable=False)
    is_deload = Column(Boolean, default=False)
    variation_name = Column(String(100))
    start_date = Column(Date, nullable=False)
    end_date = Column(Date)

    program = relationship("Program", back_populates="blocks")
    cycles = relationship("Cycle", back_populates="block")


# ---------------------------------------------------------------------------
# 4.8 cycle
# ---------------------------------------------------------------------------

class Cycle(Base):
    __tablename__ = "cycle"

    id = Column(Integer, primary_key=True, autoincrement=True)
    block_id = Column(Integer, ForeignKey("block.id"), nullable=False)
    cycle_number = Column(Integer, nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date)

    block = relationship("Block", back_populates="cycles")
    sessions = relationship("Session", back_populates="cycle")


# ---------------------------------------------------------------------------
# 4.9 session
# ---------------------------------------------------------------------------

class Session(Base):
    __tablename__ = "session"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cycle_id = Column(Integer, ForeignKey("cycle.id"), nullable=False)
    day_label = Column(String(10))
    scheduled_date = Column(Date, nullable=False)
    actual_date = Column(Date)
    status = Column(String(20), default="planned")
    readiness_sleep = Column(Integer)
    readiness_soreness = Column(Integer)
    readiness_stress = Column(Integer)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))

    cycle = relationship("Cycle", back_populates="sessions")
    prescriptions = relationship("Prescription", back_populates="session")
    set_logs = relationship("SetLog", back_populates="session")


# ---------------------------------------------------------------------------
# 4.10 prescription
# ---------------------------------------------------------------------------

class Prescription(Base):
    __tablename__ = "prescription"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("session.id"), nullable=False)
    exercise_id = Column(Integer, ForeignKey("exercise.id"), nullable=False)
    set_number = Column(Integer, nullable=False)
    prescribed_reps = Column(Integer)
    prescribed_rpe = Column(REAL)
    prescribed_load_lb = Column(REAL)
    is_warmup = Column(Boolean, default=False)
    is_backoff = Column(Boolean, default=False)
    fatigue_drop_pct = Column(REAL, default=0)
    adjustment_note = Column(Text)

    session = relationship("Session", back_populates="prescriptions")
    exercise = relationship("Exercise", back_populates="prescriptions")
    set_log = relationship("SetLog", back_populates="prescription")
    event_log = relationship("EventLog", back_populates="prescription")


# ---------------------------------------------------------------------------
# 4.11 set_log
# ---------------------------------------------------------------------------

class SetLog(Base):
    __tablename__ = "set_log"
    __table_args__ = (
        Index("ix_set_log_exercise_session", "exercise_id", "session_id"),
        Index("ix_set_log_idempotency", "idempotency_key", unique=True),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    exercise_id = Column(Integer, ForeignKey("exercise.id"), nullable=False)
    session_id = Column(Integer, ForeignKey("session.id"), nullable=True)
    prescription_id = Column(Integer, ForeignKey("prescription.id"), nullable=True)
    actual_load_lb = Column(REAL, nullable=False)
    actual_reps = Column(Integer, nullable=False)
    rpe = Column(REAL)
    e1rm_lb = Column(REAL)
    confidence = Column(String(10), default="low")
    pain_flag = Column(Boolean, default=False)
    set_type = Column(String(20), default="top")  # warmup, top, backoff, apre
    note = Column(Text)
    idempotency_key = Column(String(64), nullable=True)
    logged_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))

    exercise = relationship("Exercise", back_populates="set_logs")
    prescription = relationship("Prescription", back_populates="set_log")
    session = relationship("Session", back_populates="set_logs")


# ---------------------------------------------------------------------------
# 4.12 event_log
# ---------------------------------------------------------------------------

class EventLog(Base):
    __tablename__ = "event_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    prescription_id = Column(Integer, ForeignKey("prescription.id"), nullable=False)
    load_lb = Column(REAL)
    distance_ft = Column(REAL)
    time_sec = Column(REAL)
    reps = Column(Integer)
    note = Column(Text)
    logged_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))

    prescription = relationship("Prescription", back_populates="event_log")


# ---------------------------------------------------------------------------
# 4.13 pr
# ---------------------------------------------------------------------------

class PR(Base):
    __tablename__ = "pr"

    id = Column(Integer, primary_key=True, autoincrement=True)
    athlete_id = Column(Integer, ForeignKey("athlete.id"), nullable=False)
    exercise_id = Column(Integer, ForeignKey("exercise.id"), nullable=False)
    category = Column(String(20))
    value_lb = Column(REAL, nullable=False)
    reps = Column(Integer)
    date = Column(Date, nullable=False)

    athlete = relationship("Athlete", back_populates="prs")
    exercise = relationship("Exercise", back_populates="prs")


# ---------------------------------------------------------------------------
# 4.14 settings
# ---------------------------------------------------------------------------

class Settings(Base):
    __tablename__ = "settings"
    __table_args__ = (
        UniqueConstraint("athlete_id", "key", name="uq_athlete_setting"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    athlete_id = Column(Integer, ForeignKey("athlete.id"), nullable=False)
    key = Column(String(50), nullable=False)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))

    athlete = relationship("Athlete", back_populates="settings")


# ---------------------------------------------------------------------------
# Engine / session helpers
# ---------------------------------------------------------------------------

_engine: Optional[object] = None
_session_factory: Optional[object] = None


def get_engine(db_url: str = "sqlite:///strongman_coach.db"):
    """Return (or create) a SQLAlchemy engine.

    For in-memory SQLite (:memory:), uses StaticPool so all connections
    share the same database.
    """
    global _engine
    if _engine is None:
        if "sqlite" in db_url and ":memory:" in db_url:
            from sqlalchemy.pool import StaticPool
            _engine = create_engine(
                db_url,
                echo=False,
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
            )
        else:
            _engine = create_engine(db_url, echo=False)
    return _engine


def get_session_factory(db_url: str = "sqlite:///strongman_coach.db"):
    """Return (or create) a session factory bound to the engine."""
    global _session_factory
    if _session_factory is None:
        engine = get_engine(db_url)
        _session_factory = sessionmaker(bind=engine)
    return _session_factory


def init_db(db_url: str = "sqlite:///strongman_coach.db") -> None:
    """Create all tables (idempotent)."""
    engine = get_engine(db_url)
    Base.metadata.create_all(engine)


def reset_db(db_url: str = "sqlite:///strongman_coach.db") -> None:
    """Drop and recreate all tables. Use only in tests."""
    engine = get_engine(db_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


# ---------------------------------------------------------------------------
# Migration: TrainingEntry → new schema
# ---------------------------------------------------------------------------

def _table_exists(session: Session, name: str) -> bool:
    """Check if a table exists in the database."""
    inspector = inspect(session.bind)
    return name in inspector.get_table_names()


def _column_exists(session: Session, table: str, column: str) -> bool:
    """Check if a column exists in a table."""
    inspector = inspect(session.bind)
    if table not in inspector.get_table_names():
        return False
    cols = [c["name"] for c in inspector.get_columns(table)]
    return column in cols


def migrate_from_training_entry(db_url: str = "sqlite:///strongman_coach.db") -> dict:
    """
    Migrate legacy TrainingEntry rows into the new schema.

    Steps:
    1. Seed reference tables (athlete, exercise, equipment, settings).
    2. Create program skeleton with one block, one cycle, one session per date.
    3. Map each TrainingEntry to prescriptions and set_logs.
    4. Backfill PRs.
    5. Rename TrainingEntry → TrainingEntry_archive.

    Idempotent: checks migration_version in settings before running.
    Returns a dict with migration stats.
    """
    engine = get_engine(db_url)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    stats = {
        "migrated": False,
        "training_entry_count": 0,
        "set_log_count": 0,
        "exercise_count": 0,
        "session_count": 0,
        "pr_count": 0,
    }

    try:
        # --- Idempotency check ---
        if _table_exists(session, "settings"):
            existing = (
                session.query(Settings)
                .filter_by(key="migration_version")
                .first()
            )
            if existing and existing.value == "1":
                stats["migrated"] = True
                # Return current counts
                stats["set_log_count"] = session.query(SetLog).count()
                stats["training_entry_count"] = 0
                return stats

        # --- Check if TrainingEntry exists ---
        if not _table_exists(session, "TrainingEntry"):
            # Nothing to migrate – seed athlete if needed and mark as done
            athlete = session.query(Athlete).first()
            if not athlete:
                athlete = Athlete(
                    name="Athlete",
                    units="lb",
                    plate_increment_lb=2.5,
                    dumbbell_max_lb=120,
                )
                session.add(athlete)
                session.flush()
            if _table_exists(session, "settings"):
                _seed_settings(session, athlete.id)
                _set_migration_flag(session)
            stats["migrated"] = True
            return stats

        # --- Count original rows ---
        original_count = session.execute(text("SELECT COUNT(*) FROM TrainingEntry")).scalar()
        stats["training_entry_count"] = original_count

        if original_count == 0:
            if _table_exists(session, "settings"):
                _set_migration_flag(session)
            stats["migrated"] = True
            return stats

        # --- Step 1: Create all new tables if not present ---
        Base.metadata.create_all(engine)

        # --- Step 1a: Seed athlete if not present ---
        athlete = session.query(Athlete).first()
        if not athlete:
            athlete = Athlete(
                name="Athlete",
                units="lb",
                plate_increment_lb=2.5,
                dumbbell_max_lb=120,
            )
            session.add(athlete)
            session.flush()

        # --- Step 1b: Seed default equipment if empty ---
        if session.query(Equipment).filter_by(athlete_id=athlete.id).count() == 0:
            _seed_equipment(session, athlete.id)

        # --- Step 1c: Seed settings ---
        _seed_settings(session, athlete.id)

        # --- Step 2: Seed exercises from distinct exercise_name ---
        distinct_exercises = session.execute(
            text("SELECT DISTINCT exercise_name FROM TrainingEntry WHERE exercise_name IS NOT NULL")
        ).fetchall()
        exercise_map: dict[str, int] = {}
        for (ex_name,) in distinct_exercises:
            ex = session.query(Exercise).filter_by(name=ex_name).first()
            if not ex:
                ex = Exercise(name=ex_name, role="accessory", metric_type="load_reps")
                session.add(ex)
                session.flush()
            exercise_map[ex_name] = ex.id
        stats["exercise_count"] = len(exercise_map)

        # --- Step 3: Build program skeleton ---
        program = session.query(Program).filter_by(name="Imported History").first()
        if not program:
            program = Program(
                athlete_id=athlete.id,
                name="Imported History",
                phase="accumulation",
                start_date=datetime.date.today(),
                is_active=False,
            )
            session.add(program)
            session.flush()

        block = session.query(Block).filter_by(program_id=program.id).first()
        if not block:
            block = Block(
                program_id=program.id,
                block_number=1,
                start_date=datetime.date.today(),
            )
            session.add(block)
            session.flush()

        cycle = session.query(Cycle).filter_by(block_id=block.id).first()
        if not cycle:
            cycle = Cycle(
                block_id=block.id,
                cycle_number=1,
                start_date=datetime.date.today(),
            )
            session.add(cycle)
            session.flush()

        # --- Step 4: Read all TrainingEntry rows ---
        rows = session.execute(text(
            "SELECT id, date, exercise_name, weight, reps, sets, notes FROM TrainingEntry"
        )).fetchall()

        # Build session cache keyed by date
        session_cache: dict[str, int] = {}

        total_set_logs = 0

        for row in rows:
            entry_id, entry_date, exercise_name, weight, reps, sets, notes = row

            if exercise_name is None or exercise_name.strip() == "":
                continue

            ex_id = exercise_map.get(exercise_name)
            if ex_id is None:
                continue

            # Parse date: could be string or date object
            if isinstance(entry_date, str):
                parsed_date = datetime.date.fromisoformat(entry_date)
            elif entry_date is not None:
                parsed_date = entry_date
            else:
                parsed_date = datetime.date.today()

            # Ensure a session exists for this date
            date_str = parsed_date.isoformat()
            if date_str not in session_cache:
                sess = Session(
                    cycle_id=cycle.id,
                    day_label="A",
                    scheduled_date=parsed_date,
                    actual_date=parsed_date,
                    status="completed",
                )
                session.add(sess)
                session.flush()
                session_cache[date_str] = sess.id

            sess_id = session_cache[date_str]
            num_sets = int(sets) if sets else 1

            for set_num in range(1, num_sets + 1):
                # Create prescription
                pres = Prescription(
                    session_id=sess_id,
                    exercise_id=ex_id,
                    set_number=set_num,
                    prescribed_reps=int(reps) if reps else 1,
                    prescribed_load_lb=float(weight) if weight else 0.0,
                )
                session.add(pres)
                session.flush()

                # Compute e1RM via Epley fallback
                e1rm = None
                if weight and reps:
                    e1rm = float(weight) * (1 + int(reps) / 30.0)

                # Create set_log
                slog = SetLog(
                    exercise_id=ex_id,
                    session_id=sess.id,
                    prescription_id=pres.id,
                    actual_load_lb=float(weight) if weight else 0.0,
                    actual_reps=int(reps) if reps else 1,
                    rpe=None,
                    e1rm_lb=e1rm,
                    confidence="low",
                    pain_flag=False,
                    note=notes,
                )
                session.add(slog)
                total_set_logs += 1

        stats["set_log_count"] = total_set_logs
        stats["session_count"] = len(session_cache)

        # --- Step 5: Backfill PRs ---
        pr_count = 0
        for ex_name, ex_id in exercise_map.items():
            best = session.execute(text(
                f"SELECT MAX(e1rm_lb) FROM set_log sl "
                f"JOIN prescription p ON sl.prescription_id = p.id "
                f"WHERE p.exercise_id = {ex_id} AND sl.e1rm_lb IS NOT NULL"
            )).scalar()
            if best:
                pr = PR(
                    athlete_id=athlete.id,
                    exercise_id=ex_id,
                    category="e1rm",
                    value_lb=best,
                    reps=1,
                    date=datetime.date.today(),
                )
                session.add(pr)
                pr_count += 1
        stats["pr_count"] = pr_count

        # --- Step 6: Rename TrainingEntry → TrainingEntry_archive ---
        if _table_exists(session, "TrainingEntry"):
            session.execute(text("ALTER TABLE TrainingEntry RENAME TO TrainingEntry_archive"))

        # --- Step 7: Mark migration complete ---
        _set_migration_flag(session)

        session.commit()
        stats["migrated"] = True

    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    return stats


def _set_migration_flag(session: Session) -> None:
    """Set migration_version = 1 in settings."""
    athlete = session.query(Athlete).first()
    if not athlete:
        return
    existing = session.query(Settings).filter_by(
        athlete_id=athlete.id, key="migration_version"
    ).first()
    if existing:
        existing.value = "1"
    else:
        session.add(Settings(
            athlete_id=athlete.id,
            key="migration_version",
            value="1",
        ))


def _seed_equipment(session: Session, athlete_id: int) -> None:
    """Seed default Crunch Fitness + club + personal equipment."""
    gym_equipment = [
        ("barbell", "gym"), ("barbell_45lb", "gym"), ("barbell_35lb", "gym"),
        ("plates_2.5lb", "gym"), ("plates_5lb", "gym"), ("plates_10lb", "gym"),
        ("plates_25lb", "gym"), ("plates_35lb", "gym"), ("bench", "gym"),
        ("squat_rack", "gym"), ("pull_up_bar", "gym"), ("cable_machine", "gym"),
        ("dumbbells", "gym"), ("leg_press", "gym"), ("lat_machine", "gym"),
        ("chest_press_machine", "gym"), ("rowing_machine", "gym"),
        ("treadmill", "gym"), ("stationary_bike", "gym"),
    ]
    club_equipment = [
        ("turf_sled", "club"), ("sled", "club"), ("tires", "club"),
        ("landmines", "club"), ("kettlebells", "club"), ("medicine_balls", "club"),
    ]
    personal_equipment = [
        ("sandbag", "personal"), ("fat_grips", "personal"), ("straps", "personal"),
        ("belt", "personal"), ("chalk", "personal"),
    ]

    for name, category in gym_equipment + club_equipment + personal_equipment:
        eq = Equipment(athlete_id=athlete_id, name=name, available=True, category=category)
        session.add(eq)


def _seed_settings(session: Session, athlete_id: int) -> None:
    """Seed default settings."""
    defaults = {
        "units": "lb",
        "weight_class": "105",
        "safety_notice_seen": "false",
        "benchmarks": "{}",
    }
    for key, value in defaults.items():
        existing = session.query(Settings).filter_by(
            athlete_id=athlete_id, key=key
        ).first()
        if not existing:
            session.add(Settings(athlete_id=athlete_id, key=key, value=value))
