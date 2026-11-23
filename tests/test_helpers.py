"""Unit tests for the fixed-point helpers (emc2101._regs) and the pure
data tables (emc2101._tables). All values are pinned against datasheet
Rev 2.54; see research/emc2101-register-map.md for citations.
"""
import unittest

from emc2101._regs import (BASE_CLOCK_1P4K_HZ, BASE_CLOCK_360K_HZ,
                           EXT_TEMP_STEP_C, INT_TEMP_STEP_C, LUT_ENTRIES,
                           LUT_PAIR_STRIDE, PWM_F_MAX, RPM_DIVISOR,
                           SENTINEL_OPEN_RAW, SENTINEL_SHORT_RAW,
                           TACH_SENTINEL, TEMP_RANGE_MAX_C, TEMP_RANGE_MIN_C,
                           count_from_rpm, duty_pct_to_setting,
                           ext_raw_to_temp, ext_temp_to_raw, int_raw_to_temp,
                           int_temp_to_raw, rpm_from_count,
                           setting_to_duty_pct)
from emc2101._tables import (BETA_DISABLED_ENCODING, BETA_MINIMUM_VALUES,
                             CONV_RATE_DEFAULT_INDEX, CONV_RATES_PER_S,
                             IDEALITY_FACTORS, IDEALITY_SETTINGS_MAX,
                             IDEALITY_SETTINGS_MIN, POR_DEFAULTS,
                             SPINUP_TIMES_S, TCONV_EXTERNAL_MS,
                             TCONV_INTERNAL_MS, conv_rate_encode,
                             ideality_factor, spinup_time)


class ExtTempFixedPointTestCase(unittest.TestCase):
    def test_round_trip_positive(self):
        for temp in (0.0, 25.0, 70.0, 127.875):
            with self.subTest(temp=temp):
                self.assertEqual(ext_raw_to_temp(ext_temp_to_raw(temp)),
                                 temp)

    def test_round_trip_negative(self):
        for temp in (-1.0, -10.0, -64.0):
            with self.subTest(temp=temp):
                self.assertEqual(ext_raw_to_temp(ext_temp_to_raw(temp)),
                                 temp)

    def test_quarter_degree_steps(self):
        self.assertEqual(ext_temp_to_raw(0.125), 1)
        self.assertEqual(ext_raw_to_temp(1), EXT_TEMP_STEP_C)

    def test_boundaries(self):
        self.assertEqual(ext_temp_to_raw(-64.0), 0x600)   # -512 steps
        self.assertEqual(ext_temp_to_raw(127.875), 0x3FF)

    def test_out_of_range_raises(self):
        for bad in (-64.125, -65.0, 128.0, 200.0):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    ext_temp_to_raw(bad)

    def test_fault_sentinels_decode(self):
        self.assertEqual(ext_raw_to_temp(SENTINEL_OPEN_RAW), 127.0)
        self.assertEqual(ext_raw_to_temp(SENTINEL_SHORT_RAW), 127.875)

    def test_step_and_range_constants(self):
        self.assertEqual(EXT_TEMP_STEP_C, 0.125)
        self.assertEqual(INT_TEMP_STEP_C, 1.0)
        self.assertEqual(TEMP_RANGE_MIN_C, -64.0)
        self.assertEqual(TEMP_RANGE_MAX_C, 127.875)


class IntTempFixedPointTestCase(unittest.TestCase):
    def test_round_trip(self):
        for temp in (-128.0, -5.0, 0.0, 22.0, 127.0):
            with self.subTest(temp=temp):
                self.assertEqual(int_raw_to_temp(int_temp_to_raw(temp)),
                                 temp)

    def test_two_complement_encoding(self):
        self.assertEqual(int_temp_to_raw(-1), 0xFF)
        self.assertEqual(int_raw_to_temp(0xFF), -1.0)

    def test_out_of_range_raises(self):
        for bad in (-129.0, 128.0):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    int_temp_to_raw(bad)


