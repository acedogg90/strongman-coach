"""Program template engine for Strongman Coach.

Generates block/cycle/session structures with day templates (A/B/C/D),
variation rotation across blocks, deload logic, and stall detection.

Block structure: 3 loading cycles + 1 deload cycle = 1 block.
Macrocycle: Accumulation → Intensification → Realization (3 blocks).

Day templates:
  A – Deadlift day (hinge focus)
  B – Overhead day (press focus)
  C – Squat day (squat focus)
  D – Events day (strongman events)

Variation rotation per block:
  Deadlift:  conventional → block pull → deficit
  Overhead: push press → strict press → fat-grip clean & press
  Squat:    back squat → pause squat → front squat
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

BLOCK_PHASES = ["accumulation", "intensification", "realization"]

# Variation names per block index (0-based)
DEADLIFT_VARIATIONS = ["conventional", "block pull", "deficit"]
OVERHEAD_VARIATIONS = ["push press", "strict press", "fat-grip clean & press"]
SQUAT_VARIATIONS = ["back squat", "pause squat", "front squat"]

# Main-lift prescription table: keyed by (block_type, cycle_num)
# cycle_num 1-3 = loading, cycle_num 4 = deload
# Each entry: (reps, rpe, fatigue_drop_pct)
MAIN_LIFT_TABLE: dict[tuple[str, int], tuple[int, float, float]] = {
    # Accumulation block (cycles 1-3 loading, 4 deload)
    ("accumulation", 1): (5, 7.5, 10),
    ("accumulation", 2): (5, 8.0, 10),
    ("accumulation", 3): (4, 8.5, 15),
    ("accumulation", 4): (3, 6.5, 0),  # deload

    # Intensification block
    ("intensification", 1): (4, 8.0, 10),
    ("intensification", 2): (3, 8.5, 15),
    ("intensification", 3): (3, 9.0, 15),
    ("intensification", 4): (3, 6.5, 0),  # deload

    # Realization block
    ("realization", 1): (3, 8.5, 15),
    ("realization", 2): (2, 9.0, 20),
    ("realization", 3): (2, 9.5, 20),
    ("realization", 4): (1, 9.0, 0),  # deload with test day
}

# Secondary lift prescriptions (APRE-style): (reps_target, rpe)
SECONDARY_TABLE: dict[tuple[str, int], tuple[int, float]] = {
    ("accumulation", 1): (8, 8.0),
    ("accumulation", 2): (8, 8.5),
    ("accumulation", 3): (6, 9.0),
    ("accumulation", 4): (6, 6.5),

    ("intensification", 1): (6, 8.5),
    ("intensification", 2): (6, 9.0),
    ("intensification", 3): (5, 9.5),
    ("intensification", 4): (5, 6.5),

    ("realization", 1): (5, 9.0),
    ("realization", 2): (4, 9.5),
    ("realization", 3): (3, 9.5),
    ("realization", 4): (3, 7.0),
}

# Event prescriptions: (load_pct_of_1rm, reps) for loading cycles
# Deload events at 60%
EVENT_TABLE: dict[tuple[str, int], tuple[float, int]] = {
    ("accumulation", 1): (70, 3),
    ("accumulation", 2): (75, 3),
    ("accumulation", 3): (80, 2),
    ("accumulation", 4): (60, 2),

    ("intensification", 1): (75, 3),
    ("intensification", 2): (80, 2),
    ("intensification", 3): (85, 2),
    ("intensification", 4): (60, 2),

    ("realization", 1): (80, 2),
    ("realization", 2): (85, 2),
    ("realization", 3): (90, 1),
    ("realization", 4): (60, 1),
}

# Day template labels in order
DAY_LABELS = ["A", "B", "C", "D"]

# ---------------------------------------------------------------------------
# Athlete profile (lightweight, no DB dependency for pure logic)
# ---------------------------------------------------------------------------


@dataclass
class Athlete:
    """Minimal athlete profile for program generation."""
    id: int = 1
    name: str = "Athlete"
    bodyweight_lb: float = 200.0
    plate_increment_lb: float = 2.5
    # Estimated 1RMs for main lifts (lb)
    deadlift_1rm: float = 405.0
    overhead_1rm: float = 185.0
    squat_1rm: float = 365.0
    # Event 1RMs
    event_1rm: float = 200.0
    # Stall tracking
    stalled_lifts: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Prescription data structures
# ---------------------------------------------------------------------------


@dataclass
class Prescription:
    """A single set prescription within a session."""
    exercise_name: str
    set_number: int
    prescribed_reps: int | None = None
    prescribed_rpe: float | None = None
    prescribed_load_lb: float | None = None
    is_warmup: bool = False
    is_backoff: bool = False
    fatigue_drop_pct: float = 0.0
    adjustment_note: str = ""


@dataclass
class Session:
    """A training session (one day label)."""
    day_label: str
    scheduled_date: date
    prescriptions: list[Prescription] = field(default_factory=list)
    is_test_day: bool = False


@dataclass
class Cycle:
    """A training cycle (one week of 4 sessions)."""
    cycle_number: int
    start_date: date
    sessions: list[Session] = field(default_factory=list)
    is_deload: bool = False


@dataclass
class Block:
    """A training block (3 loading + 1 deload cycles)."""
    block_number: int
    phase: str
    variation_name: str
    cycles: list[Cycle] = field(default_factory=list)
    is_deload: bool = False


@dataclass
class Macrocycle:
    """Full macrocycle: 3 blocks (Accumulation → Intensification → Realization)."""
    blocks: list[Block] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Variation helpers
# ---------------------------------------------------------------------------


def get_variation(variations: list[str], block_index: int) -> str:
    """Return the variation name for a given block index."""
    return variations[block_index % len(variations)]


def get_deadlift_variation(block_index: int) -> str:
    """Deadlift variation for block index."""
    return get_variation(DEADLIFT_VARIATIONS, block_index)


def get_overhead_variation(block_index: int) -> str:
    """Overhead variation for block index."""
    return get_variation(OVERHEAD_VARIATIONS, block_index)


def get_squat_variation(block_index: int) -> str:
    """Squat variation for block index."""
    return get_variation(SQUAT_VARIATIONS, block_index)


# ---------------------------------------------------------------------------
# Core: generate_cycle
# ---------------------------------------------------------------------------


def _compute_load(e1rm: float, reps: int, rpe: float, plate_increment: float = 2.5) -> float:
    """Compute prescribed load from e1RM, reps, RPE using the RPE chart.

    Falls back to Epley if RPE lookup fails.
    """
    from app.strength.rpe import target_load
    try:
        return target_load(e1rm, reps, rpe, plate_increment)
    except ValueError:
        # Fallback: simple percentage
        pct = 0.75
        raw = e1rm * pct
        import math
        return math.floor(raw / plate_increment) * plate_increment


def _build_warmup_sets(e1rm: float, working_reps: int, working_rpe: float,
                       plate_increment: float = 2.5) -> list[Prescription]:
    """Generate warm-up sets leading to the working set."""
    warmup_loads = [0.40, 0.55, 0.70]
    warmup_reps = [8, 5, 3]
    sets = []
    for i, (pct, reps) in enumerate(zip(warmup_loads, warmup_reps)):
        load = round(e1rm * pct / plate_increment) * plate_increment
        sets.append(Prescription(
            exercise_name="warmup",
            set_number=i + 1,
            prescribed_reps=reps,
            prescribed_load_lb=load,
            is_warmup=True,
            prescribed_rpe=None,
        ))
    return sets


def _build_backoff_sets(e1rm: float, reps: int, rpe: float,
                        fatigue_drop: float, plate_increment: float = 2.5,
                        exercise_name: str = "main") -> list[Prescription]:
    """Generate back-off sets with fatigue drop."""
    if fatigue_drop <= 0:
        return []
    backoff_rpe = max(6.0, rpe - 1.0)
    load = _compute_load(e1rm, reps, backoff_rpe, plate_increment)
    # Apply fatigue drop
    load = load * (1.0 - fatigue_drop / 100.0)
    load = round(load / plate_increment) * plate_increment
    return [Prescription(
        exercise_name=exercise_name,
        set_number=2,
        prescribed_reps=reps,
        prescribed_rpe=backoff_rpe,
        prescribed_load_lb=load,
        is_backoff=True,
        fatigue_drop_pct=fatigue_drop,
    )]


def generate_cycle(
    cycle_num: int,
    block_type: str,
    athlete: Athlete,
    block_index: int = 0,
    start_date: date | None = None,
) -> Cycle:
    """Generate a single training cycle (4 sessions: A, B, C, D).

    Parameters
    ----------
    cycle_num : int
        Cycle number within the block (1-4; 4 = deload).
    block_type : str
        Block phase: 'accumulation', 'intensification', or 'realization'.
    athlete : Athlete
        Athlete profile with 1RM estimates.
    block_index : int
        Block index (0-based) for variation rotation.
    start_date : date, optional
        Start date for the cycle. Defaults to today.

    Returns
    -------
    Cycle
        A Cycle object with 4 Session objects, each containing prescriptions.
    """
    if start_date is None:
        start_date = date.today()

    is_deload = (cycle_num == 4)
    cycle = Cycle(
        cycle_number=cycle_num,
        start_date=start_date,
        is_deload=is_deload,
    )

    # Look up main lift prescription
    main_key = (block_type, cycle_num)
    main_reps, main_rpe, main_fatigue = MAIN_LIFT_TABLE.get(
        main_key, (3, 7.0, 10)
    )

    # Look up secondary lift prescription
    sec_key = (block_type, cycle_num)
    sec_reps, sec_rpe = SECONDARY_TABLE.get(sec_key, (6, 7.0))

    # Look up event prescription
    evt_key = (block_type, cycle_num)
    evt_pct, evt_reps = EVENT_TABLE.get(evt_key, (70, 3))

    # Get variations for this block
    dl_var = get_deadlift_variation(block_index)
    oh_var = get_overhead_variation(block_index)
    sq_var = get_squat_variation(block_index)

    # Realization deload (cycle 4) includes a test day on Day A
    is_realization_test = (block_type == "realization" and cycle_num == 4)

    # -----------------------------------------------------------------------
    # Day A: Deadlift day
    # -----------------------------------------------------------------------
    day_a = Session(day_label="A", scheduled_date=start_date)

    if is_realization_test:
        # Test day: single @ RPE 9-9.5
        test_load = _compute_load(athlete.deadlift_1rm, 1, 9.0, athlete.plate_increment_lb)
        day_a.prescriptions.append(Prescription(
            exercise_name=f"{dl_var} deadlift",
            set_number=1,
            prescribed_reps=1,
            prescribed_rpe=9.0,
            prescribed_load_lb=test_load,
            adjustment_note="Test day – single @ RPE 9-9.5",
        ))
        day_a.is_test_day = True
    else:
        # Warm-up sets
        day_a.prescriptions.extend(
            _build_warmup_sets(athlete.deadlift_1rm, main_reps, main_rpe,
                              athlete.plate_increment_lb)
        )
        # Top set
        top_load = _compute_load(athlete.deadlift_1rm, main_reps, main_rpe,
                                 athlete.plate_increment_lb)
        day_a.prescriptions.append(Prescription(
            exercise_name=f"{dl_var} deadlift",
            set_number=4,  # after warmups
            prescribed_reps=main_reps,
            prescribed_rpe=main_rpe,
            prescribed_load_lb=top_load,
            fatigue_drop_pct=main_fatigue,
        ))
        # Back-off sets (skip on deload)
        if not is_deload:
            day_a.prescriptions.extend(
                _build_backoff_sets(
                    athlete.deadlift_1rm, main_reps, main_rpe,
                    main_fatigue, athlete.plate_increment_lb,
                    f"{dl_var} deadlift"
                )
            )

    # -----------------------------------------------------------------------
    # Day B: Overhead day
    # -----------------------------------------------------------------------
    day_b = Session(
        day_label="B",
        scheduled_date=start_date + timedelta(days=1),
    )

    if is_realization_test:
        test_load = _compute_load(athlete.overhead_1rm, 1, 9.0, athlete.plate_increment_lb)
        day_b.prescriptions.append(Prescription(
            exercise_name=f"{oh_var} overhead press",
            set_number=1,
            prescribed_reps=1,
            prescribed_rpe=9.0,
            prescribed_load_lb=test_load,
            adjustment_note="Test day – single @ RPE 9-9.5",
        ))
        day_b.is_test_day = True
    else:
        day_b.prescriptions.extend(
            _build_warmup_sets(athlete.overhead_1rm, main_reps, main_rpe,
                              athlete.plate_increment_lb)
        )
        top_load = _compute_load(athlete.overhead_1rm, main_reps, main_rpe,
                                 athlete.plate_increment_lb)
        day_b.prescriptions.append(Prescription(
            exercise_name=f"{oh_var} overhead press",
            set_number=4,
            prescribed_reps=main_reps,
            prescribed_rpe=main_rpe,
            prescribed_load_lb=top_load,
            fatigue_drop_pct=main_fatigue,
        ))
        if not is_deload:
            day_b.prescriptions.extend(
                _build_backoff_sets(
                    athlete.overhead_1rm, main_reps, main_rpe,
                    main_fatigue, athlete.plate_increment_lb,
                    f"{oh_var} overhead press"
                )
            )

    # -----------------------------------------------------------------------
    # Day C: Squat day
    # -----------------------------------------------------------------------
    day_c = Session(
        day_label="C",
        scheduled_date=start_date + timedelta(days=2),
    )

    if is_realization_test:
        test_load = _compute_load(athlete.squat_1rm, 1, 9.0, athlete.plate_increment_lb)
        day_c.prescriptions.append(Prescription(
            exercise_name=f"{sq_var} squat",
            set_number=1,
            prescribed_reps=1,
            prescribed_rpe=9.0,
            prescribed_load_lb=test_load,
            adjustment_note="Test day – single @ RPE 9-9.5",
        ))
        day_c.is_test_day = True
    else:
        day_c.prescriptions.extend(
            _build_warmup_sets(athlete.squat_1rm, main_reps, main_rpe,
                              athlete.plate_increment_lb)
        )
        top_load = _compute_load(athlete.squat_1rm, main_reps, main_rpe,
                                 athlete.plate_increment_lb)
        day_c.prescriptions.append(Prescription(
            exercise_name=f"{sq_var} squat",
            set_number=4,
            prescribed_reps=main_reps,
            prescribed_rpe=main_rpe,
            prescribed_load_lb=top_load,
            fatigue_drop_pct=main_fatigue,
        ))
        if not is_deload:
            day_c.prescriptions.extend(
                _build_backoff_sets(
                    athlete.squat_1rm, main_reps, main_rpe,
                    main_fatigue, athlete.plate_increment_lb,
                    f"{sq_var} squat"
                )
            )

    # -----------------------------------------------------------------------
    # Day D: Events day
    # -----------------------------------------------------------------------
    day_d = Session(
        day_label="D",
        scheduled_date=start_date + timedelta(days=3),
    )

    if is_deload:
        # Deload events at 60%
        event_load = round(athlete.event_1rm * 0.60 / athlete.plate_increment_lb) * athlete.plate_increment_lb
        day_d.prescriptions.append(Prescription(
            exercise_name="strongman event",
            set_number=1,
            prescribed_reps=evt_reps,
            prescribed_rpe=6.5,
            prescribed_load_lb=event_load,
            adjustment_note="Deload – events at 60%",
        ))
    else:
        event_load = round(athlete.event_1rm * (evt_pct / 100.0) / athlete.plate_increment_lb) * athlete.plate_increment_lb
        day_d.prescriptions.append(Prescription(
            exercise_name="strongman event",
            set_number=1,
            prescribed_reps=evt_reps,
            prescribed_rpe=main_rpe,
            prescribed_load_lb=event_load,
        ))

    cycle.sessions = [day_a, day_b, day_c, day_d]
    return cycle


# ---------------------------------------------------------------------------
# Block generation
# ---------------------------------------------------------------------------


def generate_block(
    block_number: int,
    phase: str,
    athlete: Athlete,
    start_date: date | None = None,
) -> Block:
    """Generate a full block (3 loading + 1 deload cycles).

    Parameters
    ----------
    block_number : int
        Block number (1-based).
    phase : str
        Block phase: 'accumulation', 'intensification', or 'realization'.
    athlete : Athlete
        Athlete profile.
    start_date : date, optional
        Start date for the block.

    Returns
    -------
    Block
        A Block with 4 cycles.
    """
    if start_date is None:
        start_date = date.today()

    block_index = block_number - 1
    variation = get_deadlift_variation(block_index)

    block = Block(
        block_number=block_number,
        phase=phase,
        variation_name=variation,
    )

    for cycle_num in range(1, 5):
        cycle_start = start_date + timedelta(weeks=cycle_num - 1)
        cycle = generate_cycle(
            cycle_num=cycle_num,
            block_type=phase,
            athlete=athlete,
            block_index=block_index,
            start_date=cycle_start,
        )
        block.cycles.append(cycle)

    return block


# ---------------------------------------------------------------------------
# Macrocycle generation
# ---------------------------------------------------------------------------


def generate_macrocycle(
    athlete: Athlete,
    start_date: date | None = None,
) -> Macrocycle:
    """Generate a full macrocycle: Accumulation → Intensification → Realization.

    Each block has 4 cycles (3 loading + 1 deload).
    Total: 12 cycles, 48 sessions.

    Parameters
    ----------
    athlete : Athlete
        Athlete profile.
    start_date : date, optional
        Start date for the macrocycle.

    Returns
    -------
    Macrocycle
        A Macrocycle with 3 blocks.
    """
    if start_date is None:
        start_date = date.today()

    macro = Macrocycle()

    for i, phase in enumerate(BLOCK_PHASES):
        block_start = start_date + timedelta(weeks=i * 4)
        block = generate_block(
            block_number=i + 1,
            phase=phase,
            athlete=athlete,
            start_date=block_start,
        )
        macro.blocks.append(block)

    return macro


# ---------------------------------------------------------------------------
# Stall detection
# ---------------------------------------------------------------------------


def detect_stalls(
    athlete: Athlete,
    trend_e1rms: dict[str, list[float]],
    cycles_back: int = 3,
) -> list[str]:
    """Detect stalled lifts by comparing current trend to cycles_back ago.

    A lift is stalled if the current trend e1RM is not higher than
    the trend from cycles_back cycles ago.

    Parameters
    ----------
    athlete : Athlete
        Athlete profile.
    trend_e1rms : dict[str, list[float]]
        Mapping of exercise name to list of trend e1RM values per cycle.
    cycles_back : int
        How many cycles back to compare against.

    Returns
    -------
    list[str]
        Names of stalled exercises.
    """
    stalled = []
    for exercise, trends in trend_e1rms.items():
        if len(trends) < cycles_back + 1:
            continue
        current = trends[-1]
        past = trends[-(cycles_back + 1)]
        if current <= past:
            stalled.append(exercise)
    return stalled


def trigger_early_deload(
    athlete: Athlete,
    stalled_lifts: list[str],
) -> dict[str, Any]:
    """Trigger an early deload and swap variations for stalled lifts.

    Returns a dict with:
      - 'early_deload': True
      - 'swapped_variations': dict mapping exercise → new variation
      - 'message': human-readable explanation
    """
    swaps = {}
    for lift in stalled_lifts:
        if "deadlift" in lift.lower():
            # Rotate to next deadlift variation
            current_idx = athlete.stalled_lifts.count("deadlift")
            new_var = DEADLIFT_VARIATIONS[
                (current_idx + 1) % len(DEADLIFT_VARIATIONS)
            ]
            swaps["deadlift"] = new_var
        elif "overhead" in lift.lower() or "press" in lift.lower():
            current_idx = athlete.stalled_lifts.count("overhead")
            new_var = OVERHEAD_VARIATIONS[
                (current_idx + 1) % len(OVERHEAD_VARIATIONS)
            ]
            swaps["overhead"] = new_var
        elif "squat" in lift.lower():
            current_idx = athlete.stalled_lifts.count("squat")
            new_var = SQUAT_VARIATIONS[
                (current_idx + 1) % len(SQUAT_VARIATIONS)
            ]
            swaps["squat"] = new_var

    return {
        "early_deload": True,
        "swapped_variations": swaps,
        "message": (
            f"Stall detected on: {', '.join(stalled_lifts)}. "
            "Triggering early deload and variation swap."
        ),
    }


# ---------------------------------------------------------------------------
# Convenience: get all sessions from a macrocycle
# ---------------------------------------------------------------------------


def get_all_sessions(macrocycle: Macrocycle) -> list[Session]:
    """Flatten a macrocycle into a list of all sessions."""
    sessions = []
    for block in macrocycle.blocks:
        for cycle in block.cycles:
            sessions.extend(cycle.sessions)
    return sessions


def get_all_cycles(macrocycle: Macrocycle) -> list[Cycle]:
    """Flatten a macrocycle into a list of all cycles."""
    cycles = []
    for block in macrocycle.blocks:
        cycles.extend(block.cycles)
    return cycles
