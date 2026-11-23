"""Typed exceptions for the EMC2101 driver.

Kept in its own leaf module so the facades can re-export the exception
types without pulling in the device core.
"""


class DiodeFaultError(OSError):
    """External-diode fault condition (open circuit or short).

    Raised by ``remote_temp_c`` when a conversion returns a fault
    sentinel (raw 0x3F8 open / 0x3FF short). It is a hardware condition,
    not a bad argument, hence a typed OSError rather than ValueError
    (decision D13)."""
    pass
