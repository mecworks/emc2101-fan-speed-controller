"""M3 unit tests: calibration, scratchpad, power modes, conversion
control, presets, and raw-tier register access (shared core).
"""
import unittest

from emc2101._core import (ALERT_MODE_INTERRUPT, EMC2101, FILTER_LEVEL_1,
                           FILTER_LEVEL_2, FILTER_OFF)
from emc2101._regs import (CFG_ALT_TCH, CFG_DIS_TO, CFG_FAN_STANDBY,
                           CFG_QUEUE, CFG_STANDBY, REG_BETA, REG_CONFIG,
                           REG_CONV_RATE, REG_FAN_CFG, REG_FILTER,
                           REG_IDEALITY, REG_INT_LIMIT, REG_ONE_SHOT,
                           REG_PWM_D, REG_PWM_F, REG_SCRATCHPAD_1,
                           REG_SCRATCHPAD_2, REG_SPINUP, REG_STATUS)
from emc2101._tables import IDEALITY_FACTORS
from fakes import FakeTransport, write_entries


def make_dev(registers=None):
    t = FakeTransport(registers=dict(registers or {}))
    return EMC2101(t), t


class IdealityTestCase(unittest.TestCase):
    def test_index_roundtrip(self):
        dev, t = make_dev({REG_IDEALITY: 0x12})
        self.assertEqual(dev.ideality_factor_index, 0x12)
        dev.ideality_factor_index = 0x08
        self.assertEqual(t.registers[REG_IDEALITY], 0x08)

    def test_index_table_membership_enforced(self):
        dev, _ = make_dev()
        with self.assertRaises(ValueError):
            dev.ideality_factor_index = 0x07      # below table start
        with self.assertRaises(ValueError):
            dev.ideality_factor_index = 0x38      # above table end

    def test_factor_decode(self):
        dev, _ = make_dev({REG_IDEALITY: 0x12})
        self.assertAlmostEqual(dev.ideality_factor, 1.0080, places=9)

    def test_set_nearest_match(self):
        dev, t = make_dev({REG_IDEALITY: 0x12})
        achieved = dev.set_ideality_factor(1.0)
        # nearest table entry to 1.0 is 1.0001 (index 4 -> setting 0x0C)
        self.assertAlmostEqual(achieved, 1.0001, places=9)
        self.assertEqual(t.registers[REG_IDEALITY], 0x0C)
        self.assertIn(achieved, IDEALITY_FACTORS)


class BetaTestCase(unittest.TestCase):
    def test_auto_detect_roundtrip_preserves_field(self):
        dev, t = make_dev({REG_BETA: 0x0B})       # autodetect on, BETA=3
        self.assertTrue(dev.beta_auto_detect)
        dev.beta_auto_detect = False
        self.assertEqual(t.registers[REG_BETA], 0x03)   # field kept
        self.assertFalse(dev.beta_auto_detect)

    def test_beta_index_roundtrip_and_range(self):
        dev, t = make_dev({REG_BETA: 0x03})
        self.assertEqual(dev.beta_index, 3)
        dev.beta_index = 5
        self.assertEqual(t.registers[REG_BETA], 0x05)
        with self.assertRaises(ValueError):
            dev.beta_index = 8


class ScratchpadTestCase(unittest.TestCase):
    def test_get_both_indices(self):
        dev, t = make_dev({REG_SCRATCHPAD_1: 0x11, REG_SCRATCHPAD_2: 0x22})
        self.assertEqual(dev.scratchpad_get(0), 0x11)
        self.assertEqual(dev.scratchpad_get(1), 0x22)
        reads = [reg for kind, reg in t.log if kind == "read"]
        self.assertEqual(reads, [REG_SCRATCHPAD_1, REG_SCRATCHPAD_2])

    def test_set_and_validation(self):
        dev, t = make_dev()
        dev.scratchpad_set(1, 0xAB)
        self.assertEqual(t.registers[REG_SCRATCHPAD_2], 0xAB)
        with self.assertRaises(ValueError):
            dev.scratchpad_get(2)
        with self.assertRaises(ValueError):
            dev.scratchpad_set(0, 256)


class PowerModeTestCase(unittest.TestCase):
    def test_standby_roundtrip(self):
        dev, t = make_dev({REG_CONFIG: 0x00})
        self.assertFalse(dev.standby)
        dev.standby = True
        self.assertEqual(t.registers[REG_CONFIG], CFG_STANDBY)

    def test_fan_standby_roundtrip(self):
        dev, t = make_dev({REG_CONFIG: 0x00})
        self.assertFalse(dev.fan_standby)
        dev.fan_standby = True
        self.assertEqual(t.registers[REG_CONFIG], CFG_FAN_STANDBY)

    def test_one_shot_requires_standby(self):
        dev, t = make_dev({REG_CONFIG: CFG_STANDBY})
        dev.one_shot()
        self.assertIn(("write", REG_ONE_SHOT, 0x00), t.log)

    def test_one_shot_rejected_outside_standby(self):
        dev, t = make_dev({REG_CONFIG: 0x00})
        with self.assertRaises(ValueError):
            dev.one_shot()
        self.assertEqual([e for e in t.log if e[0] == "write"], [])


