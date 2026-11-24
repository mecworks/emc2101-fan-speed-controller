# Examples

Six shipped scripts. The three demos are board-aware: each detects the
host at runtime (`sys.platform` plus `os.uname().machine`) and builds
the right facade and pins — RPi Pico W (MicroPython, I2C0 SDA=GP0/
SCL=GP1), ESP32-S3 (MicroPython, I2C0 SDA=GPIO41/SCL=GPIO42), or
Raspberry Pi 3A+ (CPython/smbus2, bus 1) — so any demo runs on any of
the three benches; the filename is the conventional entry point for the
named bench. Both test scripts are **self-restoring**: they snapshot
every writable register up front and restore plus verify them
byte-for-byte before exiting.

| Script | Purpose | Run command |
|---|---|---|
| `pico_demo.py` | Demo flow: verify → temperatures → configure 4-wire fan → manual duty sweep with RPM reporting → save config → calm state | `python -m mpremote connect port:COM16 run examples/pico_demo.py` |
| `esp32_demo.py` | Same demo flow, ESP32-S3 entry point | `python -m mpremote connect port:COM7 run examples/esp32_demo.py` |
| `rpi_demo.py` | Same demo flow, Raspberry Pi entry point | `python3 examples/rpi_demo.py` (on the Pi) |
| `hw_smoke_test.py` | Core-behavior smoke: identity, temperatures, duty sweep, settled-RPM plausibility floor, persistence round trip, restore verification. Ends with `HW SMOKE TEST: PASS` | `python -m mpremote connect port:COM16 run examples/hw_smoke_test.py` / `... port:COM7 ...` / `python3 examples/hw_smoke_test.py` |
| `e2e_hardware_test.py` | Full public-API matrix (11 sections: identity, temps/setpoints, manual/duty/PWM, LUT, tach/RPM, faults/alerts, calibration, lifecycle, persistence incl. cold-boot-with-profile, presets, error model). One PASS/FAIL line per section, ends with `E2E HARDWARE MATRIX: PASS` | same pattern as the smoke test |
| `fan_characterize.py` | Fan speed-curve characterization: tach pull-up pre-flight (built-in vs external, up to 3 attach retries), full raw-grid sweep S=0..62 @ PWM_F=31 (5 s dwell, 250 ms sampling), CSV to stdout + four-answer summary to stderr; non-interactive via device-local `/char_answers.txt`. Render the PNG with `tools/render_curve.py` | Remote: stage `_fan_curve_math.py` + `/char_answers.txt`, then `python -u -m mpremote connect port:COM16 run examples/fan_characterize.py > curve_raw.txt` (keep only the CSV-shaped lines from the capture); native: `python3 examples/fan_characterize.py --save curve.csv` |

Prerequisites:

- **MCU benches:** the package must be deployed first —
  `python tools/deploy_mp.py --port <PORT>` (mpremote's fs/cp transfers are
  unreliable on 1.29.0; the deploy tool uses the exec channel). MicroPython
  v1.29.0.
- **Raspberry Pi:** `pip install smbus2`, I2C enabled, package
  importable from the script's directory.
- A real fan on FAN+/FAN− and a diode on DP/DN (see
  [`../docs/wiring.md`](../docs/wiring.md)); the RPM assertions assume a
  spinning fan. `fan_characterize.py` needs only the fan (the diode channel
  is not used) plus, for remote runs, the staged `/char_answers.txt`
  answer file.

Cold boot on the MCU benches (E2E section 9): the first run stages a
distinctive profile, writes a flag file, and power-cycles the board via
`machine.reset()`. Re-run the script once the board is back; it then
verifies the constructor auto-load and completes the matrix. On the
Raspberry Pi leg the scenario is approximated by constructing a fresh
driver instance against the live chip (no board power cycle is possible
from the host).
