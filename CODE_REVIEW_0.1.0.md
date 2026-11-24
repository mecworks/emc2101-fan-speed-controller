# Code Review — emc2101 v0.1.0 (M8 independent review)

**Scope:** full tree at `EMC2101_Fan_Speed_controller` (HEAD `401615b`, working tree clean).
**Method:** adversarial pass over every source, test, doc, example, script index, and research
document; every register constant, formula, and bit position re-derived against
`research/emc2101-register-map.md`; git history mined for plan-vs-code drift; all four quality
gates executed on the final tree (results in §10).
**Constraint honored:** this file is the only artifact produced; no existing file was modified.

## 1. Verdict

The driver core is **sound**: protocol logic, interlock ordering, the PROG dance, TCRIT unlock
handling, fixed-point math, and the persistence layer all match the datasheet ground truth and
the live-silicon observations recorded in `research/emc2101-register-map.md` §16. The test
harness is unusually strong (267 mock-backed tests, 100 % public-member coverage, an
eleven-section hardware E2E matrix passed on all three benches).

The defects concentrate in the **documentation/planning layer**, which describes an error model
and a persistence report shape that the code does not implement. Nothing blocks the *code*;
everything below marked FIX should be reconciled before M9 publication.

| Severity | Count | IDs |
|---|---|---|
| HIGH | 1 | F-01 |
| MEDIUM | 2 | F-02, F-03 |
| LOW | 6 | F-04 … F-09 |
| NOTE | 11 | F-10 … F-20 |

Severity legend: **HIGH** = user-facing misinformation, must fix before publish ·
**MEDIUM** = should fix before publish · **LOW** = fix recommended · **NOTE** = accepted /
informational.

---

## 2. Findings

### F-01 — HIGH — Phantom persistence exception hierarchy (docs + plan vs code)

**Location:** `emc2101/_persist.py` (absent), `emc2101/_faults.py` (absent); claimed in
`PLANS.md` (M4 Progress entry), `CONTRIBUTING.md` (Error-model bullet), `docs/api-reference.md`
(persistence section), `docs/persistence.md` (Validation policy table),
`docs/operational-notes.md` (Retry ladder & error model table), `docs/README.md` (Errors rule).

Six documents assert that persistence raises typed exceptions:
`ConfigFormatError` / `ConfigValidationError` (`ValueError` subclasses) and `ConfigApplyError`
(`OSError` subclass). **No such class exists anywhere in the tree.** Git evidence: the M4 commit
(`bd61cb9`) touches no module defining them (`git show bd61cb9 --stat`: `_faults.py` not among
changed files); `git log --all -S ConfigFormatError` shows the names appear only in the PLANS.md
progress text (`bd61cb9`) and the M5 docs commit (`4f11cff`). The M4 plan entry claims "New
exceptions …" — they were planned, never implemented, and the M5 docs propagated the fiction.

Actual behavior (self-consistent between code and tests): plain `ValueError` for decode /
validation / product-ID mismatch / strict read-back diff (`emc2101/_persist.py::decode`,
`emc2101/_core.py::load_config`), plain `OSError` for file I/O (`_read_text`, `_atomic_write`).
`tests/test_persist.py` asserts exactly this model (10 × `assertRaises(ValueError)`,
1 × `assertRaises(OSError)`).

**Disposition: FIX.** Two coherent options:
(a) *implement* the three classes (define in `_faults.py` or `_persist.py`, re-raise from
`decode()`/`apply_state()`, export through both facades' `__all__`, extend the
`test_public_surface.py` pin and `tools/api_coverage.py`), or
(b) *rewrite* the six doc sites to describe the real `ValueError`/`OSError` model and amend the
M4 PLANS entry with an erratum. Option (a) is preferable: the docs already promise typed errors,
and callers distinguishing "bad file" from "bus failed mid-apply" is a genuine need. Either way,
re-run all four gates.

### F-02 — MEDIUM — `persistence.md` invents report keys and misstates `save_config`'s return

**Location:** `docs/persistence.md` ("The two methods", "Report" paragraph, Validation policy
table, TCRIT special-case bullets) vs `emc2101/_core.py::save_config` / `::load_config`,
`emc2101/_persist.py::apply_state`.

