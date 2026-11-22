# 02 — API Parity Mapping (MAX31760 → EMC2101)

Policy: **Option B — common core, honest edges.** Identical names/semantics where functionality
genuinely corresponds; free rein (documented divergence) where the chips differ. No faked features.

Legend: **IDENTICAL** = same name, signature, semantics · **ADAPTED** = same (or near-same) name,
signature or internals adjusted to the chip · **DIVERGED** = deliberate rename/restructure with
rationale · **NEW** = EMC2101-only capability, no sibling counterpart · **N-A** = sibling feature
with no EMC2101 analog, intentionally absent.

Sibling reference: `FanSpeedController/max31760` v0.1.1 (`_core.py`, `_faults.py`, `mp.py`, `cp.py`).
Correction vs earlier interview notes: the MAX31760 driver's LUT is **48 single-byte duty entries**
(`LUT_LEN = 48`, registers `20h..4Fh`) over a fixed temperature window — not 16. The EMC2101 LUT is
**8 (temperature-threshold, fan-setting) pairs**. This structural difference is the largest parity
item in this document.

## 1. Lifecycle & raw access

| MAX31760 | EMC2101 | Verdict | Notes |
|---|---|---|---|
| `MAX31760(i2c, addr=0x50)` / `(bus=1, addr=0x50, handle=None)` | `EMC2101(i2c, addr=0x4C[, config_file=...])` / `(bus=1, addr=0x4C, handle=None[, config_file=...])` | ADAPTED | Same shape; default address differs; optional `config_file` kwarg (persistence opt-in, see 03 doc) |
| `close()` | `close()` | IDENTICAL | MP no-op / CP bus release |
| `probe()` | `probe()` | IDENTICAL | Probe reg differs internally (`0x00` vs `0x58`) |
| `scan()` | `scan()` | IDENTICAL | |
| `verify()` | `verify()` | ADAPTED | Same contract (raise OSError on NACK); additionally reads ID trio and warns on `-R` part (`0x28`) |
| `read_reg(reg, n=1)` / `write_reg(reg, buf)` | same names | ADAPTED | EMC2101 implements n>1 as sequential single-byte transactions over *consecutive* addresses (pointer does not auto-increment). Documented; never used across interlock boundaries by the core |
| `__enter__`/`__exit__`/`__repr__` | same | IDENTICAL | |

## 2. Identity (NEW domain)

| MAX31760 | EMC2101 | Verdict | Notes |
|---|---|---|---|
| — (IDs internal to verify) | `product_id`, `mfg_id`, `revision` properties + `part_info` tuple | NEW | Cheap, useful for persistence stamping and bench logs |

## 3. Temperatures & setpoints

| MAX31760 | EMC2101 | Verdict | Notes |
|---|---|---|---|
| `local_temp_c` (die, 0.125 °C) | `local_temp_c` (internal die, **1 °C steps**, guaranteed 0–85 °C) | ADAPTED | Name kept for app portability; coarser resolution documented |
| `remote_temp_c` (diode, 0.125 °C) | `remote_temp_c` (ext diode, 0.125 °C, −64..+127.875) | ADAPTED | Interlock-ordered read (`01h→10h`); raises typed error on diode-fault sentinels instead of returning +127/+127.875 |
| `local_high_c` (16-bit setpoint) | `local_high_c` (int limit `05h`, 8-bit signed, 1 °C) | ADAPTED | Narrower range/format |
| `remote_high_c` (16-bit setpoint) | `remote_high_c` (ext high `07h`+`13h`, 0.125 °C) | ADAPTED | |
| `local_overtemp_c` | — | N-A | No local overtemp setpoint on EMC2101 |
| `remote_overtemp_c` | `tcrit_c` | DIVERGED | Closest analog is TCRIT (external-only, trips fan to full-on). Renamed because "overtemp" implies symmetric per-channel setpoints; TCRIT has unique force-full-on semantics + one-shot unlock (Q5) |
| — | `remote_low_c` (ext low limit `08h`+`14h`) | NEW | No sibling counterpart (MAX31760 has no low-limit alarm) |
| — | `tcrit_hysteresis_c` (`21h`) | NEW | |

## 4. LUT (largest divergence)

