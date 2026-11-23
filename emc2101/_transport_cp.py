"""CPython transport adapter (smbus2, fallback: system smbus).

Linux-only in practice. Wraps the kernel i2c-dev interface via /dev/i2c-N.
The smbus library is imported lazily (only when opening a real bus), so this
module can be imported - and tested with an injected fake handle - on any
host.

Handle contract for the single-byte protocol:
    read_byte_data(addr, reg) -> int
    write_byte_data(addr, reg, val) -> None
Both smbus2 and the legacy system smbus module provide these natively, so
no compatibility shim is needed (unlike the sibling driver's block-read
normalization).

Retry semantics mirror _transport_mp.TransportMP exactly: every
read/write retries over RETRY_DELAYS_MS before raising OSError.
"""

import time

from ._regs import ADDR_FIXED, REG_INT_TEMP, RETRY_DELAYS_MS

_SCAN_MIN = 0x03          # conventional i2cdetect candidate range
_SCAN_MAX = 0x77


def _open_smbus(bus):
    """Open a real SMBus handle, preferring smbus2 over system smbus."""
    try:
        import smbus2 as _mod
        return _mod.SMBus(int(bus))
    except ImportError:
        import smbus as _mod
        return _mod.SMBus(int(bus))


class TransportCP:
    """Adapts an SMBus handle to the single-byte transport contract.

    Args:
        bus:    I2C bus number (RPi default 1 = /dev/i2c-1).
        addr:   7-bit slave address (fixed at 0x4C for the EMC2101).
        handle: optional pre-opened smbus2/smbus object (adopted as-is;
                close() will NOT release it).
    """

    def __init__(self, bus=1, addr=ADDR_FIXED, handle=None):
        self._addr = int(addr)
        if handle is None:
            self._bus = _open_smbus(bus)
            self._owns_bus = True
        else:
            self._bus = handle
            self._owns_bus = False

    # -- internals ------------------------------------------------------------

    @staticmethod
    def _check_reg(reg):
        if not 0 <= reg <= 0xFF:
            raise ValueError("register address out of range: %r" % (reg,))

    @staticmethod
    def _check_value(value):
        if not 0 <= value <= 0xFF:
            raise ValueError("byte value out of range: %r" % (value,))

    def _with_retry(self, fn):
        """Run fn(), retrying after escalating delays; raise the last
        OSError once RETRY_DELAYS_MS is exhausted (len+1 attempts total)."""
        attempt = 0
        while True:
            try:
                return fn()
            except OSError as exc:
                if attempt >= len(RETRY_DELAYS_MS):
                    raise
                self.delay_ms(RETRY_DELAYS_MS[attempt])
                attempt += 1

    # -- contract -------------------------------------------------------------

    def read_byte(self, reg):
        """One Read Byte transaction: read the given register."""
        self._check_reg(reg)
        return self._with_retry(
            lambda: self._bus.read_byte_data(self._addr, reg))

    def write_byte(self, reg, value):
        """One Write Byte transaction: write value to the given register."""
        self._check_reg(reg)
        self._check_value(value)
        self._with_retry(
            lambda: self._bus.write_byte_data(self._addr, reg, value))

    def probe(self):
        """Address ACK check via a read of the RO internal-temp register
        (0x00): harmless, side-effect-free. Single attempt (diagnostics
        must stay fast); returns False on any OSError."""
        try:
            self._bus.read_byte_data(self._addr, REG_INT_TEMP)
            return True
        except OSError:
            return False

    def scan(self):
        """Probe candidate 7-bit addresses; return sorted list of responders.

        smbus has no native bus scan, so each candidate in 0x03..0x77 is
        probed with a read of the RO internal-temp register (0x00);
        non-responders NACK (OSError) and are skipped. Diagnostic-only
        (~114 transactions).
        """
        found = []
        for a in range(_SCAN_MIN, _SCAN_MAX + 1):
            try:
                self._bus.read_byte_data(a, REG_INT_TEMP)
                found.append(a)
            except OSError:
                pass
        return found

    def delay_ms(self, ms):
        time.sleep(ms / 1000.0)

    def close(self):
        """Release the underlying bus (only if this object opened it)."""
        if self._owns_bus:
            self._bus.close()
