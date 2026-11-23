# emc2101 — Cross-Platform EMC2101 Fan Speed Controller Driver

One Python package (`emc2101`), one API, three machines: drive the
SMSC/Microchip **EMC2101** SMBus fan controller from ordinary Python on a
Raspberry Pi Pico W (MicroPython), an ESP32-S3 (MicroPython), and a
Raspberry Pi 3A+ (CPython/smbus2).

**Status: under active development** — milestones M0–M4 are complete
(package, protocol API, persistence) with live-silicon acceptance on the
Pico W bench; see [`PLANS.md`](PLANS.md) (the living ExecPlan) for
milestones, decisions, and progress.

## Documentation

- [Quickstart](docs/quickstart.md) — install per platform, first program,
  LUT control, save/load config
- [API reference](docs/api-reference.md) — every public member
- [Wiring guide](docs/wiring.md) — STEMMA QT/Qwiic + raw I²C, pin tables,
  pull-up rules
- [Persistence](docs/persistence.md) — JSON schema v1 semantics
- [Operational notes](docs/operational-notes.md) — cold-boot window,
  TCRIT lifecycle, ALERT/TACH trade-offs, ARA, force-register testing
- [Contributing](CONTRIBUTING.md) · [Changelog](CHANGELOG.md)

## What you can do with it (target capability)

- Read the internal die temperature and an external thermistor-diode
  junction temperature
- Program the chip's eight-entry temperature-to-fan-speed lookup table (LUT)
- Drive the fan manually at any percent duty
- Measure fan speed in RPM (single tach input)
- Service thermal alarms (interrupt/comparator modes, masking, queueing)
- Save the entire configuration to a human-readable JSON file and restore
  it automatically at startup — simulating the EEPROM auto-load of the
  `-R` variant on the plain part

## Platforms

| Platform | Runtime | Wiring |
|---|---|---|
| Raspberry Pi Pico W | MicroPython ≥ 1.29 | I2C0: SDA=GP0, SCL=GP1 |
| ESP32-S3 | MicroPython ≥ 1.29 | I2C0: SDA=GPIO41, SCL=GPIO42 |
| Raspberry Pi 3A+ | CPython (smbus2) | SMBus bus 1 |

The chip address is fixed at `0x4C` (no addressing pins). Primary hardware:
Adafruit product 4808 breakout (STEMMA QT/Qwiic); any board carrying the
same chip works.

## Hardware notes

- **TACH pull-up (important):** the EMC2101's tach input is open-collector
  and needs something to pull the line high between pulses. On the Adafruit
  4808 breakout the TACH/ALERT pull-up sits behind a solder jumper that
  ships **disabled** (the guide recommends bridging it for alert use); some
  fans provide their own internal tach pull-up, others do not. If the fan is
  verified spinning but the RPM reading sticks at 0 (count `0xFFFF`), bridge
  the TACH jumper on the back of the breakout or add an external ~10 kΩ
  pull-up from the TACH net to 3.3 V. The same pull-up also defines the
  ALERT pin's idle-high in interrupt mode.
- **FAN-pin pull-up:** enabled by default on the breakout; cut the FAN
  jumper only when using DAC (linear voltage) output mode.

## Repository layout

| Path | Contents |
|---|---|
| `emc2101/` | The driver package (dual facade: `mp.py` MicroPython, `cp.py` CPython) |
| `examples/` | Shipped demos and the canonical tri-platform E2E suites |
| `tests/` | Host-runnable mock-backed unit/integration suite + lint gate |
| `tools/` | Hardware-free dev utilities (API coverage, deploy helper) |
| `scripts/` | Bench-grouped test/diagnostic scripts (real hardware required) |
| `docs/` | Documentation: quickstart, API reference, wiring guide, persistence, operational notes |
| `research/` | Committed research trail (register map, feasibility, parity mapping, …) |
| `reference/` | Reference materials; copyrighted vendor files gitignored by filename (D28) |
| `PLANS.md` | Living ExecPlan (milestones, decisions, progress) |
| `AGENTS.md` | Ground rules for agents working in this repository |

## Development

Quality gates (run from the repository root after any code change):

```powershell
python -m unittest discover -s tests -v
python tools/api_coverage.py
python tests/lint_subset.py
python -m compileall -q emc2101 examples
```

The dev host needs `pip install mpremote` for MCU workflows (invoke as
`python -m mpremote`). CPython hosts need `smbus2>=0.4.2` (Linux);
MicroPython hosts need nothing beyond the standard library.

## References

- SMSC EMC2101 datasheet Rev 2.54 (authoritative): <https://ww1.microchip.com/downloads/en/DeviceDoc/2101.pdf>
- Adafruit product 4808 (primary hardware): <https://www.adafruit.com/product/4808>
- Adafruit 4808 board guide (wiring, pull-up jumpers): <https://learn.adafruit.com/emc2101-fan-controller-and-temperature-sensor>
- SMBus 2.0 specification: <http://smbus.org/>

## License

LGPL-2.1-or-later — see [LICENSE](LICENSE).
