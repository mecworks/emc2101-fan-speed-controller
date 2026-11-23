# Wiring guide

Primary hardware: **Adafruit product 4808** — "EMC2101 I2C PC Fan
Controller and Temperature Sensor [STEMMA QT / Qwiic]". Any board
carrying the same chip works; the address is fixed at `0x4C` either way.

## Breakout connections

| Breakout pin | Function | Connect to |
|---|---|---|
| STEMMA QT / Qwiic (SDA, SCL) | SMBus/I²C | Host I²C bus (tables below) |
| `FAN` | PWM (or DAC in linear mode) drive output | Fan power/pwm lead (the fan's +V and PWM leads are tied together on most 4-wire fans) |
| `TACH` / `ALERT` | Open-collector tach input **or** open-drain ALERT output (software-selected) | Fan tach lead |
| `DP` / `DN` | External thermistor-diode pair | Diode anode/cathode (e.g. a 2N3906 PNP junction) |
| `VIN` / `GND` | 3.0–3.6 V supply (3.3 V nominal) | 3.3 V rail |

The chip's I/O pins are 5 V-tolerant, but the supply itself must stay in
3.0–3.6 V. Bus speed: 10–400 kHz (the driver benches use 100 kHz).

### Per-host pin tables (development benches, decision D10)

| Host | Runtime | Bus | SDA | SCL |
|---|---|---|---|---|
| Raspberry Pi Pico W (RP2040) | MicroPython ≥ 1.29 | I2C0 | GP0 (board pin 1) | GP1 (board pin 2) |
| ESP32-S3 | MicroPython ≥ 1.29 | I2C0 | GPIO41 | GPIO42 |
| Raspberry Pi 3A+ | CPython + smbus2 | SMBus bus 1 (`/dev/i2c-1`) | header pin 3 (SDA1) | header pin 5 (SCL1) |

On the Pico W / ESP32-S3 you can wire the breakout straight onto the
STEMMA QT connector of a carrier board that routes those exact pins;
otherwise jumper SDA/SCL/VIN/GND from the breakout to the host headers.

## Pull-up jumpers (critical)

The breakout carries two solder-jumper-controlled pull-ups (board guide
page 7):

| Jumper | Ships as | Purpose |
|---|---|---|
| **FAN** | **enabled** (cut to disable) | Pull-up on the FAN output pin. Cut it only when using DAC (linear voltage) output mode. |
| **TACH/ALERT** | **disabled** (solder to enable) | Pull-up on the TACH/ALERT net. Bridge it when using the pin for tach counting or ALERT interrupts. |

Either jumper can be bridged with solder later.

### The diagnostic rule

The tach input is open-collector: something must pull the net high
between pulses. Some fans provide their own internal tach pull-up; many
do not. If the fan is **verified spinning** but the RPM reading sticks at
0 (raw count `0xFFFF`):

1. Bridge the onboard TACH/ALERT jumper, **or**
2. Add an external ~10 kΩ pull-up from the TACH net to 3.3 V.

This was confirmed empirically on the development bench (M1 follow-up):
with the jumper unbridged and a fan lacking an internal pull-up, the net
floated high and every read returned the `0xFFFF` sentinel; bridging
10 kΩ restored live counting with no other change. The same pull-up also
defines the ALERT pin's idle-high in interrupt mode — so interrupt use
relies on it too.

## DAC-mode caveat

`dac_enabled = True` switches the FAN output from PWM to a linear 6-bit
DAC voltage. In that mode the FAN-pin pull-up fights the DAC output:
**cut the FAN jumper first**, then enable DAC mode in software. Restore
the jumper before returning to PWM mode.

## Recommended bench loadout

One 4-wire fan on the FAN output with its tach lead on the TACH/ALERT
pin, and a 2N3906 PNP thermal diode on DP/DN (anode → DN, cathode → DP,
per the datasheet's diode orientation). This exercises every channel:
PWM out, tach in, external temperature, and (if bridged) ALERT out.
