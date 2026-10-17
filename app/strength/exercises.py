"""
Strongman Coach – Exercise library seed data, equipment filtering, and substitutes.

Provides:
- SEED_EXERCISES: list of dicts covering all roles and movement patterns
- SEED_SUBSTITUTES: substitute pairs for all 8 strongman events
- seed_exercises(session): insert exercises and substitutes into the DB
- get_available_exercises(session, equipment_ids): filter by available equipment
- get_substitutes(session, event_name): return substitute exercises for an event
"""

from __future__ import annotations

import json
from typing import Optional

from sqlalchemy.orm import Session

from app.database import Exercise, ExerciseSubstitute


# ---------------------------------------------------------------------------
# Seed data: exercises covering every role and movement pattern
# ---------------------------------------------------------------------------

SEED_EXERCISES: list[dict] = [
    # -- MAIN lifts (hinge, squat, press) --
    {"name": "Conventional Deadlift", "role": "main", "movement_pattern": "hinge",
     "required_equipment": ["barbell", "plates_2.5lb", "plates_5lb", "plates_10lb", "plates_25lb", "plates_35lb"],
     "metric_type": "load_reps"},
    {"name": "Sumo Deadlift", "role": "main", "movement_pattern": "hinge",
     "required_equipment": ["barbell", "plates_2.5lb", "plates_5lb", "plates_10lb", "plates_25lb", "plates_35lb"],
     "metric_type": "load_reps"},
    {"name": "Back Squat", "role": "main", "movement_pattern": "squat",
     "required_equipment": ["barbell", "squat_rack", "plates_2.5lb", "plates_5lb", "plates_10lb", "plates_25lb", "plates_35lb"],
     "metric_type": "load_reps"},
    {"name": "Front Squat", "role": "main", "movement_pattern": "squat",
     "required_equipment": ["barbell", "squat_rack", "plates_2.5lb", "plates_5lb", "plates_10lb", "plates_25lb", "plates_35lb"],
     "metric_type": "load_reps"},
    {"name": "Overhead Press", "role": "main", "movement_pattern": "press",
     "required_equipment": ["barbell", "plates_2.5lb", "plates_5lb", "plates_10lb", "plates_25lb"],
     "metric_type": "load_reps"},
    {"name": "Bench Press", "role": "main", "movement_pattern": "press",
     "required_equipment": ["barbell", "bench", "plates_2.5lb", "plates_5lb", "plates_10lb", "plates_25lb", "plates_35lb"],
     "metric_type": "load_reps"},

    # -- SECONDARY lifts (APRE-style accessories) --
    {"name": "Romanian Deadlift", "role": "secondary", "movement_pattern": "hinge",
     "required_equipment": ["barbell", "plates_2.5lb", "plates_5lb", "plates_10lb", "plates_25lb"],
     "metric_type": "load_reps"},
    {"name": "Barbell Row", "role": "secondary", "movement_pattern": "pull",
     "required_equipment": ["barbell", "plates_2.5lb", "plates_5lb", "plates_10lb", "plates_25lb"],
     "metric_type": "load_reps"},
    {"name": "Dumbbell Bench Press", "role": "secondary", "movement_pattern": "press",
     "required_equipment": ["dumbbells"],
     "metric_type": "load_reps"},
    {"name": "Leg Press", "role": "secondary", "movement_pattern": "squat",
     "required_equipment": ["leg_press"],
     "metric_type": "load_reps"},
    {"name": "Lat Pulldown", "role": "secondary", "movement_pattern": "pull",
     "required_equipment": ["lat_machine"],
     "metric_type": "load_reps"},
    {"name": "Chest Press Machine", "role": "secondary", "movement_pattern": "press",
     "required_equipment": ["chest_press_machine"],
     "metric_type": "load_reps"},

    # -- ACCESSORY lifts --
    {"name": "Pull Ups", "role": "accessory", "movement_pattern": "pull",
     "required_equipment": ["pull_up_bar"],
     "metric_type": "load_reps"},
    {"name": "Dumbbell Curl", "role": "accessory", "movement_pattern": "pull",
     "required_equipment": ["dumbbells"],
     "metric_type": "load_reps"},
    {"name": "Tricep Pushdown", "role": "accessory", "movement_pattern": "press",
     "required_equipment": ["cable_machine"],
     "metric_type": "load_reps"},
    {"name": "Cable Row", "role": "accessory", "movement_pattern": "pull",
     "required_equipment": ["cable_machine"],
     "metric_type": "load_reps"},
    {"name": "Plank", "role": "accessory", "movement_pattern": "core",
     "required_equipment": [],
     "metric_type": "reps_in_time"},
    {"name": "Ab Wheel Rollout", "role": "accessory", "movement_pattern": "core",
     "required_equipment": [],
     "metric_type": "load_reps"},
    {"name": "Farmer's Walk", "role": "accessory", "movement_pattern": "carry",
     "required_equipment": ["dumbbells"],
     "metric_type": "load_distance"},
    {"name": "Kettlebell Swing", "role": "accessory", "movement_pattern": "hinge",
     "required_equipment": ["kettlebells"],
     "metric_type": "load_reps"},
    {"name": "Medicine Ball Slam", "role": "accessory", "movement_pattern": "hinge",
     "required_equipment": ["medicine_balls"],
     "metric_type": "load_reps"},
    {"name": "Sandbag Carry", "role": "accessory", "movement_pattern": "carry",
     "required_equipment": ["sandbag"],
     "metric_type": "load_distance"},

    # -- EVENT exercises (the 8 strongman events) --
    {"name": "Log Press", "role": "event", "movement_pattern": "press",
     "required_equipment": ["barbell", "plates_2.5lb", "plates_5lb", "plates_10lb", "plates_25lb"],
     "metric_type": "load_reps"},
    {"name": "Axle Press", "role": "event", "movement_pattern": "press",
     "required_equipment": ["barbell", "plates_2.5lb", "plates_5lb", "plates_10lb", "plates_25lb", "plates_35lb"],
     "metric_type": "load_reps"},
    {"name": "Strongman Deadlift", "role": "event", "movement_pattern": "hinge",
     "required_equipment": ["barbell", "plates_2.5lb", "plates_5lb", "plates_10lb", "plates_25lb", "plates_35lb"],
     "metric_type": "load_reps"},
    {"name": "Farmers Walk", "role": "event", "movement_pattern": "carry",
     "required_equipment": ["dumbbells"],
     "metric_type": "load_distance"},
    {"name": "Yoke Walk", "role": "event", "movement_pattern": "carry",
     "required_equipment": ["sandbag"],
     "metric_type": "load_distance"},
    {"name": "Atlas Stone", "role": "event", "movement_pattern": "load",
     "required_equipment": ["medicine_balls"],
     "metric_type": "load_time"},
    {"name": "Loading Medley", "role": "event", "movement_pattern": "load",
     "required_equipment": ["sandbag", "kettlebells", "medicine_balls"],
     "metric_type": "load_time"},
    {"name": "Truck Pull", "role": "event", "movement_pattern": "pull",
     "required_equipment": ["sled"],
     "metric_type": "load_distance"},

    # -- EVENT_SUBSTITUTE exercises (used when primary event equipment unavailable) --
    {"name": "Dumbbell Shoulder Press", "role": "event_substitute", "movement_pattern": "press",
     "required_equipment": ["dumbbells"],
     "metric_type": "load_reps"},
    {"name": "Landmine Press", "role": "event_substitute", "movement_pattern": "press",
     "required_equipment": ["landmines", "barbell", "plates_2.5lb", "plates_5lb", "plates_10lb"],
     "metric_type": "load_reps"},
    {"name": "Trap Bar Deadlift", "role": "event_substitute", "movement_pattern": "hinge",
     "required_equipment": ["barbell", "plates_2.5lb", "plates_5lb", "plates_10lb", "plates_25lb", "plates_35lb"],
     "metric_type": "load_reps"},
    {"name": "Kettlebell Farmers Walk", "role": "event_substitute", "movement_pattern": "carry",
     "required_equipment": ["kettlebells"],
     "metric_type": "load_distance"},
    {"name": "Sandbag Shouldering", "role": "event_substitute", "movement_pattern": "load",
     "required_equipment": ["sandbag"],
     "metric_type": "load_reps"},
    {"name": "Sled Push", "role": "event_substitute", "movement_pattern": "carry",
     "required_equipment": ["sled"],
     "metric_type": "load_distance"},
    {"name": "Tire Flip", "role": "event_substitute", "movement_pattern": "hinge",
     "required_equipment": ["tires"],
     "metric_type": "load_reps"},
    {"name": "Cable Row Machine", "role": "event_substitute", "movement_pattern": "pull",
     "required_equipment": ["rowing_machine"],
     "metric_type": "load_reps"},
    {"name": "Turf Sled Drag", "role": "event_substitute", "movement_pattern": "pull",
     "required_equipment": ["turf_sled"],
     "metric_type": "load_distance"},
    {"name": "Medicine Ball Overhead Throw", "role": "event_substitute", "movement_pattern": "press",
     "required_equipment": ["medicine_balls"],
     "metric_type": "load_reps"},
]


