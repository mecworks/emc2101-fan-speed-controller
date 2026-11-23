"""JSON persistence layer ("virtual EEPROM") for the EMC2101.

Implements decisions D4/D13-D16 and ``research/03-persistence-opinion.md``
section 5. The -R variant's EEPROM auto-load is simulated: a human-readable,
versioned JSON file holds the decodable configuration, and the driver
applies it on request (or at construction when opted in).

This module is filesystem-agnostic: ``encode``/``decode`` are pure functions
and ``collect_state``/``apply_state`` take plain ``read_byte``/``write_byte``
callables, so the whole layer unit-tests against fakes on any platform.
File I/O glue (path resolution, atomic write) lives on the device core:
``save_config``/``load_config``.

Schema v1 stores SEMANTIC (decoded) values, not raw registers: units are in
the names (``*_c``, ``*_pct``, ``*_hz``, ``*_s``), the PWM frequency is
stored together with its governing fields so application is deterministic,
and the identity trio is stamped so a profile saved for one part family is
refused on another. Transient state (Status latches, temperatures, TACH
counts) is deliberately NOT persisted.
"""

import json
import time

from ._regs import (AMSK_DEFINED, AMSK_HIGH, AMSK_INT, AMSK_LOW, AMSK_TACH,
                    AMSK_TCRIT, BETA_ENABLE, BETA_FIELD_MASK,
                    BASE_CLOCK_1P4K_HZ, BASE_CLOCK_360K_HZ, CFG_DAC,
                    CFG_DIS_TO, CFG_QUEUE, CFG_STANDBY, CFG_TCRITOVRD,
                    CFG_FAN_STANDBY, CFG_ALT_TCH, FCFG_CLK_OVR, FCFG_CLK_SEL,
                    FCFG_FORCE, FCFG_POLARITY, FCFG_PROG, FCFG_TACH_M_MASK,
                    FLT_COMP, FLT_LEVEL_1, FLT_LEVEL_1_ALT, FLT_LEVEL_2,
                    FLT_LEVEL_MASK, FLT_LEVEL_OFF, LUT_ENTRIES,
                    REG_ALERT_MASK, REG_BETA, REG_CONFIG, REG_CONV_RATE,
                    REG_EXT_FORCE, REG_EXT_HIGH_LSB, REG_EXT_HIGH_MSB,
                    REG_EXT_LOW_LSB, REG_EXT_LOW_MSB, REG_EXT_TEMP_LSB,
                    REG_EXT_TEMP_MSB, REG_FAN_CFG, REG_FAN_SETTING,
                    REG_FILTER, REG_IDEALITY, REG_INT_LIMIT, REG_INT_TEMP,
                    REG_LUT_BASE, REG_LUT_HYST, REG_MANUF_ID, REG_ONE_SHOT,
                    REG_PRODUCT_ID, REG_PWM_D, REG_PWM_F, REG_REVISION,
                    REG_SCRATCHPAD_1, REG_SCRATCHPAD_2, REG_SPINUP,
                    REG_STATUS, REG_TACH_HI, REG_TACH_LIMIT_HI,
                    REG_TACH_LIMIT_LO, REG_TACH_LO, REG_TCRIT, REG_TCRIT_HYST,
                    SU_DRIVE_100, SU_DRIVE_50, SU_DRIVE_75, SU_DRIVE_BYPASS,
                    SU_FAST_TACH, SU_SPIN_DRIVE_MASK, SU_SPIN_TIME_MASK,
                    ext_raw_to_temp, ext_temp_to_raw, int_raw_to_temp,
                    int_temp_to_raw, setting_to_duty_pct,
                    duty_pct_to_setting)
from ._tables import (CONV_RATES_PER_S, IDEALITY_SETTINGS_MAX,
                      IDEALITY_SETTINGS_MIN, SPINUP_TIMES_S,
                      conv_rate_encode)

#: Version of the JSON schema implemented by this module.
SCHEMA_VERSION = 1

#: TCRIT's power-on locked value in C (the one-time unlock rule pivots on it).
TCRIT_LOCKED_C = 85

_TOP_KEYS = ("schema_version", "saved_at_utc", "device", "config", "limits",
             "lut", "fan", "calibration", "misc")
