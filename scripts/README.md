# Hardware Bench Scripts

Validation, diagnostic, and probe scripts written during development and
cross-platform verification. They are **not** part of the shipped `emc2101`
package and are **not** collected by the unit-test suite in `tests/` (they
need real hardware and/or import `machine`). Every script here is
self-contained — none imports another script from this tree — and any script
that mutates chip state must be self-restoring (leave the chip in a safe,
known state before exiting).

Scripts are grouped by the physical bench they target:

| Dir | Bench | Runtime | How to run |
|-----|-------|---------|------------|
| `pico/` | RPi Pico W (RP2040), USB-serial COM16, I2C0 SDA=GP0/SCL=GP1 | MicroPython on-device | `python -m mpremote connect port:COM16 run <script>.py` |
| `esp32/` | ESP32-S3, USB-serial COM7, I2C0 SDA=GPIO41/SCL=GPIO42 | MicroPython on-device | `python -m mpremote connect port:COM7 run <script>.py` |
| `rpi/` | Raspberry Pi 3A+ (local RPi over SSH), SMBus bus 1 (`/dev/i2c-1`) | CPython on the Pi (smbus2) | SCP to the Pi, then `python3 <script>.py` |

The canonical tri-platform suites (`hw_smoke_test.py`,
`e2e_hardware_test.py`) and the platform demos live in `examples/`; this
directory holds the incremental per-feature slices and ad-hoc probes run
during M1 characterization and M7 validation. Development utilities that do
not need hardware (coverage, lint, deploy helpers) belong in `tools/`.

## pico/

| Script | Purpose |
|--------|---------|
| `probe_bus.py` | Connectivity probe: I2C0 scan + identity ping (FDh/FEh/FFh) against the real chip |
| `probe_id.py` | Identity probe: reads 0x00/0xFD/0xFE/0xFF at 0x4C and prints each byte (M1 entry check) |
| `char_protocol.py` | M1 protocol probes: two-byte over-read behavior, interlock read orders (read-only) |
| `char_interlock.py` | M1 interlock/torn-pair probe: 200 rapid MSB-first reads + 100 alternating-order rounds (read-only; needs live diode) |
| `char_tach.py` | M1 TACH/TACH_M/manual-duty/BUSY probes (mutating; snapshots + restores 0x03/0x4A/0x4C) |
| `health_check.py` | Responsiveness + state snapshot; clears scratchpads if dirty (pre/post mutating runs) |
| `probe_tach_signal.py` | M1 follow-up: TACH-net signal probe — tap the net onto GP2, count edges/periods while the fan spins (read-only, no chip access) |
| `char_tach_diag.py` | M1 follow-up: chip-side TACH diagnostics — ALT_TCH latch check, TACH_M write acceptance (A3), CLK_SEL=1 trial (mutating; snapshots + restores 0x03/0x4A/0x4C) |
