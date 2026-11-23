# Build the EMC2101 cross-platform fan controller driver and publish it

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`,
`Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.
Every stopping point — even a partially completed task — gets a timestamped `Progress`
entry, and every decision gets a `Decision Log` entry. When revising this plan, reflect the
change across all affected sections and append a revision note at the bottom explaining what
changed and why.

## Purpose / Big Picture

After this plan completes, anyone can drive a SMSC/Microchip EMC2101 fan controller from
ordinary Python on three very different machines — a Raspberry Pi Pico W running
MicroPython, an ESP32-S3 running MicroPython, and a Raspberry Pi 3A+ running full CPython —
using one package (`emc2101`) with one API. With it you can read the die temperature and an
external thermistor-diode junction temperature, program the chip's eight-entry
temperature-to-fan-speed lookup table, drive the fan manually at any percent duty, measure
fan speed in RPM, service thermal alarms, and — unlike the bare chip, which forgets
everything at power-off — save the entire configuration to a small human-readable JSON file
and have it restored automatically at startup. That last capability simulates in software the
EEPROM auto-load behavior that only the pricier EMC2101-R variant has in silicon, closing the
gap to one line of application code.

How to see it working: on each of the three boards, `examples/pico_demo.py` (and its
ESP32/RPi siblings) prints temperatures, sweeps the fan duty, reports measured RPM, and
saves then loads the config file. `examples/e2e_hardware_test.py` exercises every public API
method against the real chip with observable-effect checks and ends with the line
`E2E HARDWARE MATRIX: PASS`. Finally, the finished and fully validated repository is
published as the public GitHub repository `emc2101-fan-speed-controller`.

## Progress

