# AGENTS.md — EMC2101 Fan Speed Controller

## ExecPlans

When writing complex features or significant refactors in this repository, use an ExecPlan
(as described below) from design to implementation. The current ExecPlan is `PLANS.md` at
the repository root; it is a living document and must be maintained in accordance with its
own rules: keep the `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes &
Retrospective` sections up to date at every stopping point, record each decision with its
rationale, and append a revision note at the bottom when revising the plan. When implementing
an ExecPlan, do not prompt for "next steps" — proceed to the next milestone, commit
frequently, and resolve ambiguities autonomously (recording them in the Decision Log).

## Project ground rules

- Driver code lives in `emc2101/` — that is the path in the git dev tree (repo root).
  On a MicroPython device the package installs under `/lib/emc2101/`; MicroPython's
  default `sys.path` is `['', '.frozen', '/lib']`, so no path manipulation is ever
  needed — just `import emc2101.mp`. Platform facades are `emc2101/mp.py`
  (MicroPython) and `emc2101/cp.py` (CPython), both exposing the identical public API
  enforced by `tests/test_api_parity.py`.
- `research/` holds the committed research trail; consult it before re-deriving register
  facts. `reference/` holds reference materials; copyrighted vendor files we cannot
  redistribute (currently the datasheet and the Adafruit board-guide PDFs) are
  gitignored by explicit filename (D28) — never commit copyrighted material, but our
  own notes placed there may be committed.
- Clean-room policy: the Adafruit CircuitPython library and other third-party drivers are
  reference material only; do not copy their code into this package.
- Hardware benches (inherited from the MAX31760 project): Pico W RP2040 @ COM16, I2C0
  SDA=GP0/SCL=GP1; ESP32-S3 @ COM7, I2C0 SDA=GPIO41/SCL=GPIO42; RPi 3A+ SMBus bus 1. Chip
  address is fixed at 0x4C. Bench scripts under `examples/` must remain self-restoring.
- Test/diagnostic utilities made during development are kept in the tree under `scripts/`,
  grouped by physical bench (`pico/`, `esp32/`, `rpi/`) and indexed in `scripts/README.md`
  (MAX31760 convention). They need real hardware, are not collected by `tests/`, are
  self-contained, and any state-mutating script must be self-restoring. Shipped demos and
  the canonical tri-platform E2E suites live in `examples/`; hardware-free dev utilities
  (coverage, lint, deploy) live in `tools/`.
- Quality gates after any code change: `python -m unittest discover -s tests -v`,
  `python tools/api_coverage.py`, `python tests/lint_subset.py`,
  `python -m compileall -q emc2101 examples`.
- Commits: imperative subject lines; commits made by the Chatbox agent that include code
  changes carry the trailer `Co-authored-by: Chatbox <chatbox@chatboxai.com>`. New Git
  branches created by the agent are prefixed `chatbox/`.
- License: LGPL-2.1-or-later (see `LICENSE`).
