"""Lifecycle unit tests for the shared core (emc2101._core.EMC2101) and
the two facades' constructors, against duck-typed fakes (tests.fakes).
Covers address validation, verify() identity checks and transaction
order, probe/scan delegation, close/context-manager behavior, and the
facades' default config paths (decision O4/D16: /emc2101.json on
MicroPython, ~/emc2101.json on CPython).
"""
import os
import unittest

import emc2101.cp as cp_facade
import emc2101.mp as mp_facade
from emc2101._core import EMC2101 as Core
from emc2101._regs import (ADDR_FIXED, MANUF_ID_SMSC, PRODUCT_ID_PLAIN,
                           PRODUCT_ID_R, REG_MANUF_ID, REG_PRODUCT_ID,
                           REG_REVISION, REVISION_EXPECTED)
from fakes import FakeI2C, FakeSMBus, FakeTransport


class CoreLifecycleTestCase(unittest.TestCase):
    def test_constructor_binds_transport_addr_and_config_path(self):
        t = FakeTransport()
        dev = Core(t, config_file="/tmp/x.json")
        self.assertIs(dev._t, t)
        self.assertEqual(dev.addr, ADDR_FIXED)
        self.assertEqual(dev.config_path, "/tmp/x.json")

    def test_constructor_defaults_config_path_to_none(self):
        dev = Core(FakeTransport())
        self.assertIsNone(dev.config_path)

    def test_constructor_rejects_non_fixed_address(self):
        for bad in (0x4B, 0x4D, 0x50):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    Core(FakeTransport(), addr=bad)

    def test_verify_plain_identity_returns_product_id(self):
        t = FakeTransport()
        dev = Core(t)
        self.assertEqual(dev.verify(), PRODUCT_ID_PLAIN)
        self.assertEqual(t.log, [("read", REG_PRODUCT_ID),
                                 ("read", REG_MANUF_ID),
                                 ("read", REG_REVISION)])

    def test_verify_accepts_minus_r_variant(self):
        t = FakeTransport(identity=(PRODUCT_ID_R, MANUF_ID_SMSC,
                                    REVISION_EXPECTED))
        self.assertEqual(Core(t).verify(), PRODUCT_ID_R)

    def test_verify_rejects_wrong_manufacturer(self):
        t = FakeTransport(identity=(PRODUCT_ID_PLAIN, 0x00,
                                    REVISION_EXPECTED))
        with self.assertRaises(ValueError):
            Core(t).verify()

    def test_verify_rejects_wrong_revision(self):
        t = FakeTransport(identity=(PRODUCT_ID_PLAIN, MANUF_ID_SMSC, 0x02))
        with self.assertRaises(ValueError):
            Core(t).verify()

    def test_verify_rejects_unknown_product(self):
        t = FakeTransport(identity=(0x99, MANUF_ID_SMSC,
                                    REVISION_EXPECTED))
        with self.assertRaises(ValueError):
            Core(t).verify()

    def test_verify_propagates_bus_errors(self):
        t = FakeTransport(bus_error=True)
        with self.assertRaises(OSError):
            Core(t).verify()

    def test_probe_delegates(self):
        t = FakeTransport(probe_result=False)
        self.assertFalse(Core(t).probe())

    def test_scan_delegates(self):
        t = FakeTransport(scan_result=[0x0C, 0x4C])
        self.assertEqual(Core(t).scan(), [0x0C, 0x4C])

    def test_close_delegates(self):
        t = FakeTransport()
        Core(t).close()
        self.assertTrue(t.closed)

    def test_context_manager_closes_transport(self):
        t = FakeTransport()
        with Core(t) as dev:
            self.assertIsInstance(dev, Core)
        self.assertTrue(t.closed)


class MpFacadeTestCase(unittest.TestCase):
    def test_default_config_path_is_flash_root(self):
        dev = mp_facade.EMC2101(FakeI2C())
        self.assertEqual(dev.config_path, "/emc2101.json")

    def test_explicit_config_file_overrides_default(self):
        dev = mp_facade.EMC2101(FakeI2C(), config_file="/data/cfg.json")
        self.assertEqual(dev.config_path, "/data/cfg.json")

    def test_rejects_non_fixed_address(self):
        with self.assertRaises(ValueError):
            mp_facade.EMC2101(FakeI2C(), addr=0x50)

    def test_verify_end_to_end_through_fake_i2c(self):
        i2c = FakeI2C(registers={REG_PRODUCT_ID: PRODUCT_ID_PLAIN,
                                 REG_MANUF_ID: MANUF_ID_SMSC,
                                 REG_REVISION: REVISION_EXPECTED})
        dev = mp_facade.EMC2101(i2c)
        self.assertEqual(dev.verify(), PRODUCT_ID_PLAIN)


class CpFacadeTestCase(unittest.TestCase):
    def test_default_config_path_is_home(self):
        dev = cp_facade.EMC2101(handle=FakeSMBus())
        self.assertEqual(dev.config_path,
                         os.path.expanduser("~/emc2101.json"))

    def test_explicit_config_file_overrides_default(self):
        dev = cp_facade.EMC2101(handle=FakeSMBus(),
                                config_file="/etc/emc2101.json")
        self.assertEqual(dev.config_path, "/etc/emc2101.json")

    def test_rejects_non_fixed_address(self):
        with self.assertRaises(ValueError):
            cp_facade.EMC2101(handle=FakeSMBus(), addr=0x50)

    def test_verify_end_to_end_through_fake_smbus(self):
        bus = FakeSMBus(values={(ADDR_FIXED, REG_PRODUCT_ID):
                                PRODUCT_ID_PLAIN,
                                (ADDR_FIXED, REG_MANUF_ID):
                                MANUF_ID_SMSC,
                                (ADDR_FIXED, REG_REVISION):
                                REVISION_EXPECTED})
        dev = cp_facade.EMC2101(handle=bus)
        self.assertEqual(dev.verify(), PRODUCT_ID_PLAIN)


if __name__ == "__main__":
    unittest.main()
