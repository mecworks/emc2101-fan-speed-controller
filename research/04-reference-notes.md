# 04 — Reference Notes (implementations, datasheet ambiguities, markings)

Purpose: knowledge mined from external sources for the clean-room implementation. Per project
policy these are **reference only** — nothing is copied into our code (clean-room preference; the
Adafruit lib is MIT-licensed so copying would be legally fine, but the policy stands).

## 1. Adafruit CircuitPython `adafruit_emc2101` (primary reference)

Repo: `adafruit/Adafruit_CircuitPython_EMC2101` (MIT). Board: Adafruit product 4808
("EMC2101 I2C PC Fan Controller and Temperature Sensor [STEMMA QT / Qwiic]").
Files studied: `__init__.py` (base class), `emc2101_regs.py`, `emc2101_lut.py` (LUT extension).

### 1.1 Facts confirmed by their code (cross-checked against datasheet)

| Fact | Their evidence | Datasheet match |
|---|---|---|
| 7-bit address `0x4C` | `I2C_ADDR = const(0x4C)` | §4.7 (`100_1100b`) ✓ |
| "These devices don't ship with any other address" | ctor comment | consistent with fixed SMBus address ✓ |
| No multi-byte reads/writes | register-definition comment: *"the chip does not support multi-byte reads or writes"* | no block protocols in §4 ✓ (drives our transport contract) |
| RPM divisor 5,400,000 | `FAN_RPM_DIVISOR = const(5400000)` | eq. [3] + Appendix B ✓ |
| Diode-fault sentinels 0x3F8/0x3FF (post-shift) | `TEMP_FAULT_OPENCIRCUIT/SHORT` | Table 5.2 raw 0x7F8/0x7FF ✓ |
| ID trio 0x5D/0x16/0x01 (and 0x28 for -R) | `MFG_ID_SMSC`, `PART_ID_*`, `part_info` docstring | Tables 6.31–6.33 ✓ |
| Full-scale fan setting = 2×PWM_F (PWM mode) or 63 (DAC) | `_calculate_full_speed()` | eq. [6]/[4] ✓ |
| PROG dance around manual fan-setting writes | `manual_fan_speed` setter saves/restores `_fan_lut_prog` around the write | Note 6.1/§6.16 ✓ (validates our Q4 ordering rule) |
| TACH read order LSB→MSB | `fan_speed` property reads `_tach_read_lsb` then `_tach_read_msb` | §6.1 interlock ✓ (their *comment* on the constant says "Read MSB first" — wrong comment, right code) |

### 1.2 Defects / questionable choices found (do NOT replicate)

1. **External-temp read order violates the Data Read Interlock.** The property reads
   `_ext_temp_lsb` **before** `_ext_temp_msb`, while their own comment above the definitions says
   "The Lsbyte is shadow-copied when Msbyte is read, so read Msbyte first". Datasheet §6.1 requires
   MSB-first (reading `01h` refreshes the LSB shadow). Reading LSB-first can return a torn pair
   across a conversion boundary. Our driver will read `01h → 10h` and unit-test the order.
2. **Contradictory comments** on `TACH_LSB` ("Read MSB first") vs the datasheet (LSB triggers the
   snapshot). Sloppy documentation hazard; we document both interlocks explicitly.
3. **`initialize()` silently forces TACH-input mode** (`_tach_mode_enable = True` ⇒ ALT_TCH=1),
   disabling the ALERT output function with no warning to the caller. We make this an explicit,
   documented decision in presets/docstrings instead of a hidden default mutation.
4. **`forced_ext_temp` uncertainty**: annotated "one's complement?" — it is plain two's-complement
   signed byte per the temperature data format (§5.5.1); no special handling needed.
5. **Split-class design** (base `EMC2101` vs `EMC2101_LUT` subclass) motivated by RAM savings in
   CircuitPython. For our dual-platform package a single core class is cleaner (MicroPython v1.29
   RAM headroom on Pico W/ESP32-S3 is adequate; the sibling driver ships one class). Noted as a
   rejected alternative.
