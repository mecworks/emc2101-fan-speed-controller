# 03 — On-Disk Config Persistence: Honest Opinion

The request: the plain EMC2101 has no EEPROM (only the `-R` variant auto-loads an external one).
Simulate that function with an **on-disk data file** holding user settings once configured — LUT
(speed/temp profile) and other register settings — so the driver can mimic the MAX31760 driver's
EEPROM-backed behavior. This document is the requested honest opinion: practical? good or bad
idea? conventional? — followed by the resulting design.

## 1. Verdict (up front)

**GO. It is practical, it is a good idea for this project's goals, and it follows conventions when
properly isolated.** The feature is a *superset* capability: nothing in the driver core depends on
it, it lives behind explicit verbs plus an opt-in constructor kwarg, and it degrades gracefully
(file absent ⇒ first-boot semantics, exactly like a blank EEPROM). Its costs are bounded and its
risks have cheap mitigations (§4). The single honest limitation — cold-boot autonomy is impossible
without bootloader involvement (§3) — was accepted during the interview given measured fan-floor
behavior (~660 RPM at 0 % setting on the last tested fan).

## 2. Practicality analysis

### 2.1 Footprint & mechanics — trivial

The entire configurable state of the EMC2101 is ~30 meaningful bytes: 8 LUT pairs (16 B), hysteresis
(1 B), limits (5–6 B), fan config/spin-up/PWM (5 B), calibration (2 B), masks/filter/conversion
(3 B). A versioned JSON document lands around **0.5–1 KB** — negligible on Pico W flash (MBs free),
ESP32-S3 SPIFFS/LittleFS, or any Pi filesystem. MicroPython ships a built-in `json` module; CPython
obviously has one. No third-party dependency on either platform.

### 2.2 Flash wear — managed by design, not by luck

MicroPython flash is wear-leveled at the FS layer (LittleFS/FAT), but gratuitous writes still cost
endurance. The design therefore mirrors the real EEPROM lifecycle: **the host burns once, the chip
"loads" every boot**. Saving is always an explicit user action (`save_config()`); there is no
autosave-on-write, no periodic checkpointing. Expected write frequency: once per configuration
change, i.e. rarely. Wear is a non-issue at that cadence.

### 2.3 Corruption & staleness — validated, not trusted

JSON is human-readable (a stated requirement) which invites hand-editing; the countermeasure is a
strict load pipeline: schema-version check → device-ID stamp check (product/mfg/revision recorded at
save time; product-ID mismatch ⇒ refuse, revision mismatch ⇒ warn) → per-field range validation →
apply only after the whole document validates (all-or-nothing; a corrupt file touches zero
registers). Atomic write on save (temp-file + rename where the port supports it; documented fallback
otherwise). This is strictly safer than the silicon EEPROM case, where corruption surfaces as
mystery behavior.

### 2.4 Cross-platform path differences — contained

Default path differs per platform facade (class constant): MicroPython → `/emc2101.json` (flash
root); CPython → `~/emc2101.json` (expanded home dir). Both overridable via attribute/ctor kwarg.
The core never hardcodes a path; it receives one from the facade. Contained, documented, testable.

## 3. What can and cannot be mimicked (honesty section)

| -R behavior | Disk-file analog | Gap |
|---|---|---|
| Loads autonomously at power-on, before any software exists | Applied when Python constructs the device (opt-in kwarg) or on explicit `load_config()` | **Boot window**: between power-up and `load_config()`, the chip runs POR defaults (fan at 0 %-setting ≈ minimum speed on modern fans; some legacy/logic-driven fans truly stop — verify per fan). Window reopens on MCU reset/watchdog events, not just cold boot. Mitigations: document prominently; optional safe-default duty applied first by app code; true closure requires bootloader-level application (out of scope for a driver package) |
| Zero host intervention required | One line in app startup: `dev.load_config()` (or ctor kwarg) | Minimal residual gap; unavoidable for any software-side scheme |
| EEPROM absence detectable (status bit, sticky ALERT) | Missing file = silent no-op (first boot); corrupt/stale file = loud error before any register write | Better failure semantics than the hardware |
| Profile persists across unlimited power cycles | Persists until file deleted/overwritten; survives MCU reflashes only if stored outside the firmware image partition (Pico W: keep config on flash root, not in `/lib`) | Document deployment note |
| Block-selective save/load (MAX31760-style) | v1: whole-config only; JSON structured into named sections so a future `sections=` param is additive | Deliberate YAGNI cut (interview decision) |

