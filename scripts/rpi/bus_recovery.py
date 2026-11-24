"""I2C bus recovery for the RPi 3A+ bench (run as ROOT, i2c driver UNLOADED).

Escape hatch for a wedged SMBus bus 1: if the EMC2101 latches SDA low
(mid-transaction abort, stuck clock stretching), the bcm2835 controller can
stop making progress and every transaction fails with EIO until the bus is
released. Sequence (Philips spec):
  1. Read SDA statically (input) - is it held low?
  2. Generate up to 9 SCL pulses; after each, sample SDA.
  3. Once SDA reads HIGH, issue a STOP (SDA rises while SCL high).
  4. Report final state.

Usage (on the Pi):
    sudo modprobe -r i2c_bcm2835      # adjust if lsmod | grep i2c differs
    sudo python3 bus_recovery.py [sda_gpio] [scl_gpio]   # defaults 2 3
    sudo modprobe i2c_bcm2835

Defaults are BCM GPIO 2/3 = header pins 3/5 (SDA1/SCL1), this bench's wiring.
Adapted from the MAX31760 sibling project's scripts/rpi/rpi_bus_recovery.py
(D24 adoption precedent); pin numbers parameterized.
"""
import sys
import time

SDA = int(sys.argv[1]) if len(sys.argv) > 1 else 2
SCL = int(sys.argv[2]) if len(sys.argv) > 2 else 3


def export(n):
    with open("/sys/class/gpio/export", "w") as f:
        f.write(str(n))
    time.sleep(0.15)


def unexport(n):
    try:
        with open("/sys/class/gpio/unexport", "w") as f:
            f.write(str(n))
    except OSError:
        pass


def set_dir(n, d):
    with open("/sys/class/gpio/gpio%d/direction" % n, "w") as f:
        f.write(d)


def set_val(n, v):
    with open("/sys/class/gpio/gpio%d/value" % n, "w") as f:
        f.write(str(v))


def get_val(n):
    with open("/sys/class/gpio/gpio%d/value" % n) as f:
        return int(f.read().strip())


try:
    export(SCL)
    export(SDA)
    set_dir(SCL, "out")
    set_dir(SDA, "in")

    print("static SDA (input, no driver): %d" % get_val(SDA))

    released = False
    for i in range(9):
        set_val(SCL, 1)
        time.sleep(0.002)
        set_val(SCL, 0)
        time.sleep(0.002)
        sda = get_val(SDA)
        print("pulse %d -> SDA=%d" % (i + 1, sda))
        if sda == 1:
            released = True
            break

    if released:
        # STOP: SDA low -> high while SCL high
        set_dir(SDA, "out")
        set_val(SDA, 0)
        time.sleep(0.001)
        set_val(SCL, 1)
        time.sleep(0.001)
        set_val(SDA, 1)
        time.sleep(0.001)
        set_val(SCL, 0)
        print("STOP issued; SDA released cleanly")
    else:
        print("SDA STILL HELD LOW after 9 pulses - device likely latched;"
              " power-cycle the breakout")
finally:
    unexport(SDA)
    unexport(SCL)
