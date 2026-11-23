"""M3 unit tests: status register and alert machinery (shared core).

Covers the destructive-read discipline, masked-alarm filtering with
reserved-bit handling in the Alert Mask register, alert mode selection,
and the service/re-arm sequence.
"""
import unittest

from emc2101._core import (ALERT_MODE_COMPARATOR, ALERT_MODE_INTERRUPT,
                           EMC2101)
from emc2101._regs import (AMSK_DEFINED, AMSK_HIGH, AMSK_INT, AMSK_LOW,
                           AMSK_TACH, AMSK_TCRIT, CFG_MASK, REG_ALERT_MASK,
                           REG_CONFIG, REG_FILTER, REG_STATUS, ST_BUSY,
                           ST_EXT_HIGH, ST_EXT_LOW, ST_FAULT, ST_INT_HIGH,
                           ST_TACH, ST_TCRIT, FLT_COMP)
from fakes import FakeTransport


def make_dev(registers=None):
    t = FakeTransport(registers=dict(registers or {}))
    return EMC2101(t), t


class StatusRawTestCase(unittest.TestCase):
    def test_status_raw_returns_byte_and_reads_0x02(self):
        dev, t = make_dev({REG_STATUS: 0x1B})
        self.assertEqual(dev.status_raw(), 0x1B)
        self.assertIn(("read", REG_STATUS), t.log)

    def test_busy_reflects_status_bit(self):
        dev, _ = make_dev({REG_STATUS: ST_BUSY})
        self.assertTrue(dev.busy())
        dev2, _ = make_dev({REG_STATUS: 0x00})
        self.assertFalse(dev2.busy())

    def test_diode_fault_reflects_fault_bit(self):
        dev, _ = make_dev({REG_STATUS: ST_FAULT})
        self.assertTrue(dev.diode_fault())
        dev2, _ = make_dev({REG_STATUS: 0x00})
        self.assertFalse(dev2.diode_fault())


class ActiveAlarmsTestCase(unittest.TestCase):
    def test_unmasked_alarms_reported_in_order(self):
        status = ST_EXT_HIGH | ST_TCRIT | ST_TACH
        dev, _ = make_dev({REG_STATUS: status, REG_ALERT_MASK: 0xA4})
        self.assertEqual(dev.active_alarms(),
                         ["ext-high", "tcrit", "tach-slow"])

    def test_masked_alarm_excluded(self):
        status = ST_EXT_HIGH | ST_TCRIT
        mask = 0xA4 | AMSK_TCRIT
        dev, _ = make_dev({REG_STATUS: status, REG_ALERT_MASK: mask})
        self.assertEqual(dev.active_alarms(), ["ext-high"])

    def test_all_defined_bits_masked_yields_empty(self):
        status = ST_INT_HIGH | ST_EXT_HIGH | ST_EXT_LOW | ST_TCRIT | ST_TACH
        dev, _ = make_dev({REG_STATUS: status,
                           REG_ALERT_MASK: 0xA4 | AMSK_DEFINED})
        self.assertEqual(dev.active_alarms(), [])

    def test_non_alarm_bits_never_reported(self):
        dev, _ = make_dev({REG_STATUS: ST_BUSY | ST_FAULT,
                           REG_ALERT_MASK: 0xA4})
        self.assertEqual(dev.active_alarms(), [])


class AlertMaskTestCase(unittest.TestCase):
    def test_getter_masks_off_reserved_bits(self):
        dev, _ = make_dev({REG_ALERT_MASK: 0xA4})
        self.assertEqual(dev.alert_mask, 0x00)

    def test_setter_preserves_reserved_bits_via_rmw(self):
        dev, t = make_dev({REG_ALERT_MASK: 0xA4})
        dev.alert_mask = AMSK_HIGH | AMSK_TACH      # 0x11
        self.assertEqual(t.registers[REG_ALERT_MASK], 0xB5)

    def test_setter_replaces_previous_defined_field(self):
        dev, t = make_dev({REG_ALERT_MASK: 0xAB})   # defined field 0x07
        dev.alert_mask = AMSK_INT                   # 0x40
        # reserved bits (0xA4) preserved; defined field replaced with 0x40
        self.assertEqual(t.registers[REG_ALERT_MASK], 0xE0)

    def test_setter_range_validation(self):
        dev, _ = make_dev()
        with self.assertRaises(ValueError):
            dev.alert_mask = AMSK_DEFINED + 1


class AlertModeTestCase(unittest.TestCase):
    def test_interrupt_mode_default(self):
        dev, _ = make_dev({REG_FILTER: 0x00})
        self.assertEqual(dev.alert_mode, ALERT_MODE_INTERRUPT)

    def test_comparator_mode_decode(self):
        dev, _ = make_dev({REG_FILTER: FLT_COMP})
        self.assertEqual(dev.alert_mode, ALERT_MODE_COMPARATOR)

    def test_setter_both_directions_preserve_filter_level(self):
        dev, t = make_dev({REG_FILTER: 0x06})       # Level 2
        dev.alert_mode = ALERT_MODE_COMPARATOR
        self.assertEqual(t.registers[REG_FILTER], 0x07)
        dev.alert_mode = ALERT_MODE_INTERRUPT
        self.assertEqual(t.registers[REG_FILTER], 0x06)

    def test_setter_rejects_unknown_mode(self):
        dev, _ = make_dev()
        with self.assertRaises(ValueError):
            dev.alert_mode = 2


class ServiceSequenceTestCase(unittest.TestCase):
    def test_service_alert_returns_status_byte(self):
        dev, t = make_dev({REG_STATUS: 0x13})
        self.assertEqual(dev.service_alert(), 0x13)
        self.assertIn(("read", REG_STATUS), t.log)

    def test_clear_alert_mask_clears_only_mask_bit(self):
        dev, t = make_dev({REG_CONFIG: 0xC0})       # MASK + STANDBY
        dev.clear_alert_mask()
        self.assertEqual(t.registers[REG_CONFIG], 0x40)

    def test_clear_alert_mask_is_noop_when_not_masked(self):
        dev, t = make_dev({REG_CONFIG: 0x04})
        dev.clear_alert_mask()
        self.assertEqual(t.registers[REG_CONFIG], 0x04)


if __name__ == "__main__":
    unittest.main()
