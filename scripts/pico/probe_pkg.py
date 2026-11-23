"""M2 acceptance probe: exercise the deployed emc2101 package end-to-end
on the Pico W bench. Read-only - verify() touches only the identity
registers (FD/FE/FF); probe()/scan() are NACK-safe bus scans.

Prerequisite: the package is deployed on the board via
    python tools/deploy_mp.py --port COM16
Run with:
    python -m mpremote connect port:COM16 run scripts/pico/probe_pkg.py
"""
import machine

from emc2101.mp import EMC2101

i2c = machine.I2C(0, sda=machine.Pin(0), scl=machine.Pin(1), freq=100_000)
dev = EMC2101(i2c)
pid = dev.verify()
variant = "plain" if pid == 0x16 else ("-R" if pid == 0x28 else "?")
print("pkg verify: product id %#x (%s)" % (pid, variant))
print("probe:", dev.probe())
print("scan:", [hex(a) for a in dev.scan()])
dev.close()
print("PKG PROBE OK")