_DEVICE_KEYS = ("product_id", "mfg_id", "revision")
_CONFIG_KEYS = ("standby", "fan_standby", "dac_enabled", "dis_to",
                "tach_input", "queue_3sample", "alert_mode", "alert_mask")
_AMSK_KEYS = ("int", "high", "low", "tcrit", "tach")
_LIMITS_KEYS = ("local_high_c", "remote_high_c", "remote_low_c", "tcrit_c",
                "tcrit_hysteresis_c")
_LUT_KEYS = ("hysteresis_c", "entries")
_ENTRY_KEYS = ("temp_c", "duty_pct")
_FAN_KEYS = ("manual", "duty_pct", "output_inverted", "clk_sel", "pwm_f",
             "clk_ovr", "pwm_div", "pwm_freq_hz", "spin_up", "force")
_SPINUP_KEYS = ("enabled", "drive_pct", "time_s", "fast_tach")
_FORCE_KEYS = ("enabled", "temp_c")
_CALIB_KEYS = ("ideality_index", "beta_auto_detect", "beta_index")
_MISC_KEYS = ("conversion_rate_per_s", "averaging_filter",
              "tach_limit_count", "scratchpad")

_DRIVE_PCTS = (0, 50, 75, 100)
_DRIVE_ENC = {0: SU_DRIVE_BYPASS, 50: SU_DRIVE_50, 75: SU_DRIVE_75,
              100: SU_DRIVE_100}
_TIME_ENC = {None: 0}
for _i, _t in enumerate(SPINUP_TIMES_S):
    _TIME_ENC[_t] = _i
_FILTER_ENC = {"off": FLT_LEVEL_OFF, "level1": FLT_LEVEL_1,
               "level2": FLT_LEVEL_2}
_HEX_DIGITS = "0123456789abcdefABCDEF"


# --- Small validators --------------------------------------------------------

def _fail(field, msg):
    raise ValueError("%s: %s" % (field, msg))


def _bool(value, field):
    if not isinstance(value, bool):
        _fail(field, "must be a boolean, got %r" % (value,))
    return value


def _int(value, field, lo, hi):
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(field, "must be an integer, got %r" % (value,))
    if not lo <= value <= hi:
        _fail(field, "%r is outside %d..%d" % (value, lo, hi))
    return value


def _num(value, field, lo, hi):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(field, "must be a number, got %r" % (value,))
    if not lo <= value <= hi:
        _fail(field, "%r is outside %g..%g" % (value, lo, hi))
    return value


def _hex_byte(value, field):
    """Validate a '0xNN' identity stamp and return its canonical form.

    Canonical form is lowercase with zero padding (the same shape
    collect_state emits), so decode(encode(state)) == state holds.
    """
    if (not isinstance(value, str) or len(value) != 4
            or value[:2].lower() != "0x"):
        _fail(field, "must be a '0xNN' hex string, got %r" % (value,))
    if not all(c in _HEX_DIGITS for c in value[2:]):
        _fail(field, "%r is not a valid hex byte" % (value,))
    return "0x%02x" % int(value[2:], 16)


def _section(data, name, keys):
    """Return data[name] as a dict whose key set is exactly ``keys``."""
    if name not in data:
        _fail(name, "section missing")
    sec = data[name]
    if not isinstance(sec, dict):
        _fail(name, "must be a JSON object")
    extra = sorted(set(sec) - set(keys))
    missing = sorted(set(keys) - set(sec))
    if extra:
        _fail(name, "unknown key(s) %s" % ", ".join(extra))
    if missing:
        _fail(name, "missing key(s) %s" % ", ".join(missing))
    return sec


def _freq_from_fields(clk_sel, pwm_f, pwm_d, clk_ovr):
    """Achievable PWM frequency (eq. [5]/[6]); mirrors the core solver."""
    if not 1 <= pwm_f <= 31:
        _fail("fan.pwm_f", "must be 1..31")
    denom = 2 * pwm_f
    if not clk_sel:
        if clk_ovr:
            if not 1 <= pwm_d <= 0xFF:
                _fail("fan.pwm_div", "must be 1..255")
            denom *= pwm_d
        return float(BASE_CLOCK_360K_HZ) / denom
    return float(BASE_CLOCK_1P4K_HZ) / denom


