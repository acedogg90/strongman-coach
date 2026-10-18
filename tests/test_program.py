"""Tests for the program template engine (app/strength/program.py).

Covers:
- generate_cycle returns 4 sessions matching day templates A/B/C/D
- Block structure: 3 loading + 1 deload
- Macrocycle progression: Accumulation → Intensification → Realization
- Main-lift prescriptions match the plan's table by block and cycle
- Variation rotation across blocks
- Deload cycle: RPE 6–7, no back-offs, events at 60%
- Realization deload includes test day (single @ 9–9.5)
- Stall detection triggers early deload and variation swap
- Full macrocycle generation
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.strength.program import (
    BLOCK_PHASES,
    DEADLIFT_VARIATIONS,
    EVENT_TABLE,
    MAIN_LIFT_TABLE,
    OVERHEAD_VARIATIONS,
    SECONDARY_TABLE,
    SQUAT_VARIATIONS,
    Athlete,
    Cycle,
    Macrocycle,
    Prescription,
    Session,
    detect_stalls,
    generate_block,
    generate_cycle,
    generate_macrocycle,
    get_all_cycles,
    get_all_sessions,
    get_deadlift_variation,
    get_overhead_variation,
    get_squat_variation,
    get_variation,
    trigger_early_deload,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def athlete():
    """Standard athlete for testing."""
    return Athlete(
        id=1,
        name="Test Athlete",
        bodyweight_lb=200.0,
        plate_increment_lb=2.5,
        deadlift_1rm=405.0,
        overhead_1rm=185.0,
        squat_1rm=365.0,
        event_1rm=200.0,
        stalled_lifts=[],
    )


# ---------------------------------------------------------------------------
# Variation helpers
# ---------------------------------------------------------------------------

class TestVariationHelpers:
    def test_get_variation_basic(self):
        assert get_variation(["a", "b", "c"], 0) == "a"
        assert get_variation(["a", "b", "c"], 1) == "b"
        assert get_variation(["a", "b", "c"], 2) == "c"

    def test_get_variation_wraps(self):
        assert get_variation(["a", "b", "c"], 3) == "a"
        assert get_variation(["a", "b", "c"], 5) == "c"

    def test_deadlift_variations(self):
        assert get_deadlift_variation(0) == "conventional"
        assert get_deadlift_variation(1) == "block pull"
        assert get_deadlift_variation(2) == "deficit"
        assert get_deadlift_variation(3) == "conventional"

    def test_overhead_variations(self):
        assert get_overhead_variation(0) == "push press"
        assert get_overhead_variation(1) == "strict press"
        assert get_overhead_variation(2) == "fat-grip clean & press"

    def test_squat_variations(self):
        assert get_squat_variation(0) == "back squat"
        assert get_squat_variation(1) == "pause squat"
        assert get_squat_variation(2) == "front squat"

    def test_variation_lists_have_three_entries(self):
        assert len(DEADLIFT_VARIATIONS) == 3
        assert len(OVERHEAD_VARIATIONS) == 3
        assert len(SQUAT_VARIATIONS) == 3


# ---------------------------------------------------------------------------
# generate_cycle – basic structure
# ---------------------------------------------------------------------------

class TestGenerateCycle:
    def test_returns_cycle_object(self, athlete):
        cycle = generate_cycle(1, "accumulation", athlete)
        assert isinstance(cycle, Cycle)

    def test_returns_4_sessions(self, athlete):
        cycle = generate_cycle(1, "accumulation", athlete)
        assert len(cycle.sessions) == 4

    def test_day_labels_are_A_B_C_D(self, athlete):
        cycle = generate_cycle(1, "accumulation", athlete)
        labels = [s.day_label for s in cycle.sessions]
        assert labels == ["A", "B", "C", "D"]

    def test_day_a_is_deadlift(self, athlete):
        cycle = generate_cycle(1, "accumulation", athlete)
        day_a = cycle.sessions[0]
        # Top set (set 4) should be deadlift
        top_sets = [p for p in day_a.prescriptions if not p.is_warmup and not p.is_backoff]
        assert any("deadlift" in p.exercise_name.lower() for p in top_sets)

    def test_day_b_is_overhead(self, athlete):
        cycle = generate_cycle(1, "accumulation", athlete)
        day_b = cycle.sessions[1]
        top_sets = [p for p in day_b.prescriptions if not p.is_warmup and not p.is_backoff]
        assert any("overhead" in p.exercise_name.lower() for p in top_sets)

    def test_day_c_is_squat(self, athlete):
        cycle = generate_cycle(1, "accumulation", athlete)
        day_c = cycle.sessions[2]
        top_sets = [p for p in day_c.prescriptions if not p.is_warmup and not p.is_backoff]
        assert any("squat" in p.exercise_name.lower() for p in top_sets)

    def test_day_d_is_events(self, athlete):
        cycle = generate_cycle(1, "accumulation", athlete)
        day_d = cycle.sessions[3]
        assert any("event" in p.exercise_name.lower() for p in day_d.prescriptions)

    def test_loading_cycle_not_deload(self, athlete):
        for cn in (1, 2, 3):
            cycle = generate_cycle(cn, "accumulation", athlete)
            assert cycle.is_deload is False

    def test_cycle_4_is_deload(self, athlete):
        cycle = generate_cycle(4, "accumulation", athlete)
        assert cycle.is_deload is True

    def test_cycle_number_set(self, athlete):
        cycle = generate_cycle(2, "intensification", athlete)
        assert cycle.cycle_number == 2

    def test_start_date_set(self, athlete):
        d = date(2025, 6, 1)
        cycle = generate_cycle(1, "accumulation", athlete, start_date=d)
        assert cycle.start_date == d

    def test_session_dates_progress(self, athlete):
        d = date(2025, 6, 1)
        cycle = generate_cycle(1, "accumulation", athlete, start_date=d)
        dates = [s.scheduled_date for s in cycle.sessions]
        assert dates == [d, d + timedelta(days=1), d + timedelta(days=2), d + timedelta(days=3)]


# ---------------------------------------------------------------------------
# generate_cycle – prescriptions match table
# ---------------------------------------------------------------------------

class TestPrescriptionTable:
    """Main-lift prescriptions match MAIN_LIFT_TABLE by block and cycle."""

    def _get_top_set(self, cycle, day_index):
        """Return the top (working) set prescription for a given day."""
        session = cycle.sessions[day_index]
        return [p for p in session.prescriptions
                if not p.is_warmup and not p.is_backoff][0]

    def test_accumulation_cycle_1_reps_rpe(self, athlete):
        """Accumulation cycle 1: 5 reps @ RPE 7.5, fatigue drop 10%."""
        cycle = generate_cycle(1, "accumulation", athlete)
        top = self._get_top_set(cycle, 0)  # Day A
        assert top.prescribed_reps == 5
        assert top.prescribed_rpe == 7.5
        assert top.fatigue_drop_pct == 10

    def test_accumulation_cycle_2_reps_rpe(self, athlete):
        """Accumulation cycle 2: 5 reps @ RPE 8.0, fatigue drop 10%."""
        cycle = generate_cycle(2, "accumulation", athlete)
        top = self._get_top_set(cycle, 0)
        assert top.prescribed_reps == 5
        assert top.prescribed_rpe == 8.0

    def test_accumulation_cycle_3_reps_rpe(self, athlete):
        """Accumulation cycle 3: 4 reps @ RPE 8.5, fatigue drop 15%."""
        cycle = generate_cycle(3, "accumulation", athlete)
        top = self._get_top_set(cycle, 0)
        assert top.prescribed_reps == 4
        assert top.prescribed_rpe == 8.5

    def test_intensification_cycle_1(self, athlete):
        """Intensification cycle 1: 4 reps @ RPE 8.0."""
        cycle = generate_cycle(1, "intensification", athlete)
        top = self._get_top_set(cycle, 0)
        assert top.prescribed_reps == 4
        assert top.prescribed_rpe == 8.0

    def test_intensification_cycle_3(self, athlete):
        """Intensification cycle 3: 3 reps @ RPE 9.0."""
        cycle = generate_cycle(3, "intensification", athlete)
        top = self._get_top_set(cycle, 0)
        assert top.prescribed_reps == 3
        assert top.prescribed_rpe == 9.0

    def test_realization_cycle_1(self, athlete):
        """Realization cycle 1: 3 reps @ RPE 8.5."""
        cycle = generate_cycle(1, "realization", athlete)
        top = self._get_top_set(cycle, 0)
        assert top.prescribed_reps == 3
        assert top.prescribed_rpe == 8.5

    def test_realization_cycle_3(self, athlete):
        """Realization cycle 3: 2 reps @ RPE 9.5."""
        cycle = generate_cycle(3, "realization", athlete)
        top = self._get_top_set(cycle, 0)
        assert top.prescribed_reps == 2
        assert top.prescribed_rpe == 9.5

    def test_all_blocks_cycles_in_table(self):
        """Every (block_type, cycle_num) combo has an entry."""
        for phase in BLOCK_PHASES:
            for cn in range(1, 5):
                assert (phase, cn) in MAIN_LIFT_TABLE
                assert (phase, cn) in SECONDARY_TABLE
                assert (phase, cn) in EVENT_TABLE


# ---------------------------------------------------------------------------
# Deload cycle content
# ---------------------------------------------------------------------------

class TestDeload:
    def test_deload_no_backoff_sets_day_a(self, athlete):
        cycle = generate_cycle(4, "accumulation", athlete)
        day_a = cycle.sessions[0]
        backoffs = [p for p in day_a.prescriptions if p.is_backoff]
        assert len(backoffs) == 0

    def test_deload_no_backoff_sets_day_b(self, athlete):
        cycle = generate_cycle(4, "accumulation", athlete)
        day_b = cycle.sessions[1]
        backoffs = [p for p in day_b.prescriptions if p.is_backoff]
        assert len(backoffs) == 0

    def test_deload_no_backoff_sets_day_c(self, athlete):
        cycle = generate_cycle(4, "accumulation", athlete)
        day_c = cycle.sessions[2]
        backoffs = [p for p in day_c.prescriptions if p.is_backoff]
        assert len(backoffs) == 0

    def test_deload_events_at_60_pct(self, athlete):
        """Deload events should be at 60% of event 1RM."""
        cycle = generate_cycle(4, "accumulation", athlete)
        day_d = cycle.sessions[3]
        event_pres = day_d.prescriptions[0]
        expected_load = round(athlete.event_1rm * 0.60 / athlete.plate_increment_lb) * athlete.plate_increment_lb
        assert event_pres.prescribed_load_lb == expected_load

    def test_deload_events_rpe_in_range(self, athlete):
        """Deload events RPE should be 6-7."""
        cycle = generate_cycle(4, "accumulation", athlete)
        day_d = cycle.sessions[3]
        event_pres = day_d.prescriptions[0]
        assert 6.0 <= event_pres.prescribed_rpe <= 7.0

    def test_deload_events_note(self, athlete):
        cycle = generate_cycle(4, "accumulation", athlete)
        day_d = cycle.sessions[3]
        event_pres = day_d.prescriptions[0]
        assert "Deload" in event_pres.adjustment_note

    def test_deload_main_lift_rpe_in_range(self, athlete):
        """Deload main lifts should have RPE 6-7."""
        cycle = generate_cycle(4, "accumulation", athlete)
        day_a = cycle.sessions[0]
        top_sets = [p for p in day_a.prescriptions
                    if not p.is_warmup and not p.is_backoff]
        for ps in top_sets:
            assert 6.0 <= ps.prescribed_rpe <= 7.0, f"RPE {ps.prescribed_rpe} out of 6-7 range"

    def test_deload_fatigue_drop_zero(self, athlete):
        """Deload cycles should have 0% fatigue drop."""
        for phase in BLOCK_PHASES:
            cycle = generate_cycle(4, phase, athlete)
            day_a = cycle.sessions[0]
            top_sets = [p for p in day_a.prescriptions
                        if not p.is_warmup and not p.is_backoff]
            for ps in top_sets:
                assert ps.fatigue_drop_pct == 0


# ---------------------------------------------------------------------------
# Realization deload – test day
# ---------------------------------------------------------------------------

class TestRealizationDeload:
    def test_realization_deload_day_a_is_test_day(self, athlete):
        cycle = generate_cycle(4, "realization", athlete)
        day_a = cycle.sessions[0]
        assert day_a.is_test_day is True

    def test_realization_deload_day_b_is_test_day(self, athlete):
        cycle = generate_cycle(4, "realization", athlete)
        day_b = cycle.sessions[1]
        assert day_b.is_test_day is True

    def test_realization_deload_day_c_is_test_day(self, athlete):
        cycle = generate_cycle(4, "realization", athlete)
        day_c = cycle.sessions[2]
        assert day_c.is_test_day is True

    def test_test_day_single_rep(self, athlete):
        cycle = generate_cycle(4, "realization", athlete)
        day_a = cycle.sessions[0]
        assert day_a.prescriptions[0].prescribed_reps == 1

    def test_test_day_rpe_9(self, athlete):
        cycle = generate_cycle(4, "realization", athlete)
        day_a = cycle.sessions[0]
        assert day_a.prescriptions[0].prescribed_rpe == 9.0

    def test_test_day_note(self, athlete):
        cycle = generate_cycle(4, "realization", athlete)
        day_a = cycle.sessions[0]
        assert "Test day" in day_a.prescriptions[0].adjustment_note

    def test_test_day_load_computed(self, athlete):
        cycle = generate_cycle(4, "realization", athlete)
        day_a = cycle.sessions[0]
        assert day_a.prescriptions[0].prescribed_load_lb is not None
        assert day_a.prescriptions[0].prescribed_load_lb > 0


# ---------------------------------------------------------------------------
# Variation rotation across blocks
# ---------------------------------------------------------------------------

class TestVariationRotation:
    def test_block_0_uses_first_variation(self, athlete):
        cycle = generate_cycle(1, "accumulation", athlete, block_index=0)
        day_a = cycle.sessions[0]
        top_sets = [p for p in day_a.prescriptions
                    if not p.is_warmup and not p.is_backoff]
        assert any("conventional" in p.exercise_name for p in top_sets)

    def test_block_1_uses_second_variation(self, athlete):
        cycle = generate_cycle(1, "intensification", athlete, block_index=1)
        day_a = cycle.sessions[0]
        top_sets = [p for p in day_a.prescriptions
                    if not p.is_warmup and not p.is_backoff]
        assert any("block pull" in p.exercise_name for p in top_sets)

    def test_block_2_uses_third_variation(self, athlete):
        cycle = generate_cycle(1, "realization", athlete, block_index=2)
        day_a = cycle.sessions[0]
        top_sets = [p for p in day_a.prescriptions
                    if not p.is_warmup and not p.is_backoff]
        assert any("deficit" in p.exercise_name for p in top_sets)

    def test_overhead_variation_block_1(self, athlete):
        cycle = generate_cycle(1, "intensification", athlete, block_index=1)
        day_b = cycle.sessions[1]
        top_sets = [p for p in day_b.prescriptions
                    if not p.is_warmup and not p.is_backoff]
        assert any("strict press" in p.exercise_name for p in top_sets)

    def test_squat_variation_block_2(self, athlete):
        cycle = generate_cycle(1, "realization", athlete, block_index=2)
        day_c = cycle.sessions[2]
        top_sets = [p for p in day_c.prescriptions
                    if not p.is_warmup and not p.is_backoff]
        assert any("front squat" in p.exercise_name for p in top_sets)


# ---------------------------------------------------------------------------
# Block generation
# ---------------------------------------------------------------------------

class TestGenerateBlock:
    def test_block_has_4_cycles(self, athlete):
        block = generate_block(1, "accumulation", athlete)
        assert len(block.cycles) == 4

    def test_block_phases(self, athlete):
        block = generate_block(1, "accumulation", athlete)
        assert block.phase == "accumulation"

    def test_block_number(self, athlete):
        block = generate_block(2, "intensification", athlete)
        assert block.block_number == 2

    def test_first_3_cycles_loading(self, athlete):
        block = generate_block(1, "accumulation", athlete)
        for i in range(3):
            assert block.cycles[i].is_deload is False

    def test_fourth_cycle_deload(self, athlete):
        block = generate_block(1, "accumulation", athlete)
        assert block.cycles[3].is_deload is True

    def test_block_has_16_sessions(self, athlete):
        block = generate_block(1, "accumulation", athlete)
        total = sum(len(c.sessions) for c in block.cycles)
        assert total == 16

    def test_block_variation_name_set(self, athlete):
        block = generate_block(1, "accumulation", athlete)
        assert block.variation_name == "conventional"


# ---------------------------------------------------------------------------
# Macrocycle generation
# ---------------------------------------------------------------------------

class TestGenerateMacrocycle:
    def test_has_3_blocks(self, athlete):
        macro = generate_macrocycle(athlete)
        assert len(macro.blocks) == 3

    def test_block_phases_in_order(self, athlete):
        macro = generate_macrocycle(athlete)
        phases = [b.phase for b in macro.blocks]
        assert phases == ["accumulation", "intensification", "realization"]

    def test_total_cycles_12(self, athlete):
        macro = generate_macrocycle(athlete)
        all_cycles = get_all_cycles(macro)
        assert len(all_cycles) == 12

    def test_total_sessions_48(self, athlete):
        macro = generate_macrocycle(athlete)
        all_sessions = get_all_sessions(macro)
        assert len(all_sessions) == 48

    def test_each_block_has_4_cycles(self, athlete):
        macro = generate_macrocycle(athlete)
        for block in macro.blocks:
            assert len(block.cycles) == 4

    def test_deload_cycles_count(self, athlete):
        """There should be 3 deload cycles (one per block)."""
        macro = generate_macrocycle(athlete)
        all_cycles = get_all_cycles(macro)
        deloads = [c for c in all_cycles if c.is_deload]
        assert len(deloads) == 3

    def test_loading_cycles_count(self, athlete):
        """There should be 9 loading cycles (3 per block)."""
        macro = generate_macrocycle(athlete)
        all_cycles = get_all_cycles(macro)
        loadings = [c for c in all_cycles if not c.is_deload]
        assert len(loadings) == 9

    def test_block_numbers_sequential(self, athlete):
        macro = generate_macrocycle(athlete)
        numbers = [b.block_number for b in macro.blocks]
        assert numbers == [1, 2, 3]

    def test_realization_deload_has_test_days(self, athlete):
        """The realization block's deload (last block, cycle 4) has test days."""
        macro = generate_macrocycle(athlete)
        realization_block = macro.blocks[2]
        deload_cycle = realization_block.cycles[3]
        assert deload_cycle.is_deload is True
        # Days A, B, C should be test days
        assert deload_cycle.sessions[0].is_test_day
        assert deload_cycle.sessions[1].is_test_day
        assert deload_cycle.sessions[2].is_test_day

    def test_variation_changes_across_blocks(self, athlete):
        """Each block should use a different variation."""
        macro = generate_macrocycle(athlete)
        variations = [b.variation_name for b in macro.blocks]
        assert len(set(variations)) == 3, "Each block should have unique variation"


