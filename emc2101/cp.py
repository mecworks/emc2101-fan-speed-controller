"""CPython / Linux SBC entry point.

Usage (Raspberry Pi 3A+, any Linux box with I2C enabled):
    from emc2101.cp import EMC2101
    dev = EMC2101(bus=1)
Requires smbus2 (pip install smbus2) or the system python3-smbus package.

Every name in ``__all__`` is importable from this module; the list mirrors
``emc2101.mp.__all__`` exactly (enforced by tests/test_api_parity.py).
"""

import os

from ._core import EMC2101 as _Core
from ._transport_cp import TransportCP
from ._regs import (
    ADDR_FIXED, ARA_GENERAL_CALL,
    PRODUCT_ID_PLAIN, PRODUCT_ID_R, MANUF_ID_SMSC, REVISION_EXPECTED,
    RETRY_DELAYS_MS,
    REG_INT_TEMP, REG_EXT_TEMP_MSB, REG_STATUS, REG_CONFIG, REG_CONFIG_ALIAS,
    REG_CONV_RATE, REG_CONV_RATE_ALIAS, REG_INT_LIMIT, REG_INT_LIMIT_ALIAS,
    REG_EXT_HIGH_MSB, REG_EXT_HIGH_MSB_ALIAS, REG_EXT_LOW_MSB,
    REG_EXT_LOW_MSB_ALIAS, REG_EXT_FORCE, REG_ONE_SHOT, REG_EXT_TEMP_LSB,
    REG_SCRATCHPAD_1, REG_SCRATCHPAD_2, REG_EXT_HIGH_LSB, REG_EXT_LOW_LSB,
    REG_ALERT_MASK, REG_IDEALITY, REG_BETA, REG_TCRIT, REG_TCRIT_HYST,
    REG_TACH_LO, REG_TACH_HI, REG_TACH_LIMIT_LO, REG_TACH_LIMIT_HI,
    REG_FAN_CFG, REG_SPINUP, REG_FAN_SETTING, REG_PWM_F, REG_PWM_D,
    REG_LUT_HYST, REG_LUT_BASE, REG_LUT_END, REG_FILTER, REG_PRODUCT_ID,
    REG_MANUF_ID, REG_REVISION,
    ST_BUSY, ST_INT_HIGH, ST_EEPROM, ST_EXT_HIGH, ST_EXT_LOW, ST_FAULT,
    ST_TCRIT, ST_TACH,
    CFG_MASK, CFG_STANDBY, CFG_FAN_STANDBY, CFG_DAC, CFG_DIS_TO,
    CFG_ALT_TCH, CFG_TCRITOVRD, CFG_QUEUE,
    AMSK_INT, AMSK_HIGH, AMSK_LOW, AMSK_TCRIT, AMSK_TACH, AMSK_DEFINED,
    AMSK_RESERVED,
    FCFG_FORCE, FCFG_PROG, FCFG_POLARITY, FCFG_CLK_SEL, FCFG_CLK_OVR,
    FCFG_TACH_M_MASK, TACH_M_FALSE_BELOW_MIN, TACH_M_SENTINEL_BELOW_MIN,
    SU_FAST_TACH, SU_SPIN_DRIVE_MASK, SU_SPIN_TIME_MASK, SU_DRIVE_BYPASS,
    SU_DRIVE_50, SU_DRIVE_75, SU_DRIVE_100,
    FLT_LEVEL_MASK, FLT_LEVEL_OFF, FLT_LEVEL_1, FLT_LEVEL_1_ALT,
    FLT_LEVEL_2, FLT_COMP,
    BETA_ENABLE, BETA_FIELD_MASK, BETA_DISABLE_AUTODETECT,
    RPM_DIVISOR, EXT_TEMP_STEP_C, INT_TEMP_STEP_C, TEMP_RANGE_MIN_C,
    TEMP_RANGE_MAX_C, SENTINEL_OPEN_RAW, SENTINEL_SHORT_RAW, TACH_SENTINEL,
    BASE_CLOCK_360K_HZ, BASE_CLOCK_1P4K_HZ, PWM_F_MAX, LUT_ENTRIES,
    LUT_PAIR_STRIDE,
    ext_temp_to_raw, ext_raw_to_temp, int_temp_to_raw, int_raw_to_temp,
    duty_pct_to_setting, setting_to_duty_pct, rpm_from_count,
    count_from_rpm,
)
from ._tables import (
    POR_DEFAULTS, LUT_POR_T, LUT_POR_S,
    IDEALITY_SETTINGS_MIN, IDEALITY_SETTINGS_MAX, IDEALITY_FACTORS,
    ideality_factor,
    CONV_RATES_PER_S, CONV_RATE_DEFAULT_INDEX, TCONV_INTERNAL_MS,
    TCONV_EXTERNAL_MS, conv_rate_encode,
    SPINUP_TIMES_S, spinup_time,
    BETA_MINIMUM_VALUES, BETA_DISABLED_ENCODING,
)

# Default JSON config path on CPython/Linux (decision O4: ~/emc2101.json,
# expanded). Kept private: the public surface exposes it through the
# device's config_path attribute, and the two facades deliberately differ
# here (MP uses the literal /emc2101.json).
_DEFAULT_CONFIG_PATH = os.path.expanduser("~/emc2101.json")

