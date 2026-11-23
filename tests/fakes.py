"""Shared fake bus objects for the host unit-test suite.

Three stand-ins, one per layer of the transport contract:

- FakeI2C:      mimics machine.I2C (readfrom_mem / writeto_mem / scan).
- FakeSMBus:    mimics smbus2.SMBus / smbus.SMBus (read_byte_data /
                write_byte_data / close).
- FakeTransport: implements the single-byte transport contract directly
                (what _core consumes), with a transaction log.

All three support injecting OSError failures (first N attempts, or always)
so the retry-ladder semantics can be asserted without hardware. These are
test doubles written from the documented contracts; they intentionally do
not model chip behavior beyond what the transports see.
"""
import errno

from emc2101._regs import (ADDR_FIXED, MANUF_ID_SMSC, PRODUCT_ID_PLAIN,
                           REG_MANUF_ID, REG_PRODUCT_ID, REG_REVISION,
                           REVISION_EXPECTED)


class FakeI2C:
    """Stand-in for machine.I2C. Records every transaction as
    ("read", addr, reg, nbytes) / ("write", addr, reg, payload-tuple) /
    ("scan",). Registers default to 0x00; unknown reads raise so silent
    wrong-address traffic is caught."""

    def __init__(self, registers=None, failures=0, always_fail=False,
                 scan_result=(ADDR_FIXED,)):
        self.registers = dict(registers or {})
        self.failures = failures          # OSErrors raised before success
        self.always_fail = always_fail
        self.scan_result = list(scan_result)
        self.calls = []

    def _maybe_fail(self):
        if self.always_fail:
            raise OSError(errno.EIO, "injected bus error")
        if self.failures > 0:
            self.failures -= 1
            raise OSError(errno.EIO, "injected bus error")

    def readfrom_mem(self, addr, reg, nbytes):
        self.calls.append(("read", addr, reg, nbytes))
        self._maybe_fail()
        if reg not in self.registers:
            raise AssertionError("unexpected read of register %#x" % reg)
        return bytes((self.registers[reg] & 0xFF,))

    def writeto_mem(self, addr, reg, payload):
        self.calls.append(("write", addr, reg, tuple(payload)))
        self._maybe_fail()
        self.registers[reg] = payload[0]

    def scan(self):
        self.calls.append(("scan",))
        return list(self.scan_result)


class FakeSMBus:
    """Stand-in for an SMBus handle. Addresses outside `responders` NACK
    (OSError ENXIO), mirroring a device that is not present."""

    def __init__(self, responders=(ADDR_FIXED,), failures=0,
                 always_fail=False, values=None):
        self.responders = set(responders)
        self.failures = failures
        self.always_fail = always_fail
        self.values = dict(values or {})   # (addr, reg) -> byte
        self.calls = []
        self.closed = False

    def _maybe_fail(self, addr):
        if self.always_fail or addr not in self.responders:
            raise OSError(errno.ENXIO, "device NACK")
        if self.failures > 0:
            self.failures -= 1
            raise OSError(errno.ENXIO, "injected bus error")

    def read_byte_data(self, addr, reg):
        self.calls.append(("read", addr, reg))
        self._maybe_fail(addr)
        return self.values.get((addr, reg), 0x00)

    def write_byte_data(self, addr, reg, value):
        self.calls.append(("write", addr, reg, value))
        self._maybe_fail(addr)
        self.values[(addr, reg)] = value

    def close(self):
        self.closed = True


class FakeTransport:
    """Implements the single-byte transport contract consumed by
    _core.EMC2101, with a transaction log and a configurable identity
    trio (product, manufacturer, revision)."""

    def __init__(self, identity=(PRODUCT_ID_PLAIN, MANUF_ID_SMSC,
                                 REVISION_EXPECTED), bus_error=False,
                 probe_result=True, scan_result=(0x0C, ADDR_FIXED)):
        self.identity = identity
        self.bus_error = bus_error
        self.log = []
        self.closed = False
        self.probe_result = probe_result
        self.scan_result = list(scan_result)

    def read_byte(self, reg):
        self.log.append(("read", reg))
        if self.bus_error:
            raise OSError("simulated bus failure")
        if reg == REG_PRODUCT_ID:
            return self.identity[0]
        if reg == REG_MANUF_ID:
            return self.identity[1]
        if reg == REG_REVISION:
            return self.identity[2]
        return 0x00

    def write_byte(self, reg, value):
        self.log.append(("write", reg, value))

    def probe(self):
        return self.probe_result

    def scan(self):
        return list(self.scan_result)

    def delay_ms(self, ms):
        pass

    def close(self):
        self.closed = True
