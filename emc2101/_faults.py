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


class ConfigFormatError(ValueError):
    """A config file cannot be parsed as schema-v1 JSON.

    Raised by the persistence layer (``decode``) for malformed JSON
    text, a non-object root, unknown or missing top-level sections, and
    an unsupported schema version. Always raised before any register
    write; the chip is untouched."""
    pass


class ConfigValidationError(ValueError):
    """A config file parses but fails semantic validation.

    Raised by the persistence layer for out-of-range fields, unknown
    section keys, a descending LUT, a pwm_freq_hz inconsistent with the
    stored PWM fields, spin_up enabled/time disagreement, and a
    product-ID stamp that does not match the device. Like
    ConfigFormatError it is raised before any register write; the chip
    is untouched."""
    pass


class ConfigApplyError(OSError):
    """Applying a validated config failed on the bus.

    Wraps the transport's OSError from mid-apply (a write, or the
    strict post-apply read-back), including a non-empty strict diff:
    the chip accepted the traffic but did not hold every value. The
    chip may be left partially configured - fix the bus condition and
    re-run load_config (or power-cycle first)."""
    pass