class DutyQuantizationTestCase(unittest.TestCase):
    def test_half_scale_at_default_pwm_f(self):
        # eq.[6]: S = pct * 2*PWM_F / 100 ; default PWM_F = 0x17 = 23
        self.assertEqual(duty_pct_to_setting(50.0, 23), 23)
        self.assertEqual(setting_to_duty_pct(23, 23), 50.0)

    def test_full_scale_clamps(self):
        self.assertEqual(duty_pct_to_setting(100.0, 23), 46)
        self.assertEqual(setting_to_duty_pct(46, 23), 100.0)
        # settings above 2*PWM_F report 100 % (hardware clamps them)
        self.assertEqual(setting_to_duty_pct(63, 23), 100.0)

    def test_max_resolution_grid(self):
        self.assertEqual(duty_pct_to_setting(100.0, PWM_F_MAX), 62)
        self.assertAlmostEqual(setting_to_duty_pct(1, PWM_F_MAX),
                               100.0 / 62.0, places=9)

    def test_bad_inputs_raise(self):
        with self.assertRaises(ValueError):
            duty_pct_to_setting(-1.0, 23)
        with self.assertRaises(ValueError):
            duty_pct_to_setting(100.1, 23)
        with self.assertRaises(ValueError):
            duty_pct_to_setting(50.0, 0)
        with self.assertRaises(ValueError):
            duty_pct_to_setting(50.0, PWM_F_MAX + 1)
        with self.assertRaises(ValueError):
            setting_to_duty_pct(-1, 23)


class RpmConversionTestCase(unittest.TestCase):
    def test_live_bench_value(self):
        # M1 round-2 measurement: count 7955 at 0 % drive
        self.assertAlmostEqual(rpm_from_count(7955), 5400000.0 / 7955,
                               places=6)

    def test_sentinel_and_zero_return_zero(self):
        self.assertEqual(rpm_from_count(TACH_SENTINEL), 0.0)
        self.assertEqual(rpm_from_count(0xFFFF), 0.0)
        self.assertEqual(rpm_from_count(0), 0.0)

    def test_inverse_pair(self):
        self.assertEqual(count_from_rpm(660), 8182)   # round(5400000/660)
        self.assertEqual(count_from_rpm(0), 0)
        self.assertEqual(count_from_rpm(-5), 0)

    def test_divisor_constant(self):
        self.assertEqual(RPM_DIVISOR, 5400000)


class IdealityTableTestCase(unittest.TestCase):
    def test_table_bounds(self):
        self.assertEqual(len(IDEALITY_FACTORS), 48)
        self.assertEqual(IDEALITY_SETTINGS_MIN, 0x08)
        self.assertEqual(IDEALITY_SETTINGS_MAX, 0x37)

    def test_endpoints(self):
        self.assertEqual(ideality_factor(0x08), 0.9949)
        self.assertEqual(ideality_factor(0x37), 1.0566)

    def test_por_default_index(self):
        # POR ideality index 0x12 => 1.0080 (datasheet Table 6.13)
        self.assertEqual(ideality_factor(0x12), 1.0080)

    def test_monotonic_non_decreasing(self):
        for a, b in zip(IDEALITY_FACTORS, IDEALITY_FACTORS[1:]):
            self.assertLessEqual(a, b)

    def test_undefined_settings_raise(self):
        for bad in (0x00, 0x07, 0x38, 0x3F):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    ideality_factor(bad)


class ConvRateTableTestCase(unittest.TestCase):
    def test_table_shape(self):
        self.assertEqual(len(CONV_RATES_PER_S), 16)
        self.assertEqual(CONV_RATE_DEFAULT_INDEX, 8)
        self.assertEqual(CONV_RATES_PER_S[8], 16.0)
        # indices 10..15 all map to 32/s (Table 6.6)
        for i in range(10, 16):
            self.assertEqual(CONV_RATES_PER_S[i], 32.0)

    def test_exact_matches(self):
        self.assertEqual(conv_rate_encode(16.0), 8)
        self.assertEqual(conv_rate_encode(32.0), 9)
        self.assertEqual(conv_rate_encode(0.0625), 0)

    def test_nearest_with_slower_tie_break(self):
        self.assertEqual(conv_rate_encode(10.0), 7)   # 8/s beats 16/s
        self.assertEqual(conv_rate_encode(12.0), 7)   # tie 8 vs 16 -> 8

    def test_non_positive_raises(self):
        for bad in (0.0, -1.0):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    conv_rate_encode(bad)

    def test_conversion_times(self):
        self.assertEqual(TCONV_INTERNAL_MS, 3)
        self.assertEqual(TCONV_EXTERNAL_MS, 21)


