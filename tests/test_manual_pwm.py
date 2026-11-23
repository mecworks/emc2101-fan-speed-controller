"""M3 unit tests: manual mode, duty quantization, and PWM output
configuration (shared core).

The PWM frequency solver is exercised against hand-computed expectations
from eq. [5]/[6], including the datasheet's own 30 Hz example region and
tie-break behavior toward the max-resolution path.
"""
import unittest

from emc2101._core import EMC2101
from emc2101._regs import (CFG_DAC, FCFG_CLK_OVR, FCFG_CLK_SEL,
                           FCFG_POLARITY, FCFG_PROG, REG_CONFIG,
                           REG_FAN_CFG, REG_FAN_SETTING, REG_PWM_D,
                           REG_PWM_F)
from fakes import FakeTransport, write_entries


def make_dev(registers=None):
    t = FakeTransport(registers=dict(registers or {}))
    return EMC2101(t), t


def writes_of(t, reg):
    return [val for r, val in write_entries(t.log, reg)]


class ManualModeTestCase(unittest.TestCase):
    def test_manual_true_when_prog_cleared(self):
        dev, _ = make_dev({REG_FAN_CFG: 0x0A})
        self.assertTrue(dev.manual)

    def test_manual_false_when_prog_set(self):
        dev, _ = make_dev({REG_FAN_CFG: 0x2A})
        self.assertFalse(dev.manual)

    def test_setter_flips_only_prog_bit(self):
        dev, t = make_dev({REG_FAN_CFG: 0x2A})
        dev.manual = True
        self.assertEqual(writes_of(t, REG_FAN_CFG)[-1], 0x0A)
        dev.manual = False
        self.assertEqual(writes_of(t, REG_FAN_CFG)[-1], 0x2A)


class DutyTestCase(unittest.TestCase):
    def test_set_duty_pct_quantizes_through_current_grid(self):
        # PWM_F=23 -> grid 100/46 %; 50% -> S=23
        dev, t = make_dev({REG_PWM_F: 0x17})
        dev.set_duty_pct(50.0)
        self.assertEqual(writes_of(t, REG_FAN_SETTING), [23])

    def test_set_duty_pct_clamps_at_full_scale(self):
        dev, t = make_dev({REG_PWM_F: 0x17})
        dev.set_duty_pct(100.0)
        self.assertEqual(writes_of(t, REG_FAN_SETTING), [46])

    def test_set_duty_pct_zero(self):
        dev, t = make_dev({REG_PWM_F: 0x17})
        dev.set_duty_pct(0.0)
        self.assertEqual(writes_of(t, REG_FAN_SETTING), [0])

    def test_set_duty_pct_range_validation(self):
        dev, _ = make_dev({REG_PWM_F: 0x17})
        with self.assertRaises(ValueError):
            dev.set_duty_pct(-1.0)
        with self.assertRaises(ValueError):
            dev.set_duty_pct(101.0)

    def test_set_duty_pct_rejects_degenerate_pwm_f(self):
        dev, _ = make_dev({REG_PWM_F: 0x00})
        with self.assertRaises(ValueError):
            dev.set_duty_pct(50.0)

    def test_duty_cmd_raw_roundtrip_and_range(self):
        dev, t = make_dev({REG_FAN_SETTING: 0x3F})
        self.assertEqual(dev.duty_cmd_raw, 0x3F)
        dev.duty_cmd_raw = 0x21
        self.assertEqual(writes_of(t, REG_FAN_SETTING), [0x21])
        with self.assertRaises(ValueError):
            dev.duty_cmd_raw = 64
        with self.assertRaises(ValueError):
            dev.duty_cmd_raw = -1


class PwmFreqGetterTestCase(unittest.TestCase):
    def test_360khz_base_no_override(self):
        dev, _ = make_dev({REG_FAN_CFG: FCFG_PROG, REG_PWM_F: 0x17})
        self.assertAlmostEqual(dev.pwm_freq_hz, 360000.0 / 46.0, places=6)

    def test_360khz_base_with_override(self):
        # Datasheet example region: PWM_F=31, PWM_D=0xC1 -> ~30.08 Hz
        dev, _ = make_dev({REG_FAN_CFG: FCFG_PROG | FCFG_CLK_OVR,
                           REG_PWM_F: 0x1F, REG_PWM_D: 0xC1})
        self.assertAlmostEqual(dev.pwm_freq_hz, 360000.0 / (62 * 193),
                               places=6)

    def test_1p4khz_base_ignores_override(self):
        dev, _ = make_dev({REG_FAN_CFG: FCFG_PROG | FCFG_CLK_SEL
                           | FCFG_CLK_OVR, REG_PWM_F: 0x01,
                           REG_PWM_D: 0x05})
        self.assertAlmostEqual(dev.pwm_freq_hz, 700.0, places=6)