class ConversionControlTestCase(unittest.TestCase):
    def test_conversion_rate_decode(self):
        dev, _ = make_dev({REG_CONV_RATE: 0x08})
        self.assertEqual(dev.conversion_rate, 16.0)

    def test_conversion_rate_set_nearest_slower_on_tie(self):
        dev, t = make_dev({REG_CONV_RATE: 0x08})
        dev.conversion_rate = 1.5     # equidistant from 1.0 and 2.0
        self.assertEqual(t.registers[REG_CONV_RATE], 0x04)
        self.assertEqual(dev.conversion_rate, 1.0)

    def test_averaging_filter_decodes_duplicated_encoding(self):
        for raw, want in ((0x00, FILTER_OFF), (0x02, FILTER_LEVEL_1),
                          (0x04, FILTER_LEVEL_1), (0x06, FILTER_LEVEL_2)):
            dev, _ = make_dev({REG_FILTER: raw})
            self.assertEqual(dev.averaging_filter, want)

    def test_averaging_filter_setter_canonical_encoding(self):
        dev, t = make_dev({REG_FILTER: 0x04})
        dev.averaging_filter = FILTER_LEVEL_1
        self.assertEqual(t.registers[REG_FILTER], 0x02)
        with self.assertRaises(ValueError):
            dev.averaging_filter = 3

    def test_dis_to_enabled_roundtrip(self):
        dev, t = make_dev({REG_CONFIG: 0x00})
        self.assertFalse(dev.dis_to_enabled)
        dev.dis_to_enabled = True
        self.assertEqual(t.registers[REG_CONFIG], CFG_DIS_TO)

    def test_fault_queue_enabled_roundtrip(self):
        dev, t = make_dev({REG_CONFIG: 0x00})
        self.assertFalse(dev.fault_queue_enabled)
        dev.fault_queue_enabled = True
        self.assertEqual(t.registers[REG_CONFIG], CFG_QUEUE)


class Configure4WireFanTestCase(unittest.TestCase):
    def test_sets_alt_tch_pwm_and_keeps_sane_spinup(self):
        dev, t = make_dev({REG_CONFIG: 0x00, REG_FAN_CFG: 0x20,
                           REG_PWM_F: 0x17, REG_PWM_D: 0x01,
                           REG_SPINUP: 0x3F})
        dev.configure_4wire_fan(25000.0)
        self.assertEqual(t.registers[REG_CONFIG], CFG_ALT_TCH)
        self.assertEqual(t.registers[REG_PWM_F], 7)      # solved grid
        self.assertEqual(t.registers[REG_SPINUP], 0x3F)  # already sane

    def test_repairs_drifted_spinup(self):
        dev, t = make_dev({REG_CONFIG: 0x00, REG_FAN_CFG: 0x20,
                           REG_PWM_F: 0x17, REG_PWM_D: 0x01,
                           REG_SPINUP: 0x00})
        dev.configure_4wire_fan()
        self.assertEqual(t.registers[REG_SPINUP], 0x3F)
        self.assertTrue(dev.tach_input_enabled)


class RawTierTestCase(unittest.TestCase):
    def test_read_reg_single_byte(self):
        dev, _ = make_dev({REG_STATUS: 0x1B})
        self.assertEqual(dev.read_reg(REG_STATUS), 0x1B)

    def test_read_reg_multi_byte_sequential_addresses(self):
        dev, t = make_dev({REG_CONFIG: 0x01, REG_CONV_RATE: 0x02,
                           REG_INT_LIMIT: 0x03})
        vals = dev.read_reg(REG_CONFIG, 3)
        self.assertEqual(vals, (0x01, 0x02, 0x03))
        reads = [reg for kind, reg in t.log if kind == "read"]
        self.assertEqual(reads, [0x03, 0x04, 0x05])

    def test_read_reg_validation(self):
        dev, _ = make_dev()
        with self.assertRaises(ValueError):
            dev.read_reg(0x100)
        with self.assertRaises(ValueError):
            dev.read_reg(REG_CONFIG, 0)

    def test_write_reg_sequential_bytes(self):
        dev, t = make_dev()
        dev.write_reg(0x07, b"\xaa\xbb")
        self.assertEqual(write_entries(t.log), [(0x07, 0xAA), (0x08, 0xBB)])

    def test_write_reg_accepts_list_payload(self):
        dev, t = make_dev()
        dev.write_reg(0x07, [0x11, 0x22])
        self.assertEqual(t.registers[0x07], 0x11)
        self.assertEqual(t.registers[0x08], 0x22)


class MiscIdentityTestCase(unittest.TestCase):
    def test_part_info_triple(self):
        dev, _ = make_dev()
        self.assertEqual(dev.part_info, (0x16, 0x5D, 0x01))

    def test_repr_shows_address(self):
        dev, _ = make_dev()
        self.assertEqual(repr(dev), "<emc2101.EMC2101 addr=0x4c>")

    def test_filter_enum_values_are_ordered_levels(self):
        self.assertEqual((FILTER_OFF, FILTER_LEVEL_1, FILTER_LEVEL_2),
                         (0, 1, 2))
        self.assertEqual(ALERT_MODE_INTERRUPT, 0)


if __name__ == "__main__":
    unittest.main()
