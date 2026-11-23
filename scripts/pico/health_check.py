"""Health check: identity trio + key-register snapshot; restores scratchpads.

Bench: RPi Pico W (RP2040), USB-serial COM16, I2C0 SDA=GP0 / SCL=GP1.
Run:   python -m mpremote connect port:COM16 run scripts/pico/health_check.py

Self-contained (pure machine.I2C, no driver imports). Mostly read-only;
clears the scratchpad registers (0x11/0x12) to 0x00 if they are non-zero.
Use before/after mutating bench scripts to confirm the chip is responsive
and at a sane state.
"""
import machine

ADDR = 0x4C
i2c = machine.I2C(0, sda=machine.Pin(0), scl=machine.Pin(1), freq=100_000)


def rb(reg):
    return i2c.readfrom_mem(ADDR, reg, 1)[0]


def wb(reg, val):
    i2c.writeto_mem(ADDR, reg, bytes((val,)))


try:
    ids = (rb(0xFD), rb(0xFE), rb(0xFF))
    print("id trio: fd=%02x fe=%02x ff=%02x" % ids)
    sp1, sp2 = rb(0x11), rb(0x12)
    print("scratchpads: 0x11=%02x 0x12=%02x" % (sp1, sp2))
    if sp1 or sp2:
        wb(0x11, 0)
        wb(0x12, 0)
        ok = (rb(0x11), rb(0x12)) == (0, 0)
        print("scratchpads cleared to 00/00: %s" % ("PASS" if ok else "FAIL"))
    print("cfg=%02x fcfg=%02x fsetting=%02x int_temp=%dC"
          % (rb(0x03), rb(0x4A), rb(0x4C), rb(0x00)))
    print("HEALTH CHECK: %s" % ("PASS" if ids == (0x16, 0x5D, 0x01)
                                else "UNEXPECTED IDS"))
except OSError as e:
    print("HEALTH CHECK FAILED: OSError errno=%s" % getattr(e, "errno", "?"))
