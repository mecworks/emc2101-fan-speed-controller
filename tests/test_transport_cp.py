"""Unit tests for emc2101._transport_cp.TransportCP against a fake SMBus
handle (tests.fakes.FakeSMBus). The handle is injected (adopted), so no
real /dev/i2c-N is opened and the tests run on any host. Asserts the same
single-byte contract and retry semantics as the MicroPython transport,
plus adopted-handle close behavior and the candidate-probing scan.
"""
import unittest
from unittest import mock

from emc2101._regs import ADDR_FIXED, REG_INT_TEMP, RETRY_DELAYS_MS
from emc2101._transport_cp import TransportCP
from fakes import FakeSMBus

_SCAN_MIN = 0x03
_SCAN_MAX = 0x77


class TransportCPTestCase(unittest.TestCase):
    def setUp(self):
        self.delays = []                     # seconds, as passed to time.sleep
        patcher = mock.patch("emc2101._transport_cp.time.sleep")
        self.fake_sleep = patcher.start()
        self.fake_sleep.side_effect = self.delays.append
        self.addCleanup(patcher.stop)

    def make(self, **kwargs):
        self.bus = FakeSMBus(**kwargs)
        return TransportCP(handle=self.bus)

    # -- happy paths ---------------------------------------------------------

    def test_read_byte_returns_handle_value(self):
        t = self.make(values={(ADDR_FIXED, REG_INT_TEMP): 0x16})
        self.assertEqual(t.read_byte(REG_INT_TEMP), 0x16)
        self.assertEqual(self.bus.calls, [("read", ADDR_FIXED, REG_INT_TEMP)])
        self.assertEqual(self.delays, [])

    def test_write_byte_forwards_to_handle(self):
        t = self.make()
        t.write_byte(0x4A, 0x20)
        self.assertEqual(self.bus.calls, [("write", ADDR_FIXED, 0x4A, 0x20)])
        self.assertEqual(self.bus.values[(ADDR_FIXED, 0x4A)], 0x20)

    # -- retry ladder ----------------------------------------------------------

    def test_read_byte_retries_then_succeeds(self):
        t = self.make(values={(ADDR_FIXED, REG_INT_TEMP): 0x11}, failures=2)
        self.assertEqual(t.read_byte(REG_INT_TEMP), 0x11)
        self.assertEqual(len(self.bus.calls), 3)
        self.assertEqual(self.delays,
                         [d / 1000.0 for d in RETRY_DELAYS_MS[:2]])

    def test_read_byte_exhaustion_raises_oserror_after_full_ladder(self):
        t = self.make(always_fail=True)
        with self.assertRaises(OSError):
            t.read_byte(REG_INT_TEMP)
        self.assertEqual(len(self.bus.calls), len(RETRY_DELAYS_MS) + 1)
        self.assertEqual(self.delays,
                         [d / 1000.0 for d in RETRY_DELAYS_MS])

    def test_write_byte_retries_then_succeeds(self):
        t = self.make(failures=1)
        t.write_byte(0x4A, 0x20)
        self.assertEqual(len(self.bus.calls), 2)
        self.assertEqual(self.delays, [RETRY_DELAYS_MS[0] / 1000.0])
        self.assertEqual(self.bus.values[(ADDR_FIXED, 0x4A)], 0x20)

    def test_write_byte_exhaustion_raises_oserror(self):
        t = self.make(always_fail=True)
        with self.assertRaises(OSError):
            t.write_byte(0x4A, 0x20)
        self.assertEqual(len(self.bus.calls), len(RETRY_DELAYS_MS) + 1)

    # -- validation ----------------------------------------------------------------

    def test_read_byte_rejects_out_of_range_register(self):
        t = self.make()
        for bad in (-1, 0x100):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    t.read_byte(bad)
        self.assertEqual(self.bus.calls, [])

    def test_write_byte_rejects_out_of_range_value(self):
        t = self.make()
        for bad in (-1, 0x100):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    t.write_byte(0x03, bad)
        self.assertEqual(self.bus.calls, [])

    # -- diagnostics -----------------------------------------------------------------

    def test_probe_true_when_device_answers(self):
        t = self.make()
        self.assertTrue(t.probe())

    def test_probe_false_on_nack_without_retry(self):
        t = self.make(responders=set())
        self.assertFalse(t.probe())
        self.assertEqual(self.delays, [])

    def test_scan_probes_candidate_range_once_each(self):
        t = self.make(responders={0x0C, 0x4C})
        found = t.scan()
        self.assertEqual(found, [0x0C, 0x4C])
        reads = [c for c in self.bus.calls if c[0] == "read"]
        self.assertEqual(len(reads), _SCAN_MAX - _SCAN_MIN + 1)
        self.assertEqual(sorted(a for (_, a, _) in reads),
                         list(range(_SCAN_MIN, _SCAN_MAX + 1)))
        self.assertEqual(self.delays, [])      # scan never retries

    def test_close_does_not_release_adopted_handle(self):
        t = self.make()
        t.close()
        self.assertFalse(self.bus.closed)

    def test_default_address_is_fixed(self):
        t = self.make()
        self.assertEqual(t._addr, ADDR_FIXED)


if __name__ == "__main__":
    unittest.main()