class SpinupTableTestCase(unittest.TestCase):
    def test_encodings(self):
        self.assertIsNone(spinup_time(0))       # bypass
        self.assertEqual(spinup_time(1), 0.05)
        self.assertEqual(spinup_time(7), 3.2)
        self.assertEqual(len(SPINUP_TIMES_S), 8)

    def test_bad_encodings_raise(self):
        for bad in (-1, 8):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    spinup_time(bad)


class BetaTableTestCase(unittest.TestCase):
    def test_values(self):
        self.assertEqual(len(BETA_MINIMUM_VALUES), 7)
        self.assertEqual(BETA_MINIMUM_VALUES[0], 0.11)
        self.assertEqual(BETA_MINIMUM_VALUES[-1], 2.33)
        self.assertEqual(BETA_DISABLED_ENCODING, 0x07)


class PorDefaultsTestCase(unittest.TestCase):
    """Spot-checks the factory power-on defaults table against the
    datasheet register tables (plain EMC2101)."""

    def test_key_defaults(self):
        from emc2101._regs import (REG_ALERT_MASK, REG_BETA, REG_CONFIG,
                                   REG_CONV_RATE, REG_EXT_FORCE,
                                   REG_EXT_HIGH_LSB, REG_EXT_HIGH_MSB,
                                   REG_EXT_LOW_LSB, REG_EXT_LOW_MSB,
                                   REG_FAN_CFG, REG_FAN_SETTING,
                                   REG_FILTER, REG_IDEALITY, REG_INT_LIMIT,
                                   REG_LUT_HYST, REG_PWM_D, REG_PWM_F,
                                   REG_SPINUP, REG_TACH_LIMIT_HI,
                                   REG_TACH_LIMIT_LO, REG_TCRIT,
                                   REG_TCRIT_HYST)
        expected = {
            REG_CONFIG: 0x00,
            REG_CONV_RATE: 0x08,
            REG_INT_LIMIT: 0x46,
            REG_EXT_HIGH_MSB: 0x46,
            REG_EXT_LOW_MSB: 0x00,
            REG_EXT_FORCE: 0x00,
            REG_EXT_HIGH_LSB: 0x00,
            REG_EXT_LOW_LSB: 0x00,
            REG_ALERT_MASK: 0xA4,
            REG_IDEALITY: 0x12,
            REG_BETA: 0x08,
            REG_TCRIT: 0x55,
            REG_TCRIT_HYST: 0x0A,
            REG_TACH_LIMIT_LO: 0xFF,
            REG_TACH_LIMIT_HI: 0xFF,
            REG_FAN_CFG: 0x20,
            REG_SPINUP: 0x3F,
            REG_FAN_SETTING: 0x00,
            REG_PWM_F: 0x17,
            REG_PWM_D: 0x01,
            REG_LUT_HYST: 0x04,
            REG_FILTER: 0x00,
        }
        for reg, want in expected.items():
            with self.subTest(reg=hex(reg)):
                self.assertEqual(POR_DEFAULTS[reg], want)

    def test_lut_por_state(self):
        from emc2101._tables import LUT_POR_S, LUT_POR_T
        self.assertEqual(LUT_POR_T, 0x7F)
        self.assertEqual(LUT_POR_S, 0x3F)

    def test_clock_constants(self):
        self.assertEqual(BASE_CLOCK_360K_HZ, 360000)
        self.assertEqual(BASE_CLOCK_1P4K_HZ, 1400)
        self.assertEqual(LUT_ENTRIES, 8)
        self.assertEqual(LUT_PAIR_STRIDE, 2)


if __name__ == "__main__":
    unittest.main()