The doc says both methods return "a dict with `written` (register/value pairs written),
`skipped` (reasons, e.g. TCRIT skip), `warnings` … and — when `strict=True` — `diff`". Reality:

- `save_config()` returns **the effective path string**, not a report.
- `load_config()` / `apply_state()` return `{"applied", "warnings", "diff"}` — there is no
  `written` key and no `skipped` key. TCRIT skips land in `warnings`
  (`_persist.py:684`: `"tcrit restore skipped: stored %d C but the device holds …"`).
- The `load_config` docstring itself documents the correct shape (`{"applied", "warnings",
  "diff"}`), so the standalone doc page is the outlier.

**Disposition: FIX** — rewrite the Report paragraph, the validation-policy table rows that name
`ConfigFormatError`/`ConfigValidationError`/`ConfigApplyError` (see F-01), and the TCRIT bullets
to reference `warnings`.

### F-03 — MEDIUM — `persistence.md` POR example contradicts the power-on default

**Location:** `docs/persistence.md` (Schema v1 JSON example) vs `research/emc2101-register-map.md`
§14, `emc2101/_tables.py::POR_DEFAULTS`, `tests/test_helpers.py::PorDefaultsTestCase`.

The example claims to "reflect the factory POR decode" but carries `"manual": false`. Ground
truth: FAN_CFG POR = `0x20` ⇒ PROG = 1 ⇒ **manual mode at power-on** (register map §14: "Mode:
Manual (PROG=1)"; live bench reads `FAN_CFG 0x20` on all three legs; `PorDefaultsTestCase` pins
`REG_FAN_CFG: 0x20`). Every other field in the example was cross-checked and is correct
(`pwm_f: 23` / `pwm_div: 1` / `pwm_freq_hz ≈ 7826.09`, `ideality_index: 18` = `0x12`,
`tcrit_hysteresis_c: 10`, spin-up 100 %/3.2 s/fast-tach, LUT uniformly 127 °C/100 %, alert mask
INT-only unmasked).

**Disposition: FIX** — set `"manual": true` in the example.

### F-04 — LOW — `tcrit_c` "reports via return value" is impossible and unimplemented

**Location:** `docs/api-reference.md` (tcrit_c row), `docs/operational-notes.md` (TCRIT
lifecycle) vs `emc2101/_core.py:377` (`@tcrit_c.setter`).

Both docs say the setter "reports what happened" / "reports via return value". A Python property
setter's return value is discarded by assignment semantics, and the implementation returns
nothing: it is silent best-effort (no-op when equal; otherwise arm TCRITOVRD + write), with the
docstring directing the caller to verify by reading back.

**Disposition: FIX** — reword both docs to "silent best-effort; if the one-time unlock was
already consumed since the last power cycle the write does not take effect — verify by reading
back".

### F-05 — LOW — Stale test count in CHANGELOG

**Location:** `CHANGELOG.md` ("mock-backed unit suite (261 tests)") vs final gated state.

Suite grew 261 → 264 (D35 regression tests, `21fb5fe`) → 267 (D36, `94252f1`). Verified: 267
tests run and pass on the current tree (§10).

**Disposition: FIX** — update to 267 at release tagging.

### F-06 — LOW — Host Python version inconsistency

**Location:** `pyproject.toml` (`requires-python = ">=3.10"`) vs `CONTRIBUTING.md`
("Python ≥ 3.9").

The code uses nothing newer than 3.8-era features (no f-strings, no walrus, no annotations), so
either bound works; the two statements simply disagree.

**Disposition: FIX** — pick one (recommend aligning CONTRIBUTING to `>=3.10` to match packaging).

### F-07 — LOW — Ineffective `set_duty_pct(0)` calls in the E2E suite

**Location:** `examples/e2e_hardware_test.py`, `sec_manual_duty_pwm` (S3) and `sec_tach_rpm`
(S5), final two statements: `dev.manual = False` then `dev.set_duty_pct(0)`.

Per `research/emc2101-register-map.md` §16.2 (bench-confirmed), writes to Fan Setting (`4Ch`)
while PROG = 0 are **silently dropped**. These statements therefore have no effect; the chip
correctly stays in LUT mode, but the code implies a restore that never happens.

**Disposition: FIX** — delete the dead statements (or replace with a comment citing §16.2).

### F-08 — LOW — `lut_set_index` performs the PROG dance twice

