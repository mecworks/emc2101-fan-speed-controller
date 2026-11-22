# emc2101 — Cross-Platform EMC2101 Fan Speed Controller Driver

One Python package (`emc2101`), one API, three machines: drive the
SMSC/Microchip **EMC2101** SMBus fan controller from ordinary Python on a
Raspberry Pi Pico W (MicroPython), an ESP32-S3 (MicroPython), and a
Raspberry Pi 3A+ (CPython/smbus2).

**Status: under active development.** Milestones, decisions, and progress
live in [`PLANS.md`](PLANS.md) (the living ExecPlan). The package is not
usable until milestone M2 lands.

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

## Repository layout

| Path | Contents |
|---|---|
| `emc2101/` | The driver package (dual facade: `mp.py` MicroPython, `cp.py` CPython) |
| `examples/` | Shipped demos and the canonical tri-platform E2E suites |
| `tests/` | Host-runnable mock-backed unit/integration suite + lint gate |
| `tools/` | Hardware-free dev utilities (API coverage, deploy helper) |
| `scripts/` | Bench-grouped test/diagnostic scripts (real hardware required) |
| `docs/` | Documentation (lands in milestone M5) |
| `research/` | Committed research trail (register map, feasibility, parity mapping, …) |
| `reference/` | Vendor materials (gitignored — copyrighted) |
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
- SMBus 2.0 specification: <http://smbus.org/>

## License

LGPL-2.1-or-later — see [LICENSE](LICENSE).