| MAX31760 | EMC2101 | Verdict | Notes |
|---|---|---|---|
| `lut` property: 48 duty bytes, fixed 17 °C-based window, index = f(temp) | `lut` property: list of **8 `(temp_c, duty_pct)` tuples**; setter validates ascending temps, applies via PROG dance (Q4) | DIVERGED | Structures are fundamentally different (fixed-grid curve vs explicit threshold pairs). Name kept; shapes documented side-by-side in docs. App code that *programs curves* must be written per-chip anyway |
| `lut_get_index(i)` / `lut_set_index(i, duty)` | `lut_get_index(i)` → `(temp_c, duty_pct)` / `lut_set_index(i, temp_c, duty_pct)` | ADAPTED | Same verbs, arity differs (threshold is data here, not implicit) |
| `build_lut_curve(...)` / `lut_index_for_temp(...)` module helpers | — | N-A | Helpers encode the fixed-window model; meaningless for threshold-pair LUT. (Optional future: a `curve_to_pairs()` converter helper if users want to reuse MAX31760-style curve definitions — flagged, not planned) |
| `hysteresis_c` (2 or 4 only) | `hysteresis_c` (0..127 °C, `4Fh`) | ADAPTED | Same name/concept; wider programmable range |
| `index_source` (LOCAL/REMOTE/MAX) | — | N-A | EMC2101 LUT always indexes on the external diode channel |
| — | `force_enabled` + `forced_temp_c` (`0Ch` + FORCE bit) | NEW | Host feeds arbitrary temp into LUT (limits still use measured temp) — partial conceptual cousin of `index_source`, plus a testing tool (Q15) |

## 5. Manual mode & duty

| MAX31760 | EMC2101 | Verdict | Notes |
|---|---|---|---|
| `manual` (CR2.DFC; True = manual) | `manual` (**~PROG**; True = manual) | ADAPTED | Same public meaning; underlying bit polarity inverted. Side effect documented: toggling also flips LUT/Fan-Setting writability (Q4) |
| `set_duty_pct(pct)` | `set_duty_pct(pct)` | ADAPTED | Quantizes through current PWM_F grid (effective duty = S/(2·PWM_F), Q7); ValueError outside 0..100 |
| `duty_cmd_raw` (0..255) | `duty_cmd_raw` (0..63) | ADAPTED | Range follows 6-bit Fan Setting |
| `actual_duty_raw` / `actual_duty_pct` (RO feedback reg) | — | N-A | No actual-duty feedback register exists (Q14) |
| `wait_for_duty(target, timeout_ms)` | — | N-A | Nothing to wait on without feedback (Q14) |
| `ramp_rate` (RAMP_* constants) | — | N-A | No ramp control (Q14) |

## 6. PWM / DAC output configuration

| MAX31760 | EMC2101 | Verdict | Notes |
|---|---|---|---|
| `pwm_freq_hz` (4 discrete values) | `pwm_freq_hz` (continuous ≈22.8 Hz–180 kHz; setter solves nearest achievable via PWM_F/PWM_D/CLK_SEL/CLK_OVR, getter returns computed actual) | ADAPTED | Same name, richer behavior; max-resolution path (PWM_F=31, CLK_OVR=1) recommended |
| `pwm_polarity` (PPS counting edge polarity) | `fan_output_inverted` (drive inversion: what `00h` means) | DIVERGED | Name collision with opposite semantics — deliberately renamed to avoid a trap |
| — | `dac_enabled` (Config bit 4) | NEW | Linear 6-bit DAC drive mode (hardware caveat: remove FAN pull-up) |
| — | `pwm_clk_sel` / `pwm_div` raw-tier accessors | NEW | Low-level escape hatch for exact frequency work |

## 7. Tachometer & RPM

