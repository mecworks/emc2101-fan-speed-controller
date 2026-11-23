"""M2 acceptance (ESP32-S3 leg): import + construct the deployed package
WITHOUT touching the bus - no chip required on this bench. The constructor
performs no I/O, so this validates deployment, sys.path resolution under
/lib, and the MicroPython subset of the shared modules.

Prerequisite: python tools/deploy_mp.py --port COM7
Run: python -m mpremote connect port:COM7 run scripts/esp32/smoke_import.py
"""
import emc2101
import machine

import emc2101.mp as mp_mod

i2c = machine.I2C(0, sda=machine.Pin(41), scl=machine.Pin(42), freq=100_000)
dev = mp_mod.EMC2101(i2c)          # constructor only - no bus traffic
print("import ok:", emc2101.__version__)
print("config_path:", dev.config_path)
print("addr:", hex(dev.addr))
# hardware-free helper sanity checks
assert mp_mod.rpm_from_count(7955) > 600.0
assert mp_mod.ext_raw_to_temp(mp_mod.ext_temp_to_raw(25.0)) == 25.0
assert len(mp_mod.IDEALITY_FACTORS) == 48
dev.close()
print("IMPORT SMOKE OK")
