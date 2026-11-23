"""M2 acceptance (RPi 3A+ leg): import + construct the package under
CPython WITHOUT touching the bus - no chip required on this bench. Uses an
adopted null handle so no /dev/i2c-N is opened; smbus2 is imported to
confirm the dependency resolves.

Run on the Pi (package deployed alongside this script):
    cd ~/emc2101-test && python3 smoke_import.py
"""
import emc2101
import smbus2                      # noqa: F401  (dependency check)

import emc2101.cp as cp_mod


class NullHandle:
    """Adopted handle stand-in: proves constructor wiring without a bus."""

    def read_byte_data(self, addr, reg):
        raise OSError("no chip on this bench")

    def write_byte_data(self, addr, reg, value):
        raise OSError("no chip on this bench")

    def close(self):
        pass


dev = cp_mod.EMC2101(handle=NullHandle())   # constructor only - no I/O
print("import ok:", emc2101.__version__)
print("config_path:", dev.config_path)
# hardware-free helper sanity checks
assert cp_mod.rpm_from_count(7955) > 600.0
assert cp_mod.ext_raw_to_temp(cp_mod.ext_temp_to_raw(25.0)) == 25.0
assert len(cp_mod.IDEALITY_FACTORS) == 48
dev.close()
print("IMPORT SMOKE OK")
