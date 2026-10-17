"""Tests for the RPE engine: percent chart, e1RM, target load, confidence."""
from app.strength.rpe import percent, e1rm, target_load


class TestPercent:
    """Test the percent-of-1RM lookup table."""

    def test_1_rep_rpe_10(self):
        assert percent(1, 10.0) == 100.0

    def test_5_reps_rpe_8(self):
        assert percent(5, 8.0) == 81.1

    def test_3_reps_rpe_9(self):
        assert percent(3, 9.0) == 89.2

    def test_1_rep_rpe_6(self):
        assert percent(1, 6.0) == 65.0

    def test_12_reps_rpe_10(self):
        assert percent(12, 10.0) == 96.0

    def test_invalid_reps_low(self):
        import pytest
        with pytest.raises(ValueError):
            percent(0, 8.0)

    def test_invalid_reps_high(self):
        import pytest
        with pytest.raises(ValueError):
            percent(13, 8.0)

    def test_invalid_rpe_low(self):
        import pytest
        with pytest.raises(ValueError):
            percent(5, 5.5)

    def test_invalid_rpe_high(self):
        import pytest
        with pytest.raises(ValueError):
            percent(5, 10.5)

    def test_invalid_rpe_step(self):
        import pytest
        with pytest.raises(ValueError):
            percent(5, 7.3)


class TestE1rm:
    """Test estimated 1RM calculation."""

    def test_e1rm_with_rpe(self):
        result = e1rm(200, 5, 8.0)
        # 200 / (81.1/100) = 246.6
        assert result["e1rm"] == 246.6
        assert result["confidence"] == "high"

    def test_e1rm_low_rpe(self):
        result = e1rm(200, 5, 6.0)
        assert result["confidence"] == "low"

    def test_e1rm_high_reps(self):
        result = e1rm(200, 10, 8.0)
        assert result["confidence"] == "low"

    def test_e1rm_no_rpe_epley(self):
        result = e1rm(200, 5, None)
        # Epley: 200 * (1 + 5/30) = 233.3
        assert result["e1rm"] == 233.3
        assert result["confidence"] == "low"

    def test_e1rm_1_rep_max(self):
        result = e1rm(300, 1, 10.0)
        assert result["e1rm"] == 300.0
        assert result["confidence"] == "high"

    def test_e1rm_405_3_9(self):
        """Acceptance criterion: e1rm(405, 3, 9) returns 454 (±1)."""
        result = e1rm(405, 3, 9.0)
        assert 453 <= result["e1rm"] <= 455
        assert result["confidence"] == "high"


class TestTargetLoad:
    """Test target load calculation."""

    def test_target_load_basic(self):
        load = target_load(300, 5, 8.0, plate_increment=5.0)
        # 300 * 0.811 = 243.3, floor to 5 = 240
        assert load == 240.0

    def test_target_load_2_5_increment(self):
        load = target_load(300, 5, 8.0, plate_increment=2.5)
        # 300 * 0.811 = 243.3, floor to 2.5 = 242.5
        assert load == 242.5
