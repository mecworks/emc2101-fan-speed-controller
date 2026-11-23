"""Public-surface pinning: every name exported by the facades (__all__)
is referenced here by literal name, with constants pinned to their
datasheet Rev 2.54 values on BOTH facades. Two jobs at once:

- regression protection: a constant drifting from its datasheet value
  fails this suite;
- coverage gate support: tools/api_coverage.py scans the test sources
  for literal name references, so this file keeps the surface fully
  exercised as it grows (the drift guard below enforces that).
"""
import unittest

import emc2101.cp as cp_mod
import emc2101.mp as mp_mod

# --- Pinned constant values (datasheet Rev 2.54) -----------------------------
EXPECTED_VALUES = {
    # bus / identity
    "ADDR_FIXED": 0x4C,
    "ARA_GENERAL_CALL": 0x06,
    "PRODUCT_ID_PLAIN": 0x16,
    "PRODUCT_ID_R": 0x28,
    "MANUF_ID_SMSC": 0x5D,
    "REVISION_EXPECTED": 0x01,
    "RETRY_DELAYS_MS": (10, 30, 60, 100, 200, 400),
    # register addresses
    "REG_INT_TEMP": 0x00,
    "REG_EXT_TEMP_MSB": 0x01,
    "REG_STATUS": 0x02,
    "REG_CONFIG": 0x03,
    "REG_CONFIG_ALIAS": 0x09,
    "REG_CONV_RATE": 0x04,
    "REG_CONV_RATE_ALIAS": 0x0A,
    "REG_INT_LIMIT": 0x05,
    "REG_INT_LIMIT_ALIAS": 0x0B,
    "REG_EXT_HIGH_MSB": 0x07,
    "REG_EXT_HIGH_MSB_ALIAS": 0x0D,
    "REG_EXT_LOW_MSB": 0x08,
    "REG_EXT_LOW_MSB_ALIAS": 0x0E,
    "REG_EXT_FORCE": 0x0C,
    "REG_ONE_SHOT": 0x0F,
    "REG_EXT_TEMP_LSB": 0x10,
    "REG_SCRATCHPAD_1": 0x11,
    "REG_SCRATCHPAD_2": 0x12,
    "REG_EXT_HIGH_LSB": 0x13,
    "REG_EXT_LOW_LSB": 0x14,
    "REG_ALERT_MASK": 0x16,
    "REG_IDEALITY": 0x17,
    "REG_BETA": 0x18,
    "REG_TCRIT": 0x19,
    "REG_TCRIT_HYST": 0x21,
    "REG_TACH_LO": 0x46,
    "REG_TACH_HI": 0x47,
    "REG_TACH_LIMIT_LO": 0x48,
    "REG_TACH_LIMIT_HI": 0x49,
    "REG_FAN_CFG": 0x4A,
    "REG_SPINUP": 0x4B,
    "REG_FAN_SETTING": 0x4C,
    "REG_PWM_F": 0x4D,
    "REG_PWM_D": 0x4E,
    "REG_LUT_HYST": 0x4F,
    "REG_LUT_BASE": 0x50,
    "REG_LUT_END": 0x5F,
    "REG_FILTER": 0xBF,
    "REG_PRODUCT_ID": 0xFD,
    "REG_MANUF_ID": 0xFE,
    "REG_REVISION": 0xFF,
    # status bits
    "ST_BUSY": 0x80,
    "ST_INT_HIGH": 0x40,
    "ST_EEPROM": 0x20,
    "ST_EXT_HIGH": 0x10,
    "ST_EXT_LOW": 0x08,
    "ST_FAULT": 0x04,
    "ST_TCRIT": 0x02,
    "ST_TACH": 0x01,
    # configuration bits
    "CFG_MASK": 0x80,
    "CFG_STANDBY": 0x40,
    "CFG_FAN_STANDBY": 0x20,
    "CFG_DAC": 0x10,
    "CFG_DIS_TO": 0x08,
    "CFG_ALT_TCH": 0x04,
    "CFG_TCRITOVRD": 0x02,
    "CFG_QUEUE": 0x01,
    # alert mask bits
    "AMSK_INT": 0x40,
    "AMSK_HIGH": 0x10,
    "AMSK_LOW": 0x08,
    "AMSK_TCRIT": 0x02,
    "AMSK_TACH": 0x01,
    "AMSK_DEFINED": 0x5B,
    "AMSK_RESERVED": 0xA4,
    # fan configuration bits
    "FCFG_FORCE": 0x40,
    "FCFG_PROG": 0x20,
    "FCFG_POLARITY": 0x10,
    "FCFG_CLK_SEL": 0x08,
    "FCFG_CLK_OVR": 0x04,
    "FCFG_TACH_M_MASK": 0x03,
    "TACH_M_FALSE_BELOW_MIN": 0x00,
    "TACH_M_SENTINEL_BELOW_MIN": 0x01,
    # spin-up fields
    "SU_FAST_TACH": 0x20,
    "SU_SPIN_DRIVE_MASK": 0x18,
    "SU_SPIN_TIME_MASK": 0x07,
    "SU_DRIVE_BYPASS": 0x00,
    "SU_DRIVE_50": 0x08,
    "SU_DRIVE_75": 0x10,
    "SU_DRIVE_100": 0x18,
    # averaging filter fields
    "FLT_LEVEL_MASK": 0x06,
    "FLT_LEVEL_OFF": 0x00,
    "FLT_LEVEL_1": 0x02,
    "FLT_LEVEL_1_ALT": 0x04,
    "FLT_LEVEL_2": 0x06,
    "FLT_COMP": 0x01,
    # beta compensation fields
    "BETA_ENABLE": 0x08,
    "BETA_FIELD_MASK": 0x07,
    "BETA_DISABLE_AUTODETECT": 0x07,
    # M3 public enums
    "ALERT_MODE_INTERRUPT": 0,
    "ALERT_MODE_COMPARATOR": 1,
    "FILTER_OFF": 0,
    "FILTER_LEVEL_1": 1,
    "FILTER_LEVEL_2": 2,
    # physical constants
    "RPM_DIVISOR": 5400000,
    "EXT_TEMP_STEP_C": 0.125,
    "INT_TEMP_STEP_C": 1.0,
    "TEMP_RANGE_MIN_C": -64.0,
    "TEMP_RANGE_MAX_C": 127.875,
    "SENTINEL_OPEN_RAW": 0x3F8,
    "SENTINEL_SHORT_RAW": 0x3FF,
    "TACH_SENTINEL": 0xFFFF,
    "BASE_CLOCK_360K_HZ": 360000,
    "BASE_CLOCK_1P4K_HZ": 1400,
    "PWM_F_MAX": 31,
    "LUT_ENTRIES": 8,
    "LUT_PAIR_STRIDE": 2,
    # table scalars
    "LUT_POR_T": 0x7F,
    "LUT_POR_S": 0x3F,
    "IDEALITY_SETTINGS_MIN": 0x08,
    "IDEALITY_SETTINGS_MAX": 0x37,
    "CONV_RATE_DEFAULT_INDEX": 8,
    "TCONV_INTERNAL_MS": 3,
    "TCONV_EXTERNAL_MS": 21,
    "BETA_DISABLED_ENCODING": 0x07,
}

