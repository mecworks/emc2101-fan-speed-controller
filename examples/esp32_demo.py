"""EMC2101 demo — ESP32-S3 (MicroPython).

Board-aware: the body detects the host at runtime (sys.platform plus
os.uname().machine), so this script runs unchanged on all three dev
platforms — RPi Pico W (I2C0 SDA=GP0/SCL=GP1), ESP32-S3 (I2C0
SDA=GPIO41/SCL=GPIO42), and Raspberry Pi 3A+ (CPython/smbus2, bus 1).
The filename is the conventional entry point for the named bench.

Demo flow: verify -> print temperatures -> configure 4-wire fan ->
manual duty sweep with RPM reporting -> restore a calm state (manual
drive at 0 % = floor speed) -> save that state as the persistent JSON
profile. Construct with config_file=<path> (or call load_config()) to
apply the profile automatically after reboot.

Prerequisite: the emc2101 package must be deployed to the MCU
(`python -m mpremote connect port:COM7 fsync ./emc2101`).

Run:
    python -m mpremote connect port:COM7 run examples/esp32_demo.py
"""
import os
import sys
import time


def build_device():
    """Construct an EMC2101 device for whichever platform we run on."""
    if sys.platform == "linux":
        # CPython on the Raspberry Pi: SMBus via smbus2.
        from emc2101.cp import EMC2101
        return EMC2101(bus=1)
    # MicroPython: machine.I2C with per-board pins.
    import machine
    from emc2101.mp import EMC2101
    machine_name = os.uname().machine.upper()
    if "RP2" in machine_name:
        sda, scl = 0, 1            # Pico W I2C0
    else:
        sda, scl = 41, 42          # ESP32-S3 I2C0
    i2c = machine.I2C(0, sda=machine.Pin(sda), scl=machine.Pin(scl),
                      freq=100_000)
    return EMC2101(i2c)


def main():
    dev = build_device()

    print("verify: product ID %#x" % dev.verify())
    print("part_info:", dev.part_info)
    print("local temp:  %.1f C" % dev.local_temp_c)
    print("remote temp: %.3f C" % dev.remote_temp_c)

    dev.configure_4wire_fan(pwm_freq_hz=25000)
    print("PWM: %.1f Hz, TACH input enabled (ALERT output disabled)"
          % dev.pwm_freq_hz)

    dev.manual = True
    for pct in (0, 25, 50, 75, 100):
        dev.set_duty_pct(pct)
        time.sleep(1.0)                       # let the fan settle
        print("duty %3d %% -> raw %2d, %.0f RPM"
              % (pct, dev.duty_cmd_raw, dev.rpm()))

    dev.set_duty_pct(0)                     # manual drive at 0 % = floor speed
    print("calm state restored: manual drive at 0 %% (floor speed)")

    path = dev.save_config()                # persist the calm state
    print("config saved to %s" % path)
    dev.close()


main()
