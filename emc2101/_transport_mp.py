"""MicroPython transport adapter (machine.I2C), single-byte contract.

Uses the canonical, universal I2C API: readfrom_mem / writeto_mem.
NOTE: mem_read/mem_write are NOT part of the standard MicroPython API
(absent on v1.19.1 RP2040; zero mentions in official docs) - do not use.

M1 live-silicon notes (2026-11-22) that shaped this contract:
- Over-long reads do NOT raise: the chip releases the bus after the first
  byte and the master reads 0xFF padding. The one-byte-per-call contract
  makes that failure mode unreachable by construction.
- Bare Receive/Send Byte transactions (no register-address phase)
  desynchronize the chip's SMBus interface (next transaction fails with
  EIO). Only register-addressed Write Byte / Read Byte forms are used.
- The chip resets its own SMBus state machine after ~25 ms of clock
  inactivity (S4.8); retry rung 2 (30 ms) therefore covers a desynced
  device without any host-side re-initialization.
"""

import time

from ._regs import ADDR_FIXED, REG_INT_TEMP, RETRY_DELAYS_MS


class TransportMP:
    """Adapts a caller-constructed machine.I2C object to the single-byte
    transport contract consumed by _core.EMC2101:

        read_byte(reg) -> int         (raises OSError after the ladder)
        write_byte(reg, value) -> None (same error model)
        probe() -> bool               (single attempt, no ladder)
        scan() -> list[int]           (7-bit addresses present)
        delay_ms(ms) -> None
        close() -> None               (no-op)

    Every read/write retries over RETRY_DELAYS_MS before raising OSError.
    The ladder deliberately does NOT re-initialize the I2C peripheral: the
    caller owns the object and may share it. If the host-side peripheral
    itself wedges, recreate the machine.I2C instance and rebuild the driver.
    """

    def __init__(self, i2c, addr=ADDR_FIXED):
        self._i2c = i2c
        self._addr = int(addr)

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
            lambda: self._i2c.readfrom_mem(self._addr, reg, 1)[0])

    def write_byte(self, reg, value):
        """One Write Byte transaction: write value to the given register."""
        self._check_reg(reg)
        self._check_value(value)
        payload = bytearray([value])
        self._with_retry(
            lambda: self._i2c.writeto_mem(self._addr, reg, payload))

    def probe(self):
        """Address ACK check via a read of the RO internal-temp register
        (0x00): harmless, side-effect-free. Single attempt (diagnostics
        must stay fast); returns False on any OSError."""
        try:
            self._i2c.readfrom_mem(self._addr, REG_INT_TEMP, 1)
            return True
        except OSError:
            return False

    def scan(self):
        """Return the 7-bit addresses present on the bus."""
        return list(self._i2c.scan())

    def delay_ms(self, ms):
        time.sleep_ms(int(ms))

    def close(self):
        """No-op on MicroPython (the garbage collector owns the bus);
        provided so portable code can call close() on both platforms."""
        pass