| MAX31760 | EMC2101 | Verdict | Notes |
|---|---|---|---|
| `rpm(port, pulses_per_rev=2)` | `rpm(pulses_per_rev=2)` | ADAPTED | Port arg dropped (single fan); formula `5,400,000/count × 2/pulses_per_rev`; `FFFFh`/0 ⇒ 0.0 (unmeasurable, Q8) |
| `tach_threshold` (count, min-RPM guard) | `tach_threshold` (count, `48h/49h`) | IDENTICAL | Same concept: alarm when count exceeds limit (fan too slow) |
| — | `min_rpm` convenience (RPM ↔ count via 5,400,000) | NEW | Adafruit-style ergonomic wrapper |
| `tach1_enabled` / `tach2_enabled` | `tach_input_enabled` (ALT_TCH bit) | ADAPTED | Single input; enabling **disables ALERT output** (Q11) — docstring warning mandatory |
| `pulse_stretch_enabled` / `tacho_full_enabled` / `measure_tach_once(...)` | — | N-A | No pulse-stretch/TACHFULL mechanisms (Q14) |
| — | `tach_mode` (TACH_M[1:0]: false-readings vs forced-FFFFh below min RPM) | NEW | Note 6.2 interaction with 360 kHz base clock documented |

## 8. Spin-up

| MAX31760 | EMC2101 | Verdict | Notes |
|---|---|---|---|
| `spin_up_enabled` (SPEN bool) | `spin_up_enabled` (composite: SPIN_TIME ≠ bypass) | ADAPTED | Same toggle semantics; implemented over the 3-field spin-up register |
| — | `spin_up_drive` (bypass/50/75/100 %) | NEW | |
| — | `spin_up_time_s` (0.05…3.2 s, bypass=0) | NEW | |
| — | `spin_up_fast_tach` (abort early on good TACH) | NEW | Ignored while TACH input disabled — documented |

## 9. Alerts, status & faults

| MAX31760 | EMC2101 | Verdict | Notes |
|---|---|---|---|
| `status_raw()` (destructive read verb) | `status_raw()` | ADAPTED | Same verb discipline (latch-consuming side effect visible at call site); different bit set (BUSY/INT_HIGH/EXT_HIGH/EXT_LOW/FAULT/TCRIT/TACH; EEPROM bit always 0) |
| `active_alarms()` | `active_alarms()` | ADAPTED | Masked subset semantics preserved |
| `alert_mask` (SR-mirrored bits) | `alert_mask` (`16h`: INT/HIGH/LOW/TCRIT/TACH) | ADAPTED | Same name; different bit meanings; reserved-bit preservation (Q6) |
| `alert_mode` (INTERRUPT / FAULT_INDICATOR) | `alert_mode` (INTERRUPT / COMPARATOR) | ADAPTED | Second constant renamed to the chip's term; both modes' status-clear/MASK differences documented (Q12) |
| `service_alert()` | `service_alert()` | ADAPTED | Same ISR-step role; EMC2101 variant = status read (clears latches, auto-sets MASK in interrupt mode) |
| `clear_alert_mask()` | `clear_alert_mask()` | ADAPTED | Re-arm after service (MASK bit 7) |
| `remote_diode_fault()` | `diode_fault()` | ADAPTED | Renamed (channel naming); covers open/short sentinels + FAULT bit (Q10) |
| `clear_fan_fail()` | — | N-A | No fan-fail latch (Q14) |
| `ff_dc_raw` / `set_ffdc_pct` / `ff_zero_detection` / `ff_mode` | — | N-A | No fan-fail-force circuitry (Q14) |
| `rd_mode` / `rd_polarity` | — | N-A | No remote-diode drive-mode control (Q14) |
| `eeprom_corrupt()` / `recover_from_corruption()` | — | N-A | Replaced by persistence-layer validation errors (03 doc) |
| `soft_por(settle_ms)` | — | N-A | **No software POR register exists** (Q14) — reset requires power cycle; documented gap |
| `standby` | `standby` (+ `fan_standby` option) | ADAPTED | STANDBY + FAN_STANDBY bits |
| — | `busy()` (ADC converting) | NEW | |
| — | `one_shot()` (mode-preconditioned) | NEW | Standby/mixed refresh (Q16) |
| — | `conversion_rate` (table-driven, 1/16…32 s⁻¹) | NEW | |
| — | `averaging_filter` (OFF/L1/L2; duplicated encoding handled, Q13) | NEW | |
| — | `dis_to_enabled` (SMBus timeout disable) | NEW | Exotic-bus escape hatch |
| — | `fault_queue_enabled` (QUEUE bit: 1 vs 3 consecutive samples) | NEW | |

