"""M3 live acceptance probe (Pico W bench): exercises the protocol-level
API against real silicon and is fully self-restoring.

Every register the probe modifies is snapshotted first, restored after
the exercise phase, and verified byte-for-byte before the script exits.
Read-only observations (temperatures, RPM, decoded LUT) are printed for
the record.

Prerequisite: package deployed via
    python tools/deploy_mp.py --port COM16
Run with:
    python -m mpremote connect port:COM16 run scripts/pico/probe_m3.py
"""
import machine
import sys

from emc2101._faults import DiodeFaultError
from emc2101.mp import EMC2101

i2c = machine.I2C(0, sda=machine.Pin(0), scl=machine.Pin(1), freq=100_000)
dev = EMC2101(i2c)

failures = []


def expect(cond, label):
    tag = "PASS" if cond else "FAIL"
    print("[%s] %s" % (tag, label))
    if not cond:
        failures.append(label)


# ---------------------------------------------------------------- snapshot
SNAP_REGS = [
    (0x03, 1),      # CONFIG
    (0x06, 1),      # ALERT_MASK
    (0x07, 1),      # FILTER
    (0x11, 2),      # SCRATCHPAD 1..2
    (0x48, 2),      # TACH_LIMIT LO/HI
    (0x4A, 4),      # FAN_CFG, FAN_SETTING, PWM_F, PWM_D
    (0x50, 16),     # LUT entries
    (0x5F, 1),      # SPINUP
]
snapshot = {}
for addr, n in SNAP_REGS:
    vals = dev.read_reg(addr, n)
    if isinstance(vals, int):
        vals = (vals,)
    for i in range(n):
        snapshot[addr + i] = vals[i]

print("snapshot: %d registers captured" % len(snapshot))

