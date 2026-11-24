# Characterize fan speed curves — utility ExecPlan

This ExecPlan is a living document governing the **fan-curve characterization utility**
(collector + renderer). It follows the same conventions as the driver's `PLANS.md`: the
sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes &
Retrospective` must be kept up to date; every stopping point gets a timestamped `Progress`
entry; every decision gets a `Decision Log` entry; revisions append a note at the bottom.
Per UC1 this file lives in `plans/` because the utility is not a driver feature;
`PLANS.md` continues to govern the driver alone.

## Purpose / Big Picture

After this plan completes, anyone with a 4-wire fan on an EMC2101 breakout can answer four
questions about their specific fan with one command:

1. Does the fan ever actually stop, or does it hold a minimum-speed floor?
2. At what commanded PWM duty does the fan start turning (or begin rising above its floor)?
3. How closely does the fan track the ideal linear duty→speed curve?
4. Is there a maximum duty above which fan speed stops increasing?

The utility produces two artifacts in the established bench-data format
(`..\FanSpeedController\NOTES\bench-data\`): a CSV (`pct,rpm_settled,rpm_min,rpm_max`) and
an annotated PNG curve whose footer records the fan's identity and whether its tach line
requires an external pull-up.

It operates in three deployment scenarios: (1) remotely against a MicroPython target
(Pico W / ESP32-S3) driven from a host computer via mpremote — data gathering happens on
the device, the CSV streams back over stdout; (2) natively on a Linux host (RPi 3A+) where
the controller is attached; (3) remotely against either kind of host (e.g. ssh transport).
Matplotlib cannot run on MicroPython, so PNG rendering is always a second, host-side stage
that reads the CSV (UC2).

How to see it working: `python -m mpremote connect port:COM16 run examples/fan_characterize.py > curve.csv`
gathers a full curve in ~5.5 minutes while prompts and progress fly past on the terminal;
the closing stderr block prints the four answers plus a ready-to-paste renderer command;
running that command yields `curve.png` and `curve.meta.json`.

## Progress

- [x] (2026-11-24) U0 Utility planning trail: `plans/` directory, this file, AGENTS.md pointer (commit e3c5541).
- [x] (2026-11-24) U1 Analysis core: `examples/_fan_curve_math.py` + `tests/test_fan_curve_math.py` (31 new tests; all four gates green).
- [x] (2026-11-24) U2 Collector: `examples/fan_characterize.py` (all four gates green; fake-device dry run of all three pre-flight paths passed — see Surprises).
- [ ] U3 Renderer: `tools/render_curve.py`.
- [ ] U4 Bench validation & docs: live runs (Pico W streamed, RPi native), PNGs verified, `examples/README.md` updated, gates green.

## Surprises & Discoveries

- (2026-11-24, U1) The saturation-ceiling walker treats a one-row impulse in an
  otherwise-zero series as a rising→flat transition (the spike presents a positive
  local slope on its left flank). Out of domain for real data — each sweep row is a
  median of ~18 tach samples and cannot spike alone — so the heuristic was left as-is
  and the degenerate-input test asserts only the contractual guarantees (no exception,
  onset located, linearity unmeasurable) rather than the ceiling value.
- (2026-11-24, U2) A throwaway host-side dry run of the collector's `main()` against a
  stateful FakeTransport (scripted stdin, instant sleeps, simulated live/dead tach)
  caught a real defect before bench time: the CSV header was collected for `--save`
  but never emitted to the stdout stream, so remote captures would have produced a
  header-less file. Fixed by printing the header at sweep start. The same harness then
  verified all three pre-flight outcomes (test-path built-in, skip-path external with
  sanity check, dead-tach abort after 3 attempts) end-to-end: correct rc, 63-row CSV
  shape, restore PASS, zero register drift, no partial CSV on abort.

## Decision Log

- Decision: UC1 — utility planning/tracking documents live in a top-level `plans/`
  directory (one file per utility); `PLANS.md` remains the driver-only ExecPlan; AGENTS.md
  gains a one-line pointer so future sessions know the convention.
Rationale: the user does not want root-directory clutter from non-driver plans/documents as
utility work accumulates; `plans/` names its purpose unambiguously and scales one-file-per-
utility. Alternatives considered: under `NOTES/` (blurs observational notes with living
ExecPlans) and under `docs/` (shipped end-user documentation, wrong genre).
Date/Author: 2026-11-24, user + agent.
- Decision: UC2 — two-stage architecture: a collector (`examples/fan_characterize.py`,
  MicroPython + CPython) that streams the CSV to **stdout** and sends everything else
  (prompts, progress, summary, renderer command) to **stderr**, plus a renderer
  (`tools/render_curve.py`, CPython/matplotlib) that turns the CSV into the PNG.
Rationale: matplotlib is unavailable on MicroPython, so the PNG can never be produced on
the Pico W or ESP32-S3; the three deployment scenarios (remote MCU, native Linux, remote
Linux) all reduce to "gather on the device connected to the fan, render on whatever host
has Python + matplotlib". A pure-stdout data channel makes scenario 1/3 capture a plain
shell redirect (`mpremote ... run ... > curve.csv`).
Date/Author: 2026-11-24, user + agent.
- Decision: UC3 — placement: collector in `examples/` (board-aware, self-contained,
  self-restoring, end-user-shippable like the demos), renderer in `tools/` (hardware-free
  host utility). Shared analysis code in `examples/_fan_curve_math.py` (underscore-private,
  deploys alongside the collector; the renderer imports it via a documented sys.path
  bootstrap).
Rationale: matches the existing bucket semantics in AGENTS.md exactly; avoids a premature
fourth top-level category (`utilities/`) and avoids duplicating a board-agnostic script
three times across `scripts/<bench>/`.
Date/Author: 2026-11-24, user + agent.
- Decision: UC4 — sweep granularity: the full raw Fan Setting grid S=0..62 with
  `PWM_F=31` programmed first (finest achievable grid; effective duty = S/(2·31), ≈1.61 %
  steps; S=62 is exactly 100 %, S=63 would clamp identically and is skipped). The CSV keeps
  the exact reference header `pct,rpm_settled,rpm_min,rpm_max`; `pct` is the *effective*
  duty rounded to 1 decimal (0.0, 1.6, 3.2 … 100.0).
Rationale: true 1 % increments are physically impossible on this chip — `PWM_F_MAX=31`
(`emc2101/_regs.py`) and full scale landing at S=2·PWM_F mean the finest grid that still
reaches 100 % is 1/62. Sweeping the raw setting gives maximum resolution for all four
determinations and stays reproducible regardless of the bench's prior PWM_F.
Date/Author: 2026-11-24, user + agent.
- Decision: UC5 — metadata handling: the collector keeps the CSV byte-pure; it prompts for
  fan name/details at start, determines the pull-up answer during the tach pre-flight, and
  at the end prints a copy-paste-ready renderer command with all metadata baked in as flags
  (`--fan/--bench/--pullup/--ppr/--date`). The renderer stamps the metadata into a PNG
  footer (a `fig.text` strip below the axes, structurally incapable of obscuring chart
  data) and writes a `<stem>.meta.json` sidecar next to the PNG.
Rationale: nothing new crosses the mpremote boundary; metadata becomes machine-readable at
render time; re-rendering from the CSV alone still works (missing metadata renders as
"—"). Alternatives rejected: collector-written sidecars (flash-file friction on MP) and
PNG-caption-only (not machine-readable).
Date/Author: 2026-11-24, user + agent.
- Decision: UC6 — tach pre-flight flow: ask "Test the tach line now? (y/N)". YES → enable
  `tach_input_enabled`, drive manual 100 %, sample ~3 s: live count ⇒ record
  `pullup=built-in`; dead count ⇒ prompt to attach the 10 kΩ pull-up, retest, up to 3
  tries ⇒ record `pullup=external`; still dead ⇒ **abort** with diagnostics (fan power,
  wiring, breakout jumper), restore, exit nonzero. NO → ask "Does this fan require an
  external pull-up on the tach? (y/n)", record the answer, then perform a silent 100 %
  sanity check: if the count is dead, warn loudly and offer to jump into the test path
  before sweeping.
Rationale: a sweep without a working tach is worthless (every row would be 0.0); the skip
path exists because experienced users already know their fan's configuration, but the
sanity check guards against a misremembered answer costing 5.5 minutes.
Date/Author: 2026-11-24, user + agent.
- Decision: UC7 — measurement protocol: each level held 5 s; `rpm(ppr)` sampled every
  250 ms; the first 500 ms discarded as transient/stale-latch; settled = median of the
  surviving samples, min/max over the same window; sentinel/zero count ⇒ 0.0.
Rationale: the TACH register holds the latest period measurement, so each sample is
independent; the discard window suppresses the stale-latch artifact visible at 0 % in the
reference plot and lets the fan settle after each duty step.
Date/Author: 2026-11-24, agent (proposed in design, approved with the design).
- Decision: UC8 — analysis heuristics centralized in `examples/_fan_curve_math.py`
  (pure stdlib, MicroPython-safe, no driver imports) and shared by both stages, so the PNG
  annotations and the text summary can never drift apart. Defaults are named constants,
  overridable via kwargs/flags.
Date/Author: 2026-11-24, agent (approved with the design).
- Decision: UC9 — self-restore discipline: snapshot the writable registers the utility
  mutates (CONFIG 0x03, FAN_CFG 0x4A, SPINUP 0x4B, FAN_SETTING 0x4C, PWM_F 0x4D, PWM_D
  0x4E) at start; restore and verify byte-for-byte in a `finally` (Ctrl-C safe). Bus error
  mid-sweep: restore, exit nonzero; the partial CSV is already on the host via stdout.
Rationale: standing convention for hardware-touching scripts in this repo (AGENTS.md,
`hw_smoke_test.py` pattern).
Date/Author: 2026-11-24, agent (approved with the design).
- Decision: UC10 — development branch `chatbox/fan-characterize`; imperative commit
  subjects; no co-author trailers (per the amended AGENTS.md convention, D41).
Date/Author: 2026-11-24, agent.

## Outcomes & Retrospective

To be written at completion. Nothing here yet.

## Context and Orientation

Assume the reader knows the repository and the driver API (`docs/api-reference.md`).
Load-bearing facts:

- **Duty grid.** Effective duty = `S / (2·PWM_F) × 100 %` where S is the 6-bit Fan Setting
  (register 0x4C). `PWM_F_MAX = 31` (`emc2101/_regs.py`); full scale lands at
  S = 2·PWM_F. With PWM_F=31 the grid is 1/62 ≈ 1.61 % and S=62 is exactly 100 %.
- **Tach reading.** `rpm(pulses_per_rev=2)` performs the LSB-first interlocked read
  (0x46→0x47) and returns 0.0 for a zero count or the 0xFFFF sentinel (input disabled,
  fan stopped, or below min detectable RPM ≈ 82 RPM). Each call snapshots the latest
  period measurement.
- **Known fan behaviors to interpret.** Some fans gate their tach output at 0 % duty
  (measured NOT to apply to the bench fan — `NOTES/bench-characterization.md`); the first
  tach reading after power-on can be a stale latch of the previous drive (visible as the
  flagged 0 % point in the reference plot); a missing receiver-side pull-up on the tach
  net defeats the chip's edge detector (bench-confirmed root cause, same notes file).
- **Self-restore convention.** Hardware-touching scripts snapshot writable registers and
  restore + verify them byte-for-byte before exiting (`examples/hw_smoke_test.py`
  pattern).
- **Benches.** Pico W COM16 (I2C0 SDA=GP0/SCL=GP1), ESP32-S3 COM7 (SDA=GPIO41/SCL=GPIO42),
  RPi 3A+ SMBus bus 1; chip fixed at 0x4C. Board detection at runtime follows the demo
  pattern (`sys.platform` + `os.uname().machine`).
- **Output reference.** `..\FanSpeedController\NOTES\bench-data\duty_curve_1pct.csv`
  (header `pct,rpm_settled,rpm_min,rpm_max`) and `fan_curve_1pct.png` (style specified in
  U3).
- **MicroPython constraints.** No `statistics`, no `os.path`, limited f-string support:
  use `%` formatting, a hand-rolled median, and a portable sleep helper
  (`time.sleep_ms` / `time.sleep`). New example files join the `tests/lint_subset.py`
  MicroPython-subset file set.

## Plan of Work

Work proceeds through five milestones, U0–U4, in strict order. U0–U3 are host-side
(Windows dev machine); U4 needs the bench.

### U0 — Utility planning trail

Scope: create `plans/`; write this file; add the one-line pointer to AGENTS.md project
ground rules ("Utility planning/tracking documents live in `plans/` (one file per
utility); `PLANS.md` governs the driver only."); create branch `chatbox/fan-characterize`.
Acceptance: committed; working tree clean.

### U1 — Analysis core

Scope: `examples/_fan_curve_math.py` — pure stdlib, MicroPython-safe, no driver imports.
Contents:

- `effective_pct(setting, pwm_f)` → float percent on the given grid.
- `median(values)` — hand-rolled (no `statistics`).
- `analyze(rows, *, onset_tol_rpm=10.0, onset_frac=0.02, sustain=3, noise_floor_rpm_per_pct=1.0, plateau_window=5)`
  returning a dict with the four determinations:
  1. `turns_off` (bool) and `floor_rpm` — `settled(S=0) > 0` ⇒ floor fan,
     `floor_rpm` = that value; otherwise the fan stops and `floor_rpm` is None.
  2. `onset_pct` — stopping fan: first row with settled > 0. Floor fan: baseline = median
     of the low-duty plateau preceding the rise; first pct exceeding baseline + max
     (`onset_tol_rpm`, `onset_frac` × max settled) sustained for `sustain` consecutive
     rows.
  3. `linearity` — straight line from the onset point to the ceiling point; max absolute
     deviation (rpm, % of span, and the pct where it occurs) plus RMS deviation, over the
     rows between the two points.
  4. `ceiling_pct` — walking down from 100 %, the first pct where the local slope over a
     `plateau_window`-row window drops below `noise_floor_rpm_per_pct`; reported as
     "plateaus above P %" (None when monotonic to 100 %).
- Row-formatting helpers (CSV line assembly, 1-decimal pct).
- Degenerate inputs (all-zero series, single nonzero row) return explicit
  "unmeasurable" markers rather than raising.

Tests: `tests/test_fan_curve_math.py` with synthetic series — stopping fan (zeros then
ramp), floor fan (flat ~660 then ramp), ideal linear, saturating tail (flat top), noisy
jitter overlay, degenerate all-zero, single-nonzero-row. Assert each determination and the
degenerate-input behavior.

Acceptance: all four quality gates green (`unittest discover`, `api_coverage.py`,
`lint_subset.py`, `compileall emc2101 examples`).

### U2 — Collector

Scope: `examples/fan_characterize.py` — board-aware (same runtime detection as the
demos), MicroPython + CPython. Flow:

1. Prompts (stderr): fan name (default "Unknown fan"), pulses/rev (default 2), bench label
   (auto-detected, editable).
2. Construct the facade, `verify()` (refuse to run on bad identity). Snapshot the six
   registers listed in UC9.
3. Tach pre-flight per UC6; outcome recorded as `pullup ∈ {built-in, external, unknown}`.
4. Program `PWM_F=31` (≈5.8 kHz at the 360 kHz base — raw-tier write or solver target,
   verified by read-back), enter `manual`, disable spin-up (a spin-up burst would corrupt
   the 0 % row).
5. Sweep S=0..62 (UC4/UC7): per level — `duty_cmd_raw = S`, dwell 5 s total, sample
   `rpm(ppr)` every 250 ms, discard the first 500 ms, compute settled/min/max over the
   survivors; print a progress line to stderr; emit the CSV row to stdout.
6. Summary (stderr): the four answers from `_fan_curve_math.analyze`, caveats (flag the 0 %
   row when it disagrees with its neighbors — stale-latch/tach-gating hint), and the
   copy-paste-ready renderer command with `--fan/--bench/--pullup/--ppr/--date` baked in.
7. `finally`: restore the snapshot byte-for-byte and verify (Ctrl-C safe). Bus error
   mid-sweep: restore, exit nonzero (partial CSV already captured by the host).

CLI flags (CPython conveniences, harmless on MicroPython): `--name`, `--ppr`, `--bench`,
`--settle-ms 5000`, `--sample-ms 250`, `--discard-ms 500`, `--save PATH` (CPython only:
tee the CSV to a file). Add the file to the `tests/lint_subset.py` MicroPython-subset set.

Acceptance: all four gates green; no driver changes (api_coverage unchanged).

### U3 — Renderer

Scope: `tools/render_curve.py` — CPython, matplotlib. CLI:
`render_curve.py CURVE_CSV [--out OUT.png] --fan NAME --bench LABEL --pullup built-in|external|unknown --ppr N --date YYYY-MM-DD`.
Imports `examples/_fan_curve_math.py` via a documented sys.path bootstrap. The figure
reproduces the reference style: title "<fan> - duty vs RPM" with subtitle "(EMC2101,
<bench>, <date>)"; blue measured curve with small markers; grey dashed min-to-max
reference line (onset → ceiling); green dotted vertical at the crossover with a label; red
ring + annotation on a flagged 0 % anomaly when present; max ±deviation arrow
annotations; legend. Metadata footer: a `fig.text` strip **below** the axes (outside the
plot area) listing fan, bench, date, pull-up requirement, ppr, and duty-grid info; missing
arguments render as "—". Writes the PNG plus a `<stem>.meta.json` sidecar
(machine-readable metadata).

Acceptance: renders a synthetic CSV (from U1 fixtures) to a PNG; visual inspection shows
the reference style matched and the footer clear of all chart data; meta.json parses.

### U4 — Bench validation & docs

Scope: (a) Pico W leg — deploy the package (`tools/deploy_mp.py`), run the collector via
`python -m mpremote connect port:COM16 run examples/fan_characterize.py > curve_pico.csv`
with a live fan; verify header + 63 rows + restore PASS; (b) RPi 3A+ leg —
`python3 examples/fan_characterize.py --save curve_rpi.csv` natively; (c) render both PNGs
with real metadata and visually verify; (d) update `examples/README.md` (new table row +
prerequisite note: diode not required); (e) all four gates; (f) final commits. Record
results in Progress.

Acceptance: two real CSVs and two PNGs produced and reviewed; README updated; gates green.

Runtime note: sweep ≈ 63 × 5 s ≈ 5.3 min plus pre-flight.

## Revision Notes

- 2026-11-24: Initial version. Design agreed with the user via brainstorming: location
  options A/B/C → A (examples + tools); platform scenarios 1–3 accepted; metadata option A
  plus PNG footer; sweep granularity option A (full raw grid); `plans/` directory for
  utility planning documents.
