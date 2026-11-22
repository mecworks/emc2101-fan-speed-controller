"""Quick bus check for the Pico W bench: scan I2C0 and ping the EMC2101 at 0x4C.

Bench: RPi Pico W (RP2040), USB-serial COM16, I2C0 SDA=GP0 / SCL=GP1.
Run:   python -m mpremote connect port:COM16 run scripts/pico/probe_bus.py

Self-contained (pure machine.I2C, no driver imports); read-only — leaves the
chip exactly as found. A healthy EMC2101 reports two addresses on scan:
0x4C (device) and 0x0C (on-wire form of the ARA general-call address 0x06).
Identity expectation (datasheet Rev 2.54): FDh=0x16, FEh=0x5D, FFh=0x01.
"""
import machine

ADDR = 0x4C
i2c = machine.I2C(0, sda=machine.Pin(0), scl=machine.Pin(1), freq=100_000)

print("bus scan:", ", ".join(hex(a) for a in i2c.scan()) or "(empty)")

results = {}
ok = True
for name, reg in (("product_id", 0xFD), ("mfg_id", 0xFE), ("revision", 0xFF)):
    try:
        results[name] = hex(i2c.readfrom_mem(ADDR, reg, 1)[0])
    except OSError as e:
        ok = False
        results[name] = "ERR(%s)" % getattr(e, "errno", "?")

print("emc2101 @ 0x4C:", "PING OK" if ok else "NO RESPONSE", results)
