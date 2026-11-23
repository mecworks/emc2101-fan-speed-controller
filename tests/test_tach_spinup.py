"""M3 unit tests: tachometer/RPM and spin-up configuration (shared core).

Covers the LSB-first TACH interlock order, RPM scaling by pulses/rev,
the FFFFh sentinel, the min-RPM convenience pair, ALT_TCH switching,
TACH_M, and the composite spin-up fields.
"""
import unittest

from emc2101._core import EMC2101
from emc2101._regs import (CFG_ALT_TCH, FCFG_PROG, FCFG_TACH_M_MASK,
                           REG_CONFIG, REG_FAN_CFG, REG_SPINUP,
                           REG_TACH_HI, REG_TACH_LIMIT_HI,
                           REG_TACH_LIMIT_LO, REG_TACH_LO, SU_DRIVE_100,
                           SU_FAST_TACH, SU_SPIN_TIME_MASK)
from fakes import FakeTransport, write_entries


def make_dev(registers=None):
    t = FakeTransport(registers=dict(registers or {}))
    return EMC2101(t), t


class RpmTestCase(unittest.TestCase):
    def test_normal_count(self):
        # count 8000 -> 5,400,000/8000 = 675.0 RPM
        dev, _ = make_dev({REG_TACH_LO: 0x40, REG_TACH_HI: 0x1F})
        self.assertEqual(dev.rpm(), 675.0)

    def test_reads_interlock_order_lsb_first(self):
        dev, t = make_dev({REG_TACH_LO: 0x40, REG_TACH_HI: 0x1F})
        dev.rpm()
        reads = [reg for kind, reg in t.log if kind == "read"]
        self.assertLess(reads.index(REG_TACH_LO), reads.index(REG_TACH_HI))

    def test_pulses_per_rev_scaling(self):
        dev, _ = make_dev({REG_TACH_LO: 0x40, REG_TACH_HI: 0x1F})
        self.assertEqual(dev.rpm(pulses_per_rev=4), 337.5)

    def test_sentinel_reports_zero(self):
        dev, _ = make_dev({REG_TACH_LO: 0xFF, REG_TACH_HI: 0xFF})
        self.assertEqual(dev.rpm(), 0.0)

    def test_zero_count_reports_zero(self):
        dev, _ = make_dev({REG_TACH_LO: 0x00, REG_TACH_HI: 0x00})
        self.assertEqual(dev.rpm(), 0.0)

    def test_pulses_per_rev_validation(self):
        dev, _ = make_dev()
        with self.assertRaises(ValueError):
            dev.rpm(pulses_per_rev=0)


class TachThresholdTestCase(unittest.TestCase):
    def test_get_combines_16_bits(self):
        dev, _ = make_dev({REG_TACH_LIMIT_LO: 0x34, REG_TACH_LIMIT_HI: 0x12})
        self.assertEqual(dev.tach_threshold, 0x1234)

    def test_set_writes_lo_then_hi(self):
        dev, t = make_dev()
        dev.tach_threshold = 0x1234
        self.assertEqual(write_entries(t.log),
                         [(REG_TACH_LIMIT_LO, 0x34),
                          (REG_TACH_LIMIT_HI, 0x12)])

    def test_set_range_validation(self):
        dev, _ = make_dev()
        with self.assertRaises(ValueError):
            dev.tach_threshold = 0x10000
        with self.assertRaises(ValueError):
            dev.tach_threshold = -1


class MinRpmTestCase(unittest.TestCase):
    def test_get_from_count(self):
        dev, _ = make_dev({REG_TACH_LIMIT_LO: 0x40, REG_TACH_LIMIT_HI: 0x1F})
        self.assertEqual(dev.min_rpm, 675.0)

    def test_get_disabled_reports_zero(self):
        dev, _ = make_dev({REG_TACH_LIMIT_LO: 0xFF, REG_TACH_LIMIT_HI: 0xFF})
        self.assertEqual(dev.min_rpm, 0.0)

    def test_set_converts_to_count(self):
        dev, t = make_dev()
        dev.min_rpm = 675.0
        lo = t.registers[REG_TACH_LIMIT_LO]
        hi = t.registers[REG_TACH_LIMIT_HI]
        self.assertEqual((hi << 8) | lo, 8000)

    def test_set_below_detectable_range_rejected(self):
        dev, _ = make_dev()
        with self.assertRaises(ValueError):
            dev.min_rpm = 0.5     # count would exceed 65535

    def test_set_nonpositive_rejected(self):
        dev, _ = make_dev()
        with self.assertRaises(ValueError):
            dev.min_rpm = 0