try:
    # ---------------------------------------------------------- identity
    pid, mid, rev = dev.part_info
    expect(pid == 0x16 and mid == 0x5D and rev == 0x01,
           "part_info (%#x, %#x, %#x)" % (pid, mid, rev))

    # ------------------------------------------------------- temperatures
    lt = dev.local_temp_c
    expect(-64.0 <= lt <= 127.875, "local_temp_c = %.1f C" % lt)
    try:
        rt = dev.remote_temp_c
        expect(-64.0 <= rt <= 127.875, "remote_temp_c = %.1f C" % rt)
    except DiodeFaultError as exc:
        print("[SKIP] remote_temp_c raised DiodeFaultError: %s" % exc)

    lh = dev.local_high_c
    print("info: local_high_c = %.1f C" % lh)
    th = dev.tcrit_c
    print("info: tcrit_c = %.1f C" % th)

    # ------------------------------------------------------------ status
    st = dev.status_raw()
    alarms = dev.active_alarms()
    print("info: status=%#x alarms=%r" % (st, alarms))
    svc = dev.service_alert()
    expect(isinstance(svc, int) and 0 <= svc <= 0xFF,
           "service_alert returned %#x" % svc)

    am = dev.alert_mask
    dev.alert_mask = am          # no-op RMW must land on the same byte
    expect(dev.alert_mask == am, "alert_mask RMW stable (%#x)" % am)

    # ------------------------------------------------------------- duty
    pf = dev.read_reg(0x4D) & 0x1F

    def duty_of(raw):
        return float(raw) / (2.0 * pf) * 100.0 if pf else 0.0

    raw_now = dev.duty_cmd_raw
    print("info: fan duty = %.1f%% (raw %#x, PWM_F=%d)"
          % (duty_of(raw_now), raw_now, pf))
    dev.set_duty_pct(50.0)
    d50 = duty_of(dev.duty_cmd_raw)
    expect(abs(d50 - 50.0) <= 100.0 / (2.0 * pf) + 0.01,
           "set_duty_pct(50) -> %.1f%%" % d50)
    dev.duty_cmd_raw = snapshot[0x4C] & 0x3F
    expect(dev.duty_cmd_raw == snapshot[0x4C] & 0x3F,
           "duty_cmd_raw restored")

    pfreq = dev.pwm_freq_hz
    expect(pfreq > 0.0, "pwm_freq_hz = %.1f Hz" % pfreq)

    # ---------------------------------------------------------------- LUT
    lut = dev.lut
    expect(len(lut) == 8, "lut decodes 8 entries")
    temps = [p[0] for p in lut]
    # Documented POR: all entries T=127 C / S=max (inactive); any
    # programmed curve must ascend strictly.
    is_por = all(t_ == 127.0 for t_ in temps)
    expect(is_por or all(a < b for a, b in zip(temps, temps[1:])),
           "lut thresholds valid%s: %r"
           % (" (POR default)" if is_por else "", temps))
    for i, (t_, d_) in enumerate(lut):
        print("info: LUT[%d] = %.1f C -> %.1f%%" % (i, t_, d_))

    curve = [(25, 0), (30, 10), (35, 20), (40, 30),
             (45, 40), (50, 50), (55, 60), (60, 70)]
    dev.lut = curve
    lut2 = dev.lut
    ok = all(abs(a[0] - b[0]) < 0.01 for a, b in zip(lut2, curve))
    expect(ok, "lut bulk write round-trips")
    dev.lut_set_index(0, 20, 5.0)
    expect(abs(dev.lut_get_index(0)[0] - 20.0) < 0.01,
           "lut_set_index/get_index round-trip")

    hy = dev.hysteresis_c
    dev.hysteresis_c = hy        # no-op RMW
    expect(dev.hysteresis_c == hy, "hysteresis_c RMW stable (%d)" % hy)

    # ----------------------------------------------------------- tach/RPM
    r = dev.rpm()
    print("info: rpm = %.1f" % r)
    expect(r >= 0.0, "rpm readable")
    tt = dev.tach_threshold
    print("info: tach_threshold = %#x" % tt)
    mr = dev.min_rpm
    print("info: min_rpm = %.1f%s" % (mr, "" if mr else " (disabled)"))
    print("info: spinup enabled=%s time=%s drive=%s%%"
          % (dev.spin_up_enabled, dev.spin_up_time_s, dev.spin_up_drive))

    # -------------------------------------------------------- calibration
    idf = dev.ideality_factor
    print("info: ideality_factor = %.4f (index %#x)"
          % (idf, dev.ideality_factor_index))
    print("info: beta auto=%s index=%d"
          % (dev.beta_auto_detect, dev.beta_index))
    cr = dev.conversion_rate
    print("info: conversion_rate = %.1f/s" % cr)
    af = dev.averaging_filter
    print("info: averaging_filter = %d" % af)

    # --------------------------------------------------------- scratchpad
    sp_orig = dev.scratchpad_get(0)
    dev.scratchpad_set(0, 0xA5)
    expect(dev.scratchpad_get(0) == 0xA5, "scratchpad round-trip 0xA5")
    dev.scratchpad_set(0, sp_orig)
    expect(dev.scratchpad_get(0) == sp_orig, "scratchpad restored")

    # ------------------------------------------------------ power modes
    dev.standby = True
    expect(dev.standby, "standby enter")
    dev.one_shot()               # legal only in standby
    dev.standby = False
    expect(not dev.standby, "standby exit")
    expect(dev.fan_standby == bool(snapshot[0x03] & 0x20),
           "fan_standby untouched")
except Exception as exc:                     # noqa: BLE001 - probe scope
    print("[FAIL] unexpected exception: %s: %s"
          % (type(exc).__name__, exc))
    failures.append("unexpected exception %s" % type(exc).__name__)
finally:
    # ---------------------------------------------------------- restore
    for addr in sorted(snapshot):
        dev.write_reg(addr, bytes([snapshot[addr]]))
    bad = []
    for addr in sorted(snapshot):
        if dev.read_reg(addr) != snapshot[addr]:
            bad.append(addr)
    if bad:
        print("[FAIL] restore mismatch at %s"
              % ", ".join(hex(a) for a in bad))
        failures.append("restore mismatch")
    else:
        print("restore: all %d registers verified" % len(snapshot))

dev.close()
if failures:
    print("M3 LIVE PROBE FAILED: %d issue(s)" % len(failures))
    sys.exit(1)
print("M3 LIVE PROBE OK")