__all__ = [
    "EMC2101",
    "ADDR_FIXED", "ARA_GENERAL_CALL",
    "PRODUCT_ID_PLAIN", "PRODUCT_ID_R", "MANUF_ID_SMSC", "REVISION_EXPECTED",
    "RETRY_DELAYS_MS",
    "REG_INT_TEMP", "REG_EXT_TEMP_MSB", "REG_STATUS", "REG_CONFIG",
    "REG_CONFIG_ALIAS", "REG_CONV_RATE", "REG_CONV_RATE_ALIAS",
    "REG_INT_LIMIT", "REG_INT_LIMIT_ALIAS", "REG_EXT_HIGH_MSB",
    "REG_EXT_HIGH_MSB_ALIAS", "REG_EXT_LOW_MSB", "REG_EXT_LOW_MSB_ALIAS",
    "REG_EXT_FORCE", "REG_ONE_SHOT", "REG_EXT_TEMP_LSB", "REG_SCRATCHPAD_1",
    "REG_SCRATCHPAD_2", "REG_EXT_HIGH_LSB", "REG_EXT_LOW_LSB",
    "REG_ALERT_MASK", "REG_IDEALITY", "REG_BETA", "REG_TCRIT",
    "REG_TCRIT_HYST", "REG_TACH_LO", "REG_TACH_HI", "REG_TACH_LIMIT_LO",
    "REG_TACH_LIMIT_HI", "REG_FAN_CFG", "REG_SPINUP", "REG_FAN_SETTING",
    "REG_PWM_F", "REG_PWM_D", "REG_LUT_HYST", "REG_LUT_BASE", "REG_LUT_END",
    "REG_FILTER", "REG_PRODUCT_ID", "REG_MANUF_ID", "REG_REVISION",
    "ST_BUSY", "ST_INT_HIGH", "ST_EEPROM", "ST_EXT_HIGH", "ST_EXT_LOW",
    "ST_FAULT", "ST_TCRIT", "ST_TACH",
    "CFG_MASK", "CFG_STANDBY", "CFG_FAN_STANDBY", "CFG_DAC", "CFG_DIS_TO",
    "CFG_ALT_TCH", "CFG_TCRITOVRD", "CFG_QUEUE",
    "AMSK_INT", "AMSK_HIGH", "AMSK_LOW", "AMSK_TCRIT", "AMSK_TACH",
    "AMSK_DEFINED", "AMSK_RESERVED",
    "FCFG_FORCE", "FCFG_PROG", "FCFG_POLARITY", "FCFG_CLK_SEL",
    "FCFG_CLK_OVR", "FCFG_TACH_M_MASK", "TACH_M_FALSE_BELOW_MIN",
    "TACH_M_SENTINEL_BELOW_MIN",
    "SU_FAST_TACH", "SU_SPIN_DRIVE_MASK", "SU_SPIN_TIME_MASK",
    "SU_DRIVE_BYPASS", "SU_DRIVE_50", "SU_DRIVE_75", "SU_DRIVE_100",
    "FLT_LEVEL_MASK", "FLT_LEVEL_OFF", "FLT_LEVEL_1", "FLT_LEVEL_1_ALT",
    "FLT_LEVEL_2", "FLT_COMP",
    "BETA_ENABLE", "BETA_FIELD_MASK", "BETA_DISABLE_AUTODETECT",
    "RPM_DIVISOR", "EXT_TEMP_STEP_C", "INT_TEMP_STEP_C", "TEMP_RANGE_MIN_C",
    "TEMP_RANGE_MAX_C", "SENTINEL_OPEN_RAW", "SENTINEL_SHORT_RAW",
    "TACH_SENTINEL", "BASE_CLOCK_360K_HZ", "BASE_CLOCK_1P4K_HZ",
    "PWM_F_MAX", "LUT_ENTRIES", "LUT_PAIR_STRIDE",
    "ext_temp_to_raw", "ext_raw_to_temp", "int_temp_to_raw",
    "int_raw_to_temp", "duty_pct_to_setting", "setting_to_duty_pct",
    "rpm_from_count", "count_from_rpm",
    "POR_DEFAULTS", "LUT_POR_T", "LUT_POR_S",
    "IDEALITY_SETTINGS_MIN", "IDEALITY_SETTINGS_MAX", "IDEALITY_FACTORS",
    "ideality_factor",
    "CONV_RATES_PER_S", "CONV_RATE_DEFAULT_INDEX", "TCONV_INTERNAL_MS",
    "TCONV_EXTERNAL_MS", "conv_rate_encode",
    "SPINUP_TIMES_S", "spinup_time",
    "BETA_MINIMUM_VALUES", "BETA_DISABLED_ENCODING",
]


class EMC2101(_Core):
    """EMC2101 driver bound to a Linux SMBus/I2C bus."""

    def __init__(self, bus=1, addr=ADDR_FIXED, handle=None,
                 config_file=None):
        """Bind to a Linux SMBus/I2C bus (smbus2).

        bus is the bus number (e.g. 1 for /dev/i2c-1); addr must be the
        fixed SMBus address 0x4C (ValueError otherwise). Pass an existing
        smbus2.SMBus object as handle to adopt it instead of opening one
        (then close() will not release it). config_file overrides the
        default JSON config path (M4).
        """
        super().__init__(TransportCP(bus, addr, handle), addr,
                         config_file if config_file is not None
                         else _DEFAULT_CONFIG_PATH)