6. **Lazy enum imports** (`SpinupTime` etc. imported inside setters to save ~1 KB bytecode) —
   CircuitPython-specific optimization; unnecessary pattern for us, table-driven constants suffice.

### 1.3 Useful ideas worth borrowing (conceptually, not code)

- `part_info` tuple + ID check at construction (we extend: warn-on-`-R`).
- Percentage↔raw duty conversion keyed off current PWM_F (our Q7 quantization).
- Dict-like/context-manager LUT editing (`with emc.lut:` batch update) — attractive UX; our
  whole-list setter covers the need; context-manager sugar flagged as optional future polish.
- `tach_limit` expressed in RPM with sane bounds (1..15000) — our `min_rpm` convenience adopts this.

## 2. Other implementations surveyed

| Project | Lang/platform | Notable behavior | Takeaway |
|---|---|---|---|
| esphome/esphome `components/emc2101` | C++/ESP-IDF | Production sensor+fan component; standard register set; whoami via `FDh` | Confirms ESP32 deployment scale; nothing exotic in protocol use |
| bitaxeorg/ESP-Miner (+ NerdQAxePlus fork) | C/ESP32 | Writes FAN_CONFIG `0b00100011` (PROG=1 + TACH_M=11); comments mislabel bit 6 as "EN" (it is FORCE) | Mining-grade reliability usage; reinforces TACH_M=11 (forced-FFFFh below min RPM) as a sensible production choice for unattended operation |
| 256foundation/mujina-miner | Rust/ESP32 | `DEFAULT_ADDRESS 0x4C`; percentage-based fan API | Independent confirmation of address & percent semantics |
| WildernessLabs/Meadow.Foundation | C#/.NET | Full register enum; polling-sensor base | Register map cross-check (no discrepancies found) |
| kvasir-io/kvasir_devices | C++ | **"Every configuration register is read back 100 ms after it is written and again every 10 seconds: a fan controller that has quietly lost its fan setting is a thermal problem."** | Strong argument for an optional strict-mode read-back verification in `load_config` (adopted as spec option, 03 doc §5.4 step 6) |
| j9brown/poppy (OctoPrint plugin) | Python/py-smbus, Linux | `SMBus(bus).read_byte_data/write_byte_data` against the chip on a Pi-class host | Direct precedent for our CPython/smbus2 transport primitives |
| AccelerationConsortium/ac-dev-lab | MicroPython/Pico W | Port of the Adafruit lib for picow fan control | Proof of MicroPython viability on our exact target board family |
| compute-blade-community/compute-blade-agent | Go | Interface-oriented EMC2101 wrapper | Cross-language register-map consistency |

**Linux kernel:** no `emc2101` driver exists in mainline (GitHub code search over
`torvalds/linux`, zero results, 2026-11-21). Consequence: no upstream hwmon ABI or maintainer
interpretation to align with; datasheet + the above corpus is the full reference set.

## 3. Datasheet ambiguities & typos (bench items for P0)

| # | Item | Detail | Planned resolution |
|---|---|---|---|
| A1 | FILTER encoding duplication | Table 6.30 maps both `01` and `10` to "Level 1" | Encode OFF/L1/L2 as `00/01/11`; decode `10`→L1; P0 verifies filter response shape if time permits |
| A2 | Status bit 5 text | "This bit only applies to the EMC2102-R" (typo for -R) | Treat as always-0 on plain part; ignore in masks |
| A3 | Note 6.2 scope | TACH_M forced to `00` "when the PWM base clock is set at 360kHz mode" — unclear whether CLK_OVR-divided clocks count | P0 test: set CLK_OVR=1 + TACH_M=01, observe sub-minimum-RPM readings |
| A4 | POLARITY default paragraph | Mixes plain-part and -R pull-up behavior in one paragraph | Plain part: software-controlled, default `0` (confirmed by Table 6.18 default `20h`) |
| A5 | TCRIT unlock lifecycle | "can only be changed once. To adjust TCRIT again, a power cycle is required" — whether the unlock bit auto-resets after the change is unspecified | P0 experiment; driver conservatively assumes bit stays set until power cycle |
| A6 | Receive Byte / pointer increment | §4.5 wording ambiguous about pointer auto-increment | P0 empirical test (design pessimistically: no increment) |
| A7 | TACH counter clock | Table 3.2 says 90 kHz; RPM formula implies effective 36 kHz division | Use the published formula (validated by Appendix B tables); note the discrepancy |
| A8 | Spin-up FAST_TACH interaction | "ignored if ALT_TCH=0" plus SPIN_TIME=000 bypass precedence | Document precedence: bypass > fast-tach-abort > timed |

