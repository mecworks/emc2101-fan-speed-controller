# 05 — Architecture Sketch (target repo & package layout)

Mirrors the `FanSpeedController` project structure and conventions, adapted for the EMC2101's
single-byte transport and the persistence seam. This is a sketch for the future spec/plan phase —
not a commitment to filenames beyond what the interview locked.

## 1. Repository layout

Repo root = `EMC2101_Fan_Speed_controller_project/` (git init at that level when work starts;
datasheet PDF stays gitignored per sibling convention — we don't own the copyright).

```
EMC2101_Fan_Speed_controller_project/
├── EMC2101_Fan_Speed_controller/        # ← driver code lives here (user-specified location)
│   ├── emc2101/                         # the package
│   │   ├── __init__.py                  # version, re-export convenience (sibling pattern)
│   │   ├── mp.py                        # MicroPython facade: EMC2101(i2c, addr=0x4C[, config_file=...])
│   │   ├── cp.py                        # CPython/Linux facade: EMC2101(bus=1, addr=0x4C, handle=None[, config_file=...])
│   │   ├── _core.py                     # shared device API (platform-neutral; all protocol knowledge)
│   │   ├── _regs.py                     # leaf: register map, bit constants, fixed-point helpers (no imports from package)
│   │   ├── _tables.py                   # factory defaults, ideality table (64), conversion-rate table, spin-up tables
│   │   ├── _persist.py                  # JSON schema v1: encode/decode/validate + apply-ordering rules (FS-agnostic core)
│   │   ├── _transport_mp.py             # machine.I2C adapter (single-byte contract)
│   │   └── _transport_cp.py             # smbus2 / python3-smbus adapter (single-byte contract)
│   ├── examples/
│   │   ├── pico_demo.py                 # probe → temps → duty sweep → RPM → save/load config
│   │   ├── esp32_demo.py                # ESP32-S3 variant (pin placeholders to adapt)
│   │   ├── rpi_demo.py                  # Raspberry Pi 3A+ (CPython) demo
│   │   ├── hw_smoke_test.py             # self-restoring core-behavior smoke (board-aware pins)
│   │   └── e2e_hardware_test.py         # full matrix over every public API domain (self-restoring)
│   ├── tests/                           # host-runnable, mock-backed unit/integration suite
│   │   ├── test_emc2101.py              # constants, regs, conversions, core behavior (transaction-sequence asserts)
│   │   ├── test_persist.py              # schema round-trip, validation, ordering, corruption cases
│   │   ├── test_api_parity.py           # mp.__all__ == cp.__all__ (sibling TestApiParity pattern)
│   │   └── lint_subset.py               # MicroPython-subset compliance gate
│   ├── tools/
│   │   └── api_coverage.py              # every public member exercised by the suite
│   ├── docs/
│   │   ├── README.md                    # wiring, per-platform install, quickstart, API reference, error model, operational notes
│   │   └── ...                          # (boot-window, TCRIT, DAC-mode, ARA notes as separate pages if long)
│   ├── NOTES/                           # research links + bench characterization records (P0 output lands here)
│   ├── reference/                       # datasheet PDF (gitignored, like sibling)
│   ├── pyproject.toml                   # name "emc2101", deps: smbus2 (Linux marker only)
│   ├── README.md                        # quick start both platforms, examples table, repo layout, dev gates
│   ├── LICENSE                          # LGPL-2.1-or-later (proposed — see §7)
│   └── CHANGELOG.md
├── research/                            # this research (kept at project top level per instruction)
└── EMC2101_datasheet.pdf
```

Notes vs sibling: `research/` sits outside the package dir (top-level, as instructed); everything
else maps 1:1 onto the `FanSpeedController` layout (`max31760/` ↔ `emc2101/`, same support dirs).
The one new module is `_persist.py`.

## 2. Module responsibilities & dependency graph

```
_regs.py  (leaf — no intra-package imports)
   ↓
_tables.py  (imports _regs)
   ↓
_core.py  (imports _regs, _tables; owns ALL protocol knowledge: interlock ordering, PROG dance,
           TCRIT unlock, retry ladder, quantization math, error model)
   ↑                              ↑
_transport_mp.py          _persist.py  (imports _regs/_tables for decode/encode; talks to _core
_transport_cp.py          ONLY via injected read/write callbacks — never opens files itself)
   ↑
mp.py / cp.py facades     (bind transport + default config path + optional ctor load; mirror __all__)
```

Rules (inherited from sibling):
- `_core` is platform-neutral: no third-party imports, no CPython-only syntax, annotations
  restricted to bare builtins (enforced by `lint_subset.py`).
- Transports are duck-typed objects; `_core` depends only on the contract below.
- Facades add nothing but binding + `close()` semantics + `__all__` mirroring.

## 3. Transport contract (adapted — single byte)

```python
class TransportMP / TransportCP:
    read_byte(reg) -> int          # one transaction; raises OSError after retry ladder
    write_byte(reg, value) -> None # one transaction; same error model
    probe() -> bool                # address ACK via harmless RO read (reg 0x00)
    scan() -> iterable[int]        # 7-bit addresses present
    delay_ms(ms) -> None
    close()                        # CP: release bus if opened; MP: no-op
```

Divergence from sibling (documented in 02 doc §Transport): no `burst_*` methods. The core exposes
`read_reg(reg, n=1)` / `write_reg(reg, buf)` as raw-tier verbs implemented as sequential
single-byte transactions over consecutive addresses, purely for dump/debug ergonomics — internal
API paths never rely on them crossing interlock boundaries. Retry ladder: escalating backoff
(sibling-style `(10, 30, 60, 100, 200, 400)` ms baseline, retuned in P0; no EEPROM-busy waits exist
for this chip).

## 4. Persistence seam design

- **Facade layer** owns paths: `DEFAULT_CONFIG_PATH` class constant per facade
  (MP: `/emc2101.json`; CP: `~/emc2101.json` expanded). Ctor kwarg `config_file=` overrides.
- **`_persist.py`** is FS-agnostic: pure functions `encode(state_dict) -> str`,
  `decode(text) -> state_dict` (with validation), plus `collect_state(read_byte) -> dict` and
  `apply_state(write_byte, state, *, strict=False) -> report` implementing the ordering rules
  (03 doc §5.4). File I/O (open/read/write/rename) happens in small glue inside `_core`'s
  `save_config`/`load_config` so the testable logic stays pure and mockable.
- **MicroPython note:** `json` module is built-in; `os.rename` exists on rp2/esp32 ports (atomic
  swap). Fallback where rename is unavailable: write `<path>.tmp`, then remove+rename with a
  documented non-atomic caveat. Spec phase picks the exact primitive per port.
- **Strict mode** (optional flag on `load_config`): post-apply read-back verification with diff
  report (kvasir practice, 04 doc §2). Default off in v1? — open item; recommendation: default ON
  for `load_config` (cheap: ~25 extra reads ≈ 1–2 ms), since silent partial application is the
  failure mode this whole feature exists to prevent.

## 5. Testing strategy (mirrors sibling gates)

| Gate | Sibling precedent | EMC2101 adaptation |
|---|---|---|
| Mock-backed unit suite (`unittest discover`) | 134 tests at v0.1.1 freeze | Expect comparable breadth; **transaction-sequence assertions** are the star: exact reg/order for interlocks (Q2), PROG dance (Q4), TCRIT unlock (Q5), status-read side effects (Q3) |
| `tools/api_coverage.py` | every public member exercised | Same; includes persistence verbs |
| `tests/lint_subset.py` | MicroPython-subset compliance | Same rule set (bare-builtin annotations, no f-string features beyond MP support, etc.) |
| `python -m compileall` | syntax gate | Same |
| Parity test | `TestApiParity`: mp/cp `__all__` identical | Same |
| Persist tests | — (new) | Round-trip stability, version rejection, ID-mismatch refusal, corrupt-file zero-register-touch assertion, TCRIT skip-case, atomic-write simulation |
| Hardware E2E | 12-section matrix, board-aware pins, self-restoring | Matrix sized to the smaller API (~10 sections incl. cold-boot-with-profile scenario); results table in PLANS later |

Mock transport records every `(op, reg, value)` tuple; tests assert sequences, not just outcomes —
this is how interlock ordering gets regression-proofed without hardware.

## 6. Examples & docs plan

Examples follow the sibling's board-aware pattern (`sys.platform` pin auto-select: `rp2` → GP0/GP1,
`esp32` → GPIO41/42, Linux → bus 1) and self-restoration (leave device at a known-safe state:
manual mode, moderate duty, limits restored). Docs cover: wiring (STEMMA QT/Qwiic + raw I²C),
per-platform install, quickstart (both facades), complete API reference, error model, and the
operational-notes set (boot window, TCRIT lifecycle, DAC hardware caveats, ALERT/TACH trade-offs,
ARA explanation, force-register testing technique).