class PwmFreqSetterTestCase(unittest.TestCase):
    def test_solve_25khz_picks_pwm_f_seven(self):
        dev, t = make_dev({REG_FAN_CFG: FCFG_PROG, REG_PWM_F: 0x17,
                           REG_PWM_D: 0x01})
        dev.pwm_freq_hz = 25000.0
        self.assertEqual(writes_of(t, REG_PWM_F)[-1], 7)
        self.assertNotIn(REG_PWM_D,
                         [r for r, v in write_entries(t.log)])
        self.assertAlmostEqual(dev.pwm_freq_hz, 360000.0 / 14.0, places=6)

    def test_solve_30hz_exact_max_resolution_path(self):
        # Exact solutions at 2*f*d = 12000: (f=24,d=250), (f=25,d=240),
        # (f=30,d=200); tie-break prefers the higher PWM_F.
        dev, t = make_dev({REG_FAN_CFG: FCFG_PROG, REG_PWM_F: 0x17,
                           REG_PWM_D: 0x01})
        dev.pwm_freq_hz = 30.0
        self.assertEqual(writes_of(t, REG_PWM_F)[-1], 30)
        self.assertEqual(writes_of(t, REG_PWM_D)[-1], 200)
        cfg = writes_of(t, REG_FAN_CFG)[-1]
        self.assertTrue(cfg & FCFG_CLK_OVR)
        self.assertFalse(cfg & FCFG_CLK_SEL)
        self.assertAlmostEqual(dev.pwm_freq_hz, 30.0, places=9)

    def test_solver_never_writes_zero_pwm_f_or_divider(self):
        dev, t = make_dev({REG_FAN_CFG: FCFG_PROG, REG_PWM_F: 0x17,
                           REG_PWM_D: 0x01})
        for target in (1.0, 22.8, 100.0, 1000.0, 10000.0, 180000.0):
            dev.pwm_freq_hz = target
            pf = writes_of(t, REG_PWM_F)[-1]
            self.assertTrue(1 <= pf <= 31, "bad pwm_f for %r" % target)
            if writes_of(t, REG_PWM_D):
                self.assertTrue(1 <= writes_of(t, REG_PWM_D)[-1] <= 255)

    def test_top_of_range_is_180khz(self):
        dev, t = make_dev({REG_FAN_CFG: FCFG_PROG, REG_PWM_F: 0x17,
                           REG_PWM_D: 0x01})
        dev.pwm_freq_hz = 180000.0
        self.assertAlmostEqual(dev.pwm_freq_hz, 180000.0, places=6)

    def test_bottom_of_range_near_22p8hz(self):
        dev, t = make_dev({REG_FAN_CFG: FCFG_PROG, REG_PWM_F: 0x17,
                           REG_PWM_D: 0x01})
        dev.pwm_freq_hz = 22.8
        self.assertGreater(dev.pwm_freq_hz, 22.0)
        self.assertLessEqual(dev.pwm_freq_hz, 23.5)

    def test_invalid_target_rejected(self):
        dev, _ = make_dev()
        with self.assertRaises(ValueError):
            dev.pwm_freq_hz = 0.0
        with self.assertRaises(ValueError):
            dev.pwm_freq_hz = -5.0


class OutputConfigBitsTestCase(unittest.TestCase):
    def test_fan_output_inverted_roundtrip(self):
        dev, t = make_dev({REG_FAN_CFG: 0x20})
        self.assertFalse(dev.fan_output_inverted)
        dev.fan_output_inverted = True
        self.assertEqual(writes_of(t, REG_FAN_CFG)[-1],
                         FCFG_PROG | FCFG_POLARITY)
        self.assertTrue(dev.fan_output_inverted)

    def test_dac_enabled_roundtrip(self):
        dev, t = make_dev({REG_CONFIG: 0x00})
        self.assertFalse(dev.dac_enabled)
        dev.dac_enabled = True
        self.assertEqual(writes_of(t, REG_CONFIG)[-1], CFG_DAC)
        self.assertTrue(dev.dac_enabled)

    def test_pwm_clk_sel_roundtrip(self):
        dev, t = make_dev({REG_FAN_CFG: 0x20})
        self.assertFalse(dev.pwm_clk_sel)
        dev.pwm_clk_sel = True
        self.assertEqual(writes_of(t, REG_FAN_CFG)[-1],
                         FCFG_PROG | FCFG_CLK_SEL)

    def test_pwm_div_roundtrip_and_range(self):
        dev, t = make_dev({REG_PWM_D: 0x01})
        self.assertEqual(dev.pwm_div, 1)
        dev.pwm_div = 0xC1
        self.assertEqual(writes_of(t, REG_PWM_D), [0xC1])
        with self.assertRaises(ValueError):
            dev.pwm_div = 0
        with self.assertRaises(ValueError):
            dev.pwm_div = 256


if __name__ == "__main__":
    unittest.main()