class TachInputAndModeTestCase(unittest.TestCase):
    def test_tach_input_enabled_roundtrip(self):
        dev, t = make_dev({REG_CONFIG: 0x00})
        self.assertFalse(dev.tach_input_enabled)
        dev.tach_input_enabled = True
        self.assertEqual(t.registers[REG_CONFIG], CFG_ALT_TCH)
        self.assertTrue(dev.tach_input_enabled)

    def test_tach_mode_roundtrip_and_range(self):
        dev, t = make_dev({REG_FAN_CFG: FCFG_PROG})
        self.assertEqual(dev.tach_mode, 0)
        dev.tach_mode = 1
        self.assertEqual(t.registers[REG_FAN_CFG], FCFG_PROG | 0x01)
        self.assertEqual(dev.tach_mode, 1)
        with self.assertRaises(ValueError):
            dev.tach_mode = 4


class SpinUpTestCase(unittest.TestCase):
    def test_enabled_composite(self):
        dev, _ = make_dev({REG_SPINUP: 0x3F})
        self.assertTrue(dev.spin_up_enabled)
        dev2, _ = make_dev({REG_SPINUP: 0x38})      # time field 0
        self.assertFalse(dev2.spin_up_enabled)

    def test_enable_from_bypass_restores_por_duration(self):
        dev, t = make_dev({REG_SPINUP: 0x38})
        dev.spin_up_enabled = True
        self.assertEqual(t.registers[REG_SPINUP] & SU_SPIN_TIME_MASK, 0x07)

    def test_disable_clears_time_field_only(self):
        dev, t = make_dev({REG_SPINUP: 0x3F})
        dev.spin_up_enabled = False
        self.assertEqual(t.registers[REG_SPINUP], 0x38)

    def test_drive_percent_mapping(self):
        for reg_val, pct in ((0x00, 0), (0x08, 50), (0x10, 75), (0x18, 100)):
            dev, _ = make_dev({REG_SPINUP: reg_val})
            self.assertEqual(dev.spin_up_drive, pct)

    def test_drive_set_and_validation(self):
        dev, t = make_dev({REG_SPINUP: 0x3F})
        dev.spin_up_drive = 50
        self.assertEqual(t.registers[REG_SPINUP],
                         SU_FAST_TACH | 0x08 | 0x07)
        with self.assertRaises(ValueError):
            dev.spin_up_drive = 60

    def test_time_decode_including_bypass(self):
        cases = ((0x00, None), (0x01, 0.05), (0x04, 0.4), (0x07, 3.2))
        for enc, want in cases:
            dev, _ = make_dev({REG_SPINUP: enc})
            self.assertEqual(dev.spin_up_time_s, want)

    def test_time_set_valid_values(self):
        dev, t = make_dev({REG_SPINUP: 0x3F})
        dev.spin_up_time_s = 0.8
        self.assertEqual(t.registers[REG_SPINUP] & SU_SPIN_TIME_MASK, 0x05)
        dev.spin_up_time_s = None
        self.assertEqual(t.registers[REG_SPINUP] & SU_SPIN_TIME_MASK, 0x00)

    def test_time_set_invalid_value(self):
        dev, _ = make_dev({REG_SPINUP: 0x3F})
        with self.assertRaises(ValueError):
            dev.spin_up_time_s = 1.0

    def test_fast_tach_roundtrip(self):
        dev, t = make_dev({REG_SPINUP: 0x3F})
        self.assertTrue(dev.spin_up_fast_tach)
        dev.spin_up_fast_tach = False
        self.assertEqual(t.registers[REG_SPINUP], 0x1F)
        self.assertFalse(dev.spin_up_fast_tach)


if __name__ == "__main__":
    unittest.main()