def _utc_now():
    t = time.gmtime()
    return "%04d-%02d-%02dT%02d:%02d:%02dZ" % t[:6]


# --- Serialization ------------------------------------------------------------

def encode(state):
    """Serialize a validated state dict to schema-v1 JSON text.

    Key order follows the canonical section order, so repeated encodes of
    the same state produce byte-identical text (round-trip stability).
    Indented where the port's json module supports it; compact otherwise.
    """
    try:
        return json.dumps(state, indent=2)
    except TypeError:
        return json.dumps(state)


def decode(text):
    """Parse and validate schema-v1 JSON text into a state dict.

    Raises ValueError naming the offending field for any structural
    problem: malformed JSON, unknown version, wrong shape, unknown or
    missing keys, out-of-range values, a descending LUT, or a
    pwm_freq_hz inconsistent with the stored PWM fields.

    NOTE on LUT ordering: the WRITE path (core ``lut`` setters) demands
    strictly ascending thresholds because equal programmed thresholds
    shadow each other. The persistence path only forbids DESCENDING
    thresholds, because the factory POR LUT is uniformly 127 C - a legal
    chip state that ``save_config`` must be able to capture and
    ``load_config`` must be able to restore.
    """
    try:
        data = json.loads(text)
    except ValueError:
        raise ValueError("config is not valid JSON")
    if not isinstance(data, dict):
        raise ValueError("config root must be a JSON object")
    extra = sorted(set(data) - set(_TOP_KEYS))
    missing = sorted(set(_TOP_KEYS) - set(data))
    if extra:
        raise ValueError("unknown top-level key(s) %s" % ", ".join(extra))
    if missing:
        raise ValueError("missing top-level key(s) %s" % ", ".join(missing))
    if data["schema_version"] != SCHEMA_VERSION:
        raise ValueError("unsupported schema version %r (want %d)"
                         % (data["schema_version"], SCHEMA_VERSION))
    if not isinstance(data["saved_at_utc"], str) \
            or not data["saved_at_utc"]:
        _fail("saved_at_utc", "must be a non-empty string")

    dev = _section(data, "device", _DEVICE_KEYS)
    cfg = _section(data, "config", _CONFIG_KEYS)
    lim = _section(data, "limits", _LIMITS_KEYS)
    lut = _section(data, "lut", _LUT_KEYS)
    if not isinstance(lut["entries"], list) \
            or len(lut["entries"]) != LUT_ENTRIES:
        _fail("lut.entries", "must be a list of exactly %d entries"
              % LUT_ENTRIES)
    fan = _section(data, "fan", _FAN_KEYS)
    cal = _section(data, "calibration", _CALIB_KEYS)
    mis = _section(data, "misc", _MISC_KEYS)

    amask = _section(cfg, "alert_mask", _AMSK_KEYS)
    spin = _section(fan, "spin_up", _SPINUP_KEYS)
    force = _section(fan, "force", _FORCE_KEYS)

    fan_sec = {
        "manual": _bool(fan["manual"], "fan.manual"),
        "duty_pct": _num(fan["duty_pct"], "fan.duty_pct", 0.0, 100.0),
        "output_inverted": _bool(fan["output_inverted"],
                                 "fan.output_inverted"),
        "clk_sel": _bool(fan["clk_sel"], "fan.clk_sel"),
        "pwm_f": _int(fan["pwm_f"], "fan.pwm_f", 1, 31),
        "clk_ovr": _bool(fan["clk_ovr"], "fan.clk_ovr"),
        "pwm_div": _int(fan["pwm_div"], "fan.pwm_div", 1, 255),
        "pwm_freq_hz": _num(fan["pwm_freq_hz"], "fan.pwm_freq_hz",
                            0.0, 1e9),
        "spin_up": {
            "enabled": _bool(spin["enabled"], "fan.spin_up.enabled"),
            "drive_pct": _drive_pct(spin["drive_pct"]),
            "time_s": _spin_time(spin["time_s"]),
            "fast_tach": _bool(spin["fast_tach"],
                               "fan.spin_up.fast_tach"),
        },
        "force": {
            "enabled": _bool(force["enabled"], "fan.force.enabled"),
            "temp_c": _int(force["temp_c"], "fan.force.temp_c",
                           -128, 127),
        },
    }
    want_hz = _freq_from_fields(fan_sec["clk_sel"], fan_sec["pwm_f"],
                                fan_sec["pwm_div"], fan_sec["clk_ovr"])
    if abs(fan_sec["pwm_freq_hz"] - want_hz) \
            > max(1e-6, 1e-6 * want_hz):
        _fail("fan.pwm_freq_hz",
              "%r is inconsistent with the stored PWM fields (%.6f Hz)"
              % (fan_sec["pwm_freq_hz"], want_hz))
    if fan_sec["spin_up"]["enabled"] \
            != (fan_sec["spin_up"]["time_s"] is not None):
        _fail("fan.spin_up", "'enabled' and 'time_s' disagree "
              "(bypass is encoded as time_s = null)")

    state = {
        "schema_version": SCHEMA_VERSION,
        "saved_at_utc": data["saved_at_utc"],
        "device": {
            "product_id": _hex_byte(dev["product_id"], "device.product_id"),
            "mfg_id": _hex_byte(dev["mfg_id"], "device.mfg_id"),
            "revision": _hex_byte(dev["revision"], "device.revision"),
        },
        "config": {
            "standby": _bool(cfg["standby"], "config.standby"),
            "fan_standby": _bool(cfg["fan_standby"], "config.fan_standby"),
            "dac_enabled": _bool(cfg["dac_enabled"], "config.dac_enabled"),
            "dis_to": _bool(cfg["dis_to"], "config.dis_to"),
            "tach_input": _bool(cfg["tach_input"], "config.tach_input"),
            "queue_3sample": _bool(cfg["queue_3sample"],
                                   "config.queue_3sample"),
            "alert_mode": _alert_mode(cfg["alert_mode"]),
            "alert_mask": {k: _bool(amask[k], "config.alert_mask.%s" % k)
                           for k in _AMSK_KEYS},
        },
        "limits": {
            "local_high_c": _int(lim["local_high_c"], "limits.local_high_c",
                                 -128, 127),
            "remote_high_c": _ext_temp(lim["remote_high_c"],
                                       "limits.remote_high_c"),
            "remote_low_c": _ext_temp(lim["remote_low_c"],
                                      "limits.remote_low_c"),
            "tcrit_c": _int(lim["tcrit_c"], "limits.tcrit_c", 0, 127),
            "tcrit_hysteresis_c": _int(lim["tcrit_hysteresis_c"],
                                       "limits.tcrit_hysteresis_c", 0, 127),
        },
        "lut": {
            "hysteresis_c": _int(lut["hysteresis_c"], "lut.hysteresis_c",
                                 0, 127),
            "entries": [_entry(e, i) for i, e in enumerate(lut["entries"])],
        },
        "fan": fan_sec,
        "calibration": {
            "ideality_index": _ideality(cal["ideality_index"]),
            "beta_auto_detect": _bool(cal["beta_auto_detect"],
                                      "calibration.beta_auto_detect"),
            "beta_index": _int(cal["beta_index"], "calibration.beta_index",
                               0, 7),
        },
        "misc": {
            "conversion_rate_per_s": _conv_rate(mis["conversion_rate_per_s"]),
            "averaging_filter": _filter_name(mis["averaging_filter"]),
            "tach_limit_count": _int(mis["tach_limit_count"],
                                     "misc.tach_limit_count", 0, 0xFFFF),
            "scratchpad": _scratchpad(mis["scratchpad"]),
        },
    }

    # Cross-field invariant: LUT thresholds must not descend (the POR
    # default is uniformly 127 C, so equality is legal here).
    prev = None
    for i, entry in enumerate(state["lut"]["entries"]):
        t = int(round(float(entry["temp_c"])))
        if prev is not None and t < prev:
            _fail("lut.entries[%d].temp_c" % i,
                  "thresholds must not descend (%r after %r)"
                  % (t, prev))
        prev = t
    return state