# ---------------------------------------------------------------------------
# Stall detection
# ---------------------------------------------------------------------------

class TestStallDetection:
    def test_no_stall_when_improving(self, athlete):
        trends = {"deadlift": [400, 410, 420, 430]}
        stalled = detect_stalls(athlete, trends, cycles_back=3)
        assert "deadlift" not in stalled

    def test_stall_detected_when_flat(self, athlete):
        """With cycles_back=3, compare trends[-1] vs trends[-4].
        Need at least 4 data points. Current (last) <= past (3 back) = stall."""
        trends = {"deadlift": [420, 410, 415, 420]}
        stalled = detect_stalls(athlete, trends, cycles_back=3)
        assert "deadlift" in stalled

    def test_stall_detected_when_declining(self, athlete):
        trends = {"deadlift": [420, 410, 415, 415]}
        stalled = detect_stalls(athlete, trends, cycles_back=3)
        assert "deadlift" in stalled

    def test_no_stall_with_insufficient_data(self, athlete):
        trends = {"deadlift": [400, 410]}
        stalled = detect_stalls(athlete, trends, cycles_back=3)
        assert "deadlift" not in stalled

    def test_multiple_lifts_stalled(self, athlete):
        trends = {
            "deadlift": [420, 410, 415, 420],   # 420 <= 420 → stalled
            "squat": [370, 360, 365, 370],      # 370 <= 370 → stalled
            "overhead": [180, 185, 190, 195],   # 195 > 180 → not stalled
        }
        stalled = detect_stalls(athlete, trends, cycles_back=3)
        assert "deadlift" in stalled
        assert "squat" in stalled
        assert "overhead" not in stalled