FUNCTION_NAMES = (
    "ext_temp_to_raw", "ext_raw_to_temp", "int_temp_to_raw",
    "int_raw_to_temp", "duty_pct_to_setting", "setting_to_duty_pct",
    "rpm_from_count", "count_from_rpm", "ideality_factor",
    "conv_rate_encode", "spinup_time",
)

COLLECTION_NAMES = (
    "POR_DEFAULTS", "IDEALITY_FACTORS", "CONV_RATES_PER_S",
    "SPINUP_TIMES_S", "BETA_MINIMUM_VALUES",
)

EXCEPTION_NAMES = (
    "DiodeFaultError",
)

# --- Device-class public surface (M3) ---------------------------------------
# Every public attribute of the device class, pinned so the coverage gate
# keeps exercising the whole API as it grows.
EXPECTED_CLASS_MEMBERS = frozenset((
    # lifecycle & raw access
    "close", "probe", "read_reg", "scan", "verify", "write_reg",
    # identity
    "mfg_id", "part_info", "product_id", "revision",
    # temperatures & setpoints
    "local_high_c", "local_temp_c", "remote_high_c", "remote_low_c",
    "remote_temp_c", "tcrit_c", "tcrit_hysteresis_c",
    # status & alerts
    "active_alarms", "alert_mask", "alert_mode", "busy",
    "clear_alert_mask", "diode_fault", "service_alert", "status_raw",
    # manual mode & duty
    "duty_cmd_raw", "manual", "set_duty_pct",
    # PWM / DAC output configuration
    "dac_enabled", "fan_output_inverted", "pwm_clk_sel", "pwm_div",
    "pwm_freq_hz",
    # LUT
    "force_enabled", "forced_temp_c", "hysteresis_c", "lut",
    "lut_get_index", "lut_set_index",
    # tachometer & RPM
    "min_rpm", "rpm", "tach_input_enabled", "tach_mode", "tach_threshold",
    # spin-up
    "spin_up_drive", "spin_up_enabled", "spin_up_fast_tach",
    "spin_up_time_s",
    # calibration
    "beta_auto_detect", "beta_index", "ideality_factor",
    "ideality_factor_index", "set_ideality_factor",
    # scratchpad
    "scratchpad_get", "scratchpad_set",
    # power modes & conversion control
    "averaging_filter", "conversion_rate", "dis_to_enabled",
    "fault_queue_enabled", "fan_standby", "one_shot", "standby",
    # presets
    "configure_4wire_fan",
))