def _alert_mode(value):
    if value not in ("interrupt", "comparator"):
        _fail("config.alert_mode",
              "must be 'interrupt' or 'comparator', got %r" % (value,))
    return value


def _ext_temp(value, field):
    v = _num(value, field, -64.0, 127.875)
    if abs(v * 8.0 - round(v * 8.0)) > 1e-6:
        _fail(field, "%r is not a multiple of the 0.125 C step" % (value,))
    return v


def _entry(raw, i):
    field = "lut.entries[%d]" % i
    if not isinstance(raw, dict):
        _fail(field, "must be a JSON object")
    extra = sorted(set(raw) - set(_ENTRY_KEYS))
    missing = sorted(set(_ENTRY_KEYS) - set(raw))
    if extra:
        _fail(field, "unknown key(s) %s" % ", ".join(extra))
    if missing:
        _fail(field, "missing key(s) %s" % ", ".join(missing))
    return {
        "temp_c": _int(raw["temp_c"], field + ".temp_c", -128, 127),
        "duty_pct": _num(raw["duty_pct"], field + ".duty_pct", 0.0, 100.0),
    }


def _drive_pct(value):
    if value not in _DRIVE_PCTS:
        _fail("fan.spin_up.drive_pct",
              "must be one of %r, got %r" % (_DRIVE_PCTS, value))
    return value