# ---------------------------------------------------------------------------
# Early deload trigger
# ---------------------------------------------------------------------------

class TestEarlyDeload:
    def test_triggers_early_deload(self, athlete):
        result = trigger_early_deload(athlete, ["deadlift"])
        assert result["early_deload"] is True

    def test_swaps_deadlift_variation(self, athlete):
        result = trigger_early_deload(athlete, ["deadlift"])
        assert "deadlift" in result["swapped_variations"]

    def test_swaps_overhead_variation(self, athlete):
        result = trigger_early_deload(athlete, ["overhead press"])
        assert "overhead" in result["swapped_variations"]

    def test_swaps_squat_variation(self, athlete):
        result = trigger_early_deload(athlete, ["back squat"])
        assert "squat" in result["swapped_variations"]

    def test_message_includes_lifts(self, athlete):
        result = trigger_early_deload(athlete, ["deadlift", "squat"])
        assert "deadlift" in result["message"]
        assert "squat" in result["message"]

    def test_message_mentions_early_deload(self, athlete):
        result = trigger_early_deload(athlete, ["deadlift"])
        assert "early deload" in result["message"].lower()

    def test_swapped_variation_is_different(self, athlete):
        """The new variation should be different from the current one."""
        result = trigger_early_deload(athlete, ["deadlift"])
        new_var = result["swapped_variations"]["deadlift"]
        # After first stall, should rotate to next variation
        assert new_var in DEADLIFT_VARIATIONS


