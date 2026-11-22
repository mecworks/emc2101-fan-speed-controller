"""Identity probe for the Pico W bench: read the EMC2101 ID registers.

Bench: RPi Pico W (RP2040), USB-serial COM16, I2C0 SDA=GP0 / SCL=GP1.
Run:   python -m mpremote connect port:COM16 run scripts/pico/probe_id.py

Self-contained (pure machine.I2C, no driver imports); read-only — leaves the
chip exactly as found. Expectation (datasheet Rev 2.54): FDh=0x16 (plain
EMC2101), FEh=0x5D (SMSC), FFh=0x01. Register 00h (internal temperature) is
printed for reference only.
"""
import machine

ADDR = 0x4C
i2c = machine.I2C(0, sda=machine.Pin(0), scl=machine.Pin(1), freq=100_000)

REGS = (
    ("reg 00h       ", 0x00),
    ("product id fdh", 0xFD),
    ("mfg id     feh", 0xFE),
    ("revision   ffh", 0xFF),
)
for name, reg in REGS:
    try:
        val = i2c.readfrom_mem(ADDR, reg, 1)[0]
        print("%s = %02x" % (name, val))
    except OSError as e:
        print("%s = ERR(%s)" % (name, getattr(e, "errno", "?")))
