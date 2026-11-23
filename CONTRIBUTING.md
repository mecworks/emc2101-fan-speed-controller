# Contributing

Thanks for helping with `emc2101`. This project follows a strict
process because it drives thermal protection hardware: every change must
keep the quality gates green and stay honest about what the silicon
actually does.

## Prerequisites

- **Host (any OS):** Python ≥ 3.9 with `unittest` (stdlib). No package
  installation is needed to run the test suite — tests run against mock
  transports.
- **MCU workflows:** `pip install mpremote` (invoke as
  `python -m mpremote`; the bare command may not be on PATH).
- **CPython target:** Linux with `smbus2>=0.4.2` (`sudo apt install
  python3-smbus2`) and I²C enabled; the chip sits on SMBus bus 1.
- **Hardware benches** (optional, for live validation): RPi Pico W
  (COM16, I2C0 SDA=GP0/SCL=GP1), ESP32-S3 (COM7, I2C0 SDA=GPIO41/
  SCL=GPIO42), Raspberry Pi 3A+ (SMBus bus 1) — see
  [`docs/wiring.md`](docs/wiring.md).

## Quality gates

Run all four from the repository root after any code change; all must
pass before a commit:

```powershell
python -m unittest discover -s tests -v
python tools/api_coverage.py
python tests/lint_subset.py
python -m compileall -q emc2101 examples
```

| Gate | What it enforces |
|---|---|
| Unit suite | Protocol behavior against stateful fake transports (interlock orders, PROG dance, TCRIT unlock ordering, persistence round-trips, facade parity, public-surface pinning). |
| `tools/api_coverage.py` | Every public member (facade `__all__` exports AND class attributes) is exercised by at least one test. Adding a public member without a test fails this gate. |
| `tests/lint_subset.py` | MicroPython-subset compliance of the shared modules: no CPython-only syntax or imports in code that ships to both ports. `json`/`time`/`os` are permitted (they ship with MicroPython v1.29.0 on both target ports); everything else exotic is not. |
| `compileall` | Byte-compiles the package and examples cleanly. |

## Architecture ground rules

- **Shared core, platform edges.** All protocol logic lives in
  `emc2101/_core.py` plus leaf modules (`_regs.py`, `_tables.py`,
  `_faults.py`, `_persist.py`). Platform facades (`mp.py`, `cp.py`) and
  transports (`_transport_mp.py`, `_transport_cp.py`) are thin: they
  bind a bus and expose the identical public API. The two facades'
  `__all__` lists must mirror each other exactly —
  `tests/test_api_parity.py` enforces this.
- **Property-per-register convention.** One property per register (or
  composite); verbs for actions and destructive reads (`status_raw()`,
  `service_alert()`, `one_shot()`). Destructive-read side effects must
  be visible at the call site and documented.
- **Error model.** `ValueError` for out-of-range arguments; `OSError`
  for bus failures after the retry ladder; typed subclasses for domain
  faults (`DiodeFaultError`, `ConfigFormatError`, `ConfigValidationError`,
  `ConfigApplyError`). Do not swallow bus errors silently.
- **Clean-room policy.** Third-party drivers (Adafruit CircuitPython et
  al.) are reference material only — never copy their code into this
  package. Conceptual borrowing is fine; code is not.
- **No faked features.** Where the EMC2101 lacks a sibling-chip feature
  (fan-fail force, pulse stretching, software POR, dual ports), the API
  honestly omits it rather than pretending.

## Hardware-testing conventions

- Bench scripts live under `scripts/<bench>/` (`pico/`, `esp32/`,
  `rpi/`), indexed in `scripts/README.md`. They need real hardware, are
  self-contained, and are NOT collected by `tests/`.
- **Any script that mutates chip state must be self-restoring:**
  snapshot the affected registers first, restore and verify them byte-
  for-byte before exiting (house pattern: raw snapshot + safety-net
  restore in `finally`). Never leave the bench misconfigured.
- **Never consume the TCRIT one-time unlock in a probe** unless the
  milestone explicitly requires it and records the consequence.
- Shipped demos and the canonical tri-platform E2E suites belong in
  `examples/`; hardware-free dev utilities (coverage, lint, deploy) in
  `tools/`.

## Commit hygiene

- Imperative subject lines describing the change ("Add …", "Fix …",
  "Gate M4: …").
- Commits made by the Chatbox agent that include code changes carry the
  trailer `Co-authored-by: Chatbox <chatbox@chatboxai.com>`; new agent
  branches are prefixed `chatbox/`.
- Milestone work lands as an implementation commit followed by a
  separate gating commit that flips the checkbox in `PLANS.md`.

## Process

`PLANS.md` is the living ExecPlan: milestones, decisions (D-log),
progress, surprises, and revision notes. When working from it, keep the
`Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes &
Retrospective` sections current at every stopping point, record each
decision with its rationale, and append a revision note when revising
the plan. Consult `research/` before re-deriving register facts.

## Licensing

LGPL-2.1-or-later (see `LICENSE`). Contributions are accepted under the
same terms. Vendor materials in `reference/` are gitignored by filename
and must never be committed.
