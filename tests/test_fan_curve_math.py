"""Unit tests for the fan-curve analysis core (examples/_fan_curve_math).

All fixtures are synthetic 63-row sweeps on the PWM_F=31 grid (S=0..62,
effective duty = S/62 * 100 %), shaped to exercise each of the four
characterization determinations plus the degenerate-input contracts.
"""
import math
import sys
import unittest

sys.path.insert(0, "examples")

from _fan_curve_math import (CSV_HEADER, NOISE_FLOOR_RPM_PER_PCT,
                             ONSET_FRAC, ONSET_TOL_RPM, PLATEAU_WINDOW_ROWS,
                             SUSTAIN_ROWS, analyze, effective_pct,
                             format_csv_row, format_summary, median)

N_ROWS = 63          # S = 0..62
STEP = 100.0 / 62.0  # percent per raw setting


def make_rows(fn):
    """Build a sweep from fn(pct, i) -> settled rpm."""
    return [(i * STEP, fn(i * STEP, i)) for i in range(N_ROWS)]


class GridMathTestCase(unittest.TestCase):
    def test_effective_pct_endpoints(self):
        self.assertEqual(effective_pct(0, 31), 0.0)
        self.assertAlmostEqual(effective_pct(1, 31), 100.0 / 62.0, places=9)
        self.assertEqual(effective_pct(62, 31), 100.0)

    def test_effective_pct_clamps_above_full_scale(self):
        self.assertEqual(effective_pct(63, 31), 100.0)

    def test_effective_pct_bad_inputs_raise(self):
        with self.assertRaises(ValueError):
            effective_pct(0, 0)
        with self.assertRaises(ValueError):
            effective_pct(0, 32)
        with self.assertRaises(ValueError):
            effective_pct(-1, 31)
        with self.assertRaises(ValueError):
            effective_pct(64, 31)

    def test_median_odd_even_single(self):
        self.assertEqual(median([3, 1, 2]), 2.0)
        self.assertEqual(median([4, 1, 3, 2]), 2.5)
        self.assertEqual(median([7]), 7.0)

    def test_median_empty_raises(self):
        with self.assertRaises(ValueError):
            median([])

    def test_format_csv_row_matches_reference_style(self):
        self.assertEqual(format_csv_row(1.6, 659.9, 658.8, 667.3),
                         "1.6,659.9,658.8,667.3")
        self.assertEqual(CSV_HEADER, "pct,rpm_settled,rpm_min,rpm_max")


class StoppingFanTestCase(unittest.TestCase):
    """Fan that truly stops: zero below 10 %, then a clean ramp to 2000."""

    @classmethod
    def setUpClass(cls):
        cls.rows = make_rows(lambda pct, i:
                             0.0 if pct < 10.0 else (pct - 10.0) / 90.0 * 2000.0)
        cls.res = analyze(cls.rows)

    def test_turns_off(self):
        self.assertTrue(self.res["turns_off"])
        self.assertIsNone(self.res["floor_rpm"])

    def test_onset_is_first_nonzero_row(self):
        # first row with pct >= 10 is i=7 (11.29 %)
        self.assertAlmostEqual(self.res["onset_pct"], 7 * STEP, places=6)
        self.assertIsNotNone(self.res["onset_rpm"])

    def test_no_saturation_ceiling(self):
        self.assertIsNone(self.res["ceiling_pct"])

    def test_linearity_near_perfect_for_clean_ramp(self):
        lin = self.res["linearity"]
        self.assertIsNotNone(lin)
        self.assertLess(abs(lin["max_dev_rpm"]), 1.0)
        self.assertLess(lin["rms_rpm"], 0.5)

    def test_peak(self):
        self.assertAlmostEqual(self.res["peak_rpm"], 2000.0, places=6)