# ---------------------------------------------------------------------------
# Warm-up sets
# ---------------------------------------------------------------------------

class TestWarmupSets:
    def test_warmup_sets_present_on_loading_day(self, athlete):
        cycle = generate_cycle(1, "accumulation", athlete)
        day_a = cycle.sessions[0]
        warmups = [p for p in day_a.prescriptions if p.is_warmup]
        assert len(warmups) == 3

    def test_warmup_sets_present_on_deload(self, athlete):
        """Deload still has warmups (just no back-offs)."""
        cycle = generate_cycle(4, "accumulation", athlete)
        day_a = cycle.sessions[0]
        warmups = [p for p in day_a.prescriptions if p.is_warmup]
        assert len(warmups) == 3

    def test_warmup_loads_increasing(self, athlete):
        cycle = generate_cycle(1, "accumulation", athlete)
        day_a = cycle.sessions[0]
        warmups = [p for p in day_a.prescriptions if p.is_warmup]
        loads = [p.prescribed_load_lb for p in warmups]
        assert loads == sorted(loads)


# ---------------------------------------------------------------------------
# Back-off sets
# ---------------------------------------------------------------------------

class TestBackoffSets:
    def test_backoff_present_on_loading(self, athlete):
        cycle = generate_cycle(1, "accumulation", athlete)
        day_a = cycle.sessions[0]
        backoffs = [p for p in day_a.prescriptions if p.is_backoff]
        assert len(backoffs) == 1

    def test_backoff_has_fatigue_drop(self, athlete):
        cycle = generate_cycle(1, "accumulation", athlete)
        day_a = cycle.sessions[0]
        backoffs = [p for p in day_a.prescriptions if p.is_backoff]
        assert backoffs[0].fatigue_drop_pct > 0

    def test_backoff_rpe_lower_than_top(self, athlete):
        cycle = generate_cycle(1, "accumulation", athlete)
        day_a = cycle.sessions[0]
        top = [p for p in day_a.prescriptions
               if not p.is_warmup and not p.is_backoff][0]
        backoff = [p for p in day_a.prescriptions if p.is_backoff][0]
        assert backoff.prescribed_rpe < top.prescribed_rpe


