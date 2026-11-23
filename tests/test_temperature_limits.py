"""M3 unit tests: temperatures and setpoints (shared core).

Covers the interlock-ordered external temperature read, the diode-fault
sentinel typing (D13), the internal/external limit pair encodings, and
the TCRIT one-time-unlock dance.
"""
import unittest

from emc2101._core import EMC2101
from emc2101._faults import DiodeFaultError
from emc2101._regs import (CFG_TCRITOVRD, REG_CONFIG, REG_EXT_HIGH_LSB,
                           REG_EXT_HIGH_MSB, REG_EXT_LOW_LSB,
                           REG_EXT_LOW_MSB, REG_EXT_TEMP_LSB,
                           REG_EXT_TEMP_MSB, REG_INT_LIMIT, REG_INT_TEMP,
                           REG_TCRIT, REG_TCRIT_HYST)
from fakes import FakeTransport, write_entries


def make_dev(registers=None):
    t = FakeTransport(registers=dict(registers or {}))
    return EMC2101(t), t


class LocalTempTestCase(unittest.TestCase):
    def test_local_temp_c_decodes_signed_byte(self):
        dev, _ = make_dev({REG_INT_TEMP: 0x1C})
        self.assertEqual(dev.local_temp_c, 28.0)

    def test_local_temp_c_negative(self):
        dev, _ = make_dev({REG_INT_TEMP: 0xE0})   # -32 two's complement
        self.assertEqual(dev.local_temp_c, -32.0)


class RemoteTempTestCase(unittest.TestCase):
    def test_remote_temp_c_positive_fractional(self):
        # raw = (0x1E << 3) | 0x04 = 0xF4 = 244 steps = 30.5 C
        dev, _ = make_dev({REG_EXT_TEMP_MSB: 0x1E, REG_EXT_TEMP_LSB: 0x04})
        self.assertEqual(dev.remote_temp_c, 30.5)

    def test_remote_temp_c_negative(self):
        # -10.0 C = -80 steps -> 11-bit 0x7B0 -> MSB 0xF6, LSB 0x00
        dev, _ = make_dev({REG_EXT_TEMP_MSB: 0xF6, REG_EXT_TEMP_LSB: 0x00})
        self.assertEqual(dev.remote_temp_c, -10.0)

    def test_remote_temp_c_reads_interlock_order_msb_first(self):
        dev, t = make_dev({REG_EXT_TEMP_MSB: 0x1E, REG_EXT_TEMP_LSB: 0x04})
        dev.remote_temp_c
        reads = [reg for kind, reg in t.log if kind == "read"]
        self.assertIn(REG_EXT_TEMP_MSB, reads)
        self.assertIn(REG_EXT_TEMP_LSB, reads)
        self.assertLess(reads.index(REG_EXT_TEMP_MSB),
                        reads.index(REG_EXT_TEMP_LSB))

    def test_open_sentinel_raises_diode_fault_error(self):
        # M1 live observation: MSB 0x7F / LSB 0x00 => raw 0x3F8
        dev, _ = make_dev({REG_EXT_TEMP_MSB: 0x7F, REG_EXT_TEMP_LSB: 0x00})
        with self.assertRaises(DiodeFaultError) as cm:
            dev.remote_temp_c
        self.assertIn("open", str(cm.exception))

    def test_short_sentinel_raises_diode_fault_error(self):
        dev, _ = make_dev({REG_EXT_TEMP_MSB: 0x7F, REG_EXT_TEMP_LSB: 0x07})
        with self.assertRaises(DiodeFaultError) as cm:
            dev.remote_temp_c
        self.assertIn("short", str(cm.exception))

    def test_diode_fault_error_is_an_oserror(self):
        self.assertTrue(issubclass(DiodeFaultError, OSError))


