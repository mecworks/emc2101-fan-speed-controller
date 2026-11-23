"""Pure data tables for the EMC2101 driver.

- Factory power-on defaults per register (datasheet S6 register tables;
  plain EMC2101).
- Ideality factor look-up, Table 6.13: defines settings 0x08..0x37 ONLY
  (48 entries); the remaining six-bit codes are undefined in the datasheet.
  (Research note correction: the field is 6 bits wide, but the published
  table covers 48 of the 64 codes.)
- Conversion rate table, Table 6.6.
- Spin-up time encodings (S6.17) and CPU beta values, Table 6.15.

Imports only _regs (leaf data dependency).
"""

from ._regs import (
    REG_ALERT_MASK, REG_BETA, REG_CONFIG, REG_CONV_RATE, REG_EXT_FORCE,
    REG_EXT_HIGH_LSB, REG_EXT_HIGH_MSB, REG_EXT_LOW_LSB, REG_EXT_LOW_MSB,
    REG_FAN_CFG, REG_FAN_SETTING, REG_FILTER, REG_INT_LIMIT, REG_LUT_HYST,
    REG_PWM_D, REG_PWM_F, REG_SPINUP, REG_TACH_LIMIT_HI, REG_TACH_LIMIT_LO,
    REG_TCRIT, REG_TCRIT_HYST, REG_IDEALITY,
)

# --- Factory power-on defaults (plain EMC2101) -------------------------------
# RO registers (INT_TEMP, EXT_TEMP_*, TACH readings, identity) are omitted:
# they carry no configurable state.
POR_DEFAULTS = {
    REG_CONFIG: 0x00,
    REG_CONV_RATE: 0x08,        # 16/s
    REG_INT_LIMIT: 0x46,        # +70 C
    REG_EXT_HIGH_MSB: 0x46,     # +70 C (with LSB 0x00)
    REG_EXT_LOW_MSB: 0x00,      #   0 C (with LSB 0x00)
    REG_EXT_FORCE: 0x00,
    REG_EXT_HIGH_LSB: 0x00,
    REG_EXT_LOW_LSB: 0x00,
    REG_ALERT_MASK: 0xA4,       # reserved bits 7,5,2 read as 1
    REG_IDEALITY: 0x12,         # 1.0080
    REG_BETA: 0x08,             # autodetect enabled
    REG_TCRIT: 0x55,            # +85 C (locked at POR)
    REG_TCRIT_HYST: 0x0A,       # 10 C
    REG_TACH_LIMIT_LO: 0xFF,    # FFFFh => effectively disabled
    REG_TACH_LIMIT_HI: 0xFF,
    REG_FAN_CFG: 0x20,          # PROG=1 (manual)
    REG_SPINUP: 0x3F,           # FAST_TACH, 100% drive, 3.2 s
    REG_FAN_SETTING: 0x00,      # 0% setting (fan floor speed applies)
    REG_PWM_F: 0x17,
    REG_PWM_D: 0x01,
    REG_LUT_HYST: 0x04,         # 4 C
    REG_FILTER: 0x00,           # filter off, interrupt mode
}

# LUT power-on state: all eight entries inactive (T=127 C, S=max drive).
LUT_POR_T = 0x7F
LUT_POR_S = 0x3F

# --- Ideality factor look-up (Table 6.13) -------------------------------------
IDEALITY_SETTINGS_MIN = 0x08
IDEALITY_SETTINGS_MAX = 0x37
# Index = setting - IDEALITY_SETTINGS_MIN. Values verbatim from Table 6.13.
IDEALITY_FACTORS = (
    0.9949, 0.9962, 0.9975, 0.9988, 1.0001, 1.0014, 1.0027, 1.0040,
    1.0053, 1.0066, 1.0080, 1.0093, 1.0106, 1.0119, 1.0133, 1.0146,
    1.0159, 1.0172, 1.0185, 1.0200, 1.0212, 1.0226, 1.0239, 1.0253,
    1.0267, 1.0280, 1.0293, 1.0306, 1.0319, 1.0332, 1.0345, 1.0358,
    1.0371, 1.0384, 1.0397, 1.0410, 1.0423, 1.0436, 1.0449, 1.0462,
    1.0475, 1.0488, 1.0501, 1.0514, 1.0527, 1.0540, 1.0553, 1.0566,
)


def ideality_factor(setting):
    """Ideality factor for a 6-bit IDCF setting.

    Table 6.13 defines settings 0x08..0x37 only; other codes are undefined
    in the datasheet and raise ValueError."""
    idx = setting - IDEALITY_SETTINGS_MIN
    if idx < 0 or idx >= len(IDEALITY_FACTORS):
        raise ValueError("ideality setting %#x undefined "
                         "(table covers 0x08..0x37)" % (setting,))
    return IDEALITY_FACTORS[idx]


# --- Conversion rate (Table 6.6) ----------------------------------------------
# CONV[3:0] -> conversions per second. Indices 10..15 all map to 32/s.
CONV_RATES_PER_S = (
    0.0625, 0.125, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0,
    16.0, 32.0, 32.0, 32.0, 32.0, 32.0, 32.0, 32.0,
)
CONV_RATE_DEFAULT_INDEX = 8    # 16/s at POR
TCONV_INTERNAL_MS = 3          # internal channel conversion time
TCONV_EXTERNAL_MS = 21         # external channel conversion time


def conv_rate_encode(rate_per_s):
    """CONV[3:0] index whose rate is nearest the requested conversions/s.

    Ties resolve to the slower (lower-index) rate. Raises ValueError for
    non-positive rates."""
    if rate_per_s <= 0:
        raise ValueError("rate must be > 0")
    best_idx = 0
    best_err = None
    for i, r in enumerate(CONV_RATES_PER_S):
        err = abs(r - rate_per_s)
        if best_err is None or err < best_err:
            best_idx = i
            best_err = err
    return best_idx


# --- Spin-up (S6.17) -----------------------------------------------------------
# SPIN_TIME[2:0] -> seconds; encoding 0 means bypass (no spin-up phase).
SPINUP_TIMES_S = (None, 0.05, 0.1, 0.2, 0.4, 0.8, 1.6, 3.2)


def spinup_time(encoding):
    """Spin-up duration in seconds for a SPIN_TIME[2:0] encoding.

    Returns None for the bypass encoding (0)."""
    if not 0 <= encoding <= 7:
        raise ValueError("spin-up time encoding must be 0..7")
    return SPINUP_TIMES_S[encoding]


# --- CPU beta values (Table 6.15) ---------------------------------------------
# BETA[2:0] -> minimum substrate-transistor beta covered by that setting.
# Encoding 7 disables compensation; ENABLE=1 selects automatic detection.
BETA_MINIMUM_VALUES = (0.11, 0.18, 0.25, 0.33, 0.43, 1.00, 2.33)
BETA_DISABLED_ENCODING = 0x07