def _spin_time(value):
    if value is None:
        return None
    v = _num(value, "fan.spin_up.time_s", 0.0, 3.2)
    for t in SPINUP_TIMES_S:
        if t is not None and abs(t - v) < 1e-6:
            return t
    _fail("fan.spin_up.time_s",
          "must be one of %r (or null for bypass), got %r"
          % (SPINUP_TIMES_S[1:], value))


def _ideality(value):
    v = _int(value, "calibration.ideality_index", 0, 0x3F)
    if not IDEALITY_SETTINGS_MIN <= v <= IDEALITY_SETTINGS_MAX:
        _fail("calibration.ideality_index",
              "%r is outside the Table 6.13 range %#x..%#x"
              % (v, IDEALITY_SETTINGS_MIN, IDEALITY_SETTINGS_MAX))
    return v


def _conv_rate(value):
    v = _num(value, "misc.conversion_rate_per_s", 0.0, 1e9)
    for rate in CONV_RATES_PER_S:
        if abs(rate - v) < 1e-9:
            return rate
    _fail("misc.conversion_rate_per_s",
          "must be one of the Table 6.6 rates %r, got %r"
          % (tuple(CONV_RATES_PER_S), value))


def _filter_name(value):
    if value not in _FILTER_ENC:
        _fail("misc.averaging_filter",
              "must be 'off', 'level1' or 'level2', got %r" % (value,))
    return value


def _scratchpad(value):
    if (not isinstance(value, list) or len(value) != 2):
        _fail("misc.scratchpad", "must be a two-element array")
    return [_int(v, "misc.scratchpad[%d]" % i, 0, 0xFF)
            for i, v in enumerate(value)]


# --- State collection ----------------------------------------------------------