class FloorFanTestCase(unittest.TestCase):
    """Floor fan (~660 rpm at 0 %) with a stale-latch spike in the 0 %
    row and a gradual rise above ~20 %."""

    @classmethod
    def setUpClass(cls):
        def fn(pct, i):
            if pct == 0.0:
                return 2320.0          # stale-latch artifact
            if pct < 20.0:
                return 660.0 + 2.0 * math.sin(i)
            return 660.0 + (pct - 20.0) / 80.0 * (2300.0 - 660.0)
        cls.rows = make_rows(fn)
        cls.res = analyze(cls.rows)

    def test_never_stops_with_plateau_baseline_floor(self):
        self.assertFalse(self.res["turns_off"])
        # floor is the plateau baseline (~660), NOT the 2320 spike
        self.assertAlmostEqual(self.res["floor_rpm"], 660.0, delta=5.0)

    def test_zero_flag_raised_for_stale_latch(self):
        self.assertIsNotNone(self.res["zero_flag"])
        self.assertIn("stale-latch", self.res["zero_flag"])

    def test_onset_in_expected_band(self):
        # threshold = 660 + max(10, 0.02*2300=46) = 706 => pct > ~22.2
        self.assertIsNotNone(self.res["onset_pct"])
        self.assertGreater(self.res["onset_pct"], 20.0)
        self.assertLess(self.res["onset_pct"], 26.0)

    def test_no_saturation_ceiling(self):
        self.assertIsNone(self.res["ceiling_pct"])

    def test_linearity_measured(self):
        lin = self.res["linearity"]
        self.assertIsNotNone(lin)
        self.assertGreater(lin["rms_rpm"], 0.0)
        self.assertLessEqual(lin["max_dev_pct_of_span"], 100.0)


class IdealLinearTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = make_rows(lambda pct, i: pct * 20.0)
        cls.res = analyze(cls.rows)

    def test_stop_at_zero_and_immediate_onset(self):
        self.assertTrue(self.res["turns_off"])
        self.assertAlmostEqual(self.res["onset_pct"], STEP, places=6)

    def test_linearity_deviations_vanish(self):
        lin = self.res["linearity"]
        self.assertIsNotNone(lin)
        self.assertLess(abs(lin["max_dev_rpm"]), 1e-6)
        self.assertLess(lin["rms_rpm"], 1e-6)

    def test_no_ceiling(self):
        self.assertIsNone(self.res["ceiling_pct"])
        self.assertIsNone(self.res["zero_flag"])

    def test_ref_line_endpoints_match_onset_and_last_row(self):
        lin = self.res["linearity"]
        x0, y0, x1, y1 = lin["ref_line"]
        self.assertAlmostEqual(x0, self.res["onset_pct"], places=6)
        self.assertAlmostEqual(y0, self.res["onset_rpm"], places=6)
        self.assertAlmostEqual(x1, (N_ROWS - 1) * STEP, places=6)
        self.assertAlmostEqual(y1, (N_ROWS - 1) * STEP * 20.0, places=6)


class SaturatingTailTestCase(unittest.TestCase):
    """Rises linearly to 1800 rpm at 60 %, then holds flat to 100 %."""

    @classmethod
    def setUpClass(cls):
        cls.rows = make_rows(lambda pct, i:
                             min(pct * 30.0, 1800.0))
        cls.res = analyze(cls.rows)

    def test_ceiling_detected_just_past_knee(self):
        # window lag shifts the reported edge up to one window (~8 %) past
        # the true knee at 60 %
        self.assertIsNotNone(self.res["ceiling_pct"])
        self.assertGreater(self.res["ceiling_pct"], 60.0)
        self.assertLess(self.res["ceiling_pct"], 60.0 + 2 * PLATEAU_WINDOW_ROWS * STEP)

    def test_linearity_span_covers_only_the_rising_part(self):
        lin = self.res["linearity"]
        self.assertIsNotNone(lin)
        # the flat tail lies below the onset->ceiling chord only near the
        # knee; deviations must be bounded by the span
        self.assertLessEqual(lin["max_dev_pct_of_span"], 100.0)