class InternalLimitTestCase(unittest.TestCase):
    def test_local_high_c_roundtrip(self):
        dev, t = make_dev({REG_INT_LIMIT: 0x46})
        self.assertEqual(dev.local_high_c, 70.0)
        dev.local_high_c = 75
        self.assertEqual(t.registers[REG_INT_LIMIT], 0x4B)
        dev.local_high_c = -5
        self.assertEqual(t.registers[REG_INT_LIMIT], 0xFB)

    def test_local_high_c_range_validation(self):
        dev, _ = make_dev()
        with self.assertRaises(ValueError):
            dev.local_high_c = 128
        with self.assertRaises(ValueError):
            dev.local_high_c = -129


class ExternalLimitsTestCase(unittest.TestCase):
    def test_remote_high_c_roundtrip_fractional(self):
        # 69.875 C = 559 steps = 0x22F -> MSB 0x45, LSB 0x07
        dev, t = make_dev({REG_EXT_HIGH_MSB: 0x45, REG_EXT_HIGH_LSB: 0x07})
        self.assertEqual(dev.remote_high_c, 69.875)
        dev.remote_high_c = 0.125
        self.assertEqual(t.registers[REG_EXT_HIGH_MSB], 0x00)
        self.assertEqual(t.registers[REG_EXT_HIGH_LSB], 0x01)

    def test_remote_low_c_roundtrip_negative(self):
        # -1.5 C = -12 steps -> 11-bit 0x7EC -> MSB 0xFE, LSB 0x04
        dev, t = make_dev({REG_EXT_LOW_MSB: 0xFE, REG_EXT_LOW_LSB: 0x04})
        self.assertEqual(dev.remote_low_c, -1.5)
        dev.remote_low_c = 127.875
        self.assertEqual(t.registers[REG_EXT_LOW_MSB], 0x7F)
        self.assertEqual(t.registers[REG_EXT_LOW_LSB], 0x07)

    def test_external_limit_range_validation(self):
        dev, _ = make_dev()
        with self.assertRaises(ValueError):
            dev.remote_high_c = -64.125
        with self.assertRaises(ValueError):
            dev.remote_low_c = 127.875 + 0.125


class TcritTestCase(unittest.TestCase):
    def test_tcrit_c_default_decode(self):
        dev, _ = make_dev({REG_TCRIT: 0x55})
        self.assertEqual(dev.tcrit_c, 85.0)

    def test_tcrit_set_equal_value_is_noop_without_unlock(self):
        dev, t = make_dev({REG_TCRIT: 0x55, REG_CONFIG: 0x00})
        dev.tcrit_c = 85
        self.assertEqual(write_entries(t.log), [])

    def test_tcrit_set_arms_unlock_then_writes(self):
        dev, t = make_dev({REG_TCRIT: 0x55, REG_CONFIG: 0x00})
        dev.tcrit_c = 90
        self.assertEqual(write_entries(t.log),
                         [(REG_CONFIG, CFG_TCRITOVRD), (REG_TCRIT, 90)])

    def test_tcrit_set_with_unlock_already_armed_skips_config_write(self):
        dev, t = make_dev({REG_TCRIT: 0x55, REG_CONFIG: CFG_TCRITOVRD})
        dev.tcrit_c = 90
        self.assertEqual(write_entries(t.log), [(REG_TCRIT, 90)])

    def test_tcrit_preserves_other_config_bits_when_arming(self):
        dev, t = make_dev({REG_TCRIT: 0x55, REG_CONFIG: 0x41})
        dev.tcrit_c = 90
        cfg_write = [val for reg, val in write_entries(t.log,
                                                       REG_CONFIG)][0]
        self.assertEqual(cfg_write, 0x43)

    def test_tcrit_hysteresis_roundtrip_and_range(self):
        dev, t = make_dev({REG_TCRIT_HYST: 0x0A})
        self.assertEqual(dev.tcrit_hysteresis_c, 10)
        dev.tcrit_hysteresis_c = 15
        self.assertEqual(t.registers[REG_TCRIT_HYST], 0x0F)
        with self.assertRaises(ValueError):
            dev.tcrit_hysteresis_c = 128
        with self.assertRaises(ValueError):
            dev.tcrit_hysteresis_c = -1


if __name__ == "__main__":
    unittest.main()
