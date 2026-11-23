"""Unit tests for emc2101._transport_mp.TransportMP against a fake
machine.I2C (tests.fakes.FakeI2C). Asserts the single-byte contract, the
retry-ladder semantics (delays taken from RETRY_DELAYS_MS, len+1 attempts
total), input validation, and probe/scan/close behavior. Host-side only;
no hardware involved.
"""
import unittest
from unittest import mock

from emc2101._regs import ADDR_FIXED, REG_INT_TEMP, RETRY_DELAYS_MS
from emc2101._transport_mp import TransportMP
from fakes import FakeI2C


class TransportMPTestCase(unittest.TestCase):
    def setUp(self):
        self.delays = []
        patcher = mock.patch("emc2101._transport_mp.time.sleep_ms",
                             create=True)
        self.fake_sleep = patcher.start()
        self.fake_sleep.side_effect = self.delays.append
        self.addCleanup(patcher.stop)

    def make(self, **kwargs):
        self.i2c = FakeI2C(**kwargs)
        return TransportMP(self.i2c)

    # -- happy paths -------------------------------------------------------

    def test_read_byte_returns_register_value(self):
        t = self.make(registers={REG_INT_TEMP: 0x16})
        self.assertEqual(t.read_byte(REG_INT_TEMP), 0x16)
        self.assertEqual(self.i2c.calls,
                         [("read", ADDR_FIXED, REG_INT_TEMP, 1)])
        self.assertEqual(self.delays, [])

    def test_write_byte_stores_single_byte_payload(self):
        t = self.make()
        t.write_byte(0x4C, 0xAB)
        self.assertEqual(self.i2c.calls,
                         [("write", ADDR_FIXED, 0x4C, (0xAB,))])
        self.assertEqual(self.i2c.registers[0x4C], 0xAB)

    # -- retry ladder --------------------------------------------------------

    def test_read_byte_retries_then_succeeds(self):
        t = self.make(registers={REG_INT_TEMP: 0x11}, failures=2)
        self.assertEqual(t.read_byte(REG_INT_TEMP), 0x11)
        self.assertEqual(len(self.i2c.calls), 3)
        self.assertEqual(self.delays, list(RETRY_DELAYS_MS[:2]))

    def test_read_byte_exhaustion_raises_oserror_after_full_ladder(self):
        t = self.make(always_fail=True)
        with self.assertRaises(OSError):
            t.read_byte(REG_INT_TEMP)
        self.assertEqual(len(self.i2c.calls), len(RETRY_DELAYS_MS) + 1)
        self.assertEqual(self.delays, list(RETRY_DELAYS_MS))

    def test_write_byte_retries_then_succeeds(self):
        t = self.make(failures=1)
        t.write_byte(0x4A, 0x20)
        self.assertEqual(len(self.i2c.calls), 2)
        self.assertEqual(self.delays, [RETRY_DELAYS_MS[0]])
        self.assertEqual(self.i2c.registers[0x4A], 0x20)

    def test_write_byte_exhaustion_raises_oserror(self):
        t = self.make(always_fail=True)
        with self.assertRaises(OSError):
            t.write_byte(0x4A, 0x20)
        self.assertEqual(len(self.i2c.calls), len(RETRY_DELAYS_MS) + 1)
        self.assertEqual(self.delays, list(RETRY_DELAYS_MS))

    # -- validation ------------------------------------------------------------

    def test_read_byte_rejects_out_of_range_register(self):
        t = self.make()
        for bad in (-1, 0x100):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    t.read_byte(bad)
        self.assertEqual(self.i2c.calls, [])

    def test_write_byte_rejects_out_of_range_value(self):
        t = self.make()
        for bad in (-1, 0x100):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    t.write_byte(0x03, bad)
        self.assertEqual(self.i2c.calls, [])

    # -- diagnostics -------------------------------------------------------------

    def test_probe_true_when_device_answers(self):
        t = self.make(registers={REG_INT_TEMP: 0x16})
        self.assertTrue(t.probe())

    def test_probe_false_on_bus_error_without_retry(self):
        t = self.make(always_fail=True)
        self.assertFalse(t.probe())
        self.assertEqual(self.delays, [])   # single attempt, no ladder

    def test_scan_delegates_to_i2c(self):
        t = self.make(scan_result=[0x0C, 0x4C])
        self.assertEqual(t.scan(), [0x0C, 0x4C])

    def test_close_is_a_noop(self):
        t = self.make()
        t.close()                            # must not raise

    def test_non_oserror_propagates_without_retry(self):
        class ExplodingI2C(FakeI2C):
            def readfrom_mem(self, addr, reg, nbytes):
                raise TypeError("boom")

        self.i2c = ExplodingI2C()
        t = TransportMP(self.i2c)
        with self.assertRaises(TypeError):
            t.read_byte(REG_INT_TEMP)
        self.assertEqual(self.delays, [])


if __name__ == "__main__":
    unittest.main()