class NoisyIdealTestCase(unittest.TestCase):
    """Ideal ramp plus deterministic jitter (amplitude 5 rpm)."""

    @classmethod
    def setUpClass(cls):
        cls.rows = make_rows(lambda pct, i: pct * 20.0 + 5.0 * math.sin(i * 1.7))
        cls.res = analyze(cls.rows)

    def test_jitter_bounded_linearity(self):
        # endpoints carry jitter too, so the chord itself tilts by up to
        # ~one amplitude; bound accordingly (amplitude 5 rpm)
        lin = self.res["linearity"]
        self.assertIsNotNone(lin)
        self.assertLessEqual(abs(lin["max_dev_rpm"]), 11.0)
        self.assertLess(lin["rms_rpm"], 6.0)

    def test_monotonic_still_has_no_ceiling(self):
        self.assertIsNone(self.res["ceiling_pct"])


class FlatFloorNoRiseTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = make_rows(lambda pct, i: 660.0)
        cls.res = analyze(cls.rows)

    def test_floor_without_onset_or_linearity(self):
        self.assertFalse(self.res["turns_off"])
        self.assertAlmostEqual(self.res["floor_rpm"], 660.0, places=6)
        self.assertIsNone(self.res["onset_pct"])
        self.assertIsNone(self.res["linearity"])
        self.assertIsNone(self.res["ceiling_pct"])
        self.assertIsNone(self.res["zero_flag"])


class DegenerateInputTestCase(unittest.TestCase):
    def test_all_zero_series(self):
        res = analyze(make_rows(lambda pct, i: 0.0))
        self.assertTrue(res["turns_off"])
        self.assertIsNone(res["onset_pct"])
        self.assertIsNone(res["linearity"])
        self.assertIsNone(res["ceiling_pct"])
        self.assertIsNone(res["floor_rpm"])
        self.assertIsNone(res["zero_flag"])

    def test_single_nonzero_row(self):
        # Contract: no exception, onset located at the spike, linearity
        # unmeasurable (fewer than three points across the fit span).
        # The ceiling heuristic is out of domain for a one-row impulse
        # (real rows are medians of ~18 samples and cannot spike alone);
        # its value here is intentionally not asserted.
        rows = make_rows(lambda pct, i: 500.0 if i == 30 else 0.0)
        res = analyze(rows)
        self.assertTrue(res["turns_off"])
        self.assertAlmostEqual(res["onset_pct"], 30 * STEP, places=6)
        self.assertIsNone(res["linearity"])

    def test_empty_rows_do_not_raise(self):
        res = analyze([])
        self.assertTrue(res["turns_off"])
        self.assertIsNone(res["onset_pct"])
        self.assertIsNone(res["linearity"])

    def test_four_tuple_rows_accepted(self):
        # settled starts at 100 rpm => floor fan; extra columns ignored
        rows = [(i * STEP, 100.0 + i, 90.0 + i, 110.0 + i)
                for i in range(N_ROWS)]
        res = analyze(rows)
        self.assertFalse(res["turns_off"])
        self.assertAlmostEqual(res["peak_rpm"], 100.0 + N_ROWS - 1, places=6)


class SummaryFormattingTestCase(unittest.TestCase):
    def test_stopping_fan_lines(self):
        res = analyze(make_rows(lambda pct, i:
                                 0.0 if pct < 10.0 else (pct - 10.0) / 90.0 * 2000.0))
        text = format_summary(res, fan_name="Test Fan")
        self.assertIn("Test Fan", text)
        self.assertIn("stops", text)
        self.assertIn("starts turning", text)
        self.assertIn("still increasing at 100", text)

    def test_floor_fan_lines(self):
        res = analyze(make_rows(lambda pct, i: 660.0 + max(0.0, pct - 20.0) * 20.0))
        text = format_summary(res)
        self.assertIn("NEVER STOPS", text)
        self.assertIn("floor", text)
        self.assertIn("begins rising", text)

    def test_unmeasurable_lines(self):
        text = format_summary(analyze(make_rows(lambda pct, i: 0.0)))
        self.assertIn("never turned", text)
        self.assertIn("unmeasurable", text)


if __name__ == "__main__":
    unittest.main()
