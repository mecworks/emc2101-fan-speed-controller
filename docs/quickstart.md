# Quickstart

## 1. Install

### Raspberry Pi Pico W / ESP32-S3 (MicroPython)

Flash MicroPython ≥ 1.29 onto the board, then deploy the package with
`mpremote` (host side: `pip install mpremote`; invoke it as
`python -m mpremote`):

```powershell
# from the repository root
python tools/deploy_mp.py --port COM16     # Pico W
python tools/deploy_mp.py --port COM7      # ESP32-S3
```

The tool copies the package to `/lib/emc2101/` on the device — no path
manipulation needed afterwards, just `import emc2101.mp`.

### Raspberry Pi 3A+ (CPython)

```bash
sudo apt install python3-smbus2        # or: pip install smbus2
sudo usermod -aG i2c $USER             # re-login afterwards
scp -r emc2101 pi@raspberrypi:~/       # copy the package next to your script
```

Enable I²C in `raspi-config` if not already done; the chip sits on SMBus
bus 1 (`/dev/i2c-1`).

## 2. First program

### MicroPython (Pico W shown; ESP32-S3 differs only in pins/bus)

```python
import machine
from emc2101.mp import EMC2101

i2c = machine.I2C(0, sda=machine.Pin(0), scl=machine.Pin(1), freq=100_000)
dev = EMC2101(i2c)

print(dev.verify())          # -> 0x16 (product ID); raises on NACK/bad identity
print(dev.part_info)         # (0x16, 0x5D, 0x01) for a plain EMC2101
print(dev.local_temp_c)      # die temperature, °C
print(dev.remote_temp_c)     # external diode temperature, °C

dev.configure_4wire_fan(pwm_freq_hz=25000)   # PWM + tach input + spin-up
dev.manual = True
dev.set_duty_pct(50)                       # drive the fan at 50 %
print(dev.rpm(pulses_per_rev=2))           # measured speed
dev.close()
```

On the ESP32-S3 use `sda=machine.Pin(41), scl=machine.Pin(42)` instead.

### CPython (Raspberry Pi 3A+)

```python
from emc2101.cp import EMC2101

with EMC2101(bus=1) as dev:
    print(dev.verify())
    print(dev.remote_temp_c)
    dev.configure_4wire_fan(pwm_freq_hz=25000)
    dev.manual = True
    dev.set_duty_pct(50)
    print(dev.rpm(pulses_per_rev=2))
```

Both facades expose the identical public surface (enforced by
`tests/test_api_parity.py`); see the [API reference](api-reference.md).

## 3. Automatic LUT control (the chip's job)

Program the eight-entry lookup table and let the chip regulate the fan
against the external diode temperature:

```python
dev.lut = [(30, 10), (40, 20), (50, 30), (60, 45),
           (70, 60), (80, 75), (90, 90), (100, 100)]
dev.manual = False          # hand control back to the LUT
```

Thresholds must be strictly ascending when written. Once engaged, an
entry holds until the temperature drops below threshold minus
`hysteresis_c` (default 4 °C).

## 4. Save and restore the configuration

The plain part has no EEPROM; this package simulates the `-R` variant's
auto-load with a JSON file (see [Persistence](persistence.md)):

```python
dev.save_config()                          # default path per platform
# ... later, after a power cycle ...
dev = EMC2101(i2c, config_file="/emc2101.json")   # auto-applied at construct
```

Default paths: `/emc2101.json` on MicroPython, `~/emc2101.json` on
CPython. Passing `config_file=None` (the default) performs zero file I/O.