## 7. Licensing & versioning

- **License: LGPL-2.1-or-later** (proposed). Rationale: consistency with the sibling driver within
  the same project family; clean-room authorship means no copyleft contamination concerns; the
  Adafruit reference is MIT (compatible either way). User can veto at spec time.
- **Versioning:** start `0.1.0-beta` (sibling reached 0.1.1 through the same gate process).
- **pyproject:** `name = "emc2101"`, `requires-python >= 3.10` (host-side tooling), dependency
  `smbus2>=0.4.2; platform_system == 'Linux'` (marker keeps MicroPython installs dependency-free).

## 8. Decisions carried from the interview (locked)

1. Plain EMC2101 target; Adafruit breakout primary hardware; must work on equivalent boards.
2. Platforms: Pico W (MP v1.29.0), ESP32-S3 (MP v1.29.0), Pi 3A+ (CPython). No WSL target.
3. Clean-room implementation; Adafruit lib mined for knowledge only.
4. Option-B parity policy (common core, honest edges).
5. Persistence: iii + default path — `save_config(path=None)`/`load_config(path=None)`,
   `config_path` attribute, `config_file=` ctor kwarg; whole-config-only v1; JSON format,
   driver-written, human-readable.
6. Boot window accepted (fan-floor behavior observed); document prominently.
7. Research deliverables: feasibility/phases, parity mapping, persistence opinion, reference notes,
   architecture sketch — all in `research/`, no code.