## 10. Calibration

| MAX31760 | EMC2101 | Verdict | Notes |
|---|---|---|---|
| `ideality_factor_index` / `ideality_factor` / `set_ideality_factor(n)` | same three names | ADAPTED | Same pattern; different 64-entry table (0.9949–1.0566, Table 6.13) |
| — | `beta_auto_detect` / `beta_index` | NEW | Beta-compensation autodetect + manual BETA[2:0] (write `07h` recipe for diode-connected transistors documented) |

## 11. Scratch memory

| MAX31760 | EMC2101 | Verdict | Notes |
|---|---|---|---|
| `user_memory_get/set/read_all/write_all` (8 B, `10h..17h`) | `scratchpad_get(index)` / `scratchpad_set(index, value)` (2 B, `11h/12h`) | DIVERGED | Renamed: function differs (no persistence, 2 bytes vs 8). Honest edge rather than a misleadingly-named 2-byte "user memory" |

## 12. Presets

| MAX31760 | EMC2101 | Verdict | Notes |
|---|---|---|---|
| `configure_4wire_fan(port=1, pwm_freq_hz=25000)` | `configure_4wire_fan(pwm_freq_hz=...)` | ADAPTED | Sets PWM freq, enables TACH input, sane spin-up; docstring states the ALERT-trade-off explicitly (Q11) |
| `configure_3wire_supply_modulation(port=1)` | — | N-A | Relies on pulse stretching which doesn't exist; a plain low-frequency setup is available via `pwm_freq_hz` directly |
| `configure_two_fans(pwm_freq_hz=25000)` | — | N-A | Single output (Q14) |

## 13. Persistence ("virtual EEPROM")

| MAX31760 | EMC2101 | Verdict | Notes |
|---|---|---|---|
| `save_config(blocks=EEX_ALL_BLOCKS, *, timeout_ms=2000)` | `save_config(path=None)` | ADAPTED | Zero-arg call sites identical; first positional arg reshaped from block bitmask to path override; whole-config only in v1 (JSON sections keep the door open for selective persistence) |
| `load_config(blocks=EEX_ALL_BLOCKS, *, timeout_ms=2000)` | `load_config(path=None)` | ADAPTED | Same reshape; validation policy + apply-ordering rules in 03 doc |
| — | `config_path` attribute + `config_file=` ctor kwarg | NEW | Default-path mechanism (03 doc §Design) |

## 14. Error model & packaging

| Aspect | Verdict | Notes |
|---|---|---|
| Exception taxonomy (ValueError args/bounds · OSError bus/NACK after retry ladder · TimeoutError timeouts) | IDENTICAL convention | Diode-fault typing decision (typed OSError subclass vs ValueError) is the one open item — spec phase |
| `mp.py`/`cp.py` facades with mirrored `__all__` + parity test | IDENTICAL pattern | `TestApiParity` carries over |
| MicroPython-subset lint gate, api_coverage tool, compileall gate | IDENTICAL pattern | Tuned per codebase |
| Property-per-register convention; verbs for actions/destructive reads | IDENTICAL convention | |
| Retry ladder with escalating backoff | IDENTICAL pattern | Delays re-tuned in P0 (no EEPROM-busy waits needed; shorter ladder likely) |

## 15. Summary statistics

Across ~45 members of the overlapping functional domain:

| Verdict | Count | Share |
|---|---|---|
| IDENTICAL (name+semantics) | ~10 | 22 % |
| ADAPTED (same/near name, chip-adjusted) | ~25 | 56 % |
| DIVERGED (deliberate rename/restructure) | 3 | 7 % |
| N-A (honestly absent) | ~15 (sibling-side features) | — |
| NEW (EMC2101-only additions) | ~18 | — |

**Bottom line:** application code operating in the common domain (probe/verify → temps → manual
duty → RPM → LUT programming → limits → alert servicing → save/load config) can be written once
and run against either driver with at most trivial adjustments (LUT shape, `rpm()` arity, preset
names). The N-A cluster is concentrated in MAX31760-specific silicon (fan-fail force, pulse
stretching, software POR, dual ports) — none of it is faked.