- [x] (2026-11-21) Research phase complete: seven documents in `research/` (feasibility and phased effort, API parity mapping, persistence opinion, reference notes, architecture sketch, register map appendix, README index).
- [x] (2026-11-22) Working directory relocated to `EMC2101_Fan_Speed_controller`; datasheet moved to `reference/` (will be gitignored); ExecPlan format adopted from the OpenAI cookbook template; hardware targets and pins confirmed from the MAX31760 sibling project.
- [x] (2026-11-22) Pre-M1 hardware check on the Pico W bench (COM16): EMC2101 seen at 0x4C; identity registers FDh=0x16 / FEh=0x5D / FFh=0x01 all match datasheet expectations.
- [x] (2026-11-22) `scripts/` tree created per user ruling (D23): bench-grouped test/diagnostic scripts are kept in the git tree; seeded with `scripts/pico/probe_bus.py` (verified green from the new location) and indexed in `scripts/README.md`.
- [x] (2026-11-22) M0 Repository foundation complete: `git init -b main`; two commits — `edee0fc` scaffolding (`.gitignore`, `LICENSE` full LGPL-2.1 text with "or later" header, `pyproject.toml` v0.1.0, `requirements.txt`, `README.md`, `.github/workflows/ci.yml` four-gate matrix, `emc2101/__init__.py` stub, `.gitkeep` placeholders for `examples/`/`tests/`/`tools/`/`docs/`/`NOTES/`) and `1ba6c1f` planning trail (`AGENTS.md`, this file, `research/` ×7, `scripts/` ×2). Acceptance verified: `git check-ignore reference/EMC2101_datasheet.pdf` echoes the path (exit 0); `git ls-files` shows zero entries under `reference/` and all seven research documents tracked; working tree clean.
- [x] (2026-11-22) M1 Bench bring-up & characterization complete (Pico W portion): identity probe green (ID trio 0x16/0x5D/0x01 matches datasheet Rev 2.54); protocol probes complete — two-byte over-reads return silent 0xFF padding (no exception), bare Receive/Send Byte transactions desynchronize the chip's SMBus interface (EIO; recovers on reconnect), status-read auto-MASK side effect empirically confirmed; after user re-seated the diode pins: external temp live at 28.0 °C, interlock re-test clean (200 stable reads, 0/100 order deltas > 1 °C), BUSY cadence measured (~64 ms period ≈ 16/s default rate, ~26 ms high per window); TACH still 0xFFFF at all duties → fault isolated to the fan side (tach wiring or motor power). All eight ambiguities A1–A8 explicitly disposed (resolved or deferred-with-reason) in `NOTES/bench-characterization.md`; fan-blocked items (A3 TACH_M sweep, A7 live RPM check, ALERT-pin idle state, breakout photo) deferred to the M7 re-test per D26. Acceptance met: notes file complete, ID trio recorded, single-byte and pointer behavior empirically confirmed.
- [x] M1 Bench bring-up & characterization: probe at 0x4C, ID trio, single-byte/pointer behavior, interlock orders, TACH_M modes, conversion timing; write `NOTES/bench-characterization.md`.
- [x] (2026-11-22) M1 follow-up — TACH channel re-isolated with user bench data: multimeter continuity confirms the TACH net (board point ↔ chip TACH input) and the fan PWM lead (fan ↔ board PWM pin); the fan is powered and spinning at ~660 RPM (floor speed at the 0 setting), ruling out the unpowered-motor and disconnected-wire suspects. 660 RPM ≫ the ~82 RPM detection floor, so a live signal at the pin would read a count in the thousands, not 0xFFFF. Fault narrowed to the TACH signal path: fan open-collector tach stage, TACH-net pull-up (breakout pull-up inventory still outstanding; an OC tach needs a receiver-side pull-up), or the chip's TACH input stage / ALT_TCH handling. Added `scripts/pico/probe_tach_signal.py` (GPIO-tap edge/period characterization, read-only) for the next bench session; D26 deferral stands.
- [x] (2026-11-22) M1 follow-up continued — TACH re-test after user power cycle (`char_tach_diag.py`): chip side EXONERATED. Health check PASS at fresh POR; ALT_TCH latches (wrote 0x04, readback 0x04); TACH_M field writable at the 360 kHz base — all four encodings latch, so Note 6.2 "forcing" does not manifest at register level (A3 partially resolved); CLK_SEL=1 trial unchanged (still 0xFFFF); restore PASS. The counter is alive but starved despite live low-going pulses at the pin → fault narrowed to the HIGH state of the TACH net (missing receiver-side pull-up now the top suspect; the same gap would also break the ALERT open-drain idle-high). Next bench step (user's hands): temporary 10 kohm pull-up bridge to 3.3 V + re-run, or GP2 tap via `probe_tach_signal.py`. A3 row updated in the ambiguity table.
- [x] (2026-11-22) M1 follow-up CLOSED — TACH root cause confirmed and live RPM validated. User bridged a 10 kOhm pull-up from the TACH net to 3.3 V; the unchanged `char_tach_diag.py` re-run went from the 0xFFFF sentinel to live counts (7959→7963 over 1 s ≈ 678 RPM at 0 % drive), confirming the missing receiver-side pull-up as the root cause (the OC tach net floated high between pulses, defeating the edge detector). New probe `scripts/pico/char_tach_pwm_gate.py` tested the reported PWM-gating caveat: count stable at 0 % drive (7955 ×3) and at 50 % drive (≈2895 ×3 ⇒ ~1865 RPM) — this fan does NOT gate its tach at zero duty, and the control loop responds monotonically. Ambiguity A7 closed early (formula 5,400,000/count validated against the user-measured ~660 RPM floor within ±10 %); A3 remains partially resolved (behavioral distinction needs a sub-min-RPM stall, unreachable on this bench). D27 amends D26 accordingly; both prior follow-up entries checked off.
- [x] (2026-11-22) Board-guide finding recorded (user-added `reference/emc2101-fan-controller-and-temperature-sensor.pdf`, Adafruit product 4808 guide): page 7 documents the breakout's solder-jumper pull-ups — the FAN-pin pull-up ships ENABLED (cut only for DAC mode), while the TACH/ALERT pull-up ships DISABLED (bridge "when using the Tach pin for alerts"). This explains the round-2 root cause exactly: with the jumper unbridged, the net's idle-high in TACH-input mode depends on the fan's own tach stage, and the bench fan has none. Two equivalent fixes documented (bridge the TACH jumper or add an external ~10 kOhm pull-up to 3.3 V); diagnostic rule "sentinel count + verified-spinning fan ⇒ check the pull-up first". Recorded in `research/04-reference-notes.md` (new §5), `NOTES/bench-characterization.md` (mechanism paragraph), and a short Hardware-notes section in `README.md` per user instruction (full treatment lands in the M5 wiring guide). The PDF is explicitly gitignored.
- [x] (2026-11-22) M2 Package skeleton & transport layer complete: `emc2101/` package committed (`_core.py` lifecycle core — verify/probe/scan/close + context manager; `_regs.py` register map, bit-fields, fixed-point helpers; `_tables.py` POR defaults, ideality LUT, conversion rates, spin-up times, beta values; `_transport_mp.py` / `_transport_cp.py` single-byte transports sharing one retry ladder; `mp.py` / `cp.py` facades exporting identical `__all__`). All four quality gates green: 91 unit tests over fakes (retry ladder, validation, identity verification, facade parity, public-surface pinning), api_coverage 100 % (133/133 members), MicroPython-subset lint clean on all six shared modules, compileall clean. Acceptance on all three platforms per D29: Pico W (COM16) full live probe via `tools/deploy_mp.py` + `scripts/pico/probe_pkg.py` (verify → 0x16 plain, probe True, scan [0x4C]); ESP32-S3 (COM7) and RPi 3A+ chip-independent import/construct smokes (`scripts/esp32/smoke_import.py`, `scripts/rpi/smoke_import.py`) — deploy, import, constructor, and helper assertions all OK; live probe/scan on those two benches folds into the M7 rotation. The new suite caught one real bug (ext_temp_to_raw accepted temperatures below the datasheet −64 °C floor). Commit `c190b0a`.
- [x] M2 Package skeleton & transport layer: `_regs.py`, `_tables.py`, both transports, facades; probe/scan green on all three platforms; mocked transport tests.
- [x] (2026-11-22) M3 Core device API complete: `emc2101/_core.py` rewritten from the M2 lifecycle stub to the full protocol surface per `research/02-api-parity-mapping.md` — identity (`part_info`), temperatures (MSB-first interlock read, `DiodeFaultError` on the 0x3F8/0x3FF sentinels), limits (incl. the TCRIT one-time-unlock dance), status/alerts (destructive-read discipline, reserved-bit-preserving alert-mask RMW, service/clear sequence), manual duty (quantized through the live PWM_F grid), PWM output configuration (frequency solver over PWM_F/PWM_D/CLK_SEL/CLK_OVR with tie-break toward the max-resolution path), LUT (eight `(temp_c, duty_pct)` pairs, ascending validation, PROG dance with restore-on-failure), tachometer (LSB-first interlock, pulses-per-rev scaling, min-RPM convenience pair), spin-up composites, calibration (ideality nearest-match, beta), scratchpads, power modes (standby + guarded `one_shot()`), conversion/filter/dis-to/queue controls, `configure_4wire_fan()` preset, and raw-tier `read_reg`/`write_reg`. New leaf module `emc2101/_faults.py` (`DiodeFaultError(OSError)`); facades export the six new public names (parity held by `test_api_parity.py`). Unit suite grew 91 → 223 tests across five new files (`test_temperature_limits`, `test_status_alerts`, `test_manual_pwm`, `test_lut`, `test_tach_spinup`, `test_calibration_misc`) plus a stateful register-file mode and a `write_entries` helper added to `tests/fakes.py`; transaction-sequence assertions guard both interlocks, the PROG dance (including restore when a mid-write bus failure is injected), the TCRIT unlock ordering, and the no-op paths. All four gates green: 223 tests OK, api_coverage 100 % (201/201 members — tool extended to check facade `__all__` AND every public class attribute, with a drift-guard frozenset in `test_public_surface.py`), lint clean, compileall clean. Live acceptance on the Pico W bench via new self-restoring probe `scripts/pico/probe_m3.py` (snapshots 27 registers, exercises the whole API, restores and verifies byte-for-byte): **M3 LIVE PROBE OK** — every observed value matches the documented POR table (LUT uniformly 127 °C/max inactive, PWM_F 0x17 ⇒ 7826 Hz, spin-up 3.2 s @ 100 % with FAST_TACH, ideality idx 0x12, 16/s conversion, 70/85 °C limits, beta autodetect on), and `rpm()` returned 1870.5 RPM at 50 % drive, matching the M1 measurement (~1865) through the driver's own interlock+formula path. The probe also caught two probe-side contract slips (int-vs-tuple from `read_reg(n=1)`; an invented member name not in the parity doc) — both fixed in the probe, no driver change needed. ESP32-S3/RPi legs fold into M7 per D29/D30.
- [x] M3 Core device API (no persistence): full property/verb surface; mock-backed unit suite green; api_coverage 100%.
- [x] (2026-11-22) M4 Persistence layer complete: new leaf module `emc2101/_persist.py` (filesystem-agnostic core per D4/D13–D16): JSON schema v1 with `encode`/`decode` (full validation: version pin, identity stamps as canonical lowercase `0xNN` strings, integer °C fields, LUT of exactly 8 non-descending entries, spin-up enabled/time cross-checks, PWM frequency-consistency check), `collect_state(read_byte)` (device → state; emits ints for the 1 °C-resolution fields so round-trips are byte-stable), and `apply_state(write_byte, read_byte, state, *, strict=True)` (preflight validation before any bus traffic; ordered writes ending with fan configuration; TCRIT special case — a stored value differing from both 85 °C and the current value gets the one-time unlock dance attempted once, otherwise skipped with a loud warning; the PROG dance always ends with the stored PROG bit; optional strict post-apply read-back producing a per-register diff report, ON by default per D15). File-I/O glue in `_core`: `save_config(path=None)` (atomic temp-file + rename where the port supports it, plain-overwrite fallback) and `load_config(path=None, *, strict=True)` (product-ID mismatch refused before any register write; revision mismatch warns); constructor kwarg `auto_load` per D14 (omitted → zero file I/O; missing file → silent no-op; corrupt file → raises before any register write); facades pass `auto_load=config_file is not None`. New exceptions `ConfigFormatError`/`ConfigValidationError` (ValueError subclasses) and `ConfigApplyError` (OSError subclass). Unit suite grew 223 → 261 tests with `tests/test_persist.py` (round-trip stability incl. byte-identical re-encode, unknown-version rejection, every field-validation branch, descending-LUT refusal, wrong-count refusal, product-ID refusal asserted via an empty transport log, revision-mismatch warning, TCRIT skip/noop cases, strict-diff reporting, atomic-write simulation, constructor auto-load matrix). Toolchain: `tools/deploy_mp.py` ships `_persist.py`; `tests/lint_subset.py` covers it and now permits `json`/`time`/`os` imports in shared modules (all ship with MicroPython v1.29.0 on both target ports — documented in its docstring, D32); `test_public_surface.py` pins `save_config`/`load_config`. All four gates green: 261 tests OK, api_coverage 100 % (203/203 members), lint clean, compileall clean. Live acceptance on the Pico W bench per D29/D30 via new self-restoring probe `scripts/pico/probe_persist.py` (raw safety-net snapshot of 40 registers; save → mutate 8 domains through the public API → load with strict read-back → verify restoration → delete probe file; never touches TCRIT so the one-time unlock survives): **M4 LIVE PROBE PASSED** — flash round-trip clean, no temp files left behind, strict read-back diff empty, every mutated value restored. ESP32-S3/RPi legs fold into M7.
- [x] (2026-11-22) M4 Persistence layer: JSON schema v1, save/load with validation and apply-ordering, atomic write; round-trip and corruption tests.
- [x] (2026-11-22) M5 Quality gates & docs complete: the two host gates were already tuned to this codebase during M2–M4 (`tests/lint_subset.py` MicroPython-subset compliance over every shared module incl. `_persist.py`; `tools/api_coverage.py` checking facade `__all__` exports AND public class attributes, backed by the `test_public_surface.py` drift guard) and are re-verified green on the final tree. New `docs/` set: index (`README.md`), `quickstart.md` (per-platform install, first program for both facades, LUT control, save/load), `api-reference.md` (every public member grouped by domain with ranges, exceptions, side effects), `wiring.md` (breakout connections, D10 per-host pin tables, pull-up jumper rules with the bench-confirmed diagnostic rule, DAC-mode caveat, recommended loadout), `persistence.md` (schema v1 with a POR-accurate example, validation policy, apply ordering, TCRIT special case, auto-load semantics, LUT ordering rule D31, practical notes), `operational-notes.md` (cold-boot window + mitigations, TCRIT lifecycle, ALERT/TACH pin trade-offs, ARA general-call scan footprint, force-register testing technique, SMBus TIMEOUT, retry ladder/error model, no-software-POR reset gap). New `CONTRIBUTING.md` (prerequisites, the four gates, architecture ground rules incl. clean-room policy and honest-edges, hardware-testing conventions incl. self-restoring mandate and TCRIT caution, commit hygiene, licensing) and `CHANGELOG.md` starting at 0.1.0 (unreleased). Root `README.md` polished: status line reflects M0–M4 completion, new Documentation section, layout table updated. Doc accuracy was checked against the implemented API while writing and two drifts were caught and fixed pre-commit (verify() returns the product ID byte, not True; the POR alert-mask decodes with only INT unmasked). All four gates green: 261 tests OK, api_coverage 100 % (203/203 members), lint clean, compileall clean.
- [x] (2026-11-22) M5 Quality gates & docs: lint gate, coverage tool, `docs/`, README polish, CHANGELOG.
- [x] (2026-11-22) M6 Examples complete: five scripts in `examples/` — `pico_demo.py` / `esp32_demo.py` / `rpi_demo.py` (identical board-aware body: runtime platform detection via sys.platform + os.uname().machine, verify → temperatures → configure_4wire_fan(25 kHz) → manual duty sweep with RPM reporting → save_config → POR-equivalent calm state), `hw_smoke_test.py` (self-restoring: identity, temperature plausibility, duty-sweep quantization, settled-RPM floor > 500, persistence round trip, byte-for-byte restore; ends `HW SMOKE TEST: PASS`), `e2e_hardware_test.py` (eleven sections per the M7 matrix: identity, temps/setpoints, manual/duty/PWM, LUT incl. force-register synthetic temperature, tach/RPM, faults/alerts, calibration, lifecycle, persistence incl. two-phase cold-boot-with-profile on the MCU benches and fresh-instance approximation on the Pi, presets, error model; self-restoring; one PASS/FAIL line per section, ends `E2E HARDWARE MATRIX: PASS`). Every public class member appears in at least one E2E section (checked against the pinned surface). New `examples/README.md` indexing the five scripts with per-platform run commands. `tests/lint_subset.py` extended: all five examples join the MicroPython-subset file set and `sys` is allowed (ships with MicroPython v1.29.0, same rationale as D32). New host-side dev utility `tools/probe_error_model.py` (fake-transport exercise of the documented ValueError paths). Live Pico W work surfaced the PROG-polarity inversion inherited from M3 (D34): fixed across `_core.py`, `_persist.py`, tests, and the research erratum before trusting any example output. Verification: all four host gates green (261 tests, api_coverage 203/203, lint incl. examples, compileall); on real silicon `hw_smoke_test.py` ends `HW SMOKE TEST: PASS` (duty sweep sticks: raw 12/23/34/46; settled 2110 RPM at full drive) and the M4 live persistence probe re-passed on the fixed package.
- [x] (2026-11-22) M6 Examples: three platform demos, `hw_smoke_test.py`, `e2e_hardware_test.py`.
- [ ] M7 Hardware E2E validation: smoke + full matrix PASS on Pico W, ESP32-S3, RPi 3A+; results recorded in Artifacts.
- [~] (2026-11-22) M7 in progress — Pico W leg: E2E phase A (full matrix + cold-boot profile staging) passes all sections; phase B initially FAILED in the persistence section (`0x4c expected 0x2c got 0x0c`), root-caused to the undocumented PROG=0 mirror/drop behavior (Surprise above; D35). Fix implemented in `_persist.py` (collect + strict read-back dances), `examples/e2e_hardware_test.py` (snapshot dance, S4 LUT capture/restore dance, safety-net repair under PROG=1) and `examples/hw_smoke_test.py` (same snapshot/restore discipline); `research/emc2101-register-map.md` gained §16 (four live observations incl. Table 6.28 POR LUT default 3Fh). Host gates green: 264 tests OK, api_coverage 100 % (203/203), lint clean, compileall clean. Pending: redeploy + rerun both phases on COM16, then ESP32-S3 (COM7) and RPi 3A+ legs.
- [~] (2026-11-22) M7 in progress — second phase-B failure mode root-caused and fixed (D36): after the D35 fix, uninstrumented phase-B runs still failed intermittently with `0x4c expected 0x29 got 0xc` while an instrumented run (per-transaction logging adding µs-scale overhead per I²C op) passed the full matrix. Forensics (trace-log retrieval via `mpremote cat`, burst analysis of the passing trace, step-by-step probes) established that the Fan Setting READ-OUT lags one temperature-conversion window (~64 ms at 16/s) after a FAN_CFG PROG-bit transition, keeping the previously active drive source visible; writes stick immediately, so step-by-step probes with explicit sleeps never reproduced it. Fix: `_persist._settle_ms()` (portable 100 ms settle, `SETTLE_MS`) called after every PROG-on transition before fan-domain reads in `collect_state`, plus a settle-and-retry-once pass over disagreeing registers in the `apply_state` strict read-back; the E2E/smoke snapshot-capture dances, S4 raw-LUT capture/restore, and safety-net verification got the same 0.1 s settle. `MirrorTransport` now models the stale read-out window (`settled()` advances it; module-level fake settle keeps the suite sleep-free) and three new regression tests pin the behavior (collect settles, strict retry absorbs the stale mirror, genuine mismatches still fail after retry). Research note gained §16.5. Host gates green: 267 tests OK, api_coverage 100 % (203/203), lint clean, compileall clean. Pending: redeploy + 3× phase A→B cycles on COM16, then ESP32-S3 (COM7) and RPi 3A+ legs.
- [~] (2026-11-23) M7 in progress — remote-diode verification REOPENED on the ESP32-S3 bench after the user re-benched the board there (wires moved from the Pico W): post-power-up readings of 35–38 °C against 24 °C ambient, decaying to a live 29.0 °C within ~4 min with no chip writes (see Surprises). Investigation paused at user departure; resume with host-polled drift samples every ~100 s over ~15–30 min (short fresh mpremote sessions — see the mpremote-stall Surprise) plus a coordinated finger-on-junction touch test, then conclude (slow convergence vs steady-state offset vs wiring) and record the outcome before the RPi 3A+ leg. No code changes; tree remains gated.
- [~] (2026-11-23) M7 in progress — Pico W leg CLOSED and ESP32-S3 leg COMPLETE. Pico W (COM16): after the D36 deploy, three consecutive full E2E phase A→B cycles PASSED (persistence section included) plus `hw_smoke_test.py` PASS; committed as `7c8dcb4`. Board rotated to the ESP32-S3 bench (single-board rotation confirmed by user). ESP32-S3 (COM7, I2C0 SDA=GPIO41/SCL=GPIO42, MicroPython v1.29.0): comms established (scan `[0x4c]`; identity trio 0x16/0x5D/0x01 exact match); `hw_smoke_test.py` PASS (duty quantization identical to the Pico — raw 12/23/34/46 on the 0x17 grid; settled 2123 RPM > 500 floor; strict persistence round trip clean; 40-reg safety-net restore byte-for-byte); E2E phase A all sections PASS with profile staging + soft reset; phase B PASSED twice (two full A→B cycles), each verifying the constructor cold-boot auto-load (local high 65 C, scratchpad 0xAB, LUT entry 0 @ 30 C) before the full eleven-section matrix (`E2E HARDWARE MATRIX: PASS`). Notable: this bench has the fan AND diode connected (live tach ~2100–2300 RPM, remote temp ~28 °C, diode-fault negative check passes) — unlike the Pico bench's open diode channel; the PSRAM init errors in the ESP32-S3 boot log are a module-firmware artifact (no PSRAM populated) and do not affect MicroPython or I²C. One operational note: mpremote can linger in a REPL follow-loop after the phase-A soft reset and hold the port; kill the stale process before the phase-B run. Remaining: RPi 3A+ leg (SMBus bus 1, CPython facade, fresh-instance approximation for phase B), then results table + gate.
- [ ] M8 Independent code review: independent agent reviews the full tree after M7; every finding addressed (fixed + gated, or declined + logged) before M9 proceeds.
- [ ] M9 GitHub publication: create public repo, push full history, verify.

## Surprises & Discoveries

Seeded from the research phase; implementation-phase discoveries are appended below with
evidence.

- Observation: the EMC2101 supports single-byte SMBus transactions only; the register pointer does not auto-increment between transactions.
Evidence: the datasheet defines only Write Byte / Read Byte / Send Byte / Receive Byte protocols (§4.2–4.5), and Adafruit's driver states in a code comment that "the chip does not support multi-byte reads or writes". Consequence: the transport contract is single-byte and the core composes multi-register sequences explicitly. Empirical confirmation is scheduled in M1.
- Observation: Adafruit's CircuitPython driver reads the external-temperature LSB *before* the MSB, contradicting its own adjacent comment and the datasheet's Data Read Interlock (§6.1: reading the MSB refreshes the LSB shadow).
Evidence: `adafruit_emc2101/__init__.py` ext-temp property versus the comment "read Msbyte first". Our driver reads MSB-first and regression-tests the transaction order.
- Observation: no Linux kernel driver for the EMC2101 exists.
Evidence: GitHub code search over `torvalds/linux` returned zero results (2026-11-21). There is no upstream authority to mirror; the datasheet plus surveyed third-party implementations are the reference set.
- Observation: the chip's fixed 7-bit address is 0x4C.
Evidence: datasheet §4.7 (`100_1100b`); Adafruit constant `I2C_ADDR = const(0x4C)`; six independent third-party drivers agree.
- Observation: the MAX31760 sibling driver's LUT is 48 single-byte duty entries (registers 20h–4Fh), not the 16 entries assumed in early interview notes.
Evidence: `FanSpeedController/max31760/_regs.py` (`LUT_LEN = 48`). Corrected in `research/02-api-parity-mapping.md`.
- Observation: the averaging-filter register encodes "Level 1" twice (bit patterns 01 and 10).
Evidence: datasheet Table 6.30. The decoder maps both to LEVEL_1; the encoder emits 01.
- Observation: the TCRIT limit is locked at 85 °C until the TCRITOVRD bit is set, and the unlock permits only one change before a power cycle is required.
Evidence: datasheet §6.5 bit 1. Drives the special handling in `tcrit_c` and in the persistence layer.
- Observation (inherited from the sibling project): MicroPython's `machine.I2C` exposes `readfrom_mem`/`writeto_mem`; the names `mem_read`/`mem_write` do not exist on any port.
Evidence: `FanSpeedController/SUMMARY.md` (live-testing finding). The MicroPython transport uses the former pair.
- Observation (inherited from the sibling project): when a device may reset or NACK mid-transaction, issue the write exactly once and swallow the expected error; a retry ladder would re-trigger the event.
Evidence: sibling decision D33 (soft-POR errno-121 root cause). Relevant here to any operation where the chip can momentarily vanish from the bus.
- Observation (first live silicon contact, 2026-11-22): an I2C scan on the Pico W bench shows exactly two addresses — 0x4C (the device) and 0x0C (on-wire form of the ARA general-call address 0x06, §4.6).
Evidence: `python -m mpremote connect port:COM16 run probe_bus.py` (ad-hoc sandbox script): scan returned `[0xc, 0x4c]`; reads of FDh/FEh/FFh returned 0x16/0x5d/0x01. Consequence: (a) a healthy EMC2101 makes `scan()` report 0x0C alongside the device — treat it as part of the chip's footprint, not a foreign device; (b) `probe()` targets 0x4C only; (c) the ID trio matches datasheet Rev 2.54 expectations exactly — plain EMC2101 confirmed on the bench, no revision deviation.
- Observation (host environment, 2026-11-22): bare `mpremote` is not on the PATH of this
machine's default PowerShell; the module form works (`python -m mpremote --version` →
1.29.0). Both COM16 and COM7 enumerate normally.
Evidence: `mpremote connect port:COM16 run ...` failed with "The term 'mpremote' is not
recognized"; the identical call prefixed `python -m` ran the probe successfully (twice).
Consequence: every mpremote invocation in this plan and in `scripts/README.md` uses
`python -m mpremote`.
- Observation (first live silicon contact, 2026-11-22): multi-byte reads do not raise an error; the chip transmits the requested byte and then releases the bus, so over-read bytes come back as 0xFF (pulled-up line).
Evidence: `readfrom_mem(0x4C, 0x00, n=2)` returned `0x16, 0xFF` on repeated runs (internal temp followed by undriven-bus 0xFF), no OSError. Consequence: the transport cannot rely on exceptions to catch over-long reads and must enforce single-byte reads by construction; 0xFF padding is indistinguishable from data at byte level. Also confirms the pessimistic pointer model (no auto-increment; resolves ambiguity A6).
- Observation (first live silicon contact, 2026-11-22): bare Receive Byte / Send Byte transactions (no register-address phase) are unusable against this chip: a bare read returns a value unrelated to the last addressed register, and a bare write — accepted without error — desynchronizes the SMBus interface such that the next transaction fails with EIO (errno 5).
Evidence: M1 one-off experiment (transcript in `NOTES/bench-characterization.md`): after `writeto_mem(0x11, [0x11])`, bare `readfrom` returned 0x00; bare `writeto([0x22])` left scratchpad 0x11 unchanged and the following read raised EIO. Recovery: fresh mpremote connection (fresh `machine.I2C` init) plus the chip's ~25 ms SMBus TIMEOUT reset; subsequent health check PASS. Consequence: the driver uses only register-addressed Write Byte / Read Byte (`writeto_mem`/`readfrom_mem`) — the planned transport contract is empirically validated; bare forms are forbidden in-tree (rule noted in `char_protocol.py`'s docstring).
- Observation (first live silicon contact, 2026-11-22): the interrupt-mode status-read side effect is real — reading Status while EXT_HIGH was latched auto-set the MASK bit (Config 0x03: 0x00 → 0x80).
Evidence: diagnostic status read during M1 (status 0x16 = FAULT + EXT_HIGH, diode-fault sentinel above the 70 °C ext-high limit); Config subsequently read 0x80. Matches datasheet §6.4 exactly. Consequence: `service_alert()` semantics (status read clears latches, auto-sets MASK) rest on confirmed behavior; MASK was cleared back to POR afterwards.
- Observation (bench state, 2026-11-22): the Pico W bench presents an OPEN external-diode channel (raw 0x7F/0x00 = +127.000 °C sentinel, FAULT status bit set) and zero tach pulses at every manual duty level (TACH 0xFFFF through 100 % drive).
Evidence: `char_protocol.py` / `char_tach.py` runs 2026-11-22. Most likely cause: the fan and/or the 2N3906 diode are not currently connected to the Adafruit 4808 breakout (single-controller rotation per D25). Consequence: TACH_M sweep (ambiguity A3), BUSY cadence, and the interlock torn-pair exercise are PENDING re-test; bench-loadout question raised with the user.
- Observation (bench repair, 2026-11-22 round 2): the TACH fault was a missing receiver-side pull-up on the open-collector tach net.
Evidence: with nothing pulling the net high, the chip read the 0xFFFF sentinel at every duty despite live low-going closures at the pin (multimeter beeps) and a verified-spinning fan (~660 RPM floor); bridging 10 kOhm from the net to 3.3 V made the same diagnostics read live counts (7955–7963 ⇒ ~678 RPM) with no other change. Consequence: (a) an OC tach input needs a receiver-side pull-up even where the datasheet app notes are silent — document it in the M5 wiring guide; (b) the same gap breaks the ALERT open-drain idle-high, so interrupt mode on this breakout also relies on that resistor; (c) the reported caveat "some fans gate their tach output at 0 % PWM duty" did NOT reproduce on this bench (stable count at FS=00h) — kept as a general warning for other fans. The live RPM data also closes ambiguity A7 early.
- Observation (board hardware, 2026-11-22): the Adafruit 4808 breakout's TACH/ALERT pull-up is behind a solder jumper that ships disabled; the FAN-pin pull-up ships enabled.
Evidence: Adafruit board guide page 7 (`reference/emc2101-fan-controller-and-temperature-sensor.pdf`, added by the user): "TACH - solder this jumper to enable the pull-up on the Tach pin when using the Tach pin for alerts"; "FAN - Cut this jumper to disable the built-in pull-up on the Fan pin when using the DAC/DC voltage output". Corroborated empirically: with the jumper unbridged and a fan lacking an internal tach pull-up, the net floated high in TACH-input mode (0xFFFF sentinel at every duty); an external 10 kOhm to 3.3 V restored live counting. Consequence: fan-to-fan variation in internal tach pull-ups means the driver docs must carry the pull-up diagnostic rule (sentinel count + spinning fan ⇒ bridge the onboard TACH jumper or add an external ~10 kOhm pull-up); the same pull-up also defines the ALERT open-drain idle-high. README gained a Hardware-notes section now; full treatment in the M5 wiring guide.
- Observation (MicroPython environment, 2026-11-22): the rp2 port of v1.29.0 takes the I2C clock-speed keyword as `freq=`, not `baudrate=`.
Evidence: `machine.I2C(0, sda=..., scl=..., baudrate=100000)` raised `TypeError: extra keyword arguments given` during the M2 package probe; the identical call with `freq=100_000` (the proven M1 probe form) succeeded. Consequence: all in-tree bench scripts use `freq=`; the driver itself never constructs a `machine.I2C` (caller-supplied), so this constrains bench scripts only.
- Observation (format semantics, 2026-11-22): the external-temperature field is 11-bit two's-complement and could encode down to −128.0 °C, but the datasheet guarantees only −64.0..+127.875 °C.
Evidence: the first `ext_temp_to_raw` cut bounded its range check at −1024 steps (−128 °C) and silently accepted −64.125 °C; the new unit suite flagged it against the documented range. Consequence: the encoder enforces the tighter datasheet-guaranteed bounds (−512..+1023 steps); decoding is unaffected (the fault sentinels 0x3F8/0x3FF decode inside the guaranteed range).
- Observation (first full-POR corroboration on live silicon, 2026-11-22): every register default the driver encodes in `_tables.py`/`_regs.py` matched the as-found chip during the M3 live probe — LUT entries uniformly 127 °C / S=max (the documented "inactive" POR curve, which is NOT strictly ascending, so factory curves must be exempted from ascending validation), PWM_F=0x17/PWM_D=0x01 (⇒ 7826.1 Hz computed by the driver's getter), spin-up 100 % for 3.2 s with FAST_TACH, ideality index 0x12 (1.0080), conversion rate 16/s, filter off, local-high 70 °C, TCRIT 85 °C locked, beta autodetect on, TACH limit FFFFh (disabled).
Evidence: `scripts/pico/probe_m3.py` run 2026-11-22 (output quoted in the M3 Progress entry). Consequence: the entire POR-default layer is now empirically grounded, not just datasheet-derived; the uniform-127 LUT default is recorded here because any future "validate the shipping LUT" logic must treat it as legal.
- Observation (driver-path RPM validation, 2026-11-22): the first end-to-end tach reading through the finished driver — LSB-first interlock read, 16-bit combine, 5,400,000/count formula — returned 1870.5 RPM at 50 % manual drive, agreeing with the independent M1 measurement (~1865 RPM via raw-register probes) within 0.4 %.
Evidence: same `probe_m3.py` run (duty set to 50 % before the tach block by design). Consequence: the tachometer domain needs no further bench re-test beyond the M7 matrix; A3's remaining sliver (sub-minimum-RPM stall behavior) stays deferred unchanged.
- Observation (MicroPython environment, 2026-11-22): the rp2 port has no `os.path` module; existence checks must go through `open()`/`OSError`.
Evidence: the first `probe_persist.py` run died with `AttributeError: 'module' object has no attribute 'path'` on `os.path.exists`. Consequence: device-side scripts use an `open()`-based `_exists()` helper; the driver itself (`_persist.py`/`_core.py`) never references `os.path` — the atomic-write path probes `os.replace` via `getattr` and falls back to `os.rename`, which littlefs supports.
- Observation (process, 2026-11-22): two consecutive probe runs failed on invented member names (`scratchpad_1`, `conv_rate_s`) that do not exist in the implemented surface (real names: `scratchpad_get/set(index)`, `conversion_rate`).
Evidence: `AttributeError`s during `probe_persist.py` development on 2026-11-22; the pinned surface lives in `tests/test_public_surface.py`. Consequence: bench probes must be written against the pinned public surface (or introspected live), never from memory or planning notes — same slip class as the M3 probe contract slips.
- Observation (repo hygiene, 2026-11-22): `probe_m3.py`'s `SNAP_REGS` comments carry stale address labels (0x06 labelled ALERT_MASK, 0x07 FILTER; the real map puts ALERT_MASK at 0x16 and FILTER at 0xBF).
Evidence: comparison of `probe_m3.py` SNAP_REGS against the `_regs.py` constants while writing the M4 probe. Consequence: harmless (the raw snapshot/restore is label-independent and verified byte-for-byte), but the comments should be corrected when the file next changes; the M4 probe instead derives its snapshot list from the named `_regs` constants, which cannot drift.
- Observation (process, 2026-11-22): writing the M5 docs against the implemented API surfaced two claim/code drifts — `verify()` returns the product-ID byte (not `True`) and raises `ValueError` on an unexpected identity, and the POR alert mask (A4h) decodes with only the INT bit unmasked of the five defined bits.
Evidence: direct inspection of `_core.verify` source and the `AMSK_*` constants against the datasheet default while drafting `docs/`. Consequence: both docs corrected pre-commit; standing rule reinforced — documentation is written against the pinned public surface (`test_public_surface.py`) and decoded constants, never from planning notes.
- Observation (silicon-vs-code, 2026-11-22): the `manual` property had its PROG-bit polarity inverted since M3 — the getter returned True when PROG=0 and the setter cleared PROG on `manual = True`, i.e. "entering manual mode" actually switched the chip into LUT mode and made the Fan Setting register read-only.
Evidence: (a) datasheet §6.16 Bit 5 PROG — '0': Fan Setting/LUT registers read-only, LUT used; '1' (default): writable, written value instantly applied, LUT not used; Table 6.18 FAN_CFG default 20h (PROG=1 at POR); §6.18 writes ignored while the LUT is in use; (b) live M6 smoke on Pico W: after `dev.manual = True` every duty write was silently dropped (raw stayed 0, fan sat at LUT floor speed ~680 RPM), whereas the M3 probe — which never touched `dev.manual` and thus kept the POR PROG=1 — saw duty writes stick. The unit suite had encoded the same inversion (fake transport asserted the flipped bit pattern), and the persistence layer double-inverted (collect `not (fc & FCFG_PROG)` / apply `if not fa["manual"]: fc_final |= FCFG_PROG`), so save/load round trips were self-consistent and the M4 strict read-back passed despite the lying semantics.
Consequence: fixed in one coordinated change — `_core.py` manual getter/setter now PROG-active-high, `_persist.py` collect/apply now truthful (`"manual": bool(fc & FCFG_PROG)`; apply sets PROG iff stored manual), `tests/test_manual_pwm.py` ManualModeTestCase rewritten, `tests/test_persist.py` expectations flipped, and the erratum recorded in `research/02-api-parity-mapping.md` §5. Verified: all four host gates green, Pico W `hw_smoke_test.py` PASS (duty sweep sticks: raw 12/23/34/46, settled 2110 RPM at full drive), and the M4 live persistence probe re-passed on the fixed package. Schema v1 files saved before this fix carry an inverted `manual` field; no migration needed (pre-release, no published artifacts).
- Observation (silicon behavior, undocumented, 2026-11-22): while PROG=0 (LUT active) the Fan Setting register (4Ch) reads back the EFFECTIVE LUT-DRIVEN duty instead of its stored content, and writes to 4Ch plus the LUT table (50h–5Fh) are silently dropped. The LUT S bytes themselves hold true content in both modes; only 4Ch mirrors.
Evidence: (a) dedicated live probe on the Pico W bench — with a programmed curve, 4Ch tracked the forced-temperature LUT index exactly (ambient → raw 00h, forced 75 °C → 1Ch = 60 %, forced 82 °C → 29h = 90 % on the 17h grid); a write of 2Ch issued in LUT mode left 4Ch unchanged; (b) the M7 phase-B strict load failed with `0x4c expected 0x2c got 0x0c` — the read-back compared the intended stored value against the mirror; (c) raw safety-net restores performed in LUT mode drifted on exactly the fan-domain addresses (plus volatile TACH/status bits). Consequence: `collect_state` and the `apply_state` strict read-back now bracket their fan-domain traffic in a temporary PROG=1 dance (original FAN_CFG restored afterwards), the E2E/smoke snapshot/restore/safety-net code does the same, and `tests/test_persist.py` gained a `MirrorTransport` silicon model with three regression tests (suite 261 → 264). Recorded in `research/emc2101-register-map.md` §16.
- Observation (silicon behavior, undocumented, 2026-11-22): the Fan Setting READ-OUT lags one temperature-conversion window (~64 ms at the fastest 16/s rate) after a FAN_CFG write that flips the PROG bit — it keeps reporting the previously active drive source (the LUT-driven duty) before switching to the new mode's value. It is the read-out that trails, not the write path: writes stick immediately.
Evidence: (a) the post-D35 uninstrumented phase-B runs still failed intermittently with `0x4c expected 0x29 got 0xc` (stored manual-mode duty raw 41 vs stale LUT mirror raw 12 at ambient) while the identical code with per-transaction logging (µs-scale overhead per I²C op) passed the full matrix — the overhead pushed the read-back past the settle window; (b) step-by-step probes with explicit sleeps (PROG on → immediate/delayed FS reads → write 0x29 → immediate/delayed reads) showed no lag at all, ruling out a write-path problem; (c) the apply-tail replay (no-op writes to PWM_F/PWM_D/FAN_CFG/SPINUP/EXT_FORCE individually and as a full tail) never disturbed FS, ruling out spontaneous chip-side rewrites. Consequence: a settling pause of at least one conversion window precedes fan-domain reads after any PROG-on transition (`_persist.SETTLE_MS = 100`, decision D36), and the strict read-back retries disagreeing registers once after such a pause; the E2E/smoke snapshot/LUT-capture/safety-net paths settle likewise. Regression coverage: `MirrorTransport` models the stale window; three new tests (suite 264 → 267). Recorded in `research/emc2101-register-map.md` §16.5.
- Observation (bench electricals, 2026-11-23): after the single rotation board was re-wired from the Pico W bench to the ESP32-S3 bench, the external diode channel reads far above ambient shortly after power-up and decays toward ambient over minutes. User's first reading ~35 °C (wall thermometer 24 °C, transistor cool to the touch); probe run 1 (minutes later) showed raw 0x130 = +38.000 °C rock-stable across ~24 consecutive conversions (zero LSB jitter; the unused upper nibble of the 10h register visibly counted 0xC0→0x20→0x60→0xA0→0xE0); probe run 2 (~4 min later, no chip writes in between) showed raw ≈0xE8 = +29.0 °C with normal ±1 LSB live jitter (0xE0/0xE8/0xF0). Local die read 23–25 °C throughout, tracking the wall thermometer. Chip state unremarkable: CONFIG=0x04 (ALT_TCH only — deliberate on this bench), CONV_RATE=0x08 (default 16/s), IDEALITY=0x12 / BETA=0x08 are the POR defaults (`_tables.py`) — calibration registers untouched. Candidate explanations, not yet discriminated: (a) beta autodetect / REC series-resistance correction converging slowly after power-up (research note §11: REC corrects up to 100 Ω series resistance, +0.7 °C/Ω beyond); (b) steady-state board self-heating leaving a legitimate +5 °C offset; (c) disturbed diode wiring from the move adding uncompensated series resistance. Discriminating tests pending: long drift sampling (decay toward ~24–26 °C would support (a)) and a finger-on-junction touch test (a live channel rises while the junction warms; no response ⇒ frozen/clamped).
Evidence: two ad-hoc read-only probes on COM7 (sandbox `probe_diag.py`, run via mpremote host-path upload): per-sample raw bytes as above; driver API `local_temp_c` 23–24, `remote_temp_c` 38.0 → 29.0. No code changes involved.
- Observation (host tooling, 2026-11-23): long-lived mpremote sessions on COM7 stall deterministically when an I²C transaction follows a ≥2 s idle gap within the SAME session: both diagnostic probes hung mid-script at exactly the first 2 s sleep of their touch windows (host timeout, exit unknown), and a device-side `_thread` logger stopped writing after its first sample following a 30 s gap. Fresh short-lived mpremote invocations (fresh `machine.I2C` init) always succeed, including immediately after a stall; no board reset occurs (volatile CONFIG=0x04 persisted through every incident, ruling out power events). Additionally: constructing `machine.I2C` inside a non-main MicroPython thread dies silently (the v2 logger wrote zero lines while the board stayed healthy). Consequence: keep every mpremote invocation short and fresh (one logical step per connection); never do I²C work from device-side threads; time-series measurements must be host-polled with short sessions, not device-logged autonomously.

## Decision Log

Format: Decision / Rationale / Date-Author. D1–D6 are interview locks (2026-11-21); D7 onward
are session decisions (2026-11-22). D13–D21 adopt the research-phase recommendations as
defaults; the user may override any of them at any time, in which case a superseding entry is
recorded here.

- Decision: D1 — target the plain EMC2101 (Product ID 0x16), not the -R variant (0x28).
Rationale: the user's hardware is the plain part; the -R's EEPROM auto-loader is simulated in software instead (D4).
Date/Author: 2026-11-21, user + agent.
- Decision: D2 — clean-room implementation; the Adafruit CircuitPython library is mined for knowledge (quirks, timing, workarounds) only, never copied.
Rationale: user preference; keeps provenance unambiguous despite the reference being MIT-licensed.
Date/Author: 2026-11-21, user + agent.
- Decision: D3 — API parity policy "Option B": common core, honest edges. Identical names where semantics truly match; deliberate divergences documented; no faked features.
Rationale: user choice among presented options.
Date/Author: 2026-11-21, user + agent.
- Decision: D4 — persistence design "iii + default path": `save_config(path=None)` / `load_config(path=None)`; zero-arg calls use `dev.config_path`; an optional positional path overrides per call; `config_path` is seeded by the constructor kwarg `config_file=` falling back to a class constant. Whole-config-only for v1; JSON, human-readable, driver-written, versioned, stamped with observed Product/Manufacturer/Revision IDs.
Rationale: user choice; mirrors the MAX31760 verb vocabulary; superset feature isolated behind explicit verbs.
Date/Author: 2026-11-21, user + agent.
- Decision: D5 — accept the cold-boot window: between power-up and `load_config()` the chip runs power-on defaults (fan at 0%-setting ≈ minimum speed on modern fans; user-measured ~660 RPM floor on the last tested fan). Document prominently everywhere.
Rationale: user acceptance after measurement; true closure would require bootloader involvement, out of scope.
Date/Author: 2026-11-21, user + agent.
- Decision: D6 — research deliverables live in `research/` at the project root; no code written during the research phase.
Rationale: user instruction.
Date/Author: 2026-11-21, user + agent.
- Decision: D7 — repository name `emc2101-fan-speed-controller`, **public**.
Rationale: user instruction (2026-11-22).
Date/Author: 2026-11-22, user.
- Decision: D8 — the GitHub project is created and first pushed only after hardware E2E validation passes on all three platforms (option b, a superset of the host-side-local option a).
Rationale: user instruction (2026-11-22): nothing is published until silicon-proven.
Date/Author: 2026-11-22, user.
- Decision: D9 — license LGPL-2.1-or-later, matching the sibling driver.
Rationale: user choice (2026-11-22); consistency within the project family; clean-room authorship means no copyleft contamination concerns.
Date/Author: 2026-11-22, user.
- Decision: D10 — hardware targets and pins inherit the MAX31760 bench: Pico W first edition (RP2040), MicroPython v1.29.0, USB serial COM16, I2C0 SDA=GP0 (board pin 1) / SCL=GP1 (board pin 2); ESP32-S3, MicroPython v1.29.0, USB serial COM7, I2C0 SDA=GPIO41 / SCL=GPIO42; Raspberry Pi 3A+, Raspberry Pi OS Debian 13 / Python 3.13.5, smbus2, SMBus bus 1 (`/dev/i2c-1`, header pins 3/5). Bench loadout: one 4-wire fan on the FAN output with tach feedback on the ALERT/TACH pin, and a 2N3906 PNP thermal diode on DP/DN.
Rationale: user instruction (2026-11-22) to reuse the sibling project's validated bench; verified against `FanSpeedController` planning docs and test harnesses.
Date/Author: 2026-11-22, user + agent.
- Decision: D11 — `research/` is committed to the repository; `reference/` (vendor datasheet PDF) is gitignored.
Rationale: user instruction (2026-11-22); the research trail is justification material worth publishing, the PDF is vendor copyright.
Date/Author: 2026-11-22, user.
- Decision: D12 — add a root `AGENTS.md` stating the ExecPlan convention so future agent sessions pick it up automatically.
Rationale: user approval (2026-11-22); companion pattern from the cookbook template.
Date/Author: 2026-11-22, user + agent.
- Decision: D13 — diode-fault conditions raise a typed `OSError` subclass `DiodeFaultError` (not ValueError).
Rationale: research open item O1 recommendation; it is a hardware condition, not a bad argument.
Date/Author: 2026-11-22, agent (default adopted).
- Decision: D14 — constructor-kwarg failure behavior: if `config_file` points at an invalid/corrupt file, construction raises before touching any register; a missing file is a silent no-op (first-boot semantics).
Rationale: research open item O2 recommendation; a silently half-configured boot is the worst outcome.
Date/Author: 2026-11-22, agent (default adopted).
- Decision: D15 — strict post-apply read-back verification is ON by default in `load_config` (about 25 extra reads ≈ 1–2 ms).
Rationale: research open item O3 recommendation, borrowing kvasir_devices' practice; silent partial application is the failure mode this feature exists to prevent.
Date/Author: 2026-11-22, agent (default adopted).
- Decision: D16 — default config paths: MicroPython `/emc2101.json` (flash root); CPython `~/emc2101.json` (expanded home directory).
Rationale: research open item O4 recommendation; absolute defaults avoid CWD surprises.
Date/Author: 2026-11-22, agent (default adopted).
- Decision: D17 — DAC mode is included in v1 (register access + `dac_enabled` property) but marked experimental in docs because it requires removing the FAN pull-up resistor on the breakout.
Rationale: research open item O5 recommendation.
Date/Author: 2026-11-22, agent (default adopted).
- Decision: D18 — `rpm()` returns 0.0 when the TACH count reads 0xFFFFh or zero (stopped/unmeasurable), matching the sibling's zero-count convention.
Rationale: research open item O6 recommendation.
Date/Author: 2026-11-22, agent (default adopted).
- Decision: D19 — no LUT context-manager sugar (`with dev.lut:`) in v1; the whole-list setter covers the need.
Rationale: research open item O7 recommendation; defer optional polish.
Date/Author: 2026-11-22, agent (default adopted).
- Decision: D20 — raw-tier `read_reg(reg, n>1)` / `write_reg(reg, buf)` are implemented as sequential single-byte transactions over consecutive addresses, positioned as debug/dump ergonomics; internal API paths never rely on them crossing interlock boundaries.
Rationale: research open item O8 recommendation; preserves the sibling's raw-access vocabulary honestly.
Date/Author: 2026-11-22, agent (default adopted).
- Decision: D21 — package/layout follows `research/05-architecture-sketch.md` §1 verbatim (package `emc2101/` with `mp.py`/`cp.py` facades, `_core.py`, `_regs.py`, `_tables.py`, `_persist.py`, `_transport_mp.py`, `_transport_cp.py`; support dirs `examples/`, `tests/`, `tools/`, `docs/`, `NOTES/`, `reference/`).
Rationale: research open item O9 recommendation; mirrors the sibling's proven layout.
Date/Author: 2026-11-22, agent (default adopted).
- Decision: D22 — path terminology: every reference to `emc2101/` in this plan and in
  `AGENTS.md` denotes the path in the git dev tree (repository root). Deployment to a
  MicroPython device places the package under `/lib/emc2101/`; MicroPython's default
  `sys.path` is `['', '.frozen', '/lib']`, so no path manipulation is needed — scripts
  simply do `import emc2101.mp`. CPython deployment has no fixed install location
  (pip/site-packages or `sys.path` insertion).
Rationale: user clarification (2026-11-22); keeps dev-tree layout and device-side install
location from being conflated in M6 (examples/install steps) and M7 (bench validation);
the `sys.path` fact means M6 examples carry no bootstrap boilerplate.
Date/Author: 2026-11-22, user + agent.
- Decision: D23 — test/diagnostic utilities made during development are kept in the git tree under `scripts/`, grouped by physical bench (`pico/`, `esp32/`, `rpi/`) with an index README, mirroring the MAX31760 sibling's convention. Distinct from `examples/` (shipped demos + canonical tri-platform E2E suites) and `tools/` (hardware-free dev utilities). Scripts are self-contained, need real hardware, are not collected by `tests/`, and any state-mutating script must be self-restoring.
Rationale: user instruction (2026-11-22) after the pre-M1 bus probe; the probe script proved the value of keeping ad-hoc bench work in-tree, and the sibling project demonstrates the layout works across a full validation campaign.
Date/Author: 2026-11-22, user + agent.
- Decision: D24 — adopt the sibling's generic (non-driver-specific) scaffolding: `.github/workflows/ci.yml` (four quality gates on push/PR, Python matrix) created in M0; `requirements.txt` (host deps) in M0; `tools/deploy_mp.py` (copy package `.py` files to `/lib/emc2101/` over mpremote, file-by-file) in M2; `CONTRIBUTING.md` in M5; `examples/README.md` index in M6; `.gitignore` broadened to the sibling's fuller set (packaging, venvs, tool caches, OS cruft).
Rationale: user request (2026-11-22) to audit the MAX31760 tree for reusable scaffolding; these items are platform-generic and were absent from the M0–M6 scopes. Deliberately NOT adopted: `TODO.md` (superseded by this living ExecPlan), `SUMMARY.md`/`CODE_REVIEW_*`/`PLANS_0.1.1.md` (driver-specific retrospectives; the Outcomes & Retrospective section and revision notes serve that role, and the `PLANS_<version>.md` archive pattern applies at release), `tests/mock_i2c.py`/`fake_smbus.py` (M2/M3 implementation detail, already implied by the mock-backed suite requirement).
Date/Author: 2026-11-22, user + agent.
- Decision: D25 — single-controller bench rotation: only one physical EMC2101 breakout exists and it is moved between platforms; the validation order is fixed Pico W → ESP32-S3 → RPi 3A+, with code developed and solidified on the Pico W before rotating to the next bench (MAX31760 precedent).
Rationale: user instruction (2026-11-22); constrains M1/M7 scheduling — no parallel bench work, each platform's characterization/E2E runs sequentially as the controller rotates.
Date/Author: 2026-11-22, user.
- Decision: D26 — close M1 with explicit deferrals: the fan/tach channel is dead on the bench (TACH 0xFFFF at every duty even with the diode healthy; the fault isolates to tach wiring or fan motor power), so the fan-dependent M1 items — A3 TACH_M sweep conclusion, A7 live RPM-vs-formula check, ALERT-pin idle-state measurement, breakout photograph — are deferred to the M7 re-test (or earlier, as soon as the bench loadout is repaired) rather than blocking the milestone.
Rationale: M1's purpose is de-risking silicon assumptions before driver code; every assumption the driver depends on (single-byte contract, pointer model, interlock safety, status side effects, conversion cadence, identity) is now empirically grounded. The remaining items concern the fan peripheral, not the chip's protocol, and M7's E2E matrix re-exercises them with the repaired loadout. Recorded 2026-11-22 after the diode re-seat; the fan-side suspect list lives in `NOTES/bench-characterization.md` (Bench state).
Date/Author: 2026-11-22, agent (user informed; bench repair pending).
- Decision: D27 — amend D26: the TACH channel is repaired (external 10 kOhm pull-up added to the TACH net, 2026-11-22 round 2); A7 (live RPM-vs-formula check) is closed early with live data (~678 RPM at 0 % drive vs the ~660 RPM user-measured floor; ~1865 RPM at 50 % drive, monotonic); the remaining D26 deferrals stand as amended — A3 behavioral distinction (sub-min-RPM stall unreachable on this bench), ALERT-pin idle-state measurement, breakout photograph — all folding into M7.
Rationale: the root cause (missing receiver-side pull-up) is confirmed by the before/after diagnostic runs; the fan-dependent characterization data the driver cares about (live RPM tracking duty) is now available and recorded in `NOTES/bench-characterization.md`. No milestone status change beyond closing the M1 follow-up thread.
Date/Author: 2026-11-22, agent (user performed the bench repair).
- Decision: D28 — refine D11: `reference/` is NOT blanket-gitignored; only individual copyrighted vendor files we cannot redistribute (currently `EMC2101_datasheet.pdf` and `emc2101-fan-controller-and-temperature-sensor.pdf`) are ignored by explicit filename. Other items placed in `reference/` (e.g. our own notes) remain committable.
Rationale: user instruction (2026-11-22): the ignore policy targets copyright, not the directory.
Date/Author: 2026-11-22, user.
- Decision: D29 — M2 acceptance split by bench: the Pico W leg ran the full live probe/scan (the chip is wired there per D25); the ESP32-S3 and RPi 3A+ legs ran chip-independent import/construct smokes (deploy + import + constructor + hardware-free helper assertions). Live probe/scan on those two benches folds into the M7 E2E rotation (hw_smoke_test covers probe on every bench).
Rationale: rotating the single physical controller is a user action; the software-side acceptance (deploys cleanly, imports, constructs, helpers behave) was fully verified on all three platforms on 2026-11-22.
Date/Author: 2026-11-22, agent.
- Decision: D30 — M3 live acceptance follows the D29 split: the Pico W leg runs the full self-restoring protocol probe (`scripts/pico/probe_m3.py`, deployed package); the ESP32-S3 and RPi 3A+ legs get no dedicated M3 hardware step — their M3 coverage arrives with the M7 E2E rotation (hw_smoke_test + e2e_hardware_test exercise the same API domains on each bench once the controller rotates).
Rationale: single physical controller (D25); the software-side acceptance (full mock suite + 100 % coverage + live silicon on the development bench) is complete, and duplicating a reduced probe on benches that currently lack the chip would test deployment plumbing rather than protocol behavior.
Date/Author: 2026-11-22, agent.
- Decision: D31 — LUT ordering rule splits by path: the WRITE path keeps strictly-ascending threshold validation (equal thresholds shadow each other in hardware), but the PERSISTENCE path (decode + apply preflight) accepts NON-descending curves, because the factory POR curve is uniformly 127 °C and `save_config`/`load_config` must round-trip it losslessly.
Rationale: the M3 live probe established the uniform-127 POR LUT empirically; a strict-ascending persistence check made saving the as-found chip impossible and broke the TCRIT-noop test paths. Documented in the `_persist.py` docstring.
Date/Author: 2026-11-22, agent.
- Decision: D32 — `json`, `time`, and `os` are permitted imports in shared (MicroPython-shipped) modules, removing them from `tests/lint_subset.py`'s BAD_MODULES.
Rationale: all three ship with MicroPython v1.29.0 on both target ports (rp2 and esp32); M4 legitimately needs `json` (serialization), `time.gmtime` (UTC timestamps), and `os` (file ops/rename). The lint gate's purpose is CPython-only constructs, not stdlib breadth; the rationale is recorded in the lint file's docstring.
Date/Author: 2026-11-22, agent.
- Decision: D33 — insert a new milestone M8 (independent code review) between M7 and publication; the former M8 (GitHub publication) is renumbered to M9. An independent agent reviews the full tree after M7; every finding must be addressed — fixed with all four quality gates green, or explicitly declined with rationale in this log — before M9 may proceed.
Rationale: user instruction (2026-11-22): an outside set of eyes on the complete tree before anything is published; publication is the one irreversible external action, so it now sits behind both the M7 hardware acceptance and the closed M8 review.
Date/Author: 2026-11-22, user.
- Decision: D34 — PROG bit polarity: PROG=1 means manual mode (Fan Setting drives the fan directly and is writable; LUT bypassed), PROG=0 means LUT mode (Fan Setting/LUT read-only). The public `manual` property and the JSON schema v1 `fan.manual` field are both active-high aliases of PROG, matching the datasheet (§6.16 Bit 5, Table 6.18 default 20h, §6.18).
Rationale: the M3 implementation (and the parity-mapping note it followed) had the polarity inverted; live evidence from the M6 smoke test plus the primary-source datasheet text confirmed the correct direction. Fixed across `_core.py`, `_persist.py`, tests, and the research erratum on 2026-11-22 (see Surprises & Discoveries).
Date/Author: 2026-11-22, agent.
- Decision: D35 — treat the Fan Setting register and the LUT table as readable/writable ONLY under PROG=1: `collect_state(read_byte, write_byte)` captures them behind a temporary PROG=1 dance (original FAN_CFG restored), the `apply_state` strict read-back verifies them the same way when the final state ends in LUT mode (with the FAN_CFG comparison adjusted for the temporary bit), and every raw diagnostic/safety-net snapshot-restore path in `examples/` enforces the same discipline. The signature change is internal-only (one caller in `_core.save_config`).
Rationale: live silicon (2026-11-22, Pico W bench) proved that while PROG=0 the 4Ch read returns the LUT-driven effective duty and fan-domain writes are dropped — so any collection or verification done without the dance silently corrupts saved profiles (the M7 phase-B failure: `0x4c expected 0x2c got 0x0c`) or leaves chips mis-restored. The dance is the minimal correct abstraction; the alternative (schema-level "value not meaningful" sentinels) would leak the quirk into user-visible data. Regression coverage: `MirrorTransport` + `TestProgQuirkModel` in `tests/test_persist.py` (three tests).
Date/Author: 2026-11-22, agent.
- Decision: D36 — settle before reading the fan domain after a PROG-bit transition, and make the strict read-back retry-once: `_persist._settle_ms(SETTLE_MS)` (100 ms ≥ one 64 ms conversion window, portable across MicroPython `time.sleep_ms` / CPython `time.sleep`) is called after every PROG-on transition before fan-domain reads in `collect_state` and in the `apply_state` strict read-back dance; when the first strict pass reports diffs, a second settle + re-read of only the disagreeing registers follows, and only surviving diffs are reported. The E2E/smoke scripts' own snapshot-capture, S4 raw-LUT capture/restore, and safety-net verification use the same 0.1 s settle.
Rationale: live forensics (2026-11-22, Pico W bench) showed the post-D35 intermittent phase-B failures (`0x4c expected 0x29 got 0xc`) were a read-out race, not a logic bug: the 4Ch read-out keeps the previously active drive source visible for up to one conversion window after a PROG transition, and the instrumented-run-passes/uninstrumented-fails asymmetry plus the clean step-by-step probes localized it to the read side. The retry preserves strictness (genuine corruption still fails — pinned by a sabotage test) while absorbing the silicon's switch-over latency; a blanket tolerance or non-strict default was rejected because it would weaken the D15 guarantee. Regression coverage: `MirrorTransport` stale-window model + three tests in `TestProgQuirkModel` (suite 264 → 267).
Date/Author: 2026-11-22, agent.

## Outcomes & Retrospective

To be written at the completion of each major milestone and at the end of the plan: what was
achieved relative to the original purpose, what remains, and lessons learned. Nothing here yet.

## Context and Orientation

Assume the reader knows nothing beyond this file and the current working tree. The working
directory is `C:\Users\mecwo\Documents\ChatboxAI Sandbox\EMC2101_Fan_Speed_controller` (Git
repository root once M0 runs). Its current contents are: `research/` with seven
Markdown documents (the completed research phase: `README.md` index,
`emc2101-register-map.md`, `01-feasibility-effort.md`, `02-api-parity-mapping.md`,
`03-persistence-opinion.md`, `04-reference-notes.md`, `05-architecture-sketch.md`);
`reference/EMC2101_datasheet.pdf` (SMSC EMC2101 datasheet Rev 2.54, 06-16-09, 57 pages —
vendor copyright, gitignored); `AGENTS.md` (ExecPlan convention + ground rules); this file;
and `scripts/` (bench-script tree per D23: `README.md` index plus `pico/probe_bus.py`,
verified green against the live chip on 2026-11-22). The directory became a Git
repository on 2026-11-22 (M0: branch `main`, scaffolding and planning trail committed);
no driver source code beyond the `emc2101/__init__.py` stub yet.
The authoritative register-level reference is `research/emc2101-register-map.md`; the load-
bearing facts are also embedded in this plan so it stays self-contained.

Terms of art used in this plan. An **ExecPlan** is this kind of executable specification: a
living, self-contained design document that a novice (human or agent) can follow end-to-end.
A **facade** is a thin platform-specific module (`emc2101/mp.py` for MicroPython,
`emc2101/cp.py` for CPython) that binds a transport and exposes the shared core class; the
two facades export an identical public API, enforced by a parity test. A **transport** is a
duck-typed object providing the low-level bus primitives the core depends on; the core never
imports a transport directly. An **interlock** is a mandatory read ordering imposed by the
chip: the external-temperature snapshot is refreshed when the MSB register (0x01) is read, so
MSB must be read before LSB (0x10); the TACH snapshot is refreshed when the LSB register
(0x46) is read, so LSB must be read before MSB (0x47). The two pairs snapshot in opposite
directions. The **PROG bit** (bit 5 of the Fan Configuration register 0x4A) gates writability
of the LUT and Fan Setting registers: with PROG=1 (the power-on default) those registers are
writable and the Fan Setting drives the fan directly (manual mode); with PROG=0 the LUT
drives the fan and those registers become read-only. Applying a saved profile therefore
requires writing the LUT while PROG=1 and restoring the stored PROG value last. **TCRIT** is
the external-channel critical-temperature trip (register 0x19, default 85 °C) that forces the
fan to full drive; it is locked at its default until the TCRITOVRD bit (Config register bit 1)
is set, and the unlock permits one change before a power cycle is required. A **LUT pair** is
one of the chip's eight (temperature-threshold, fan-setting) entries at registers 0x50–0x5F
(even offset = threshold in °C, odd offset = 6-bit fan setting). **Virtual EEPROM** is the
on-disk JSON config file that simulates the -R variant's EEPROM auto-load (decision D4).
**mpremote** is the host-side tool for running/uploading scripts on MicroPython boards over
USB serial. **SMBus** is the subset of I²C this chip speaks (single-byte protocols, fixed
address, TIMEOUT behavior); for driver purposes it is accessed with ordinary I²C primitives.
**POR** means power-on-reset state.

The chip in one paragraph. The EMC2101 is a single-channel brushless-fan controller with dual
temperature sensing (internal die diode ±2 °C, external transistor diode ±1 °C), an 8-entry
temperature-to-fan LUT, a 6-bit PWM or linear-DAC fan output, one tachometer input sharing the
ALERT pin, and SMBus control at fixed 7-bit address 0x4C. Identity registers: Product ID at
0xFD (0x16 plain / 0x28 -R), Manufacturer ID at 0xFE (0x5D), Revision at 0xFF (0x01). Key
registers: Status 0x02; Configuration 0x03/0x09; Conversion Rate 0x04/0x0A; Internal Temp
Limit 0x05/0x0B; Ext High Limit 0x07+0x13; Ext Low Limit 0x08+0x14; Force Temp 0x0C; One-Shot
0x0F; Scratchpads 0x11/0x12; Alert Mask 0x16; Ideality Factor 0x17; Beta Comp 0x18; TCRIT
0x19; TCRIT Hysteresis 0x21; TACH reading 0x46/0x47 (LSB first); TACH limit 0x48/0x49; Fan
Configuration 0x4A; Spin-Up 0x4B; Fan Setting 0x4C; PWM Frequency 0x4D; PWM Divide 0x4E; LUT
Hysteresis 0x4F; LUT pairs 0x50–0x5F; Averaging Filter 0xBF. Effective PWM duty is
`S / (2·PWM_F) × 100%` where S is the 6-bit Fan Setting; fan speed is
`RPM = 5,400,000 / TACH_COUNT` assuming 2 pulses per revolution. Power-on defaults: manual
mode (PROG=1), fan at 0% setting, limits at 70/70/0 °C, TCRIT 85 °C locked, conversion rate
16/s, ALERT in interrupt mode, TACH input disabled, spin-up 100% for 3.2 s. Full detail with
datasheet citations: `research/emc2101-register-map.md`.

The sibling project. `..\FanSpeedController` contains the completed MAX31760 driver
(package `max31760/`, v0.1.1, validated on the same three platforms). It is the architectural
template for this project: same layout, same quality gates, same conventions (property-per-
register, verbs for actions and destructive reads, ValueError/OSError/TypeError-free error
model, mock-backed tests asserting exact transaction sequences, MicroPython-subset lint gate,
api-coverage tool, self-restoring hardware test scripts). Per decision D2 its code is not
copied; it is consulted for structure and hard-won lessons only.

The bench. Three development/test platforms, all already proven on this exact bench in the
sibling project (decision D10). Platform one: Raspberry Pi Pico W, first edition (RP2040),
flashed with MicroPython v1.29.0, USB serial COM16 at 115200 baud, I2C0 with SDA on GP0
(board pin 1) and SCL on GP1 (board pin 2). Platform two: ESP32-S3-class board, MicroPython
v1.29.0, USB serial COM7, I2C0 with SDA on GPIO41 and SCL on GPIO42. Platform three:
Raspberry Pi 3A+ running Raspberry Pi OS (Debian 13, Python 3.13.5) with the smbus2 package,
accessing SMBus bus 1 (`/dev/i2c-1`, GPIO header pins 3/5). The EMC2101 sits on the Adafruit
breakout (product 4808, STEMMA QT/Qwiic footprint) wired to the same SDA/SCL/VDD/GND nets the
MAX31760 used; one 4-wire PC fan connects to the FAN output with its tach signal routed to the
ALERT/TACH pin (which the driver switches into tach-input mode), and a 2N3906 PNP thermal
diode provides the external temperature channel on DP/DN. Equivalent Amazon-sourced boards
with the same chip are supported by virtue of the fixed address and identical register map.


## Plan of Work

The work proceeds through ten milestones, M0 through M9, in strict order. Each milestone is
independently verifiable: it ends with a concrete artifact and an observable acceptance check
detailed under Concrete Steps. Milestones M0–M6 are host-side (Windows dev machine) except
M1, which needs the bench; M7 needs all three boards; M8 is a review gate with no external
dependencies; M9 needs network access to GitHub. The
sequence mirrors the research-phase phase plan P0–P6 (`research/01-feasibility-effort.md` §7),
with M0 added for repository foundation, M8 for the independent code review, and M9 for
publication.

### M0 — Repository foundation

Scope: turn the working directory into a Git repository with the project's permanent
scaffolding. Create `.gitignore` (mirroring the sibling's fuller set: `reference/`,
bytecode caches, packaging/build artifacts, virtualenvs, tool caches, OS cruft), the root
`AGENTS.md` (ExecPlan convention stub, already drafted alongside this plan), `LICENSE`
(containing the full GNU LGPL version 2.1 text with the "or later" clause header, per D9),
`pyproject.toml` (distribution name `emc2101`, version 0.1.0, no required dependencies on
MicroPython hosts, `smbus2>=0.4.2` declared only under the `platform_system == 'Linux'`
environment marker, `requires-python >= 3.10` for host tooling), `requirements.txt`
(host-side runtime dependency: `smbus2>=0.4.2`), `.github/workflows/ci.yml` (CI running
the four quality gates on push/PR across a Python-version matrix, mirroring the sibling's
workflow per D24), a first-cut `README.md`
(title, one-paragraph description, platform table, quick-start placeholder, repo layout), and
the empty directories `emc2101/`, `examples/`, `tests/`, `tools/`, `docs/`, `NOTES/`, plus
`scripts/` (already seeded with `pico/probe_bus.py` and its index README per D23). Then
`git init` (default branch `main`), stage everything, and make the first commit(s): one for
the research trail plus scaffolding, or split into two (scaffold, then research) if preferred.
At the end of M0 the repository exists, `git status` is clean, and the datasheet PDF is
confirmed ignored. Acceptance: `git log --oneline` shows the initial commit(s);
`git check-ignore reference/EMC2101_datasheet.pdf` exits successfully; `git ls-files` lists
`research/` files but nothing under `reference/`.

### M1 — Bench bring-up & characterization (hardware)

Scope: de-risk every silicon assumption before writing driver code. Wire the Adafruit
breakout to each bench on the inherited nets (D10). On the Pico W (primary development
board, used throughout M2–M7 as the live MicroPython target), run a small probe script via
mpremote that reads register 0x00 and the ID trio 0xFD/0xFE/0xFF, recording actual values
against expectations (Product 0x16, Manufacturer 0x5D, Revision 0x01 — any deviation,
especially revision, triggers a datasheet-revision re-check of the power-on defaults table).
Then characterize, in order: (a) single-byte-only behavior — attempt a two-byte read from
register 0x00 and observe truncation or NACK, confirming the pessimistic transport model;
(b) pointer behavior — use Receive Byte twice after one Write Byte and determine whether the
second read returns the same register or the next (expected: same, i.e., no auto-increment);
(c) ALERT pin idle state in interrupt mode (expected high via the breakout pull-up);
(d) TACH input exercise — set ALT_TCH, drive the fan at a known duty, confirm RPM readings
track reality within ±10% using the 5,400,000 formula; (e) TACH_M modes 00/01/10/11 below
minimum detectable RPM (false readings vs forced 0xFFFFh), including whether CLK_OVR-divided
clocks force mode 00 (ambiguity A3); (f) conversion timing — sample the BUSY bit cadence at
the default 16 conversions/s; (g) board inspection — photograph the breakout and note pull-up
resistors on ALERT and FAN (relevant to DAC-mode caveats). Deliberately do NOT consume the
TCRIT one-time unlock during characterization (it interacts ambiguously with restoration,
ambiguity A5); the unlock dance is exercised only in M7 where persistence needs it. Output:
`NOTES/bench-characterization.md` containing measured values, the resolved-or-deferred status
of each ambiguity A1–A8 from `research/04-reference-notes.md` §3, and any corrections to the
quirk catalog Q1–Q18. Acceptance: the notes file exists with every ambiguity item explicitly
resolved or deferred-with-reason; the ID trio is recorded; single-byte behavior and pointer
behavior are empirically confirmed or corrected (if the pointer DOES auto-increment, record
it here and relax the transport contract in M2 accordingly).

### M2 — Package skeleton & transport layer

Scope: create the package skeleton and the two transports. `emc2101/_regs.py` is a leaf
module importing nothing from the package: every register address, every bit-field constant,
mode/frequency encodings, physical constants (RPM divisor 5,400,000; temperature resolutions),
and fixed-point helpers (external-temp encode/decode over the 11-bit two's-complement format
with 0.125 °C steps; internal-temp 8-bit signed; duty quantization through the current PWM_F
grid; rpm-from-count and count-from-rpm). `emc2101/_tables.py` holds pure data: factory
power-on defaults per register, the 64-entry ideality-factor table (Table 6.13), the
conversion-rate table (Table 6.6), and spin-up time/drive tables. `emc2101/_transport_mp.py`
implements the single-byte contract over `machine.I2C` using `readfrom_mem(addr, reg, 1)` and
`writeto_mem(addr, reg, bytearray([value]))` (never `mem_read`/`mem_write` — Surprise #8),
plus `probe()` (address ACK by reading harmless RO register 0x00), `scan()`, `delay_ms`
(`time.sleep_ms`), and a no-op `close()`. `emc2101/_transport_cp.py` implements the same
contract over smbus2 (`read_byte_data` / `write_byte_data`), supporting both opening its own
bus handle and adopting a caller-supplied one, with `close()` releasing only self-opened
handles. Both transports wrap every transaction in a retry ladder with escalating backoff
(starting from the sibling's `(10, 30, 60, 100, 200, 400)` ms baseline, retuned against M1
observations) and raise `OSError` when exhausted. `emc2101/mp.py` and `emc2101/cp.py` expose
the `EMC2101` class (at this point implementing only lifecycle: constructor binding transport
and config path, `verify()`, `probe()`, `scan()`, `close()`, context-manager methods) with
mirrored `__all__` lists. Host unit tests use a mock transport that records every
`(op, reg, value)` tuple and assert exact sequences and retry-ladder behavior. Add
`tools/deploy_mp.py` (per D24): a host-side helper that copies the package's `.py` files
to `/lib/emc2101/` on a MicroPython board over mpremote (individual-file copies —
MicroPython cannot copy whole directories), used from M2 onward whenever the package
changes on a device. At the end of
M2, a ten-line probe script runs on all three platforms and prints the ID trio. Acceptance:
host unit tests green; probe script prints `probe OK` plus the ID trio on Pico W, ESP32-S3,
and RPi 3A+.

### M3 — Core device API (no persistence)

Scope: implement the full public API surface from `research/02-api-parity-mapping.md` in
`emc2101/_core.py`, domain by domain, in dependency order: identity properties
(`product_id`, `mfg_id`, `revision`, `part_info`); temperatures (`local_temp_c`,
`remote_temp_c` with MSB-first interlock ordering and `DiodeFaultError` on fault sentinels,
per D13); limits (`local_high_c`, `remote_high_c`, `remote_low_c`, `tcrit_c` with the
unlock dance and loud documentation of the one-change rule, `tcrit_hysteresis_c`); status and
alerts (`status_raw()` as a documented destructive-read verb, `active_alarms()`,
`alert_mask` with reserved-bit-preserving RMW, `alert_mode` INTERRUPT/COMPARATOR,
`service_alert()`, `clear_alert_mask()`, `diode_fault()`, `busy()`); manual control
(`manual` property backed by ~PROG with the writability side effect documented,
`set_duty_pct` quantizing through the current PWM_F grid, `duty_cmd_raw` 0..63); output
configuration (`pwm_freq_hz` setter solving the nearest achievable frequency across
PWM_F/PWM_D/CLK_SEL/CLK_OVR with the getter returning the computed actual,
`fan_output_inverted`, `dac_enabled` marked experimental per D17, raw-tier `pwm_clk_sel` /
`pwm_div`); LUT (`lut` property as a list of eight `(temp_c, duty_pct)` tuples with
ascending-threshold validation and the PROG dance, `lut_get_index(i)` /
`lut_set_index(i, temp_c, duty_pct)`, `hysteresis_c` 0..127, `force_enabled` +
`forced_temp_c`); tachometer (`rpm(pulses_per_rev=2)` with LSB-first interlock ordering and
0.0 on 0xFFFFh/zero per D18, `tach_threshold`, `min_rpm`, `tach_input_enabled` with the
ALERT-trade-off warning in its docstring, `tach_mode`); spin-up (`spin_up_enabled` composite
over the three fields, `spin_up_drive`, `spin_up_time_s`, `spin_up_fast_tach`); calibration
(`ideality_factor_index`, `ideality_factor`, `set_ideality_factor(n)` nearest-match,
`beta_auto_detect`, `beta_index`); scratchpads (`scratchpad_get(index)` /
`scratchpad_set(index, value)` for the two bytes at 0x11/0x12); lifecycle extras
(`standby`, `one_shot()` with standby/mixed precondition checks, `conversion_rate`,
`averaging_filter` handling the duplicated Level-1 encoding, `dis_to_enabled`,
`fault_queue_enabled`); and the preset `configure_4wire_fan(pwm_freq_hz=...)` (sets PWM
frequency, enables the TACH input, applies sane spin-up, documents the ALERT trade-off).
Raw-tier `read_reg(reg, n=1)` / `write_reg(reg, buf)` follow decision D20. The mock-backed
unit suite grows to cover every member, with transaction-sequence assertions specifically
guarding the two interlocks, the PROG dance, the TCRIT unlock sequence, and the
status-read side effects. Acceptance: the full host suite green (target ≥ 120 tests),
`tools/api_coverage.py` reports 100% of public members exercised, the MicroPython-subset lint
gate green, `python -m compileall` clean.

### M4 — Persistence layer ("virtual EEPROM")

Scope: implement decisions D4/D13–D16. `emc2101/_persist.py` is filesystem-agnostic: pure
functions `encode(state) -> str` and `decode(text) -> state` implementing JSON schema v1
(version field, UTC timestamp, device ID stamp, and named sections `config`, `limits`, `lut`,
`fan`, `calibration`, `misc` — see `research/03-persistence-opinion.md` §5.3 for the sketch),
plus `collect_state(read_byte) -> dict` and `apply_state(write_byte, state, *, strict=True)
-> report` implementing the apply-ordering rules (validate everything first; ensure PROG=1;
write calibration/misc/limits with the TCRIT special case — stored value differing from both
85 °C and the current value gets the unlock dance attempted once, else skipped with a loud
error; write LUT entries with ascending validation re-checked at apply time; write fan
configuration last ending with the stored PROG value; optional strict post-apply read-back
verification producing a per-register diff report, ON by default per D15). File I/O glue
lives in `_core.save_config(path=None)` / `load_config(path=None)`: resolve the effective
path (argument, else `self.config_path`), serialize/deserialize, and write atomically
(temp file + rename where the port supports it, documented fallback otherwise). Constructor
kwarg semantics per D14: kwarg omitted means zero file I/O; kwarg passed with a missing file
means silent no-op (first-boot semantics); kwarg passed with an invalid file raises before
any register write. Default paths per D16 live as class constants in the facades. Unit tests
cover round-trip stability, unknown-version rejection, product-ID mismatch refusal,
revision-mismatch warning, corrupt-file zero-register-touch (asserted via the mock
transport's empty log), the TCRIT skip case, explicit-load-of-missing-file raising, and
atomic-write simulation. Acceptance: persist tests green; real-file smoke test passes on Pico
W flash and the Pi filesystem (save, mutate a register, load, verify restored).

### M5 — Quality gates & docs

Scope: finalize the four host quality gates and write the documentation. Tune
`tests/lint_subset.py` (MicroPython-subset compliance: bare-builtin annotations, no
CPython-only syntax or imports in shared modules) and `tools/api_coverage.py` (every public
member exercised by the suite) to this codebase, mirroring the sibling's implementations in
style. Write `docs/`: API reference (every public member with signatures, ranges, exceptions),
wiring guide (STEMMA QT/Qwiic plus raw I²C, per-platform pin tables from D10), per-platform
installation (mpremote workflow for the MCUs, smbus2 install for the Pi), quickstart, and the
operational-notes set (cold-boot window and mitigation options, TCRIT lifecycle, DAC-mode
hardware caveat, ALERT/TACH pin trade-offs, ARA explanation, force-register testing
technique). Write `CONTRIBUTING.md` (per D24: prerequisites, how to run the four gates,
shared-core/error-model ground rules adapted from the sibling, hardware-testing
conventions, licensing). Polish the root `README.md` (quick start for both facades, examples table, repo
layout, development gates) and add `CHANGELOG.md` starting at 0.1.0. Acceptance: all four
gates green on the host; docs complete and internally consistent with the implemented API.

### M6 — Examples

Scope: write the five example scripts following the sibling's patterns exactly.
`examples/pico_demo.py`, `examples/esp32_demo.py`, `examples/rpi_demo.py`: board-aware pin
selection via `sys.platform` (rp2 → GP0/GP1, esp32 → GPIO41/42, linux → bus 1), demo flow of
verify → print temperatures → configure 4-wire fan → manual duty sweep with RPM reporting →
save config → restore a calm state. `examples/hw_smoke_test.py`: self-restoring core-behavior
smoke (identity, temperatures, manual duty sweep, settled RPM above a plausibility floor,
persistence round trip, restore with byte-for-byte verification), printing
`HW SMOKE TEST: PASS`. `examples/e2e_hardware_test.py`: the full matrix described under M7,
self-restoring (snapshot the enumerated writable registers at start, restore and verify at
end), printing one PASS/FAIL line per section and finally `E2E HARDWARE MATRIX: PASS`. Add
`examples/README.md` (per D24) indexing the five scripts with their per-platform run
commands. All scripts must pass `compileall` and the lint gate (they run on MicroPython). Acceptance:
scripts exist, compile cleanly, and are reviewed against the parity table so every public
member appears in at least one E2E section.

### M7 — Hardware E2E validation (all three platforms)

Scope: prove the driver on silicon. For each platform in turn (Pico W, ESP32-S3, RPi 3A+):
confirm firmware/environment (MicroPython v1.29.0 on the MCUs; smbus2 importable on the Pi),
run `hw_smoke_test.py` expecting `HW SMOKE TEST: PASS`, then run `e2e_hardware_test.py`
expecting every section PASS and the final `E2E HARDWARE MATRIX: PASS`. The E2E matrix has
eleven sections: (1) identity/probe/scan/part-info; (2) temperature/setpoints (both channels
plausible, limit round trips, TCRIT read sanity, hysteresis round trip); (3) manual-mode/duty/
PWM (duty sweep with observable fan response, `duty_cmd_raw` round trip, `pwm_freq_hz`
solver round trip, `fan_output_inverted` toggle, DAC toggle off-and-back); (4) LUT (bulk
round trip of eight pairs, index get/set, hysteresis, force register feeding a synthetic
temperature while the LUT follows); (5) tach/RPM (enable TACH input, settle-and-measure RPM
above 500 at full duty, threshold round trip, `min_rpm`, TACH_M behavior); (6) faults/alerts
(status raw, active alarms, alert-mask RMW preserving reserved bits, both alert modes,
service/clear sequence, diode-fault negative check, busy, conversion rate, filter, DIS_TO,
queue bit); (7) calibration (ideality index/value round trip, nearest-match setter, beta
auto-detect and index); (8) lifecycle (standby enter/exit with probe staying alive, one-shot
precondition errors, scratchpads, spin-up composites); (9) persistence (save → clobber a
register → load restores; explicit load of a missing file raises; corrupt file rejected with
zero register writes; cold-boot-with-profile scenario: save a profile, power-cycle the MCU,
construct with the `config_file` kwarg, assert applied values); (10) presets
(`configure_4wire_fan` register effects: ALT_TCH set, PWM frequency applied, spin-up sane);
(11) error model (the expected ValueError paths: out-of-range registers, bad percentages,
non-ascending LUT thresholds, bad indices, bad hysteresis, bad PWM frequency, bad port-less
arguments). Any silicon delta discovered (a quirk behaving differently than the datasheet or
research predicted) is fixed in code and tests, recorded in Surprises & Discoveries with
evidence, and noted in `NOTES/bench-characterization.md`. Results are tabulated in Artifacts
(platform × section outcomes, with dates). Acceptance: smoke PASS and matrix PASS on all
three platforms; results table recorded; no open failures.

### M8 — Independent code review

Scope: an independent agent (not the implementing agent) reviews the complete tree as of the
end of M7 — package source, tests, tools, scripts, examples, docs, and the research trail —
against the datasheet facts in `research/`, the decisions in this plan, and general
correctness/security/maintainability standards. Findings are recorded in this plan (a
dedicated subsection under Surprises & Discoveries if numerous) with severity
(blocker/high/medium/low/nit), location, and description. Every finding must be addressed
before M9 proceeds: fixed in a commit that keeps all four quality gates green, or explicitly
declined with a rationale recorded in the Decision Log. Review scope includes at least:
protocol correctness (interlocks, retry ladder, destructive-read discipline), persistence
validation completeness, API-surface consistency with the docs, MicroPython subset
compliance, test-quality gaps, and documentation accuracy. Acceptance: findings list
complete; every item closed (fixed + gated, or declined + logged); no open blocker or
high-severity items.

### M9 — GitHub publication

Scope: publish the validated repository. Resolve the account login via the GitHub API
(`get_me`). Create the public repository `emc2101-fan-speed-controller` (no auto-init; the
local history carries everything). Add the remote
`https://github.com/<login>/emc2101-fan-speed-controller.git` and push the `main` branch
with full history. Verify: the repository page renders the README and detects the LGPL-2.1
license; the tree contains `research/` (all seven documents) and the full source tree;
`reference/` is absent (gitignored); the latest commit matches local HEAD. Commit messages
throughout the project use imperative subjects describing the change; commits made by the
Chatbox agent carry the trailer `Co-authored-by: Chatbox <chatbox@chatboxai.com>`.
Acceptance: the public URL is reachable and shows the complete tree; `git ls-remote origin`
matches local refs.


## Concrete Steps

Working directory for every command below is the repository root
(`C:\Users\mecwo\Documents\ChatboxAI Sandbox\EMC2101_Fan_Speed_controller`) unless stated.
Host shell is PowerShell. Expected transcripts are abbreviated; compare substance, not
whitespace. Update this section as work proceeds (commands that change get rewritten in
place).

M0 — Repository foundation:

    git init -b main
    # create .gitignore, AGENTS.md, LICENSE, pyproject.toml, requirements.txt,
    # .github/workflows/ci.yml, README.md and the directories emc2101/ examples/
    # tests/ tools/ docs/ NOTES/ scripts/ (see M0 scope)
    git add .gitignore AGENTS.md LICENSE pyproject.toml README.md research
    git commit -m "Scaffold repository: scaffolding files and research trail"
    git log --oneline
    # expect: one commit line, e.g. a1b2c3d Scaffold repository: ...
    git check-ignore reference/EMC2101_datasheet.pdf
    # expect: the path echoed back (exit code 0), proving it is ignored
    git ls-files | Select-String "^reference/"
    # expect: no output

M1 — Bench bring-up & characterization (run on the Pico W first; repeat probes per board):

    pip install mpremote            # once, host-side
    python -m mpremote connect port:COM16 run scripts/probe_id.py
    # probe_id.py (created in M1, kept under scripts/): reads 0x00, 0xFD, 0xFE, 0xFF via
    # machine.I2C(0, sda=Pin(0), scl=Pin(1)) at address 0x4C and prints each byte.
    # expect:
    #   reg 00h = xx
    #   product id  fdh = 16
    #   mfg id      feh = 5d
    #   revision    ffh = 01
    # then the characterization probes (two-byte read attempt, Receive Byte pointer test,
    # ALERT pin state, TACH exercise, TACH_M sweep, BUSY cadence) per M1 scope; results go
    # into NOTES/bench-characterization.md as they are taken.
    python -m mpremote connect port:COM7 run scripts/probe_id.py     # ESP32-S3
    sudo i2cdetect -y 1                                              # RPi 3A+
    # expect: 0x4c listed in the bus map

M2 — Package skeleton & transport layer:

    python -m unittest discover -s tests -v
    # expect: all transport/lifecycle tests pass, e.g.
    # test_probe_ok ... ok
    # test_retry_ladder_exhaustion_raises_oserror ... ok
    # OK (N tests)
    python -m mpremote connect port:COM16 run scripts/probe_id.py
    # expect: same ID trio as M1 (now through the package's verify()/probe())
    python -m mpremote connect port:COM7 run scripts/probe_id.py
    python3 scripts/probe_id_cp.py                                   # on the Pi
    # expect: "probe OK" plus the ID trio on all three platforms

M3 — Core device API:

    python -m unittest discover -s tests -v
    # expect: full suite green, target >= 120 tests, e.g.
    # test_remote_temp_reads_msb_first_interlock_order ... ok
    # test_lut_apply_uses_prog_dance_and_restores_stored_prog_last ... ok
    # test_tcrit_unlock_sequence_writes_config_bit_then_limit ... ok
    # OK (NNN tests)
    python tools/api_coverage.py
    # expect: "api coverage: 100% (all NN public members exercised)"
    python tests/lint_subset.py
    # expect: "lint subset: clean"
    python -m compileall -q emc2101
    # expect: exit code 0, no output

M4 — Persistence layer:

    python -m unittest discover -s tests -v
    # expect: persist tests green, e.g.
    # test_round_trip_save_load_restores_all_sections ... ok
    # test_corrupt_file_touches_zero_registers ... ok
    # test_product_id_mismatch_refuses_load ... ok
    # test_ctor_missing_file_is_silent_noop ... ok
    # OK (NNN tests)
    # real-file smoke (Pico W): save a profile to /emc2101.json, clobber register 0x4D,
    # load, assert restored:
    python -m mpremote connect port:COM16 run scripts/persist_smoke.py
    # expect: "persist smoke: PASS"
    # same script on the Pi against ~/emc2101.json:
    python3 scripts/persist_smoke.py
    # expect: "persist smoke: PASS"

M5 — Quality gates & docs:

    python -m unittest discover -s tests -v && python tools/api_coverage.py && python tests/lint_subset.py && python -m compileall -q emc2101
    # expect: all four gates green in sequence (suite OK, coverage 100%, lint clean,
    # compileall silent)
    # docs review: every public member appears in docs/API reference with signature,
    # range, and exceptions; operational notes cover boot window, TCRIT, DAC caveat,
    # ALERT/TACH trade-offs, ARA, force-register testing.

M6 — Examples:

    python -m compileall -q examples
    # expect: exit code 0 (scripts are MicroPython-compatible)
    python tests/lint_subset.py
    # expect: clean (examples included in the gate's file set)

M7 — Hardware E2E validation (per platform; substitute the correct serial port):

    # Pico W (COM16):
    python -m mpremote connect port:COM16 run examples/hw_smoke_test.py
    # expect final line: HW SMOKE TEST: PASS
    python -m mpremote connect port:COM16 run examples/e2e_hardware_test.py
    # expect: eleven "[PASS] <section>" lines, then
    # sections: 11 passed, 0 failed
    # E2E HARDWARE MATRIX: PASS
    # ESP32-S3 (COM7): identical two commands with port:COM7
    # RPi 3A+:
    python3 examples/hw_smoke_test.py        # expect: HW SMOKE TEST: PASS
    python3 examples/e2e_hardware_test.py    # expect: E2E HARDWARE MATRIX: PASS
    # cold-boot-with-profile scenario (each MCU bench):
    #   1. dev.save_config() with a distinctive profile (e.g. LUT entry at 30 C -> 25 %)
    #   2. power-cycle the board
    #   3. construct EMC2101(i2c, config_file=<path>) and assert the applied values
    # record all outcomes in PLANS.md Artifacts (results table) with dates.

M8 — Independent code review:

    # hand the committed tree (HEAD after M7 gating) to the independent reviewer;
    # record findings in PLANS.md (subsection under Surprises & Discoveries):
    #   - id, severity (blocker/high/medium/low/nit), file:line, description
    # address each finding: fix (commit, then re-run ALL FOUR gates) or decline
    # (Decision Log entry with rationale). Re-review only what changed, if requested.
    # expect: every finding closed; no open blocker/high items.

M9 — GitHub publication:

    # resolve login via GitHub API (get_me); then create the public repo
    # emc2101-fan-speed-controller (no auto-init) via the GitHub MCP or:
    gh repo create emc2101-fan-speed-controller --public
    git remote add origin https://github.com/<login>/emc2101-fan-speed-controller.git
    git push -u origin main
    # expect: branch 'main' set to track 'origin/main'
    git ls-remote origin
    # expect: refs matching local HEAD
    # verify publicly: open https://github.com/<login>/emc2101-fan-speed-controller —
    # README rendered, LGPL-2.1 license detected, research/ present, reference/ absent.


## Validation and Acceptance

The plan is complete when all of the following hold, each verifiable by a human with no prior
context. Host gates: from the repository root, `python -m unittest discover -s tests -v`
reports OK with zero failures; `python tools/api_coverage.py` reports 100% coverage of public
members; `python tests/lint_subset.py` reports clean; `python -m compileall -q emc2101
examples` exits silently. Hardware: on each of the three platforms (Pico W via COM16,
ESP32-S3 via COM7, RPi 3A+ directly), `hw_smoke_test.py` ends with `HW SMOKE TEST: PASS` and
`e2e_hardware_test.py` ends with `E2E HARDWARE MATRIX: PASS`, with the results table recorded
in Artifacts including dates and any EXCLUDED-HW items justified. Behavior demonstration:
on at least one board, the demo script visibly spins the fan through a duty sweep with RPM
readings that rise and fall with duty, and the persistence round trip restores a clobbered
register after `load_config()`. Publication: the public GitHub repository
`emc2101-fan-speed-controller` exists, renders its README, shows the LGPL-2.1 license,
contains the full tree including `research/`, excludes `reference/`, and its remote HEAD
matches local HEAD. Code review: the independent M8 review's findings are all closed
(fixed with gates green, or declined with a Decision Log rationale). If any item fails, the plan is not complete: record the failure in
Progress and Surprises & Discoveries and continue from there.

## Idempotence and Recovery

Every step is safe to repeat. Host-side steps (M0 scaffolding files, M2–M6 code and tests)
are additive or overwrite-in-place edits followed by re-running the gates; re-running a gate
never mutates state. Git operations are recoverable: before any risky rewrite, the working
tree should be committed, and `git reset --hard <milestone-commit>` returns to the last
known-good milestone without losing history. The hardware scripts are self-restoring by
construction: they snapshot the writable registers at start and restore plus verify them at
end, so an interrupted run leaves the chip at most temporarily misconfigured — re-running the
script completes the restoration, and a power cycle always returns the chip to its power-on
defaults. Two cautions. First, the TCRIT one-time unlock (D5/D13 territory): the E2E
persistence section consumes it deliberately; if a run dies mid-way through that section,
the chip may sit with TCRITOVRD set and a non-default TCRIT value — resolve by power-cycling
the bench and letting the next run start from defaults (record this in NOTES if it happens).
Second, flash wear: config saves are explicit-only and rare by design; nothing in the test
suite loops saves thousands of times. Power loss during a `save_config()` write is handled by
the temp-file-plus-rename atomicity: the previous good file survives intact. No step in this
plan deletes user data outside the repository, and the only irreversible external action is
the M9 push, which is gated behind the full M7 acceptance and the closed M8 review.

## Artifacts and Notes

Populated as milestones complete; keep entries concise and evidence-focused.

- Bench characterization excerpt (M1, Pico W, 2026-11-22): ID trio 0x16/0x5D/0x01 (plain EMC2101, Rev 2.54 match); over-reads pad silently with 0xFF (no exception); bare Receive/Send Byte desync the SMBus interface (EIO, recovers on reconnect) — register-addressed transactions only; interlock re-test clean (200 stable MSB-first reads at 28.0 °C, 0/100 alternating-order deltas > 1 °C); status read auto-set MASK (Config 0x00→0x80) per §6.4; BUSY cadence ~64 ms period ≈ 16/s, ~26 ms high per window; TACH 0xFFFF at all duties — fault isolated to fan side, TACH_M sweep (A3) and live RPM check (A7) deferred to M7 re-test per D26. Full detail: `NOTES/bench-characterization.md`.
- E2E results table (M7):

  | Platform | Firmware | Smoke | Matrix (sections) | Cold-boot scenario | Date |
  |---|---|---|---|---|---|
  | Pico W (COM16) | MicroPython v1.29.0 | PASS | PASS (11/11) ×3 consecutive A→B cycles | staged profile + `machine.reset()`, constructor auto-load verified | 2026-11-22 |
  | ESP32-S3 (COM7) | MicroPython v1.29.0 | PASS | PASS (11/11) ×2 A→B cycles | staged profile + `machine.reset()`, constructor auto-load verified | 2026-11-23 |
  | RPi 3A+ (bus 1) | CPython / smbus2 | pending | pending | fresh-instance approximation (no host-side power cycle) | pending |

  Notes: duty quantization identical across both MCU benches (raw 12/23/34/46 on the POR 0x17 PWM_F grid); the ESP32 bench additionally exercises live tach (~2100–2300 RPM) and a connected diode channel (~28 °C remote).
- Notable transcripts: pending — e.g. first `E2E HARDWARE MATRIX: PASS` per platform, any
  silicon-delta discovery with its fix commit.
- Code review findings log (M8): pending — findings with severities and closure status
  (fixed-commit or declined-decision reference per item).
- GitHub URL (M9): pending — final public repository address.

## Interfaces and Dependencies

Dependencies: MicroPython hosts need nothing beyond the standard library (`machine`,
`time`, `json`, `os`, `sys`); CPython hosts need `smbus2>=0.4.2` (declared under the Linux
environment marker in `pyproject.toml`; system `python3-smbus` is the documented fallback);
the dev host needs `mpremote` for MCU workflows. No other third-party code enters the
package. Distribution name `emc2101`, starting version 0.1.0, license LGPL-2.1-or-later.

Transport contract (implemented by both `_transport_mp.py` and `_transport_cp.py`, consumed
by `_core.py`):

    read_byte(reg) -> int            # one transaction; OSError after retry ladder
    write_byte(reg, value) -> None   # one transaction; same error model
    probe() -> bool                  # address ACK via harmless RO read (reg 0x00)
    scan() -> iterable[int]          # 7-bit addresses present on the bus
    delay_ms(ms) -> None
    close()                          # CP: release self-opened bus; MP: no-op

Core public API (class `EMC2101`, identical on both facades; grouped here for reference —
full semantics in `docs/` once written): lifecycle `close()`, `probe()`, `scan()`,
`verify()`, `read_reg(reg, n=1)`, `write_reg(reg, buf)`, context-manager support; identity
`product_id`, `mfg_id`, `revision`, `part_info`; temperatures `local_temp_c`,
`remote_temp_c`, `diode_fault()`; limits `local_high_c`, `remote_high_c`, `remote_low_c`,
`tcrit_c`, `tcrit_hysteresis_c`; LUT `lut` (list of eight `(temp_c, duty_pct)` tuples),
`lut_get_index(i)`, `lut_set_index(i, temp_c, duty_pct)`, `hysteresis_c`, `force_enabled`,
`forced_temp_c`; manual control `manual`, `set_duty_pct(pct)`, `duty_cmd_raw`; output
configuration `pwm_freq_hz`, `fan_output_inverted`, `dac_enabled`, `pwm_clk_sel`,
`pwm_div`; tachometer `rpm(pulses_per_rev=2)`, `tach_threshold`, `min_rpm`,
`tach_input_enabled`, `tach_mode`; spin-up `spin_up_enabled`, `spin_up_drive`,
`spin_up_time_s`, `spin_up_fast_tach`; alerts/status `status_raw()`, `active_alarms()`,
`alert_mask`, `alert_mode`, `service_alert()`, `clear_alert_mask()`, `busy()`,
`one_shot()`, `conversion_rate`, `averaging_filter`, `dis_to_enabled`,
`fault_queue_enabled`; calibration `ideality_factor_index`, `ideality_factor`,
`set_ideality_factor(n)`, `beta_auto_detect`, `beta_index`; scratchpads
`scratchpad_get(index)`, `scratchpad_set(index, value)`; preset
`configure_4wire_fan(pwm_freq_hz=...)`; persistence `save_config(path=None)`,
`load_config(path=None)`, `config_path`. Public constants include the alert-mode values
(`ALERT_MODE_INTERRUPT`, `ALERT_MODE_COMPARATOR`), the ideality table (`IDEALITY_TABLE`),
and conversion-rate/spin-up encodings. Exceptions: `ValueError` for argument/range errors
with informative messages, `OSError` for bus failures after retries and for
`DiodeFaultError` (a typed `OSError` subclass signaling diode open/short sentinels),
`TimeoutError` for bounded waits. Facade constructors:
`EMC2101(i2c, addr=0x4C, config_file=None)` on MicroPython and
`EMC2101(bus=1, addr=0x4C, handle=None, config_file=None)` on CPython. Persistence module
interfaces (pure, filesystem-agnostic): `encode(state) -> str`, `decode(text) -> state`,
`collect_state(read_byte) -> dict`, `apply_state(write_byte, state, *, strict=True) ->
report`.

---

Revision note (2026-11-22): initial creation of this ExecPlan. Basis: completed research
phase (`research/`, seven documents), the OpenAI cookbook ExecPlan template, and the user's
2026-11-22 rulings (repository name/public visibility, hardware-E2E-gated publication,
LGPL-2.1-or-later, inherited MAX31760 bench pins, committing `research/`, adding
`AGENTS.md`). Research-phase open items O1–O9 were adopted as decisions D13–D21 per their
recorded recommendations.

Revision note (2026-11-22): added D22 — `emc2101/` is the dev-tree path; the MicroPython
device install location is `/lib/emc2101/` (imports unchanged). Companion bullet in
`AGENTS.md` updated to state the same distinction.

Revision note (2026-11-22): refined D22 per user note — MicroPython's default
`sys.path` is `['', '.frozen', '/lib']`, so a package installed under `/lib` needs no
path setup; M6 examples will contain no `sys.path` boilerplate. `AGENTS.md` bullet
updated accordingly.

Revision note (2026-11-22): added D23 — `scripts/` directory for bench-grouped
test/diagnostic scripts (MAX31760 convention); seeded with `scripts/pico/probe_bus.py`
and `scripts/README.md`; `AGENTS.md` ground rules extended to cover it.

Revision note (2026-11-22): added D24 — generic scaffolding audit of the MAX31760 tree;
adopted `ci.yml` (M0), `requirements.txt` (M0), `deploy_mp.py` (M2), `CONTRIBUTING.md`
(M5), `examples/README.md` (M6), broadened `.gitignore` (M0); declined TODO/SUMMARY/code-
review archives as driver-specific or superseded by this ExecPlan.

Revision note (2026-11-22): M0 marked complete in Progress (repository initialized,
two commits, acceptance checks verified); added D25 — single-controller bench rotation
order Pico W → ESP32-S3 → RPi 3A+ per user instruction; Context and Orientation updated
to reflect the new repository state.

Revision note (2026-11-22): M1 marked complete in Progress (both entries checked off);
added D26 — fan-blocked M1 items (A3 sweep, A7 live RPM check, ALERT-pin idle state,
breakout photo) formally deferred to the M7 re-test. `NOTES/bench-characterization.md`
gained the A1–A8 ambiguity-disposition table plus the two deferred physical checks;
Artifacts populated with the M1 benchmark excerpt.

Revision note (2026-11-22): appended the M1-follow-up Progress entry — user
multimeter data re-isolates the TACH fault to the signal path (fan tach stage /
net pull-up / chip input stage); added the read-only
`scripts/pico/probe_tach_signal.py` probe and its `scripts/README.md` row;
`NOTES/bench-characterization.md` Bench state updated with the revised suspect
list. No milestone status change (D26 deferral stands).

Revision note (2026-11-22): appended the second M1-follow-up Progress entry —
evening TACH re-test exonerates the chip side (ALT_TCH latches; TACH_M
writable at 360 kHz base, partial A3 resolution; CLK_SEL=1 trial unchanged);
fault narrowed to the TACH net's HIGH state (missing pull-up top suspect).
Added `scripts/pico/char_tach_diag.py` (+ README row); NOTES gained the
re-test section, the A3 disposition update, and the rewritten Bench-state
bullet.

Revision note (2026-11-22): M1 follow-up thread closed — TACH root cause
confirmed (missing receiver-side pull-up on the OC tach net; user added a
10 kOhm pull-up to 3.3 V, now permanent on the bench). Both follow-up
Progress entries checked off and a closure entry appended; new Surprise
(pull-up root cause + PWM-gating caveat non-reproduction); D27 amends D26
(A7 closed early with live RPM data; remaining deferrals stand);
`NOTES/bench-characterization.md` gained the TACH-resolution section,
updated A3/A7 rows, and a rewritten Bench-state bullet;
`scripts/pico/char_tach_pwm_gate.py` added (+ README row).

Revision note (2026-11-22): recorded the Adafruit board-guide finding (user-
added PDF in `reference/`, page 7): the breakout's TACH/ALERT pull-up is a
solder jumper shipping disabled, the FAN-pin pull-up ships enabled —
explaining the round-2 root cause mechanism. New Progress entry, new
Surprise observation, `research/04-reference-notes.md` gained §5 (board
guide jumpers; Source links renumbered §6 and extended), NOTES gained the
mechanism paragraph, README gained a Hardware-notes section plus the board-
guide reference link, and `.gitignore` gained an explicit entry for the PDF.

Revision note (2026-11-22): D28 refines D11 — `reference/` is no longer
blanket-gitignored; the two vendor PDFs are ignored by explicit filename so
non-copyrighted items placed there stay committable. `.gitignore`,
`AGENTS.md`, and the README layout table updated to match.

Revision note (2026-11-22): M2 gated — checkbox flipped and a timestamped
completion entry appended (package + transports + facades committed as
c190b0a; 91-test suite, api_coverage 133/133, lint, and compileall all
green; Pico W live probe green; ESP32-S3/RPi import smokes green per D29).
Two new Surprise observations (rp2 MicroPython `freq=` keyword; the
external-temperature representable-vs-guaranteed range nuance that exposed
an encoder bug). D29 records the bench-split acceptance policy.

Revision note (2026-11-22): M3 implementation recorded — full protocol API
in `_core.py` (+ new leaf module `_faults.py`), facades extended, toolchain
updated (`tools/api_coverage.py` now checks facade exports AND public class
attributes; `tests/lint_subset.py` covers `_faults.py`; `test_public_surface.py`
pins the M3 surface with a drift guard), six new unit-test files (suite 91 →
223), stateful register-file mode + `write_entries` helper added to
`tests/fakes.py`, and the self-restoring live probe `scripts/pico/probe_m3.py`
(+ README row). Two new Surprise observations (first full-POR corroboration
on live silicon incl. the uniform-127 LUT default; driver-path RPM validation
at 50 % drive). D30 records the M3 bench-split acceptance policy.

Revision note (2026-11-22): M4 implementation recorded — new leaf module
`emc2101/_persist.py` (schema v1 encode/decode/collect/apply with the TCRIT
special case, PROG dance, and strict read-back diff), `_core.py` gained
`save_config`/`load_config` + `auto_load` ctor kwarg + atomic-write helpers,
facades wire `auto_load=config_file is not None`, `tools/deploy_mp.py` ships
the new module, `tests/lint_subset.py` extended (covers `_persist.py`; permits
`json`/`time`/`os` per D32), `test_public_surface.py` pins the two new
methods, new `tests/test_persist.py` (suite 223 → 261), and the self-restoring
live probe `scripts/pico/probe_persist.py` (+ README row) — **M4 LIVE PROBE
PASSED** on the Pico W bench (flash round-trip, strict read-back clean, all
values restored, no TCRIT touch). Three new Surprise observations (no
`os.path` on the rp2 port; probe-side invented member names; stale SNAP_REGS
labels in probe_m3.py). D31 records the split LUT-ordering rule;
D32 records the shared-module stdlib allowance.

Revision note (2026-11-22): M4 gated — checkbox flipped. Acceptance met:
persist unit tests green (261-suite OK), api_coverage 100 % (203/203), lint
and compileall clean, and the real-file smoke test passed on Pico W flash
(probe_persist.py: save → mutate 8 domains → load with strict read-back →
verified restoration → probe file removed; ESP32-S3/RPi legs fold into M7
per D29/D30). Implementation landed as d4d4595.

Revision note (2026-11-22): milestone renumbering per user instruction — new M8 =
independent code review gate inserted between M7 and publication; former M8 (GitHub
publication) becomes M9. Updated everywhere: Plan-of-Work intro (ten milestones),
Progress checklist, new `### M8` scope section, Concrete Steps block, Validation and
Acceptance (review closure added as a completion criterion), Idempotence (M9 push),
Artifacts (findings-log placeholder + GitHub URL relabeled). D33 records the decision.

Revision note (2026-11-22): M5 implementation recorded — `docs/` set (index,
quickstart, API reference, wiring guide, persistence, operational notes),
`CONTRIBUTING.md`, `CHANGELOG.md` (0.1.0 unreleased), root README polish;
quality gates required no further tuning beyond the M4 extensions and are
re-verified green (261 tests, api_coverage 203/203, lint, compileall).
One new Surprise observation (doc-vs-code drifts caught during the write:
verify() return contract; POR alert-mask decode).

Revision note (2026-11-22): M5 gated — checkbox flipped. Acceptance met:
all four host gates green on the final tree (261 tests OK, api_coverage
100 % at 203/203 members, lint clean, compileall clean) and the docs are
complete and internally consistent with the implemented API (accuracy
checked member-by-member against the pinned surface and decoded constants;
two drifts found and fixed pre-commit). Implementation landed as 21d3bdd.

Revision note (2026-11-22): M6 implementation recorded — five example scripts
(three board-aware demos, self-restoring hw_smoke_test.py, eleven-section
e2e_hardware_test.py with two-phase cold-boot on the MCU benches) plus
examples/README.md; lint gate extended to examples/ (sys allowed per the
D32 rationale); new host-side tools/probe_error_model.py. Live work on the
Pico W bench uncovered and fixed the PROG-polarity inversion (D34) before
any M6 code could be trusted: hw_smoke_test.py now ends HW SMOKE TEST: PASS
on real silicon and the M4 persistence probe re-passed. One new Surprise
observation (the polarity bug itself, with evidence chain).

Revision note (2026-11-22): M6 gated — checkbox flipped. Acceptance met:
five scripts exist and compile cleanly (compileall silent; lint gate now
covers all five under the MicroPython subset rules), and the E2E matrix
was reviewed against the pinned public surface so every public class
member appears in at least one section. Bonus beyond acceptance: the
smoke test already passes on the Pico W bench (`HW SMOKE TEST: PASS`)
and the PROG-polarity fix (D34) was verified on real silicon before
gating. Implementation landed as ab75f8f.

Revision note (2026-11-22): M7 fix recorded — E2E phase-B persistence failure root-caused to
an undocumented silicon behavior: while PROG=0 the Fan Setting register mirrors the LUT-driven
effective duty and fan-domain writes are dropped (dedicated live probe + failure forensics).
Fix per D35: PROG=1 dances around fan-domain reads in `collect_state` (signature now takes
write_byte; single internal caller updated) and around the `apply_state` strict read-back when
the final state ends in LUT mode (FAN_CFG comparison adjusted for the temporary bit); the E2E
and smoke scripts' snapshot/restore/safety-net paths enforce the same discipline (including the
S4 raw-LUT capture/restore). New research section §16 in `research/emc2101-register-map.md`
(four live observations, incl. Table 6.28 POR LUT S default 3Fh). Test suite 261 → 264 with a
`MirrorTransport` silicon model and three regression tests. All four host gates green.
Pending: Pico W rerun (both phases), then ESP32-S3 and RPi 3A+ legs.

Revision note (2026-11-22): M7 second fix recorded — the post-D35 intermittent phase-B failure
(`0x4c expected 0x29 got 0xc`) root-caused to a READ-OUT race: after a FAN_CFG PROG-bit
transition the Fan Setting read-out keeps reporting the previously active drive source for up
to one conversion window (~64 ms at 16/s); writes stick immediately. Evidence chain: the
instrumented run (per-transaction logging) passed while uninstrumented runs failed; step-by-step
probes with explicit sleeps showed no lag; the apply-tail replay never disturbed FS. Fix per
D36: `_persist._settle_ms(SETTLE_MS=100)` after every PROG-on transition before fan-domain
reads (`collect_state`, `apply_state` strict read-back dance) plus a settle-and-retry-once pass
over disagreeing registers in the strict read-back (genuine mismatches still fail); the E2E/
smoke snapshot-capture, S4 raw-LUT capture/restore, and safety-net verification use the same
0.1 s settle. `MirrorTransport` now models the stale read-out window; three new regression
tests (suite 264 → 267). Research note gained §16.5. All four host gates green (267 tests,
api_coverage 203/203, lint clean, compileall clean). Pending: redeploy + 3× phase A→B cycles
on COM16, then ESP32-S3 and RPi 3A+ legs.

Revision note (2026-11-22, session close): M7 Pico W leg complete — after the D36 deploy,
three consecutive full E2E phase A→B cycles PASSED on COM16 (including the previously
failing persistence section) plus `hw_smoke_test.py` PASS; committed as `7c8dcb4`. The user
confirmed the bench topology: a SINGLE fan-sensor board is physically rotated between the
target devices, so the ESP32-S3 (COM7) and RPi 3A+ legs await physical moves and continue
in the next session. M8 adjustment: the independent code review will be performed by a
SEPARATE EXTERNAL agent arranged by the user (not spawned from this workspace); this agent
then acts on that report (every finding fixed + gated, or declined + logged) before M9
proceeds. Tree fully gated at session close (267 tests, api_coverage 203/203, lint clean,
compileall clean).

Revision note (2026-11-23): M7 ESP32-S3 leg recorded — board rotated from the Pico W bench
(single-board rotation), comms established on COM7 (scan [0x4c], identity trio exact),
hw_smoke_test PASS, and two full E2E phase A→B cycles PASSED including the constructor
cold-boot auto-load verification; results table in Artifacts now holds the Pico W and
ESP32-S3 rows. No code changes were needed for this leg — the D35/D36 fixes carried over
unchanged. Operational notes captured: mpremote can hold the port in a REPL follow-loop
after the phase-A soft reset (kill the stale process before phase B); the ESP32-S3 module's
PSRAM boot errors are cosmetic; this bench has fan + diode connected (live tach and remote
temperature exercised). Remaining: RPi 3A+ leg, then gate.

Revision note (2026-11-23, mid-session pause): recorded the ESP32-S3 remote-diode temperature-anomaly investigation (post-power-up 35→38→29 °C decay with the local die tracking ambient and calibration registers at POR defaults) and the COM7 mpremote stall-after-idle-gap finding plus the off-main-thread I²C death; matching Progress line added. Investigation paused at user departure — resume with host-polled drift sampling + touch-response test, then conclude before the RPi 3A+ leg. No code changes; gates remain green as of the last commit.
