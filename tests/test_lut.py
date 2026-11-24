"""M3 unit tests: LUT programming (shared core).

Covers threshold/duty decoding through the current PWM_F grid, the
ascending-threshold validation, and the PROG dance (temporary PROG=1
while registers are RO in LUT mode, including restore-on-failure).
"""
import unittest

from emc2101._core import EMC2101
from emc2101._regs import (FCFG_CLK_SEL, FCFG_FORCE, FCFG_PROG, REG_EXT_FORCE,
                           REG_FAN_CFG, REG_LUT_BASE, REG_LUT_HYST,
                           REG_PWM_F)
from fakes import FakeTransport, write_entries


def make_dev(registers=None):
    t = FakeTransport(registers=dict(registers or {}))
    return EMC2101(t), t


CURVE_TEMPS = (25, 30, 35, 40, 45, 50, 55, 60)
CURVE_DUTIES = (0, 8, 16, 24, 32, 40, 48, 56)


def curve_registers():
    regs = {REG_FAN_CFG: FCFG_PROG, REG_PWM_F: 0x1F}   # grid 100/62 %
    for i in range(8):
        regs[REG_LUT_BASE + 2 * i] = CURVE_TEMPS[i]
        regs[REG_LUT_BASE + 2 * i + 1] = CURVE_DUTIES[i]
    return regs


class LutGetterTestCase(unittest.TestCase):
    def test_decodes_all_eight_pairs(self):
        dev, _ = make_dev(curve_registers())
        lut = dev.lut
        self.assertEqual(len(lut), 8)
        self.assertEqual(lut[0], (25.0, 0.0))
        self.assertAlmostEqual(lut[3][1], 24 / 62.0 * 100.0, places=9)
        self.assertEqual(lut[-1][0], 60.0)

    def test_reads_addresses_in_order_0x50_to_0x5F(self):
        dev, t = make_dev(curve_registers())
        dev.lut
        reads = [reg for kind, reg in t.log if kind == "read"]
        self.assertEqual(reads[-16:], list(range(0x50, 0x60)))

    def test_negative_threshold_decode(self):
        regs = curve_registers()
        regs[REG_LUT_BASE] = 0xFC                      # -4 C
        dev, _ = make_dev(regs)
        self.assertEqual(dev.lut[0][0], -4.0)


class LutSetterTestCase(unittest.TestCase):
    def test_bulk_write_in_manual_mode_touches_no_fan_cfg(self):
        dev, t = make_dev({REG_FAN_CFG: FCFG_PROG, REG_PWM_F: 0x1F})
        dev.lut = [(t_, d_) for t_, d_ in zip(CURVE_TEMPS, CURVE_DUTIES)]
        lut_writes = write_entries(t.log)
        self.assertEqual(len(lut_writes), 16)
        self.assertEqual(lut_writes[0], (0x50, 25))
        self.assertNotIn(REG_FAN_CFG,
                         [r for r, v in write_entries(t.log)])

    def test_prog_dance_when_in_lut_mode(self):
        # PROG=0 with CLK_SEL=1 set: original byte 0x0A must be restored
        dev, t = make_dev({REG_FAN_CFG: FCFG_CLK_SEL, REG_PWM_F: 0x1F})
        dev.lut = [(t_, d_) for t_, d_ in zip(CURVE_TEMPS, CURVE_DUTIES)]
        cfg_writes = [val for r, val in write_entries(t.log, REG_FAN_CFG)]
        self.assertEqual(cfg_writes[0], FCFG_CLK_SEL | FCFG_PROG)
        self.assertEqual(cfg_writes[-1], FCFG_CLK_SEL)
        self.assertEqual(len(cfg_writes), 2)

    def test_prog_restored_even_when_a_write_fails(self):
        inner = FakeTransport(registers={REG_FAN_CFG: FCFG_CLK_SEL,
                                         REG_PWM_F: 0x1F})

        class FlakyProxy(object):
            def __init__(self, inner):
                self.inner = inner
                self.writes = 0

            def read_byte(self, reg):
                return self.inner.read_byte(reg)

            def write_byte(self, reg, value):
                self.writes += 1
                if self.writes == 5:
                    raise OSError("injected mid-LUT failure")
                self.inner.write_byte(reg, value)

            probe = property(lambda self: True)
            scan = property(lambda self: [])
            delay_ms = staticmethod(lambda ms: None)
            close = lambda self: setattr(self.inner, "closed", True)

        proxy = FlakyProxy(inner)
        dev = EMC2101(proxy)
        with self.assertRaises(OSError):
            dev.lut = [(t_, d_) for t_, d_ in zip(CURVE_TEMPS, CURVE_DUTIES)]
        cfg_writes = [val for r, val in write_entries(inner.log,
                                                      REG_FAN_CFG)]
        self.assertEqual(cfg_writes[-1], FCFG_CLK_SEL)   # restored

    def test_length_validation(self):
        dev, _ = make_dev({REG_FAN_CFG: FCFG_PROG, REG_PWM_F: 0x1F})
        with self.assertRaises(ValueError):
            dev.lut = [(25, 0)] * 7

    def test_equal_thresholds_rejected(self):
        dev, _ = make_dev({REG_FAN_CFG: FCFG_PROG, REG_PWM_F: 0x1F})
        pairs = [(25, 0), (25, 10), (30, 20), (35, 30), (40, 40),
                 (45, 50), (50, 60), (55, 70)]
        with self.assertRaises(ValueError):
            dev.lut = pairs

    def test_descending_thresholds_rejected(self):
        dev, _ = make_dev({REG_FAN_CFG: FCFG_PROG, REG_PWM_F: 0x1F})
        pairs = [(30, 0), (25, 10), (35, 20), (40, 30), (45, 40),
                 (50, 50), (55, 60), (60, 70)]
        with self.assertRaises(ValueError):
            dev.lut = pairs

    def test_malformed_entry_rejected(self):
        dev, _ = make_dev({REG_FAN_CFG: FCFG_PROG, REG_PWM_F: 0x1F})
        with self.assertRaises(ValueError):
            dev.lut = [(25, 0), 42, (30, 20), (35, 30), (40, 40),
                       (45, 50), (50, 60), (55, 70)]

    def test_out_of_range_threshold_rejected_without_partial_writes(self):
        dev, t = make_dev({REG_FAN_CFG: FCFG_PROG, REG_PWM_F: 0x1F})
        pairs = [(25, 0), (30, 10), (128, 20), (40, 30), (45, 40),
                 (50, 50), (55, 60), (60, 70)]
        with self.assertRaises(ValueError):
            dev.lut = pairs
        self.assertEqual(write_entries(t.log), [])


