"""Tests for the APRE (Adaptive Periodization Reps in Reserve) protocol.

Covers:
- Set weight calculations (50%, 75%, 100% of estimated RM)
- AMRAP flags on sets 3 and 4
- Set 4 load adjustment for all rep ranges in both 6RM and 3RM tables
- Carry-forward of next session's load
- Adjustment range reporting
- Edge cases and validation
"""

import pytest

from app.strength.apre import (
    ApreResult,
    ApreSet,
    calculate_apre_sets,
    adjust_set4_weight,
    adjust_next_session,
    get_apre_adjustment_range,
    APRE_6RM_ADJUSTMENT,
    APRE_3RM_ADJUSTMENT,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def apre_6rm():
    """APRE result for 6RM with 200 lb estimated RM."""
    return calculate_apre_sets(estimated_rm=200.0, rm_type="6RM")


@pytest.fixture
def apre_3rm():
    """APRE result for 3RM with 200 lb estimated RM."""
    return calculate_apre_sets(estimated_rm=200.0, rm_type="3RM")


# ---------------------------------------------------------------------------
# Test: Set weight calculations
# ---------------------------------------------------------------------------

class TestSetWeights:
    """Verify Set 1, 2, 3 weights are correct percentages of estimated RM."""

    def test_set1_is_50_percent_6rm(self, apre_6rm):
        """Set 1 should be 50% of estimated RM."""
        assert apre_6rm.sets[0].weight == 100.0  # 200 * 0.50

    def test_set1_is_50_percent_3rm(self, apre_3rm):
        """Set 1 should be 50% of estimated RM for 3RM too."""
        assert apre_3rm.sets[0].weight == 100.0

    def test_set2_is_75_percent_6rm(self, apre_6rm):
        """Set 2 should be 75% of estimated RM."""
        assert apre_6rm.sets[1].weight == 150.0  # 200 * 0.75

    def test_set2_is_75_percent_3rm(self, apre_3rm):
        """Set 2 should be 75% of estimated RM for 3RM too."""
        assert apre_3rm.sets[1].weight == 150.0

    def test_set3_is_100_percent_6rm(self, apre_6rm):
        """Set 3 should be 100% of estimated RM."""
        assert apre_6rm.sets[2].weight == 200.0

    def test_set3_is_100_percent_3rm(self, apre_3rm):
        """Set 3 should be 100% of estimated RM for 3RM too."""
        assert apre_3rm.sets[2].weight == 200.0

    def test_set4_placeholder_equals_set3(self, apre_6rm):
        """Set 4 starts as a placeholder equal to Set 3 weight."""
        assert apre_6rm.sets[3].weight == apre_6rm.sets[2].weight

    def test_set_weights_with_different_rm(self):
        """Weights scale correctly with different estimated RM."""
        result = calculate_apre_sets(estimated_rm=300.0, rm_type="6RM")
        assert result.sets[0].weight == 150.0  # 300 * 0.50
        assert result.sets[1].weight == 225.0  # 300 * 0.75
        assert result.sets[2].weight == 300.0  # 300 * 1.00

    def test_set_weights_rounded_to_plate(self):
        """Weights are rounded to plate increment."""
        result = calculate_apre_sets(estimated_rm=205.0, rm_type="6RM", plate_increment=2.5)
        # 205 * 0.50 = 102.5 → 102.5
        assert result.sets[0].weight == 102.5
        # 205 * 0.75 = 153.75 → 155.0
        assert result.sets[1].weight == 155.0
        # 205 * 1.00 = 205.0 → 205.0
        assert result.sets[2].weight == 205.0


# ---------------------------------------------------------------------------
# Test: Set properties (reps, AMRAP flags)
# ---------------------------------------------------------------------------

class TestSetProperties:
    """Verify set_number, target_reps, and is_amrap flags."""

    def test_four_sets(self, apre_6rm):
        """APRE should produce exactly 4 sets."""
        assert len(apre_6rm.sets) == 4

    def test_set_numbers(self, apre_6rm):
        """Sets should be numbered 1-4."""
        assert [s.set_number for s in apre_6rm.sets] == [1, 2, 3, 4]

    def test_set1_target_reps_10(self, apre_6rm):
        """Set 1 targets 10 reps."""
        assert apre_6rm.sets[0].target_reps == 10

    def test_set2_target_reps_6(self, apre_6rm):
        """Set 2 targets 6 reps."""
        assert apre_6rm.sets[1].target_reps == 6

    def test_set3_is_amrap(self, apre_6rm):
        """Set 3 is AMRAP (no target reps)."""
        assert apre_6rm.sets[2].target_reps is None
        assert apre_6rm.sets[2].is_amrap is True

    def test_set4_is_amrap(self, apre_6rm):
        """Set 4 is AMRAP (no target reps)."""
        assert apre_6rm.sets[3].target_reps is None
        assert apre_6rm.sets[3].is_amrap is True

    def test_set1_not_amrap(self, apre_6rm):
        """Set 1 is not AMRAP."""
        assert apre_6rm.sets[0].is_amrap is False

    def test_set2_not_amrap(self, apre_6rm):
        """Set 2 is not AMRAP."""
        assert apre_6rm.sets[1].is_amrap is False

    def test_actual_reps_initially_none(self, apre_6rm):
        """Actual reps are None until the set is performed."""
        for s in apre_6rm.sets:
            assert s.actual_reps is None


# ---------------------------------------------------------------------------
# Test: Set 4 load adjustment – 6RM table
# ---------------------------------------------------------------------------

class TestSet4Adjustment6RM:
    """Verify Set 4 load adjustment for all 6RM rep ranges."""

    def test_0_reps_decrease(self, apre_6rm):
        """0 reps on Set 3 → -5 to -10 lb adjustment."""
        weight = adjust_set4_weight(apre_6rm, set3_reps=0)
        # 200 - 7.5 = 192.5, rounded to 2.5 = 192.5
        assert weight == 192.5

    def test_1_rep_decrease(self, apre_6rm):
        """1 rep on Set 3 → -5 to -10 lb adjustment."""
        weight = adjust_set4_weight(apre_6rm, set3_reps=1)
        assert weight == 192.5

    def test_2_reps_decrease(self, apre_6rm):
        """2 reps on Set 3 → -5 to -10 lb adjustment."""
        weight = adjust_set4_weight(apre_6rm, set3_reps=2)
        assert weight == 192.5

    def test_3_reps_small_decrease(self, apre_6rm):
        """3 reps on Set 3 → 0 to -5 lb adjustment."""
        weight = adjust_set4_weight(apre_6rm, set3_reps=3)
        # 200 - 2.5 = 197.5
        assert weight == 197.5

    def test_4_reps_small_decrease(self, apre_6rm):
        """4 reps on Set 3 → 0 to -5 lb adjustment."""
        weight = adjust_set4_weight(apre_6rm, set3_reps=4)
        assert weight == 197.5

    def test_5_reps_same(self, apre_6rm):
        """5 reps on Set 3 → same load."""
        weight = adjust_set4_weight(apre_6rm, set3_reps=5)
        assert weight == 200.0

    def test_6_reps_same(self, apre_6rm):
        """6 reps on Set 3 → same load."""
        weight = adjust_set4_weight(apre_6rm, set3_reps=6)
        assert weight == 200.0

    def test_7_reps_same(self, apre_6rm):
        """7 reps on Set 3 → same load."""
        weight = adjust_set4_weight(apre_6rm, set3_reps=7)
        assert weight == 200.0

    def test_8_reps_increase(self, apre_6rm):
        """8 reps on Set 3 → +5 to +10 lb adjustment."""
        weight = adjust_set4_weight(apre_6rm, set3_reps=8)
        # 200 + 7.5 = 207.5
        assert weight == 207.5

    def test_9_reps_increase(self, apre_6rm):
        """9 reps on Set 3 → +5 to +10 lb adjustment."""
        weight = adjust_set4_weight(apre_6rm, set3_reps=9)
        assert weight == 207.5

    def test_10_reps_increase(self, apre_6rm):
        """10 reps on Set 3 → +5 to +10 lb adjustment."""
        weight = adjust_set4_weight(apre_6rm, set3_reps=10)
        assert weight == 207.5

    def test_11_reps_increase(self, apre_6rm):
        """11 reps on Set 3 → +5 to +10 lb adjustment."""
        weight = adjust_set4_weight(apre_6rm, set3_reps=11)
        assert weight == 207.5

    def test_12_reps_increase(self, apre_6rm):
        """12 reps on Set 3 → +5 to +10 lb adjustment."""
        weight = adjust_set4_weight(apre_6rm, set3_reps=12)
        assert weight == 207.5

    def test_13_reps_big_increase(self, apre_6rm):
        """13 reps on Set 3 → +10 to +15 lb adjustment."""
        weight = adjust_set4_weight(apre_6rm, set3_reps=13)
        # 200 + 12.5 = 212.5
        assert weight == 212.5

    def test_15_reps_big_increase(self, apre_6rm):
        """15 reps on Set 3 → +10 to +15 lb adjustment."""
        weight = adjust_set4_weight(apre_6rm, set3_reps=15)
        assert weight == 212.5

    def test_20_reps_big_increase(self, apre_6rm):
        """20 reps on Set 3 → +10 to +15 lb adjustment."""
        weight = adjust_set4_weight(apre_6rm, set3_reps=20)
        assert weight == 212.5


# ---------------------------------------------------------------------------
# Test: Set 4 load adjustment – 3RM table
# ---------------------------------------------------------------------------

class TestSet4Adjustment3RM:
    """Verify Set 4 load adjustment for all 3RM rep ranges."""

    def test_0_reps_decrease(self, apre_3rm):
        """0 reps on Set 3 → treated as worst case for 3RM."""
        weight = adjust_set4_weight(apre_3rm, set3_reps=0)
        assert weight == 192.5

    def test_1_rep_decrease(self, apre_3rm):
        """1 rep on Set 3 → -5 to -10 lb adjustment."""
        weight = adjust_set4_weight(apre_3rm, set3_reps=1)
        assert weight == 192.5

    def test_2_reps_decrease(self, apre_3rm):
        """2 reps on Set 3 → -5 to -10 lb adjustment."""
        weight = adjust_set4_weight(apre_3rm, set3_reps=2)
        assert weight == 192.5

    def test_3_reps_same(self, apre_3rm):
        """3 reps on Set 3 → same load."""
        weight = adjust_set4_weight(apre_3rm, set3_reps=3)
        assert weight == 200.0

    def test_4_reps_same(self, apre_3rm):
        """4 reps on Set 3 → same load."""
        weight = adjust_set4_weight(apre_3rm, set3_reps=4)
        assert weight == 200.0

    def test_5_reps_increase(self, apre_3rm):
        """5 reps on Set 3 → +5 to +10 lb adjustment."""
        weight = adjust_set4_weight(apre_3rm, set3_reps=5)
        assert weight == 207.5

    def test_6_reps_increase(self, apre_3rm):
        """6 reps on Set 3 → +5 to +10 lb adjustment."""
        weight = adjust_set4_weight(apre_3rm, set3_reps=6)
        assert weight == 207.5

    def test_7_reps_big_increase(self, apre_3rm):
        """7 reps on Set 3 → +10 to +15 lb adjustment."""
        weight = adjust_set4_weight(apre_3rm, set3_reps=7)
        assert weight == 212.5

    def test_10_reps_big_increase(self, apre_3rm):
        """10 reps on Set 3 → +10 to +15 lb adjustment."""
        weight = adjust_set4_weight(apre_3rm, set3_reps=10)
        assert weight == 212.5

    def test_15_reps_big_increase(self, apre_3rm):
        """15 reps on Set 3 → +10 to +15 lb adjustment."""
        weight = adjust_set4_weight(apre_3rm, set3_reps=15)
        assert weight == 212.5


# ---------------------------------------------------------------------------
# Test: Next session carry-forward
# ---------------------------------------------------------------------------

class TestNextSessionCarryForward:
    """Verify next session load and RM reps are carried forward correctly."""

    def test_next_session_load_6rm_good_performance(self):
        """Good Set 3 performance increases next session load (6RM)."""
        result = calculate_apre_sets(estimated_rm=200.0, rm_type="6RM")
        adjusted = adjust_next_session(result, set3_reps=8, set4_reps=6)
        # 8 reps → +7.5 adjustment → 207.5
        assert adjusted.next_session_load == 207.5

    def test_next_session_load_6rm_poor_performance(self):
        """Poor Set 3 performance decreases next session load (6RM)."""
        result = calculate_apre_sets(estimated_rm=200.0, rm_type="6RM")
        adjusted = adjust_next_session(result, set3_reps=1, set4_reps=2)
        # 1 rep → -7.5 adjustment → 192.5
        assert adjusted.next_session_load == 192.5

    def test_next_session_load_6rm_moderate_performance(self):
        """Moderate Set 3 performance keeps same load (6RM)."""
        result = calculate_apre_sets(estimated_rm=200.0, rm_type="6RM")
        adjusted = adjust_next_session(result, set3_reps=5, set4_reps=5)
        # 5 reps → 0 adjustment → 200.0
        assert adjusted.next_session_load == 200.0

    def test_next_session_load_3rm_good_performance(self):
        """Good Set 3 performance increases next session load (3RM)."""
        result = calculate_apre_sets(estimated_rm=200.0, rm_type="3RM")
        adjusted = adjust_next_session(result, set3_reps=7, set4_reps=4)
        # 7 reps → +12.5 adjustment → 212.5
        assert adjusted.next_session_load == 212.5

    def test_next_session_load_3rm_poor_performance(self):
        """Poor Set 3 performance decreases next session load (3RM)."""
        result = calculate_apre_sets(estimated_rm=200.0, rm_type="3RM")
        adjusted = adjust_next_session(result, set3_reps=1, set4_reps=1)
        # 1 rep → -7.5 adjustment → 192.5
        assert adjusted.next_session_load == 192.5

    def test_next_session_rm_reps_from_set4(self):
        """Set 4 reps determine next session's RM reps target."""
        result = calculate_apre_sets(estimated_rm=200.0, rm_type="6RM")
        adjusted = adjust_next_session(result, set3_reps=6, set4_reps=5)
        assert adjusted.next_session_rm_reps == 5

    def test_next_session_rm_reps_different_value(self):
        """Set 4 reps are correctly carried forward regardless of value."""
        result = calculate_apre_sets(estimated_rm=200.0, rm_type="6RM")
        adjusted = adjust_next_session(result, set3_reps=10, set4_reps=8)
        assert adjusted.next_session_rm_reps == 8

    def test_set4_weight_updated_in_result(self):
        """Set 4 weight is updated in the result after adjustment."""
        result = calculate_apre_sets(estimated_rm=200.0, rm_type="6RM")
        adjusted = adjust_next_session(result, set3_reps=8, set4_reps=6)
        # Set 4 weight should be adjusted based on Set 3 reps
        assert adjusted.sets[3].weight == 207.5

    def test_next_session_load_rounded_to_plate(self):
        """Next session load is rounded to plate increment."""
        result = calculate_apre_sets(estimated_rm=205.0, rm_type="6RM", plate_increment=2.5)
        adjusted = adjust_next_session(result, set3_reps=8, set4_reps=6, plate_increment=2.5)
        # 205 + 7.5 = 212.5, already on plate increment
        assert adjusted.next_session_load == 212.5

    def test_carry_forward_chain(self):
        """Verify that next session load can be used as input for next APRE."""
        # First session
        result1 = calculate_apre_sets(estimated_rm=200.0, rm_type="6RM")
        adjusted1 = adjust_next_session(result1, set3_reps=8, set4_reps=6)

        # Use next session load for second session
        result2 = calculate_apre_sets(
            estimated_rm=adjusted1.next_session_load,
            rm_type="6RM",
        )
        # Set 1 should be 50% of 207.5 = 103.75 → 105.0
        assert result2.sets[0].weight == 105.0
        # Set 2 should be 75% of 207.5 = 155.625 → 155.0
        assert result2.sets[1].weight == 155.0
        # Set 3 should be 100% of 207.5 = 207.5
        assert result2.sets[2].weight == 207.5


# ---------------------------------------------------------------------------
# Test: Adjustment range reporting
# ---------------------------------------------------------------------------

class TestAdjustmentRange:
    """Verify get_apre_adjustment_range returns correct ranges."""

    def test_6rm_0_2_reps(self):
        """0-2 reps → -10 to -5 lb."""
        for reps in [0, 1, 2]:
            lo, hi = get_apre_adjustment_range(reps, "6RM")
            assert lo == -10.0
            assert hi == -5.0

    def test_6rm_3_4_reps(self):
        """3-4 reps → 0 to -5 lb."""
        for reps in [3, 4]:
            lo, hi = get_apre_adjustment_range(reps, "6RM")
            assert lo == 0.0
            assert hi == -5.0

    def test_6rm_5_7_reps(self):
        """5-7 reps → same (0 to 0)."""
        for reps in [5, 6, 7]:
            lo, hi = get_apre_adjustment_range(reps, "6RM")
            assert lo == 0.0
            assert hi == 0.0

    def test_6rm_8_12_reps(self):
        """8-12 reps → +5 to +10 lb."""
        for reps in [8, 9, 10, 11, 12]:
            lo, hi = get_apre_adjustment_range(reps, "6RM")
            assert lo == 5.0
            assert hi == 10.0

    def test_6rm_13_plus_reps(self):
        """13+ reps → +10 to +15 lb."""
        for reps in [13, 15, 20]:
            lo, hi = get_apre_adjustment_range(reps, "6RM")
            assert lo == 10.0
            assert hi == 15.0

    def test_3rm_1_2_reps(self):
        """1-2 reps → -10 to -5 lb."""
        for reps in [1, 2]:
            lo, hi = get_apre_adjustment_range(reps, "3RM")
            assert lo == -10.0
            assert hi == -5.0

    def test_3rm_3_4_reps(self):
        """3-4 reps → same (0 to 0)."""
        for reps in [3, 4]:
            lo, hi = get_apre_adjustment_range(reps, "3RM")
            assert lo == 0.0
            assert hi == 0.0

    def test_3rm_5_6_reps(self):
        """5-6 reps → +5 to +10 lb."""
        for reps in [5, 6]:
            lo, hi = get_apre_adjustment_range(reps, "3RM")
            assert lo == 5.0
            assert hi == 10.0

    def test_3rm_7_plus_reps(self):
        """7+ reps → +10 to +15 lb."""
        for reps in [7, 10, 15]:
            lo, hi = get_apre_adjustment_range(reps, "3RM")
            assert lo == 10.0
            assert hi == 15.0


# ---------------------------------------------------------------------------
# Test: Validation and edge cases
# ---------------------------------------------------------------------------

class TestValidation:
    """Verify input validation and edge cases."""

    def test_zero_estimated_rm_raises(self):
        """Zero estimated RM should raise ValueError."""
        with pytest.raises(ValueError, match="positive"):
            calculate_apre_sets(estimated_rm=0.0, rm_type="6RM")

    def test_negative_estimated_rm_raises(self):
        """Negative estimated RM should raise ValueError."""
        with pytest.raises(ValueError, match="positive"):
            calculate_apre_sets(estimated_rm=-100.0, rm_type="6RM")

    def test_invalid_rm_type_raises(self):
        """Invalid rm_type should raise ValueError."""
        with pytest.raises(ValueError, match="6RM.*3RM"):
            calculate_apre_sets(estimated_rm=200.0, rm_type="5RM")

    def test_negative_set3_reps_raises(self):
        """Negative set3_reps should raise ValueError."""
        result = calculate_apre_sets(estimated_rm=200.0, rm_type="6RM")
        with pytest.raises(ValueError, match="non-negative"):
            adjust_set4_weight(result, set3_reps=-1)

    def test_negative_set3_reps_in_adjust_next(self):
        """Negative set3_reps in adjust_next_session should raise."""
        result = calculate_apre_sets(estimated_rm=200.0, rm_type="6RM")
        with pytest.raises(ValueError, match="non-negative"):
            adjust_next_session(result, set3_reps=-1, set4_reps=5)

    def test_negative_set4_reps_in_adjust_next(self):
        """Negative set4_reps in adjust_next_session should raise."""
        result = calculate_apre_sets(estimated_rm=200.0, rm_type="6RM")
        with pytest.raises(ValueError, match="non-negative"):
            adjust_next_session(result, set3_reps=5, set4_reps=-1)

    def test_plate_increment_5_lb(self):
        """Weights round correctly with 5 lb plate increment."""
        result = calculate_apre_sets(estimated_rm=205.0, rm_type="6RM", plate_increment=5.0)
        # 205 * 0.50 = 102.5 → round(102.5/5)*5 = round(20.5)*5 = 20*5 = 100.0
        assert result.sets[0].weight == 100.0
        # 205 * 0.75 = 153.75 → round(153.75/5)*5 = round(30.75)*5 = 31*5 = 155.0
        assert result.sets[1].weight == 155.0
        # 205 * 1.00 = 205.0 → 205.0
        assert result.sets[2].weight == 205.0

    def test_estimated_rm_preserved(self):
        """estimated_rm is preserved in the result."""
        result = calculate_apre_sets(estimated_rm=250.0, rm_type="6RM")
        assert result.estimated_rm == 250.0

    def test_rm_type_preserved(self):
        """rm_type is preserved in the result."""
        result = calculate_apre_sets(estimated_rm=200.0, rm_type="3RM")
        assert result.rm_type == "3RM"

    def test_initial_next_session_load_equals_estimated_rm(self):
        """Before adjustment, next_session_load equals estimated_rm."""
        result = calculate_apre_sets(estimated_rm=200.0, rm_type="6RM")
        assert result.next_session_load == 200.0

    def test_initial_next_session_rm_reps_is_zero(self):
        """Before adjustment, next_session_rm_reps is 0."""
        result = calculate_apre_sets(estimated_rm=200.0, rm_type="6RM")
        assert result.next_session_rm_reps == 0