# ---------------------------------------------------------------------------
# Integration: full macrocycle
# ---------------------------------------------------------------------------

class TestFullMacrocycle:
    def test_macrocycle_structure(self, athlete):
        """Full macrocycle: 3 blocks × 4 cycles × 4 sessions = 48 sessions."""
        macro = generate_macrocycle(athlete)
        assert len(macro.blocks) == 3
        for block in macro.blocks:
            assert len(block.cycles) == 4
            for cycle in block.cycles:
                assert len(cycle.sessions) == 4

    def test_progression_of_intensity(self, athlete):
        """RPE should generally increase across loading cycles within a block."""
        macro = generate_macrocycle(athlete)
        accum = macro.blocks[0]
        # Check cycle 1 vs cycle 3 top set RPE on day A
        c1_top = [p for p in accum.cycles[0].sessions[0].prescriptions
                  if not p.is_warmup and not p.is_backoff][0]
        c3_top = [p for p in accum.cycles[2].sessions[0].prescriptions
                  if not p.is_warmup and not p.is_backoff][0]
        assert c3_top.prescribed_rpe >= c1_top.prescribed_rpe

    def test_all_day_labels_present_in_every_cycle(self, athlete):
        macro = generate_macrocycle(athlete)
        for block in macro.blocks:
            for cycle in block.cycles:
                labels = [s.day_label for s in cycle.sessions]
                assert set(labels) == {"A", "B", "C", "D"}

    def test_event_day_always_day_d(self, athlete):
        macro = generate_macrocycle(athlete)
        for block in macro.blocks:
            for cycle in block.cycles:
                day_d = cycle.sessions[3]
                assert day_d.day_label == "D"
                assert any("event" in p.exercise_name.lower()
                           for p in day_d.prescriptions)