def collect_state(read_byte):
    """Snapshot every persisted register into a schema-v1 state dict.

    Takes a single-byte reader (the transport's ``read_byte``). Status,
    temperatures and TACH counts are transient and are NOT collected.
    Duties are dequantized through the CURRENT PWM_F grid; a degenerate
    PWM_F of 0 is treated as 1 for that purpose.
    """
    rb = read_byte
    cfg = rb(REG_CONFIG)
    filt = rb(REG_FILTER)
    am = rb(REG_ALERT_MASK)
    fc = rb(REG_FAN_CFG)
    su = rb(REG_SPINUP)
    fs = rb(REG_FAN_SETTING) & 0x3F
    pwm_f = rb(REG_PWM_F) & 0x1F
    pwm_d = rb(REG_PWM_D) & 0xFF
    clk_sel = bool(fc & FCFG_CLK_SEL)
    clk_ovr = bool(fc & FCFG_CLK_OVR)
    deq_grid = pwm_f if pwm_f else 1

    lvl = filt & FLT_LEVEL_MASK
    if lvl == FLT_LEVEL_OFF:
        filter_name = "off"
    elif lvl in (FLT_LEVEL_1, FLT_LEVEL_1_ALT):
        filter_name = "level1"
    else:
        filter_name = "level2"

    entries = []
    for i in range(LUT_ENTRIES):
        t = rb(REG_LUT_BASE + 2 * i)
        s = rb(REG_LUT_BASE + 2 * i + 1) & 0x3F
        t_signed = t if t < 0x80 else t - 0x100
        entries.append({"temp_c": t_signed,
                        "duty_pct": setting_to_duty_pct(s, deq_grid)})

    return {
        "schema_version": SCHEMA_VERSION,
        "saved_at_utc": _utc_now(),
        "device": {
            "product_id": "0x%02x" % rb(REG_PRODUCT_ID),
            "mfg_id": "0x%02x" % rb(REG_MANUF_ID),
            "revision": "0x%02x" % rb(REG_REVISION),
        },
        "config": {
            "standby": bool(cfg & CFG_STANDBY),
            "fan_standby": bool(cfg & CFG_FAN_STANDBY),
            "dac_enabled": bool(cfg & CFG_DAC),
            "dis_to": bool(cfg & CFG_DIS_TO),
            "tach_input": bool(cfg & CFG_ALT_TCH),
            "queue_3sample": bool(cfg & CFG_QUEUE),
            "alert_mode": "comparator" if (filt & FLT_COMP) else "interrupt",
            "alert_mask": {
                "int": bool(am & AMSK_INT),
                "high": bool(am & AMSK_HIGH),
                "low": bool(am & AMSK_LOW),
                "tcrit": bool(am & AMSK_TCRIT),
                "tach": bool(am & AMSK_TACH),
            },
        },
        "limits": {
            "local_high_c": int(int_raw_to_temp(rb(REG_INT_LIMIT))),
            "remote_high_c": ext_raw_to_temp(
                ((rb(REG_EXT_HIGH_MSB) & 0xFF) << 3)
                | (rb(REG_EXT_HIGH_LSB) & 0x07)),
            "remote_low_c": ext_raw_to_temp(
                ((rb(REG_EXT_LOW_MSB) & 0xFF) << 3)
                | (rb(REG_EXT_LOW_LSB) & 0x07)),
            "tcrit_c": int(int_raw_to_temp(rb(REG_TCRIT))),
            "tcrit_hysteresis_c": rb(REG_TCRIT_HYST) & 0x7F,
        },
        "lut": {
            "hysteresis_c": rb(REG_LUT_HYST) & 0x7F,
            "entries": entries,
        },
        "fan": {
            "manual": not (fc & FCFG_PROG),
            "duty_pct": setting_to_duty_pct(fs, deq_grid),
            "output_inverted": bool(fc & FCFG_POLARITY),
            "clk_sel": clk_sel,
            "pwm_f": pwm_f if pwm_f else 1,
            "clk_ovr": clk_ovr,
            "pwm_div": pwm_d,
            "pwm_freq_hz": _freq_from_fields(clk_sel, pwm_f if pwm_f else 1,
                                             pwm_d, clk_ovr),
            "spin_up": {
                "enabled": (su & SU_SPIN_TIME_MASK) != 0,
                "drive_pct": _DRIVE_PCTS[(su & SU_SPIN_DRIVE_MASK) // 8],
                "time_s": SPINUP_TIMES_S[su & SU_SPIN_TIME_MASK],
                "fast_tach": bool(su & SU_FAST_TACH),
            },
            "force": {
                "enabled": bool(fc & FCFG_FORCE),
                "temp_c": int(int_raw_to_temp(rb(REG_EXT_FORCE))),
            },
        },
        "calibration": {
            "ideality_index": rb(REG_IDEALITY) & 0x3F,
            "beta_auto_detect": bool(rb(REG_BETA) & BETA_ENABLE),
            "beta_index": rb(REG_BETA) & BETA_FIELD_MASK,
        },
        "misc": {
            "conversion_rate_per_s": CONV_RATES_PER_S[rb(REG_CONV_RATE) & 0x0F],
            "averaging_filter": filter_name,
            "tach_limit_count": (((rb(REG_TACH_LIMIT_HI) & 0xFF) << 8)
                                | (rb(REG_TACH_LIMIT_LO) & 0xFF)),
            "scratchpad": [rb(REG_SCRATCHPAD_1), rb(REG_SCRATCHPAD_2)],
        },
    }


# --- State application -----------------------------------------------------------

def apply_state(write_byte, read_byte, state, *, strict=True):
    """Apply a decoded state dict to the device, in the documented order.

    Ordering rules (research/03-persistence-opinion.md section 5.4):
    1. Re-validate the critical invariant (no descending LUT) BEFORE any
       bus traffic.
    2. Ensure PROG=1 so Fan Setting/LUT are writable.
    3. Write the Config section, then calibration, misc and limits.
       TCRIT is special-cased: a stored value differing from BOTH the
       current value and 85 C gets the one-time unlock dance attempted;
       a stored 85 C while the chip already holds something else means
       the unlock was consumed elsewhere and is skipped with a loud
       warning (a power cycle is required to restore 85 C).
    4. Write the LUT (descending re-checked at apply time).
    5. Write the fan configuration LAST, ending with the stored PROG
       value (ordering rule Q4).
    6. When strict (default, decision D15), read back every written
       register and report per-address diffs.

    Returns a report dict: ``{"applied": True, "warnings": [...],
    "diff": {addr_hex: (expected, actual)}}``. Callers surface the
    warnings and decide how to act on a non-empty diff.
    """
    warnings = []
    expected = {}

    def wr(reg, value):
        write_byte(reg, value & 0xFF)
        expected[reg] = value & 0xFF

    # 1. Pre-flight: LUT shape and ordering (cheap; no bus traffic yet).
    entries = state["lut"]["entries"]
    if len(entries) != LUT_ENTRIES:
        raise ValueError("lut must have exactly %d entries, got %d"
                         % (LUT_ENTRIES, len(entries)))
    prev = None
    for i in range(len(entries)):
        t = int(round(float(entries[i]["temp_c"])))
        if prev is not None and t < prev:
            raise ValueError("lut thresholds must not descend "
                             "(entry %d: %r after %r)" % (i, t, prev))
        prev = t

    # 2. Ensure PROG=1 (Fan Setting + LUT writable).
    fc_cur = read_byte(REG_FAN_CFG)
    if not (fc_cur & FCFG_PROG):
        wr(REG_FAN_CFG, fc_cur | FCFG_PROG)

    # 3a. Config section (whole byte; reserved bits written 0).
    co = state["config"]
    cfg_new = 0
    if co["standby"]:
        cfg_new |= CFG_STANDBY
    if co["fan_standby"]:
        cfg_new |= CFG_FAN_STANDBY
    if co["dac_enabled"]:
        cfg_new |= CFG_DAC
    if co["dis_to"]:
        cfg_new |= CFG_DIS_TO
    if co["tach_input"]:
        cfg_new |= CFG_ALT_TCH
    if co["queue_3sample"]:
        cfg_new |= CFG_QUEUE
    wr(REG_CONFIG, cfg_new)
    am_new = 0
    if co["alert_mask"]["int"]:
        am_new |= AMSK_INT
    if co["alert_mask"]["high"]:
        am_new |= AMSK_HIGH
    if co["alert_mask"]["low"]:
        am_new |= AMSK_LOW
    if co["alert_mask"]["tcrit"]:
        am_new |= AMSK_TCRIT
    if co["alert_mask"]["tach"]:
        am_new |= AMSK_TACH
    # Reserved mask bits are preserved (their read-back behaviour varies;
    # an RMW keeps whatever the chip holds there).
    wr(REG_ALERT_MASK,
       (read_byte(REG_ALERT_MASK) & ~AMSK_DEFINED) | am_new)

    # 3b. Calibration.
    cal = state["calibration"]
    wr(REG_IDEALITY, cal["ideality_index"])
    beta = cal["beta_index"] & BETA_FIELD_MASK
    if cal["beta_auto_detect"]:
        beta |= BETA_ENABLE
    wr(REG_BETA, beta)

    # 3c. Misc.
    mi = state["misc"]
    wr(REG_CONV_RATE, conv_rate_encode(mi["conversion_rate_per_s"]))
    wr(REG_FILTER, _FILTER_ENC[mi["averaging_filter"]]
       | (FLT_COMP if state["config"]["alert_mode"] == "comparator" else 0))
    tl = mi["tach_limit_count"]
    wr(REG_TACH_LIMIT_LO, tl & 0xFF)
    wr(REG_TACH_LIMIT_HI, (tl >> 8) & 0xFF)
    wr(REG_SCRATCHPAD_1, mi["scratchpad"][0])
    wr(REG_SCRATCHPAD_2, mi["scratchpad"][1])

    # 3d. Limits (TCRIT special-cased).
    li = state["limits"]
    wr(REG_INT_LIMIT, int_temp_to_raw(li["local_high_c"]))
    raw = ext_temp_to_raw(li["remote_high_c"])
    wr(REG_EXT_HIGH_MSB, (raw >> 3) & 0xFF)
    wr(REG_EXT_HIGH_LSB, raw & 0x07)
    raw = ext_temp_to_raw(li["remote_low_c"])
    wr(REG_EXT_LOW_MSB, (raw >> 3) & 0xFF)
    wr(REG_EXT_LOW_LSB, raw & 0x07)
    cur_tc = read_byte(REG_TCRIT)
    st_tc = li["tcrit_c"]
    if st_tc != cur_tc:
        if st_tc == TCRIT_LOCKED_C:
            warnings.append(
                "tcrit restore skipped: stored %d C but the device holds "
                "%#x; the one-time unlock was already consumed, a power "
                "cycle is required to restore %d C"
                % (st_tc, cur_tc, st_tc))
        else:
            cfg_now = read_byte(REG_CONFIG)
            if not (cfg_now & CFG_TCRITOVRD):
                wr(REG_CONFIG, cfg_now | CFG_TCRITOVRD)
            wr(REG_TCRIT, int_temp_to_raw(st_tc))
    wr(REG_TCRIT_HYST, li["tcrit_hysteresis_c"])

    # 4. LUT (duties quantize onto the STORED PWM_F grid).
    lu = state["lut"]
    pwm_f_store = state["fan"]["pwm_f"]
    for i in range(LUT_ENTRIES):
        entry = lu["entries"][i]
        wr(REG_LUT_BASE + 2 * i, int_temp_to_raw(int(round(
            float(entry["temp_c"])))))
        wr(REG_LUT_BASE + 2 * i + 1,
           duty_pct_to_setting(entry["duty_pct"], pwm_f_store))
    wr(REG_LUT_HYST, lu["hysteresis_c"])

    # 5. Fan configuration LAST, ending with the stored PROG value.
    fa = state["fan"]
    wr(REG_FAN_SETTING, duty_pct_to_setting(fa["duty_pct"], fa["pwm_f"]))
    wr(REG_PWM_F, fa["pwm_f"])
    wr(REG_PWM_D, fa["pwm_div"])
    fc_final = fc_cur & FCFG_TACH_M_MASK     # preserve TACH_M (not in v1)
    if fa["output_inverted"]:
        fc_final |= FCFG_POLARITY
    if fa["clk_sel"]:
        fc_final |= FCFG_CLK_SEL
    if fa["clk_ovr"]:
        fc_final |= FCFG_CLK_OVR
    if fa["force"]["enabled"]:
        fc_final |= FCFG_FORCE
    if not fa["manual"]:
        fc_final |= FCFG_PROG
    wr(REG_FAN_CFG, fc_final)
    su = 0
    if fa["spin_up"]["fast_tach"]:
        su |= SU_FAST_TACH
    su |= _DRIVE_ENC[fa["spin_up"]["drive_pct"]]
    su |= _TIME_ENC[fa["spin_up"]["time_s"]]
    wr(REG_SPINUP, su)
    wr(REG_EXT_FORCE, int_temp_to_raw(fa["force"]["temp_c"]))

    # 6. Strict post-apply read-back (decision D15).
    diff = {}
    if strict:
        for reg in sorted(expected):
            actual = read_byte(reg)
            if actual != expected[reg]:
                diff["%#02x" % reg] = (expected[reg], actual)
    return {"applied": True, "warnings": warnings, "diff": diff}