class PublicSurfaceTestCase(unittest.TestCase):
    def test_pinned_tables_track_the_exported_surface(self):
        """Drift guard: EXPECTED_VALUES + functions + collections + the
        device class must cover __all__ exactly. Adding an export without
        pinning it here fails this test."""
        exported = set(mp_mod.__all__)
        pinned = (set(EXPECTED_VALUES) | set(FUNCTION_NAMES)
                  | set(COLLECTION_NAMES) | set(EXCEPTION_NAMES)
                  | {"EMC2101"})
        self.assertEqual(exported, pinned)

    def test_device_class_surface_is_pinned(self):
        """Drift guard: the public attributes of the device class must
        match EXPECTED_CLASS_MEMBERS exactly (both facades inherit the
        same core). Adding/removing a member without updating the pin
        fails this test."""
        actual = frozenset(n for n in dir(mp_mod.EMC2101)
                           if not n.startswith("_"))
        self.assertEqual(actual, EXPECTED_CLASS_MEMBERS)

    def test_exceptions_are_oserror_subclasses_on_both_facades(self):
        for name in EXCEPTION_NAMES:
            with self.subTest(name=name):
                self.assertTrue(issubclass(getattr(mp_mod, name), OSError))
                self.assertTrue(issubclass(getattr(cp_mod, name), OSError))

    def test_constants_match_datasheet_on_both_facades(self):
        for name, want in sorted(EXPECTED_VALUES.items()):
            with self.subTest(name=name):
                self.assertEqual(getattr(mp_mod, name), want)
                self.assertEqual(getattr(cp_mod, name), want)

    def test_functions_are_callable_on_both_facades(self):
        for name in FUNCTION_NAMES:
            with self.subTest(name=name):
                self.assertTrue(callable(getattr(mp_mod, name)))
                self.assertTrue(callable(getattr(cp_mod, name)))

    def test_collections_have_expected_shapes(self):
        self.assertIsInstance(mp_mod.POR_DEFAULTS, dict)
        self.assertEqual(len(mp_mod.IDEALITY_FACTORS), 48)
        self.assertEqual(len(mp_mod.CONV_RATES_PER_S), 16)
        self.assertEqual(len(mp_mod.SPINUP_TIMES_S), 8)
        self.assertEqual(len(mp_mod.BETA_MINIMUM_VALUES), 7)

    def test_device_classes_share_a_common_base(self):
        self.assertTrue(issubclass(mp_mod.EMC2101, cp_mod.EMC2101.__bases__[0]))


if __name__ == "__main__":
    unittest.main()
