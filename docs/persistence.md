# Persistence ("virtual EEPROM")

The plain EMC2101 has no configuration EEPROM; the `-R` variant loads its
settings from on-chip EEPROM at power-on. This package simulates that
auto-load with a human-readable, versioned JSON file: `save_config()`
snapshots the chip's decodable configuration, and `load_config()` (or the
constructor opt-in) applies it back.

## The two methods

```python
path = dev.save_config()                 # -> effective path used
report = dev.load_config()               # strict read-back ON by default
report = dev.load_config("/alt/path.json", strict=False)
```

- **Effective path**: argument first, else the instance's `config_path`.
  Defaults: `/emc2101.json` on MicroPython, `~/emc2101.json` on CPython.
- **Atomic write**: `save_config` writes a temp file in the same
  directory and renames it over the target where the port supports
  rename (`os.replace`, falling back to `os.rename`); otherwise it falls
  back to a plain overwrite. A crash mid-save therefore never leaves a
  half-written config behind (worst case: the previous file intact).
- **Report** (returned by both): a dict with `written` (register/value
  pairs written), `skipped` (reasons, e.g. TCRIT skip), `warnings`
  (e.g. revision mismatch, unlock consumed), and — when `strict=True` —
  `diff` (per-register expected-vs-actual mismatches found by the
  post-apply read-back).

### Validation policy

`load_config` validates the *entire* file before touching any register:

| Condition | Outcome |
|---|---|
| Unparseable JSON / wrong shape / unknown schema version | `ConfigFormatError` or `ConfigValidationError` (both `ValueError` subclasses); zero register writes. |
| Product-ID stamp ≠ device's FDh | `ValueError` raised before any register write (wrong profile for this part). |
| Revision stamp ≠ device's FFh | Warning appended to the report; apply proceeds. |
| Field out of range / LUT malformed | `ConfigValidationError`; zero register writes. |
| Bus failure mid-apply | `ConfigApplyError` (`OSError` subclass); partial state possible — re-run after fixing the bus. |
| Strict read-back mismatch | `ValueError("post-apply verification failed: ...")` listing each mismatching register; use `strict=False` to accept the diff (it is still reported). |

### Apply ordering

Writes follow a fixed order so every intermediate state is legal:
calibration → misc/limits (with the TCRIT special case below) → LUT
entries → fan configuration last, ending with the stored PROG value.
The LUT pre-flight re-checks ordering before any bus traffic.

#### TCRIT special case

TCRIT (19h) is locked until the one-time TCRITOVRD unlock, which is
consumed by the first change and then requires a power cycle. On apply:

- Stored TCRIT equals the current chip value → **skipped** (no unlock
  consumed), noted in `skipped`.
- Stored TCRIT differs from both 85 °C (the locked POR value) and the
  current value → the unlock dance is attempted once; if the bit was
  already consumed since save, the write fails loudly and the mismatch
  surfaces in the strict diff (warning in `warnings`).
- Everything else → written normally.

Never rely on persistence to re-program TCRIT twice between power
cycles — see [Operational notes](operational-notes.md#tcrit-lifecycle).

## Auto-load at construction (decision D14)

```python
dev = EMC2101(i2c)                        # zero file I/O
dev = EMC2101(i2c, config_file="/x.json")  # auto-load enabled
```

Semantics when the kwarg is present:

| File state at construct | Behaviour |
|---|---|
| Exists and valid | Applied after binding (strict read-back ON). |
| Missing | Silent no-op — first-boot semantics. |
| Corrupt / invalid | Raises **before any register write**; the chip is untouched. |

When omitted, the constructor performs no file I/O at all.

## Schema v1

Top level: `schema_version` (must be `1`), `saved_at_utc` (UTC
timestamp string), `device` (identity stamps as canonical lowercase
`0xNN` strings), and six semantic sections. Values are decoded units
(°C, %, Hz), not raw registers:

```json
{
  "schema_version": 1,
  "saved_at_utc": "2026-11-22T23:14:07Z",
  "device": {"product_id": "0x16", "mfg_id": "0x5d", "revision": "0x01"},
  "config": {
    "standby": false, "fan_standby": false, "dac_enabled": false,
    "dis_to": false, "tach_input": false, "queue_3sample": false,
    "alert_mode": "interrupt",
    "alert_mask": {"int": true, "high": false, "low": false,
                   "tcrit": false, "tach": false}
  },
  "limits": {"local_high_c": 70, "remote_high_c": 70.0,
             "remote_low_c": 0.0, "tcrit_c": 85, "tcrit_hysteresis_c": 10},
  "lut": {"hysteresis_c": 4,
          "entries": [{"temp_c": 127, "duty_pct": 100.0}, "... x8"]},
  "fan": {
    "manual": false, "duty_pct": 0.0, "output_inverted": false,
    "clk_sel": false, "pwm_f": 23, "clk_ovr": false, "pwm_div": 1,
    "pwm_freq_hz": 7826.08695652174,
    "spin_up": {"enabled": true, "drive_pct": 100, "time_s": 3.2,
                "fast_tach": true},
    "force": {"enabled": false, "temp_c": 0}
  },
  "calibration": {"ideality_index": 18, "beta_auto_detect": true,
                  "beta_index": 0},
  "misc": {"conversion_rate_per_s": 16.0, "averaging_filter": "off",
           "tach_limit_count": 65535,
           "scratchpad": [0, 0]}
}
```

Validation details: exactly 8 LUT entries; integer °C fields stay
integers; spin-up `enabled`/`time_s` cross-checked against the bypass
encoding; the stored `pwm_freq_hz` must be consistent with the stored
`pwm_f`/`pwm_div`/`clk_sel`/`clk_ovr` grid. The example above reflects
the factory POR decode — of the five defined alert-mask bits, only INT
ships unmasked.

### LUT ordering rule (decision D31)

The **write path** (`lut` setter) requires strictly ascending
thresholds — equal thresholds shadow each other in hardware. The
**persistence path** accepts *non-descending* curves, because the
factory POR curve is uniformly 127 °C and `save_config`/`load_config`
must round-trip it losslessly. Saving an as-found chip always works;
loading such a file back reproduces the factory curve exactly.

## Practical notes

- **Flash wear (MicroPython):** the config lives on flash via littlefs,
  which wears levels internally, but saving on every boot is pointless —
  save only when you actually change the configuration.
- **Stale files:** a file saved for a different part (different product
  ID) is refused outright; a file from a different revision warns. Keep
  one file per physical chip if your profiles differ.
- **Corruption recovery:** delete the file (or fix it by hand — it is
  plain JSON) and re-save; nothing about the driver depends on the file
  existing.
