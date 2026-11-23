"""Interlock / torn-pair probe for the Pico W bench (M1 re-test).

Bench: RPi Pico W (RP2040), USB-serial COM16, I2C0 SDA=GP0 / SCL=GP1.
Run:   python -m mpremote connect port:COM16 run scripts/pico/char_interlock.py

Self-contained (pure machine.I2C, no driver imports); read-only. Requires a
connected external diode (live conversion). Exercises the two-byte
external-temperature interlock:
  1. Stability: 200 rapid MSB-first reads, min/max/distinct
  2. Order sensitivity: 100 rounds of MSB-first vs LSB-first back-to-back;
     flags any round where the two decoded values disagree by > 1 C
     (would indicate a non-atomic byte update caught mid-conversion)
"""
import machine

ADDR = 0x4C
i2c = machine.I2C(0, sda=machine.Pin(0), scl=machine.Pin(1), freq=100_000)


def rb(reg):
    return i2c.readfrom_mem(ADDR, reg, 1)[0]


def ext_raw(msb_first):
    if msb_first:
        m = rb(0x01)
        l = rb(0x10)
    else:
        l = rb(0x10)
        m = rb(0x01)
    return (m << 3) | (l & 0x07)


def decode(raw):
    v = raw - 0x800 if raw >= 0x400 else raw
    return v * 0.125


print("=== 1. stability (200 rapid MSB-first reads) ===")
vals = [decode(ext_raw(True)) for _ in range(200)]
print("min=%.1f C max=%.1f C distinct=%d"
      % (min(vals), max(vals), len(set(vals))))

print()
print("=== 2. order sensitivity (100 rounds, back-to-back) ===")
bad = 0
for i in range(100):
    a = decode(ext_raw(True))
    b = decode(ext_raw(False))
    if abs(a - b) > 1.0:
        bad += 1
        print("round %d: msb-first=%.1f C lsb-first=%.1f C DELTA" % (i, a, b))
print("rounds with delta > 1 C: %d" % bad)