**Location:** `emc2101/_core.py::lut_set_index`.

Each of the two byte writes (T byte, S byte) is wrapped in its own `_with_prog_writable(...)`
call. When the chip is in LUT mode this toggles FAN_CFG twice (four extra transactions) and
leaves a transient window between the dances in which the fan-domain registers are RO again.
Functionally correct (each dance restores properly); wasteful.

**Disposition: FIX (cheap)** — combine both writes into a single `_with_prog_writable` callback.

### F-09 — LOW — Demo "POR-equivalent" claim is inaccurate

**Location:** `examples/pico_demo.py` / `esp32_demo.py` / `rpi_demo.py` (final print: "calm
state restored: manual drive at 0 % (POR-equivalent)").

After the demo flow the chip is *not* at POR: ALT_TCH = 1 (TACH input, ALERT output disabled),
PWM_F solved to 7 (25 kHz grid), spin-up repaired. Only the fan drive level matches POR.
Related footgun in the same scripts: `save_config()` runs **before** `set_duty_pct(0)`, so the
saved profile captures the last sweep step (100 % duty); a reboot with `config_file=` auto-load
would start the fan at full drive until software intervenes.

**Disposition: FIX** — reorder (restore calm state first, then `save_config()`) or add an
explicit warning; reword the print to "fan at floor speed".

### F-10 — NOTE — ARA `0x0C` scan-footprint statement overgeneralized

**Location:** `docs/operational-notes.md` (ARA general call section).

"Bench-confirmed: a bus scan reports `0x0C` alongside `0x4C`" was observed on the Pico W bench
while the external-diode channel was OPEN (FAULT latched ⇒ ALERT asserted ⇒ ARA answers). The
RPi 3A+ leg (fresh POR, no alarms) scanned `[0x4c]` only — consistent with datasheet §4.6/§5.4.2
(the chip answers ARA only when configured as interrupt AND the pin is asserted). Presence of
`0x0C` is therefore **state-dependent**, not unconditional.

**Disposition: NOTE** — tighten the wording: "`0x0C` appears in scans while the ARA conditions
hold (interrupt mode + ALERT asserted); its absence does not indicate a fault."

### F-11 — NOTE — Diode orientation instruction lacks a research-trail citation

**Location:** `docs/wiring.md` ("Recommended bench loadout": "anode → DN, cathode → DP, per the
datasheet's diode orientation").

No supporting citation exists in `research/` (zero hits for "orientation"/"2N3906"); the
datasheet text cache referenced by `research/README.md` is not present in the tree. The stated
orientation is internally consistent with the standard PNP ratio-method connection, but the
repo's own evidence chain does not verify it.

**Disposition: NOTE** — add the datasheet figure/section citation to the research trail, or
soften the doc wording to "connect per the datasheet's external-diode diagram (verify before
publishing)".

### F-12 — NOTE — CP transport scan probe shape at the ARA address is untested under alarm

**Location:** `emc2101/_transport_cp.py:24` (`_SCAN_MIN/_SCAN_MAX`), `TransportCP.scan`.

CP `scan()` probes each candidate `0x03..0x77` with a full Write Byte + Read Byte
(`read_byte_data(a, 0x00)`), whereas the MP transport delegates to the port-native
`machine.I2C.scan()`. Probing the ARA address `0x0C` with a register-addressed Write Byte is not
a defined SMBus sequence; empirically benign on the RPi leg (chip healthy afterwards, ARA not
armed at scan time), but untested with an active alarm. Given the M1 finding that ill-formed
transactions desynchronize this chip's interface, the residual risk is small but nonzero.

**Disposition: NOTE** — exercise CP `scan()` once against an alarmed chip on the next bench
session; if any anomaly appears, restrict the CP scan range or document the caveat.

### F-13 — NOTE — Constructor auto-load swallows all `OSError`, not just missing file

**Location:** `emc2101/_core.py::__init__` (auto-load block).

`except OSError: pass` treats permission errors and unreadable directories as first-boot
silence, slightly broader than the documented "missing file = silent no-op" (D14). Acceptable
for the threat model (a config the host cannot read is indistinguishable from none at boot),
but worth knowing.

**Disposition: ACCEPT** (optionally log via `sys.print_exception` on CPython).

### F-14 — NOTE — PWM solver is an exhaustive search on MicroPython

**Location:** `emc2101/_core.py::_solve_pwm`.

≈ 2 × 31 × (1 + 255) ≈ 16 k frequency evaluations per `pwm_freq_hz` assignment; expect
~0.1–0.5 s on RP2040-class hardware. Fine for a rarely-called setter; would hurt if ever used in
a loop.

**Disposition: ACCEPT** (document latency if it ever matters).

### F-15 — NOTE — Magic number for POR spin-time encoding

**Location:** `emc2101/_core.py::spin_up_enabled` setter (`reg |= 0x07`) and
`configure_4wire_fan` (`SU_FAST_TACH | SU_DRIVE_100 | 0x07`).

`0x07` is the SPIN_TIME encoding for the POR default (3.2 s). Named constants exist for the
drive field (`SU_DRIVE_*`) but not for this time encoding.

**Disposition: NOTE** — introduce `SU_SPIN_TIME_POR = 0x07` in `_regs.py` and use it in both
spots.

### F-16 — NOTE — CI matrix includes Python 3.15

**Location:** `.github/workflows/ci.yml` (matrix `["3.11"…"3.15"]`).

As of the review date 3.15 is at most days old on runner images; if `setup-python` cannot
resolve it, CI fails spuriously.

**Disposition: NOTE** — confirm the workflow ran green post-publish; drop `3.15` if flaky.

### F-17 — NOTE — Three near-duplicate demo files

**Location:** `examples/pico_demo.py`, `examples/esp32_demo.py`, `examples/rpi_demo.py`.

Bodies are identical apart from docstrings (deliberate: runtime platform detection, filename as
conventional entry point — documented in `examples/README.md`). Triple maintenance burden for
any future demo change (F-09's footgun lives in three copies).

**Disposition: ACCEPT** (convention is documented); consider one canonical body + thin wrappers
if the demo evolves.

### F-18 — NOTE — `set_ideality_factor` tie-break not pinned by a test

**Location:** `emc2101/_core.py::set_ideality_factor`.

Nearest-match uses strict `<`, so equidistant factors resolve to the lower table index.
Deterministic, but no test pins the tie case.

**Disposition: NOTE** — add one subTest with an equidistant target.

### F-19 — NOTE — Raw-tier `read_reg`/`write_reg` semantics

**Location:** `emc2101/_core.py::read_reg` / `::write_reg`.

`(reg + i) & 0xFF` wraps past `0xFF`; multi-byte spans cross interlock boundaries at the caller's
risk. Both are documented as debug/dump ergonomics and the core API never uses them across
interlocks.

**Disposition: ACCEPT** (documented).

### F-20 — NOTE — `dis_to_enabled` double-negative naming

**Location:** `emc2101/_core.py::dis_to_enabled`.

`True` means the SMBus timeout watchdog is *disabled*. Faithful to the register bit name
(DIS_TO) and documented in the docstring; mildly awkward as an English adjective.

**Disposition: ACCEPT** (renaming would break the pinned surface for marginal gain).

---

## 3. Correctness vs. the research register map

Every constant, formula, and bit position in `emc2101/_regs.py` and `emc2101/_tables.py` was
cross-checked against `research/emc2101-register-map.md`. **No discrepancies found.**

| Item | Source fact | Driver | Status |
|---|---|---|---|
| SMBus address | `0x4C` (§4.7) | `ADDR_FIXED` | ✓ |
| ARA general call | `0x06`, on-wire `0x0C`/`0x0D` (§4.6) | `ARA_GENERAL_CALL` | ✓ |
| Identity trio | `0x16`/`0x28`, `0x5D`, `0x01` (§6.24–6.26) | `PRODUCT_ID_PLAIN/R`, `MANUF_ID_SMSC`, `REVISION_EXPECTED` | ✓ |
| Retry ladder | rung 2 (30 ms) > ~25 ms TIMEOUT (§4.8) | `RETRY_DELAYS_MS = (10, 30, 60, 100, 200, 400)` | ✓ |
| Register addresses | §2 table (incl. dual aliases) | all `REG_*` constants | ✓ (pinned by `test_public_surface.EXPECTED_VALUES`) |
| Status bits | §3 | `ST_*` | ✓ |
| Config bits | §4 | `CFG_*` | ✓ |
| Alert mask | default `0xA4`, reserved bits 7/5/2 preserved (§5) | `AMSK_DEFINED = 0x5B`, RMW in `_core.alert_mask` setter | ✓ |
| FanCfg bits | §6 (PROG=1 ⇒ manual; POR `0x20`) | `FCFG_*` | ✓ (D34 polarity fix verified in tests) |
| Spin-up fields | §7 (POR `0x3F`: fast-tach, 100 %, 3.2 s) | `SU_*`, `SPINUP_TIMES_S` | ✓ |
| PWM math | eq. [5]/[6]: $f = \frac{360\,\text{kHz}}{2\cdot\mathrm{PWM\_F}\cdot\mathrm{PWM\_D}}$, duty $\frac{S}{2\cdot\mathrm{PWM\_F}}$ | `_pwm_freq_hz`, `duty_pct_to_setting` | ✓ (solver pinned by hand-computed cases incl. the 30 Hz max-resolution path) |
| Conversion rate | Table 6.6 (default idx 8 = 16/s; 10–15 ⇒ 32/s) | `CONV_RATES_PER_S`, `conv_rate_encode` (slower tie-break) | ✓ |
| Filter encodings | duplicated Level-1 folded (§10) | `FLT_LEVEL_1_ALT` decode, canonical encode | ✓ |
| Temp formats | 11-bit ext / 8-bit int, −64…+127.875 guaranteed (§11) | `ext_/int_temp_to_raw` enforce the tighter bounds | ✓ |
| Fault sentinels | open ⇒ +127.0 raw `0x3F8` (FAULT set); short ⇒ +127.875 raw `0x3FF` (FAULT clear) (§11) | `SENTINEL_OPEN_RAW/SHORT_RAW`, `DiodeFaultError` in `remote_temp_c` | ✓ |
| Interlocks | ext temp MSB-first `01h→10h`; TACH LSB-first `46h→47h` (§12) | `remote_temp_c`, `rpm()` order, transaction-sequence asserts in tests | ✓ |
| RPM formula | $n = \frac{5{,}400{,}000}{\text{TACH\_COUNT}}$ (eq. [3]) | `rpm_from_count`, `count_from_rpm` | ✓ (validated live ±10 %) |
| POR defaults | §14 table | `POR_DEFAULTS` spot-checked by `PorDefaultsTestCase` | ✓ |
| Live quirks | §16.1–16.5 (mirror, drop, settle) | `_persist` collect/apply dances, `SETTLE_MS = 100`, E2E/smoke safety nets | ✓ |

Protocol contract (single-byte transactions, no pointer auto-increment, bare Send/Receive
Byte forbidden) is enforced by construction in both transports and documented in their
docstrings.

## 4. API parity (`mp` vs `cp`)

- `__all__` lists mirror exactly — enforced by `tests/test_api_parity.py` and the
  `test_public_surface.py` drift guard (`exported == pinned` set equality).
- Both facades subclass the same `emc2101._core.EMC2101` (pinned by
  `test_device_classes_share_a_common_base`); all protocol behavior is shared code.
- Constructor surfaces aligned: `mp.EMC2101(i2c, addr=…, config_file=…)`,
  `cp.EMC2101(bus=…, handle=…, addr=…, config_file=…)`; default config paths
  `/emc2101.json` (MP) vs `~/emc2101.json` (CP) covered by `MpFacadeTestCase`/`CpFacadeTestCase`.
- Transport contracts identical (`read_byte`/`write_byte`/`probe`/`scan`/`delay_ms`/`close`),
  retry ladder shared via `RETRY_DELAYS_MS`; adopted-handle semantics (CP `handle=` ⇒
  `close()` does not release) documented.
- **No parity gaps found.** The only behavioral divergence is `scan()` mechanics (F-12, NOTE).

## 5. Test coverage

- 267 unit tests, all passing; `tools/api_coverage.py`: **100 % (203/203 public members
  exercised)**; `test_public_surface.py` pins every exported constant to its datasheet value on
  both facades and freezes the class surface (drift guards in both directions).
- Transaction-order assertions guard both interlocks, the PROG dance (including restore on
  injected mid-write failure), TCRIT unlock ordering, and the D35/D36 silicon quirks
  (`MirrorTransport` models the stale read-out window).
- Hardware E2E: eleven-section matrix covering every public class member, passed on all three
  benches (Pico W 3× phase A→B, ESP32-S3 2×, RPi 3A+ 2× fresh-instance approximation), plus
  self-restoring smoke tests.
- Gaps: only NOTE-level (F-18 tie-break pin; F-12 alarmed-chip CP scan). No public member or
  documented branch lacks a test.

## 6. Docs accuracy

Findings F-01 … F-04, F-09, F-10, F-11 above. Beyond those, the docs are notably good:
destructive-read side effects are flagged at every relevant call site, the pull-up diagnostic
rule is bench-evidenced, the DAC-mode jumper caveat and Pi-header power-rail correction are
present, and the M5 entry records two doc-vs-code drifts caught and fixed pre-commit.

## 7. Clean-room compliance

**Compliant.** No third-party driver code in the package: the layered design
(`_regs` → `_tables` → `_core` → facades/transports) is original, and the only borrowed
material is conceptual and explicitly attributed in the research trail (single-byte contract
observation, Adafruit LSB-before-MSB bug noted as a contrast, pull-up diagnostic rule).
`scripts/rpi/bus_recovery.py` is adapted from the user's own MAX31760 sibling project and
discloses the provenance in its header (line 18) and in `scripts/README.md` / commit `d332b61`.
Vendor PDFs remain gitignored by explicit filename (D28); `git ls-files` shows nothing under
`reference/`.

## 8. Effective-Python pass (`slatkin-effective-python` skill, all 90 items)

**Method:** every one of the book's 90 items was checked against the tree using the skill's
chapter files (ch05 classes/interfaces, ch06 metaclasses/attributes, ch09 testing/debugging,
ch10 collaboration) and its `patterns.md` severity-rated anti-pattern catalog (SEV-1 … SEV-4).
Where an item could be settled mechanically it was: AST scans over `emc2101/*.py` +
`tests/*.py` for mutable defaults and bare excepts (**none found**), property-getter purity in
`_core.py` (zero `write_byte` calls inside any `@property` getter body — **getters are pure**),
and `saved_at_utc` provenance (`_persist.py:180`: `t = time.gmtime()`; key emitted at
`_persist.py:492`). Expanded 2026-11-23, replacing the earlier selected-items pass.

**Bottom line: strong.** Most of the 90 items are satisfied outright or N/A under the
MicroPython constraint; the deviations are deliberate, documented, and largely pinned by the
lint gate. One substantive miss — Item 87 (root exception hierarchy) — is exactly the F-01
HIGH finding in §2.

### 8.1 Items scoring strong

| Item | Practice | Evidence |
|---|---|---|
| 44 — plain attributes first | Instance state lives in external silicon, not attributes; the escalation ladder stops at rung 2 (no descriptors, no dunder hooks, no metaclass) | `_core.py`; AST scan: no `write_byte` in any getter |
| 76–79 — testing | Fakes-not-mocks at the transport boundary; transaction-order assertions pin the hardware protocol contract (externally observable), so the "over-tight test" anti-pattern does not apply | `MirrorTransport`, sequence asserts in `tests/` |
| 84 — docstrings | Docstrings match behavior; the "documenting lies" pitfall hit the standalone `docs/` pages (F-01 … F-04), not the docstrings themselves | `save_config`/`load_config` docstrings carry the *correct* report shape |
| 85 — `__all__` | Curated on both facades, mirrored by `test_api_parity.py`, pinned by `test_public_surface.py` with bidirectional drift guards | facades + tests |
| 88 — circular imports | Exemplary: leaf-module refactor (`_regs.py` imports nothing); deferred imports only where structurally forced, each with docstring justification | §9 import graph |

### 8.2 Justified deviations

- **Item 90 (type annotations):** deliberately absent for MicroPython portability; the lint
  gate (`tests/lint_subset.py`) enforces the allowed subset, and docstrings plus the pinned
  public surface compensate.
- **`%`-formatting over f-strings:** not a violation — a deliberate MicroPython-subset
  contract, applied consistently and enforced by `tests/lint_subset.py`.
- **`except BaseException` in `_atomic_write`:** justified — temp-file cleanup must survive
  `KeyboardInterrupt`/`SystemExit`; acceptable.
- **No `dataclass`/`typing` reliance, no walrus operators;** properties used uniformly for
  state, verbs for actions and destructive reads.

### 8.3 Single substantive shortfall

- **Item 87 (root exception hierarchy)** = **F-01 (HIGH).** The docs promise a typed
  `ConfigFormatError`/`ConfigValidationError`/`ConfigApplyError` hierarchy rooted in
  `ValueError`/`OSError`; the code raises plain `ValueError`/`OSError` and defines no such
  classes. This is the only item where the practice is genuinely missing rather than
  consciously traded off.

### 8.4 Anti-pattern catalog scan (`patterns.md`, SEV-1 … SEV-4)

| Tier | Pattern | Result |
|---|---|---|
| SEV-1 | Untyped exception leakage | **Present** — F-01: docs promise typed errors, code leaks plain `ValueError`/`OSError` |
| SEV-1 | Mutable-default aliasing | Absent — AST scan over `emc2101/*.py` + `tests/*.py` clean |
| SEV-1 | Pickling hazards | N/A — persistence is the JSON v1 schema, no `pickle` anywhere |
| SEV-1 | Wildname clobbering | Absent |
| SEV-2 | Cyclic imports | None — §9 graph acyclic |
| SEV-2 | asyncio / GIL races | None — single-threaded, no `asyncio` |
| SEV-2 | Naive-datetime hazard | None — `saved_at_utc` derives from `time.gmtime()` (UTC), informational only |
| SEV-3 | Material algorithmic cost | None material; one noted cost: exhaustive PWM solver (F-14) |
| SEV-4 | Documentation drift | Two partials: F-01 … F-04 (docs describe an unimplemented error/report model) and F-06 (version bound `≥3.9` vs `≥3.10`) |

Strong practices worth keeping beyond the items above: `dir()`-based public-surface pinning,
drift-guard frozensets, table-driven enum folding (duplicated filter encoding), nearest-match
helpers returning the achieved value. Actionable nits surfaced by this pass: F-08 (double PROG
dance), F-15 (magic `0x07`), F-18 (unpinned tie-break).

## 9. Circular-import check

Import graph (verified by inspection of every import statement):

```
_regs.py (leaf, no imports)
   ↑
_tables.py            _faults.py (leaf)
   ↑                    ↑
_core.py ───────────────┘
   ↑
_transport_mp.py / _transport_cp.py (imported only by facades)
   ↑
mp.py / cp.py
```

Acyclic. Deferred imports are intentional and documented: `import os` inside `_atomic_write`
(keeps `os` out of module scope for the lint/portability story), `import smbus2`/`import smbus`
inside `_open_smbus` (lazy, testable without the dependency), `import machine` inside
platform-gated branches of the examples. **No cycles, no hidden coupling.**

## 10. Quality-gate verification (executed on the reviewed tree)

Run with `PYTHONDONTWRITEBYTECODE=1` (bytecode caches left untouched):

| Gate | Result |
|---|---|
| `python -m unittest discover -s tests` | **OK — 267 tests** (0.07 s) |
| `python tools/api_coverage.py` | **100 % (203/203 public members)** |
| `python tests/lint_subset.py` | **PASS** — all 8 shared modules + 5 examples CLEAN |
| Syntax check (`ast.parse` over `emc2101/*.py` + `examples/*.py`) | **OK — 15 files** |

`git status --porcelain`: clean. `examples/__pycache__`, `emc2101/__pycache__`: gitignored.

## 11. Prioritized pre-M9 action list

1. **F-01** — reconcile the persistence error model (implement the three exception classes or
   rewrite six doc sites + amend the M4 PLANS entry). *(blocking)*
2. **F-02, F-03** — fix `persistence.md` report shape and the POR example. *(blocking)*
3. **F-04, F-05, F-06, F-07, F-09** — remaining LOW fixes (tcrit_c wording, changelog count,
   Python bound, dead E2E statements, demo save-order/comment).
4. **F-08, F-15, F-18** — cheap code polish (single PROG dance, named spin-time constant,
   tie-break test).
5. **F-10 … F-12, F-14, F-16, F-17, F-19, F-20** — NOTEs: accept as-is or fold into the same
   fix commit; F-12 gets a one-off bench verification.

Every FIX item requires re-running the four gates (§10) before M9 proceeds, per the M8 closure
criterion in `PLANS.md`.