## 4. Silicon marking note

User's chip prints **"2102 OBTH"** with circled **e3**. Interpretation: likely date/lot/batch code
(e3 ≈ RoHS/lead-free + assembly-site marker; "2102" plausibly a 2021-era lot or internal code —
new stock ordered recently could still carry older die lots). The authoritative identity check is
runtime: Product ID `FDh` must read `0x16` (plain EMC2101); Manufacturer `FEh` = `0x5D`; Revision
`FFh` expected `0x01` per datasheet Rev 2.54. P0 records actual values; any deviation becomes a
datasheet-revision question (a newer Microchip revision might alter defaults — re-verify POR table
if `FFh ≠ 0x01`).

## 5. Adafruit board guide (product 4808) — pull-up jumpers (page 7)

Local copy: `../emc2101-fan-controller-and-temperature-sensor.pdf` (Adafruit
guide for product 4808; added to `reference/` 2026-11-22, gitignored). Page 7
documents two solder-jumper-controlled pull-ups on the breakout:

| Jumper | Ships | Guide wording |
|---|---|---|
| FAN | **enabled** (cut to disable) | "Cut this jumper to disable the built-in pull-up on the Fan pin when using the DAC/DC voltage output" — matches the datasheet §5.6.1 DAC caveat |
| TACH | **disabled** (solder to enable) | "Solder this jumper to enable the pull-up on the Tach pin when using the Tach pin for alerts" |

Either jumper can be bridged with solder later to re-enable after cutting.

Empirical confirmation (M1 follow-up, 2026-11-22 round 2): with the TACH
jumper unbridged (as shipped) and a fan whose open-collector tach stage has
no internal pull-up, the net floats high in TACH-input mode (ALT_TCH=1) and
the chip reads the 0xFFFF sentinel at every duty; bridging 10 kOhm from the
net to 3.3 V restored live counting (~678 RPM at 0 % drive). Fan-to-fan
variation: some fans provide their own tach pull-up, others do not — the
bench fan does not. Although the guide ties the jumper to alert use, the
pull-up equally serves TACH-input mode (demonstrated via the external
equivalent). Practical rule for the M5 wiring guide and README: if the TACH
count sticks at the 0xFFFF sentinel with a verified-spinning fan, enable the
onboard TACH pull-up (solder jumper) or add an external ~10 kOhm pull-up to
3.3 V. The same pull-up also defines the ALERT open-drain idle-high in
interrupt mode.

## 6. Source links

- Local datasheet (authoritative): `../EMC2101_datasheet.pdf` (SMSC EMC2101 Rev 2.54, 06-16-09)
- Adafruit board guide (product 4808; local copy gitignored): `../emc2101-fan-controller-and-temperature-sensor.pdf` — page 7: pull-up jumpers (§5 above); online: <https://learn.adafruit.com/emc2101-fan-controller-and-temperature-sensor>
- Microchip-hosted copy (referenced by Adafruit): `https://ww1.microchip.com/downloads/en/DeviceDoc/2101.pdf`
- Adafruit product page: `https://www.adafruit.com/product/4808`
- Adafruit lib: `https://github.com/adafruit/Adafruit_CircuitPython_EMC2101`
- SMBus 2.0 specification (protocol background): `http://smbus.org/` (TIMEOUT/ARA details as quoted in datasheet §§4.6, 4.8)
- Sibling driver (template): `..\..\FanSpeedController`