8. Downstream: findings roll into `PLANS.md` when the user triggers it (post-research).

## 9. Open items for the spec phase

| # | Item | Recommendation (default if unchallenged) |
|---|---|---|
| O1 | Diode-fault exception typing (typed OSError subclass vs ValueError) | Typed `OSError` subclass (`DiodeFaultError`) — it's a hardware condition, not a bad argument |
| O2 | Constructor-kwarg failure behavior (raise vs construct-with-warning on invalid file) | Raise before any register write (03 doc §5.2) |
| O3 | Strict read-back verification default in `load_config` | Default ON (cheap insurance against silent partial apply) |
| O4 | Default config paths per platform | MP `/emc2101.json`; CP `~/emc2101.json` |
| O5 | DAC mode scope in v1 | Include registers/property, mark experimental in docs (hardware-dependent) |
| O6 | `rpm()` behavior on `FFFFh`/zero count | Return 0.0 (stopped/unmeasurable) — matches sibling's zero-count convention |
| O7 | LUT context-manager sugar (`with dev.lut:`) | Defer (v1 uses whole-list setter) |
| O8 | Raw-tier `read_reg(n>1)` semantics | Sequential single-byte over consecutive addresses, debug-only positioning |
| O9 | Package/dir naming confirmation (`emc2101/` under `EMC2101_Fan_Speed_controller/`) | As sketched (§1) |