# ---------------------------------------------------------------------------
# Seed data: substitute pairs for all 8 events
# ---------------------------------------------------------------------------

# Maps event name -> list of substitute exercise names (ordered by priority)
EVENT_SUBSTITUTES: dict[str, list[str]] = {
    "Log Press": ["Dumbbell Shoulder Press", "Landmine Press", "Medicine Ball Overhead Throw"],
    "Axle Press": ["Dumbbell Shoulder Press", "Landmine Press", "Medicine Ball Overhead Throw"],
    "Strongman Deadlift": ["Trap Bar Deadlift", "Tire Flip"],
    "Farmers Walk": ["Kettlebell Farmers Walk", "Sandbag Carry"],
    "Yoke Walk": ["Sandbag Shouldering", "Sled Push"],
    "Atlas Stone": ["Sandbag Shouldering", "Medicine Ball Overhead Throw"],
    "Loading Medley": ["Sandbag Shouldering", "Kettlebell Farmers Walk", "Tire Flip"],
    "Truck Pull": ["Turf Sled Drag", "Sled Push", "Cable Row Machine"],
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def seed_exercises(session: Session) -> None:
    """Insert all seed exercises and substitute relationships into the DB.

    Idempotent: skips exercises that already exist by name.
    """
    # Insert exercises
    for ex_data in SEED_EXERCISES:
        existing = session.query(Exercise).filter_by(name=ex_data["name"]).first()
        if existing:
            continue
        ex = Exercise(
            name=ex_data["name"],
            role=ex_data["role"],
            movement_pattern=ex_data["movement_pattern"],
            required_equipment=json.dumps(ex_data["required_equipment"]),
            metric_type=ex_data.get("metric_type", "load_reps"),
            is_hidden=False,
        )
        session.add(ex)
    session.flush()

    # Build name -> id map (now includes any pre-existing exercises)
    name_to_id: dict[str, int] = {}
    for ex in session.query(Exercise).all():
        name_to_id[ex.name] = ex.id

    # Insert substitute relationships
    for event_name, sub_names in EVENT_SUBSTITUTES.items():
        primary_id = name_to_id.get(event_name)
        if primary_id is None:
            continue
        for priority, sub_name in enumerate(sub_names, start=1):
            sub_id = name_to_id.get(sub_name)
            if sub_id is None:
                continue
            # Avoid duplicate rows
            existing = session.query(ExerciseSubstitute).filter_by(
                primary_exercise_id=primary_id,
                substitute_exercise_id=sub_id,
            ).first()
            if existing:
                continue
            sub = ExerciseSubstitute(
                primary_exercise_id=primary_id,
                substitute_exercise_id=sub_id,
                priority=priority,
            )
            session.add(sub)


def get_available_exercises(session: Session, equipment_ids: list[int]) -> list[Exercise]:
    """Return exercises whose required equipment is a subset of the given equipment IDs.

    Parameters
    ----------
    session : Session
        Active SQLAlchemy session.
    equipment_ids : list[int]
        IDs of equipment that the athlete has available.

    Returns
    -------
    list[Exercise]
        Exercises that can be performed with the available equipment.
    """
    available_names = set()
    for eq_id in equipment_ids:
        eq = session.query(Exercise.__table__.c.name)  # type: ignore[attr-defined]
        # We need to look up equipment names by id
        from app.database import Equipment
        eq_obj = session.query(Equipment).filter_by(id=eq_id).first()
        if eq_obj:
            available_names.add(eq_obj.name)

    results: list[Exercise] = []
    for ex in session.query(Exercise).filter_by(is_hidden=False).all():
        required = json.loads(ex.required_equipment) if ex.required_equipment else []
        if set(required).issubset(available_names):
            results.append(ex)
    return results


def get_substitutes(session: Session, event_name: str) -> list[Exercise]:
    """Return substitute exercises for a given strongman event.

    Parameters
    ----------
    session : Session
        Active SQLAlchemy session.
    event_name : str
        Name of the event (e.g. "Log Press", "Axle Press").

    Returns
    -------
    list[Exercise]
        Substitute exercises ordered by priority (lowest first).
    """
    primary = session.query(Exercise).filter_by(name=event_name).first()
    if not primary:
        return []

    subs = (
        session.query(ExerciseSubstitute)
        .filter_by(primary_exercise_id=primary.id)
        .order_by(ExerciseSubstitute.priority)
        .all()
    )

    result: list[Exercise] = []
    for sub_rel in subs:
        ex = session.query(Exercise).filter_by(id=sub_rel.substitute_exercise_id).first()
        if ex:
            result.append(ex)
    return result