**Convention check:** do drivers own persistence? Generally *no* — persistence belongs to the
hardware (EEPROM/NVRAM) or to the application layer. Adding it to a driver is unusual but not
unconventional when (a) the hardware lacks NVRAM, (b) it is clearly separated behind explicit
verbs/opt-in, (c) the schema is versioned and driver-owned, and (d) docs state the boundary. All
four conditions hold here. Precedents for "driver-managed config files" exist in adjacent spaces
(Home Assistant integrations, ESPHome YAML profiles, network-device startup configs) — the pattern
is established even if uncommon in bare sensor-driver packages. The MAX31760 sibling already
establishes the *verb vocabulary* (`save_config`/`load_config`), so within this project family the
feature reads as continuity, not novelty.

**Is it a good idea?** For the stated goal (same cross-platform experience as the MAX31760 driver,
including "set once, restored every boot"): yes, it is the right mechanism. The alternatives
(§6) are worse for this use case. The main intellectual-honesty caveat: it is *not* the same
mechanism — it is a behavioral approximation whose weakest point (boot window) must stay visible in
every doc and docstring that mentions it.

## 4. Risk table

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Cold boot window leaves fan at floor speed | Certain (by physics) | Low–Medium (device-dependent) | Accepted (interview); prominent docs; per-fan verification note; app-level safe-duty option |
| File corrupted mid-write (power loss during save) | Low | Medium (bad config applied) | Temp-file + rename atomicity; all-or-nothing validation; previous-good file untouched until rename completes |
| Hand-edited file passes syntax but fails ranges | Medium | Low (rejected loudly) | Full field-range validation; precise error messages naming the offending field |
| Config saved from board A loaded onto board B (different diode/calibration) | Medium | Medium (wrong temps/fan curve) | ID stamp + revision check; calibration section documented as board-specific |
| TCRIT one-shot lockout (Q5) makes a saved TCRIT unappliable after prior unlock+change | Low | Medium (partial apply) | Load detects the case, applies everything else, raises/informs about TCRIT specifically (power cycle needed) — never silently skips |
| Path coupling surprises (CWD-relative paths on CPython) | Low | Low | Absolute default (home dir); override is explicit |
| Flash wear | Very low (explicit-save-only) | Negligible | §2.2 |

## 5. Design (carried forward to spec phase)

### 5.1 API surface (locked from interview)

```python
dev = EMC2101(i2c, addr=0x4C)                       # explicit mode: no file I/O ever
dev = EMC2101(i2c, addr=0x4C, config_file="/p/q.json")  # convenience: load_config() at init if present

dev.config_path          # instance attr, seeded from kwarg or class default
dev.save_config()        # -> dev.config_path
dev.save_config("/alt/profile.json")   # positional override
dev.load_config()        # -> dev.config_path
dev.load_config("/profiles/quiet.json")  # runtime profile switch
```

Zero-arg call sites are identical to the MAX31760 driver's `save_config()`/`load_config()`.
Constructor stays pure-binding except for the opt-in kwarg (documented side effect: one file read +
conditional register writes after probe succeeds).

### 5.2 Constructor-kwarg semantics

- Kwarg passed & file exists & valid → apply during init (after probe/verify), then continue.
- Kwarg passed & file missing → **silent no-op** (first-boot semantics; matches blank-EEPROM -R).
- Kwarg passed & file invalid/corrupt → raise **before touching any register** (ValueError with
  reason; object construction proceeds with the device left at POR defaults — decision: raise
  vs. construct-with-warning is a spec-phase choice; recommendation: raise, since a silently
  half-configured boot is the worst outcome).
- Kwarg omitted → zero file I/O, period.

### 5.3 JSON schema v1 (sketch)