class LutIndexAccessTestCase(unittest.TestCase):
    def test_get_index(self):
        dev, _ = make_dev(curve_registers())
        self.assertEqual(dev.lut_get_index(0), (25.0, 0.0))
        self.assertAlmostEqual(dev.lut_get_index(7)[1], 56 / 62.0 * 100.0,
                               places=9)

    def test_get_index_range(self):
        dev, _ = make_dev(curve_registers())
        with self.assertRaises(ValueError):
            dev.lut_get_index(8)
        with self.assertRaises(ValueError):
            dev.lut_get_index(-1)

    def test_set_index_writes_pair(self):
        dev, t = make_dev({REG_FAN_CFG: FCFG_PROG, REG_PWM_F: 0x1F})
        dev.lut_set_index(3, 40, 50.0)     # S = round(50*62/100) = 31
        self.assertEqual(write_entries(t.log), [(0x56, 40), (0x57, 31)])

    def test_set_index_single_prog_dance_in_lut_mode(self):
        # PROG=0 with CLK_SEL=1: both bytes go out under ONE temporary
        # PROG=1 (arm + restore = exactly two FAN_CFG writes), not one
        # dance per byte.
        dev, t = make_dev({REG_FAN_CFG: FCFG_CLK_SEL, REG_PWM_F: 0x1F})
        dev.lut_set_index(3, 40, 50.0)
        entries = write_entries(t.log)
        cfg_writes = [val for r, val in entries if r == REG_FAN_CFG]
        self.assertEqual(cfg_writes, [FCFG_CLK_SEL | FCFG_PROG,
                                      FCFG_CLK_SEL])
        self.assertEqual([e for e in entries if e[0] != REG_FAN_CFG],
                         [(0x56, 40), (0x57, 31)])

    def test_set_index_range(self):
        dev, _ = make_dev({REG_FAN_CFG: FCFG_PROG, REG_PWM_F: 0x1F})
        with self.assertRaises(ValueError):
            dev.lut_set_index(8, 25, 0.0)


class LutAuxiliaryTestCase(unittest.TestCase):
    def test_hysteresis_roundtrip_and_range(self):
        dev, t = make_dev({REG_LUT_HYST: 0x04})
        self.assertEqual(dev.hysteresis_c, 4)
        dev.hysteresis_c = 127
        self.assertEqual(t.registers[REG_LUT_HYST], 0x7F)
        with self.assertRaises(ValueError):
            dev.hysteresis_c = 128

    def test_force_enabled_roundtrip(self):
        dev, t = make_dev({REG_FAN_CFG: FCFG_PROG})
        self.assertFalse(dev.force_enabled)
        dev.force_enabled = True
        self.assertEqual(t.registers[REG_FAN_CFG], FCFG_PROG | FCFG_FORCE)

    def test_forced_temp_roundtrip_signed(self):
        dev, t = make_dev({REG_EXT_FORCE: 0x19})
        self.assertEqual(dev.forced_temp_c, 25.0)
        dev.forced_temp_c = -5
        self.assertEqual(t.registers[REG_EXT_FORCE], 0xFB)
        with self.assertRaises(ValueError):
            dev.forced_temp_c = 128


if __name__ == "__main__":
    unittest.main()
