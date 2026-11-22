# 01 — Feasibility & Effort Assessment

## 1. Verdict

**Feasible on all three target platforms with low-to-moderate risk.** The EMC2101 is a simple
single-byte SMBus client; every architectural ingredient of the sibling MAX31760 driver (dual
facade packaging, duck-typed transport, mock-backed tests, MicroPython-subset lint gate) transfers
directly. The chip's quirks are well-documented and enumerable (§4), none of them block a clean
implementation, and third parties have already run this exact chip on each target runtime (§2).

Estimated shape: **seven phases (P0–P6)**, P0 being a short bench characterization pass that de-risks
everything downstream. No phase depends on hardware not yet owned.

## 2. Platform evidence (prior art)

| Platform/runtime | Prior art running the EMC2101 | Implication |
|---|---|---|
| MicroPython, RP2040-class (Pico W) | AccelerationConsortium/ac-dev-lab ships a Pico-W MicroPython port of the Adafruit lib (`src/ac_training_lab/picow/fan-control/lib/EMC2101.py`) | `machine.I2C` + single-byte transactions proven on our exact MCU family & firmware generation |
| MicroPython/CircuitPython, ESP32(-S3) | Adafruit CircuitPython lib (official); ESPHome `emc2101` component (ESP-IDF C++); bitaxeorg/ESP-Miner, shufps/ESP-Miner-NerdQAxePlus, 256foundation/mujina-miner (bare-metal C/Rust on ESP32) | Extensive field deployment on ESP32 silicon incl. S3-class boards |
| CPython / Linux SMBus | j9brown/poppy OctoPrint plugin (`octoprint_poppy/emc2101.py`, py-smbus `read_byte_data/write_byte_data` on `/dev/i2c-*`) | smbus2/py-smbus byte-primitive access proven on Raspberry Pi-class hosts |
| Other (context) | WildernessLabs/Meadow.Foundation (C#/NETMF), kvasir-io/kvasir_devices (C++), compute-blade-community/compute-blade-agent (Go) | Register semantics cross-checked across ≥6 independent implementations |

**No Linux kernel driver exists** (verified via GitHub code search over `torvalds/linux`, 2026-11-21).
There is no upstream authority to mirror or diverge from; the datasheet + surveyed implementations
are the reference set, and our clean-room driver will be one of the most thorough public Python
implementations of this part.

## 3. Transport layer analysis

### 3.1 The governing constraint: single-byte transactions only

- Datasheet defines only Write Byte / Read Byte / Send Byte / Receive Byte protocols (§4.2–4.5);
  no block read/write protocol exists for this device.
- Adafruit's implementation states it explicitly in-code: *"the chip does not support multi-byte
  reads or writes"* (`adafruit_emc2101/__init__.py`, register-definition comments).
- Receive Byte re-reads the *same* pointer location ⇒ the internal pointer does **not** auto-increment
  between transactions (to be confirmed empirically in P0; if it did increment, burst reads would be
  possible and we'd relax the contract — but design against the pessimistic case).

**Consequence:** the sibling driver's transport contract
(`burst_read(reg, n)` / `burst_write(reg, data)` as single I²C transactions) cannot be reused
verbatim. The EMC2101 transport contract becomes:

```
read_byte(reg) -> int        # one Write-Byte-pointer + Read-Byte transaction
write_byte(reg, value) -> None
probe() -> bool              # address ACK (read a harmless RO reg, e.g. 0x00)
scan() -> iterable           # 7-bit addresses present
delay_ms(ms) -> None
close()                      # optional (CPython bus release)
```

The core composes multi-register sequences explicitly (LUT load = 16 individual writes ≈ 16 × ~50 µs
at 400 kHz — negligible). This is an honest divergence from the sibling contract, documented under
Option B (see 02-api-parity-mapping.md §Transport).

### 3.2 Reuse estimate vs `FanSpeedController`

| Component | Reuse strategy |
|---|---|
| `_transport_mp.py` | New file, ~60 % shared structure: same `machine.I2C` binding, `readfrom_mem(addr, reg, 1)` / `writeto_mem(addr, reg, bytearray([v]))`; probe reg changes (`0x00` internal temp instead of `0x58`); note about `mem_read/mem_write` non-standard API carries over |
| `_transport_cp.py` | New file, ~70 % shared structure: smbus2 `read_byte_data`/`write_byte_data` (or system python3-smbus fallback), same handle-adoption pattern |
| `_core.py` | New (different register map/API), but identical *patterns*: retry ladder with escalating backoff, RMW helpers, property-per-register convention, verb-vs-property discipline, error model (ValueError/OSError/TimeoutError) |
| `_regs.py` | New leaf module, same role/style (addresses, bit constants, fixed-point helpers) |
| `_tables.py` | New (factory defaults, ideality table ×64, conversion-rate table, spin-up tables) |
| `mp.py` / `cp.py` facades | Same shape: thin subclass + mirrored `__all__` enforced by a parity test |
| `tests/`, `tools/` | Same gates: unittest discover (mock transport asserting exact transaction sequences), `api_coverage.py`, `lint_subset.py` (MicroPython subset compliance), `compileall` |

Net: the *engineering machinery* is ~80 % transferable; the *chip knowledge* is new work, which is
exactly what the research/register-map documents now make cheap.

### 3.3 SMBus-specific considerations

| Topic | Finding | Driver impact |
|---|---|---|
| Address | Fixed `0x4C`, no pin-strapped alternatives (Adafruit: "These devices don't ship with any other address") | `addr` param kept for flexibility/validation, default `0x4C` |
| Speed | 10–400 kHz supported; all prior art runs standard I²C at ≤400 kHz | No special timing needed; Pico W/ESP32-S3 default 400 kHz fine |
| TIMEOUT (25 ms) | Device resets its SMBus interface after clock stuck >25 ms; can be disabled via DIS_TO | Bus-glitch resilience comes free; expose `dis_to_enabled` for exotic buses; no action needed otherwise |
| ARA | Host-initiated; device answers only in interrupt mode when asserted | Not implemented (deliberate); polling `status_raw()` covers alert servicing |
| Clock stretching | Device never stretches | Standard blocking transactions safe |
| Invalid protocol | Ignored, registers unaffected | Safe probing behavior |

## 4. Chip-quirk catalog (driver-relevant)

Numbered for citation in the future spec/plan. All sourced to the datasheet unless noted.

| # | Quirk | Driver consequence |
|---|---|---|
| Q1 | Single-byte transactions only; pointer does not auto-increment | Single-byte transport contract (§3.1); explicit sequence composition |
| Q2 | Data Read Interlock: ext-temp snapshot triggered by MSB read; TACH snapshot triggered by LSB read — **opposite directions** | `remote_temp_c` must read `01h→10h`; `rpm()` must read `46h→47h`; unit tests assert exact order |
| Q3 | Status read clears latched bits (interrupt mode) and auto-sets MASK | `status_raw()` documented as destructive-read verb (same convention as sibling); `service_alert()` wraps it |
| Q4 | PROG bit gates writability of Fan Setting + LUT registers; LUT governs fan only when PROG=0 | Every LUT/fan-setting write path ensures PROG=1 first; profile application ends by restoring stored PROG last (ordering rule, register-map §6) |
| Q5 | TCRIT limit locked at 85 °C until TCRITOVRD set; unlock permits **one** change, then power cycle required | `tcrit_c` setter implements unlock dance; persistence layer flags files whose TCRIT differs from both 85 °C and current value (may need power cycle) — loud documentation |
| Q6 | Alert-mask reserved bits (7,5,2) read back as 1 (default `A4h`) | RMW masks touch defined bits only; constants document reserved layout |
| Q7 | Effective duty ≠ raw setting: duty% = S/(2·PWM_F); full scale at S=2·PWM_F | `set_duty_pct` quantizes through the current PWM_F; docs state effective-resolution caveat; max-resolution preset (PWM_F=31, CLK_OVR=1) recommended |
| Q8 | TACH_M behavior below min detectable RPM: false readings (mode 00, forced at 360 kHz base) vs forced `FFFFh` (modes 01–11) | `rpm()` treats `FFFFh`/0 as "unmeasurable" (returns 0.0 or raises per chosen policy); expose `tach_mode` |
| Q9 | Spin-up triggers only on 00h→nonzero transitions, never at power-up | Presets/docs manage expectations; no boot-time spin-up to rely on |
| Q10 | Diode fault sentinels (+127 °C open/VDD-short w/ FAULT bit; +127.875 °C short w/o FAULT bit) | `remote_temp_c` raises a typed error (e.g. `DiodeFaultError` ⊂ OSError family or ValueError — decide in spec) instead of returning sentinel floats; `diode_fault()` exposes the bit |
| Q11 | ALERT/TACH pin multiplexing: TACH-input mode disables ALERT output + ARA entirely | `tach_input_enabled` setter warns (docstring + return-value note); presets choose deliberately |
| Q12 | Comparator vs interrupt ALERT modes differ in status-clear and MASK semantics | `alert_mode` property with both constants; `service_alert()` behavior documented per mode |
| Q13 | FILTER encoding duplicates Level 1 (`01` and `10`) | Table-driven encode/decode; decoder maps both to LEVEL_1 |
| Q14 | No software POR, no EEPROM, no actual-duty feedback register, no ramp control, no fan-fail force | Honest N/A list in API (02 doc); reset = physical power cycle; `actual_duty_*`/`wait_for_duty`/`ramp_rate` intentionally absent |
| Q15 | Force register (`0Ch` + FORCE bit) lets host feed an arbitrary temperature into the LUT while limits still use measured temp | Bonus feature exposed (`force_enabled`, `forced_temp_c`) — useful for testing LUT without heating anything |
| Q16 | One-shot register meaningful only in standby/mixed modes | `one_shot()` verb with mode precondition check |
| Q17 | Conversion rate default 16/s; BUSY bit indicates in-flight ADC | `conversion_rate` property (table-driven, like sibling's enum style); `busy()` helper |
| Q18 | -R-only behaviors (EEPROM loader, pull-up mode select, POLARITY-at-boot) must not leak into plain-part logic | Product-ID check at `verify()` distinguishes `0x16` vs `0x28`; driver targets `0x16` and *warns* (not errors) on `0x28` since the register map is compatible |

## 5. Power-on baseline

See register-map §14. Key planning facts: fan starts at 0 %-setting (≈ minimum speed on modern
fans), manual mode active, all limits at conservative defaults, ALERT in interrupt mode. A freshly
constructed driver object therefore sees a *safe* device state; nothing in the constructor needs to
touch registers beyond the ID/probe verification.

## 6. Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Pointer actually auto-increments (contradicting §3.1 assumption) | Low | Minor (relaxation, not breakage) | P0 empirical test; contract designed pessimistically |
| Adafruit board wiring surprises (ALERT pull-up value, FAN pull-up presence, DP/DN termination) | Medium | Minor | P0 bench inspection + `i2cdetect`/probe; board schematic/datasheet review |
| TCRIT one-shot lockout bites during testing | Medium | Minor (test friction) | Documented; bench procedure includes power-cycle step; P0 records initial TCRIT state |
| Flash wear from config saves on MicroPython | Low (explicit-save-only design) | Low | No autosave; save is user-invoked; FAT/LFS wear-leveling on Pico W |
| ESP32-S3 I²C pin/bus differences vs Pico | Certain (different pins) | Trivial | Board-aware pin selection in examples (same pattern as sibling's `sys.platform` auto-select) |
| smbus2 availability on Pi 3A+ image | Low | Trivial | `pip install smbus2` documented; system python3-smbus fallback (sibling pattern) |
| Datasheet ambiguities (FILTER dup, Note 6.2 scope, TACH_M at divided clocks) | Certain | Low | P0 characterizes each; driver encodes observed behavior with datasheet citations |

## 7. Phased effort plan

Phases ordered by dependency; each has entry/exit criteria. (Per agreement: phases, not man-hours.)

### P0 — Bench bring-up & characterization *(hardware)*
Entry: Adafruit board + Pico W + ESP32-S3 + Pi 3A+ assembled.
Tasks: probe at `0x4C`; read ID trio (`FDh/FEh/FFh`) — record actual revision vs marking "2102 OBTH";
confirm single-byte-only behavior (attempt 2-byte read, observe NACK/truncation); verify pointer
behavior; measure ALERT pin idle state (interrupt mode expected high w/ pull-up); exercise TACH
input with a known fan; characterize TACH_M modes; confirm TCRIT lockout behavior; record
conversion timing (BUSY bit cadence at 16/s); inspect board schematic/photos for pull-ups.
Exit: `NOTES/bench-characterization.md` with measured values; quirk catalog §4 confirmed/refuted item-by-item.

### P1 — Package skeleton & transport layer
Repo/package scaffold per 05-architecture-sketch.md; `_regs.py` (full map + constants + fixed-point
helpers); `_tables.py`; `_transport_mp.py`/`_transport_cp.py` implementing the single-byte contract;
retry ladder + error model; `mp.py`/`cp.py` facades with empty-but-valid class shells.
Exit: `probe()`/`scan()` green on all three platforms; unit tests for transports (mocked).

### P2 — Core device API (no persistence)
All properties/verbs of the parity table except persistence: identity, temps (+fault handling),
limits (incl. TCRIT unlock dance), status/alert service sequence, manual duty + quantization, LUT
(get/set whole + per-index, ascending-temp validation, PROG ordering), hysteresis, PWM frequency
solver, DAC toggle, spin-up, tach threshold/min_rpm, calibration (ideality/beta), scratchpads,
standby, conversion rate, filter, force/one-shot, presets (`configure_4wire_fan`).
Exit: full mock-backed unit suite passing; `api_coverage` 100 % of public members exercised.

### P3 — Persistence layer ("virtual EEPROM")
JSON schema v1 (per 03-persistence-opinion.md §Design): versioned, sectioned, ID-stamped;
`save_config(path=None)` / `load_config(path=None)`; `config_path` attribute + `config_file` ctor
kwarg; validation policy (version, product-ID match, range checks); apply-ordering rules (PROG
dance, TCRIT caveat); atomic-write strategy; platform default paths.
Exit: round-trip tests (save→mutate→load restores); corruption/stale-version/mismatch-ID rejection
tests; real-file smoke test on Pico W flash and Pi filesystem.

### P4 — Quality gates & docs
`lint_subset.py` MicroPython-compliance gate tuned to this codebase; `tools/api_coverage.py`;
`docs/` (API reference, wiring, per-platform install, quickstart, operational notes incl. boot-window
and TCRIT caveats); README/LICENSE/CHANGELOG/pyproject (LGPL-2.1-or-later proposed).
Exit: all four sibling-style gates green on host; docs complete.

### P5 — Examples
`examples/pico_demo.py`, `esp32_demo.py`, `rpi_demo.py` (probe → temps → duty sweep → RPM →
save/load config), `hw_smoke_test.py` (self-restoring core-behavior smoke), `e2e_hardware_test.py`
(full matrix over every public API domain, self-restoring, board-aware pins).
Exit: scripts run cleanly on each platform (manual execution recorded).

### P6 — Hardware E2E validation
Run the full E2E matrix on all three platforms; record results table (sibling PLANS.md §7 style);
fix any silicon-behavior deltas discovered (update NOTES + tests).
Exit: E2E matrix PASS on 3/3 platforms; handoff summary written.

**Critical path:** P0 → P1 → P2 → P3 → {P4 ∥ P5} → P6. P4/P5 can overlap once P3 lands.