```json
{
  "schema_version": 1,
  "saved_at_utc": "2026-11-21T21:30:00Z",
  "device": { "product_id": "0x16", "mfg_id": "0x5D", "revision": "0x01" },
  "config":  { "standby": false, "fan_standby": false, "dac_enabled": false,
               "dis_to": false, "tach_input": true, "queue_3sample": false,
               "alert_mode": "interrupt", "alert_mask": { "int": false, "high": false,
                                                          "low": false, "tcrit": false, "tach": false } },
  "limits":  { "local_high_c": 70, "remote_high_c": 70.0, "remote_low_c": 0.0,
               "tcrit_c": 85, "tcrit_hysteresis_c": 10 },
  "lut":     { "hysteresis_c": 4,
               "entries": [ {"temp_c": 30, "duty_pct": 20}, ... ] },
  "fan":     { "manual": false, "duty_pct": 0.0, "pwm_freq_hz": 25000,
               "clk_sel": "override", "pwm_div": 193, "output_inverted": false,
               "spin_up": { "enabled": true, "drive_pct": 100, "time_s": 3.2, "fast_tach": true },
               "force": { "enabled": false, "temp_c": 25.0 } },
  "calibration": { "ideality_index": 18, "beta_auto_detect": true, "beta_index": 0 },
  "misc":    { "conversion_rate_per_s": 16, "averaging_filter": "off",
               "tach_limit_count": 65535, "scratchpad": [0, 0] }
}
```

Design choices: semantic (decoded) values rather than raw registers — human-readable/editable per
requirement; raw snapshot deliberately excluded in v1 (forensic value judged insufficient against
size/clarity cost — revisit if demanded); units in names (`*_c`, `*_pct`, `*_hz`, `*_s`).

### 5.4 Apply-ordering rules (load)

1. Validate everything first (§2.3); compute the full target register set.
2. Ensure PROG=1 (needed for LUT + Fan Setting writes).
3. Write calibration, misc, limits (TCRIT handled specially: if stored ≠ current and ≠ 85 °C,
   attempt unlock dance; if already unlocked-and-changed, skip TCRIT with a loud warning/error).
4. Write LUT entries (ascending-temp validation again at apply time).
5. Write fan config last, ending with the stored PROG value (ordering rule Q4).
6. Optional strict mode (spec item): read-back verification pass with per-register diff report
   (borrowing kvasir_devices' read-back-after-write practice, see 04 doc).

Save is the inverse: read all registers, decode, serialize, atomic write.

### 5.5 Error taxonomy

- `ValueError` — malformed JSON structure, unknown schema version, failed field validation,
  product-ID mismatch (message names the field/value).
- `OSError` — file I/O failures (missing file during explicit `load_config()` is *not* a no-op:
  explicit load of a missing file raises; only the constructor path treats missing as first-boot).
- Warning channel (docstring-stated return info / logged string) — revision mismatch, TCRIT
  skip-case. (MicroPython logging is minimal; prefer raising informative exceptions over prints.)

## 6. Alternatives considered

| Alternative | Why rejected |
|---|---|
| Binary register-image file (byte-for-byte EEPROM mirror) | Violates the human-readability requirement; opaque diffs; no validation story; marginal size savings (~30 B) |
| Hardware: add an external EEPROM + use an -R part | Changes the hardware under test; defeats the purpose (plain EMC2101 is what we have); out of scope |
| No persistence (explicit configure-every-boot in app code) | Works, but pushes boilerplate into every application and abandons the stated parity goal; the disk file is ~100 lines of well-isolated driver code |
| Bootloader-level application (true autonomy) | Real solution to the boot window, but requires owning/modifying firmware images per platform — disproportionate for a driver package; noted as future work |
| Selective (section) persistence in v1 | Interview decision: whole-config only; schema keeps the door open |

## 7. Recommendation

Implement as designed (§5). Keep the boot-window caveat in: README quickstart, `load_config`/ctor
docstrings, and the E2E test plan (P6 should include a "cold boot with saved profile" scenario).
This delivers the requested -R-like behavior at the smallest possible distance from it — one line
of application code — without compromising the driver's core purity or the sibling's conventions.
