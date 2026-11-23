"""Shared device core for the EMC2101 (platform-neutral).

M2 scope: lifecycle only - constructor binding (transport, address, config
path), verify(), probe(), scan(), close(), context manager. The protocol
level API (temperatures, fan control, LUT, alerts, persistence) lands in
later milestones on this same class.

The transport is a duck-typed object implementing the single-byte contract:
    read_byte(reg) -> int
    write_byte(reg, value) -> None
    probe() -> bool
    scan() -> iterable[int]
    delay_ms(ms) -> None
    close() -> None
"""

from ._regs import (ADDR_FIXED, MANUF_ID_SMSC, PRODUCT_ID_PLAIN,
                    PRODUCT_ID_R, REVISION_EXPECTED, REG_MANUF_ID,
                    REG_PRODUCT_ID, REG_REVISION)


class EMC2101:
    """EMC2101 driver core bound to a transport object."""

    def __init__(self, transport, addr=ADDR_FIXED, config_file=None):
        """Bind a transport and record the configuration file path.

        addr must be the fixed SMBus address 0x4C (ValueError otherwise).
        config_file is the resolved JSON config path owned by the facade
        (save/load semantics land in M4; the attribute exists now so the
        public surface is stable from M2).
        """
        if addr != ADDR_FIXED:
            raise ValueError("EMC2101 SMBus address is fixed at %#x"
                             % ADDR_FIXED)
        self._t = transport
        self.addr = addr
        self.config_path = config_file

    def verify(self):
        """Read the identity trio (FDh/FEh/FFh) and check it against the
        expected SMSC EMC2101 values.

        Returns the product-ID byte on success (0x16 plain / 0x28 -R; both
        share the register map, and the -R EEPROM auto-load is simulated by
        this driver's JSON persistence). Raises ValueError on an identity
        mismatch and OSError if the device does not respond.
        """
        product = self._t.read_byte(REG_PRODUCT_ID)
        manuf = self._t.read_byte(REG_MANUF_ID)
        revision = self._t.read_byte(REG_REVISION)
        if manuf != MANUF_ID_SMSC or revision != REVISION_EXPECTED \
                or product not in (PRODUCT_ID_PLAIN, PRODUCT_ID_R):
            raise ValueError("unexpected identity: fd=%#02x fe=%#02x "
                             "ff=%#02x" % (product, manuf, revision))
        return product

    def probe(self):
        """True if the device answers at its address (single attempt, no
        retry ladder - diagnostics must stay fast)."""
        return self._t.probe()

    def scan(self):
        """Addresses present on the bus (delegates to the transport)."""
        return self._t.scan()

    def close(self):
        """Release platform resources (no-op on MicroPython)."""
        self._t.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False
