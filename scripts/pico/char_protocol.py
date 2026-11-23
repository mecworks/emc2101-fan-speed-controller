"""Protocol characterization probes for the Pico W bench (M1).

Bench: RPi Pico W (RP2040), USB-serial COM16, I2C0 SDA=GP0 / SCL=GP1.
Run:   python -m mpremote connect port:COM16 run scripts/pico/char_protocol.py

Self-contained (pure machine.I2C, no driver imports); read-only — leaves
the chip exactly as found. Probes:
  1. Two-byte read attempt (datasheet defines single-byte protocols only;
     finding: over-reads return 0xFF padding, no exception raised)
  2. Data-read interlock orders (ext temp MSB-first; TACH LSB-first)

NOTE: bare Receive/Send Byte transactions (no register-address phase) were
tried once during M1 characterization and desynchronize the chip's SMBus
interface (next transaction fails with EIO; recovers on reconnect). They are
deliberately absent from this script; see NOTES/bench-characterization.md.
"""
import machine

ADDR = 0x4C
i2c = machine.I2C(0, sda=machine.Pin(0), scl=machine.Pin(1), freq=100_000)


def rb(reg):
    return i2c.readfrom_mem(ADDR, reg, 1)[0]


print("=== 1. two-byte read attempt ===")
try:
    data = i2c.readfrom_mem(ADDR, 0x00, 2)
    print("readfrom_mem(0x00, n=2) OK:", ",".join(hex(b) for b in data))
except OSError as e:
    print("readfrom_mem(0x00, n=2) raised OSError errno=%s" % getattr(e, "errno", "?"))

print()
print("=== 2. interlock orders (external temperature) ===")


def ext_temp(msb_first):
    if msb_first:
        m = rb(0x01)
        l = rb(0x10)
    else:
        l = rb(0x10)
        m = rb(0x01)
    raw = (m << 3) | (l & 0x07)
    if raw >= 0x400:
        raw -= 0x800
    return raw * 0.125


for trial in range(3):
    a = ext_temp(True)
    b = ext_temp(False)
    print("trial %d: msb-first=%.3f C  lsb-first=%.3f C" % (trial, a, b))

print()
print("tachi read-order sanity (lsb-first, input disabled at POR):")
lo = rb(0x46)
hi = rb(0x47)
print("tachi count = %d (hi=%02x lo=%02x)" % ((hi << 8) | lo, hi, lo))
