"""APRE (Adaptive Periodization Reps in Reserve) protocol for secondary lifts.

Pure functions – no DB, no framework dependencies.

APRE uses 4 sets:
  Set 1: 50% of estimated RM for 10 reps (accumulation) or 3RM (intensification/realization)
  Set 2: 75% of estimated RM for 6 reps
  Set 3: 100% of estimated RM for AMRAP
  Set 4: Adjusted load based on Set 3 reps, AMRAP again

Set 4 reps determine the next session's estimated RM reps target.

Adjustment tables (load change for Set 4 based on Set 3 reps):
  6RM: 0-2 reps → -10 to -5 lb, 3-4 reps → 0 to -5 lb, 5-7 reps → same,
       8-12 reps → +5 to +10 lb, 13+ → +10 to +15 lb
  3RM: 1-2 reps → -10 to -5 lb, 3-4 reps → same, 5-6 reps → +5 to +10 lb,
       7+ → +10 to +15 lb
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ApreSet:
    """Represents one set in an APRE protocol."""
    set_number: int
    target_reps: int | None  # None means AMRAP
    actual_reps: int | None  # Filled in after the set is performed
    weight: float  # Planned weight in lb
    is_amrap: bool = False


@dataclass
class ApreResult:
    """Complete APRE protocol result for one exercise."""
    sets: list[ApreSet] = field(default_factory=list)
    estimated_rm: float = 0.0  # The estimated RM used for calculations
    rm_type: Literal["6RM", "3RM"] = "6RM"  # Which RM type (based on phase)
    next_session_load: float = 0.0  # Estimated RM for next session
    next_session_rm_reps: int = 0  # RM reps target for next session (from Set 4)


# ---------------------------------------------------------------------------
# Adjustment tables
# ---------------------------------------------------------------------------
# Each entry: (min_reps, max_reps, load_adjustment_lb)
# max_reps of None means "and above"

APRE_6RM_ADJUSTMENT = [
    (0, 2, -7.5),   # 0-2 reps: -5 to -10 lb → midpoint -7.5
    (3, 4, -2.5),   # 3-4 reps: 0 to -5 lb → midpoint -2.5
    (5, 7, 0.0),    # 5-7 reps: same load
    (8, 12, 7.5),   # 8-12 reps: +5 to +10 lb → midpoint +7.5
    (13, None, 12.5),  # 13+: +10 to +15 lb → midpoint +12.5
]

APRE_3RM_ADJUSTMENT = [
    (1, 2, -7.5),   # 1-2 reps: -5 to -10 lb → midpoint -7.5
    (3, 4, 0.0),    # 3-4 reps: same load
    (5, 6, 7.5),    # 5-6 reps: +5 to +10 lb → midpoint +7.5
    (7, None, 12.5),  # 7+: +10 to +15 lb → midpoint +12.5
]


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def _get_adjustment(reps: int, rm_type: Literal["6RM", "3RM"]) -> float:
    """Return the load adjustment in lb for Set 4 based on Set 3 reps.

    Parameters
    ----------
    reps : int
        Number of reps completed on Set 3.
    rm_type : str
        Either "6RM" or "3RM".

    Returns
    -------
    float
        Load adjustment in lb (can be negative).
    """
    table = APRE_6RM_ADJUSTMENT if rm_type == "6RM" else APRE_3RM_ADJUSTMENT
    for min_r, max_r, adj in table:
        if max_r is None:
            if reps >= min_r:
                return adj
        else:
            if min_r <= reps <= max_r:
                return adj
    # Fallback: if reps is 0 for 3RM (not in table), treat as worst case
    if rm_type == "3RM" and reps == 0:
        return -7.5
    return 0.0


def _round_to_plate(weight: float, plate_increment: float = 2.5) -> float:
    """Round weight to nearest plate increment."""
    return round(weight / plate_increment) * plate_increment


def calculate_apre_sets(
    estimated_rm: float,
    rm_type: Literal["6RM", "3RM"] = "6RM",
    plate_increment: float = 2.5,
) -> ApreResult:
    """Calculate the 4 APRE sets for a secondary lift.

    Parameters
    ----------
    estimated_rm : float
        The estimated RM weight (6RM or 3RM) in lb.
    rm_type : str
        "6RM" for accumulation phase, "3RM" for intensification/realization.
    plate_increment : float
        Smallest plate step (default 2.5 lb).

    Returns
    -------
    ApreResult
        Contains the 4 planned sets with weights and AMRAP flags.
    """
    if estimated_rm <= 0:
        raise ValueError(f"estimated_rm must be positive, got {estimated_rm}")
    if rm_type not in ("6RM", "3RM"):
        raise ValueError(f"rm_type must be '6RM' or '3RM', got {rm_type!r}")

    sets: list[ApreSet] = []

    # Set 1: 50% of estimated RM for 10 reps
    set1_weight = _round_to_plate(estimated_rm * 0.50, plate_increment)
    sets.append(ApreSet(
        set_number=1,
        target_reps=10,
        actual_reps=None,
        weight=set1_weight,
        is_amrap=False,
    ))

    # Set 2: 75% of estimated RM for 6 reps
    set2_weight = _round_to_plate(estimated_rm * 0.75, plate_increment)
    sets.append(ApreSet(
        set_number=2,
        target_reps=6,
        actual_reps=None,
        weight=set2_weight,
        is_amrap=False,
    ))

    # Set 3: 100% of estimated RM for AMRAP
    set3_weight = _round_to_plate(estimated_rm * 1.00, plate_increment)
    sets.append(ApreSet(
        set_number=3,
        target_reps=None,  # AMRAP
        actual_reps=None,
        weight=set3_weight,
        is_amrap=True,
    ))

    # Set 4: weight TBD (depends on Set 3 reps), AMRAP
    # We set the weight to the estimated RM as a placeholder;
    # it will be adjusted by adjust_next_session() after Set 3 is logged.
    set4_weight = set3_weight  # placeholder, adjusted later
    sets.append(ApreSet(
        set_number=4,
        target_reps=None,  # AMRAP
        actual_reps=None,
        weight=set4_weight,
        is_amrap=True,
    ))

    return ApreResult(
        sets=sets,
        estimated_rm=estimated_rm,
        rm_type=rm_type,
        next_session_load=estimated_rm,  # placeholder
        next_session_rm_reps=0,  # placeholder
    )


def adjust_set4_weight(
    apre_result: ApreResult,
    set3_reps: int,
    plate_increment: float = 2.5,
) -> float:
    """Adjust Set 4 weight based on Set 3 reps.

    Parameters
    ----------
    apre_result : ApreResult
        The APRE result from calculate_apre_sets().
    set3_reps : int
        Actual reps completed on Set 3.
    plate_increment : float
        Smallest plate step (default 2.5 lb).

    Returns
    -------
    float
        Adjusted Set 4 weight in lb.
    """
    if set3_reps < 0:
        raise ValueError(f"set3_reps must be non-negative, got {set3_reps}")

    adjustment = _get_adjustment(set3_reps, apre_result.rm_type)
    base_weight = apre_result.estimated_rm
    adjusted = base_weight + adjustment
    return _round_to_plate(adjusted, plate_increment)


def adjust_next_session(
    apre_result: ApreResult,
    set3_reps: int,
    set4_reps: int,
    plate_increment: float = 2.5,
) -> ApreResult:
    """Calculate next session's load based on Set 3 and Set 4 performance.

    Set 4 reps determine the next session's estimated RM reps target.
    The load adjustment for Set 4 is also applied to the next session's load.

    Parameters
    ----------
    apre_result : ApreResult
        The APRE result from calculate_apre_sets().
    set3_reps : int
        Actual reps completed on Set 3.
    set4_reps : int
        Actual reps completed on Set 4.
    plate_increment : float
        Smallest plate step (default 2.5 lb).

    Returns
    -------
    ApreResult
        Updated result with next_session_load and next_session_rm_reps set.
    """
    if set3_reps < 0:
        raise ValueError(f"set3_reps must be non-negative, got {set3_reps}")
    if set4_reps < 0:
        raise ValueError(f"set4_reps must be non-negative, got {set4_reps}")

    # Update Set 4 weight based on Set 3 reps
    set4_weight = adjust_set4_weight(apre_result, set3_reps, plate_increment)
    if len(apre_result.sets) >= 4:
        apre_result.sets[3].weight = set4_weight

    # Calculate next session's load adjustment
    adjustment = _get_adjustment(set3_reps, apre_result.rm_type)
    next_load = apre_result.estimated_rm + adjustment
    apre_result.next_session_load = _round_to_plate(next_load, plate_increment)

    # Set 4 reps determine next session's RM reps target
    apre_result.next_session_rm_reps = set4_reps

    return apre_result


def get_apre_adjustment_range(
    reps: int,
    rm_type: Literal["6RM", "3RM"] = "6RM",
) -> tuple[float, float]:
    """Return the (min_adjustment, max_adjustment) range for a given rep count.

    This is useful for displaying the adjustment range to the user.

    Parameters
    ----------
    reps : int
        Number of reps completed on Set 3.
    rm_type : str
        Either "6RM" or "3RM".

    Returns
    -------
    tuple[float, float]
        (min_adjustment_lb, max_adjustment_lb) for the given rep range.
    """
    if rm_type == "6RM":
        # 6RM table ranges
        if 0 <= reps <= 2:
            return (-10.0, -5.0)
        elif 3 <= reps <= 4:
            return (0.0, -5.0)
        elif 5 <= reps <= 7:
            return (0.0, 0.0)
        elif 8 <= reps <= 12:
            return (5.0, 10.0)
        elif reps >= 13:
            return (10.0, 15.0)
        else:
            return (0.0, 0.0)
    else:
        # 3RM table ranges
        if 1 <= reps <= 2:
            return (-10.0, -5.0)
        elif 3 <= reps <= 4:
            return (0.0, 0.0)
        elif 5 <= reps <= 6:
            return (5.0, 10.0)
        elif reps >= 7:
            return (10.0, 15.0)
        else:
            return (0.0, 0.0)
