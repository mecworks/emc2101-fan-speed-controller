"""EMC2101 hardware smoke test — core behavior on real silicon.

Self-restoring: snapshots every writable register up front and restores
them byte-for-byte (verified) before exiting, so an interrupted run
leaves the chip at most temporarily misconfigured. Prints one PASS/FAIL
line per check and finally `HW SMOKE TEST: PASS` (exit 0) or
`HW SMOKE TEST: FAIL` (exit 1).

Board-aware: runs unchanged on all three dev platforms — RPi Pico W
(MicroPython, I2C0 GP0/GP1), ESP32-S3 (MicroPython, I2C0 GPIO41/42),
Raspberry Pi 3A+ (CPython/smbus2, bus 1).

Sections: identity, temperatures, manual duty sweep, settled-RPM
plausibility floor, persistence round trip, restore verification.

Run:
    Pico W:     python -m mpremote connect port:COM16 run examples/hw_smoke_test.py
    ESP32-S3:   python -m mpremote connect port:COM7 run examples/hw_smoke_test.py
    RPi 3A+:    python3 examples/hw_smoke_test.py        (on the Pi)
"""
import os
import sys
import time

from emc2101 import _regs as R

# Persistence paths: MicroPython flash root vs. a writable host dir.
BASE_DIR = os.path.expanduser("~") if sys.platform == "linux" else "/"


def build_device():
    """Construct an EMC2101 device for whichever platform we run on."""
    if sys.platform == "linux":
        from emc2101.cp import EMC2101
        return EMC2101(bus=1)
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


failures = []


def pwm_f_of(dev):
    """Current PWM_F value (raw tier; no dedicated property)."""
    return dev.read_reg(R.REG_PWM_F) & 0x1F


def expect(cond, label):
    tag = "PASS" if cond else "FAIL"
    print("[%s] %s" % (tag, label))
    if not cond:
        failures.append(label)


# ------------------------------------------------------------- snapshot
SNAP = [R.REG_CONFIG, R.REG_CONV_RATE, R.REG_INT_LIMIT,
        R.REG_EXT_HIGH_MSB, R.REG_EXT_LOW_MSB, R.REG_EXT_HIGH_LSB,
        R.REG_EXT_LOW_LSB, R.REG_EXT_FORCE, R.REG_SCRATCHPAD_1,
        R.REG_SCRATCHPAD_2, R.REG_ALERT_MASK, R.REG_IDEALITY,
        R.REG_BETA, R.REG_TCRIT, R.REG_TCRIT_HYST, R.REG_TACH_LIMIT_LO,
        R.REG_TACH_LIMIT_HI, R.REG_FAN_CFG, R.REG_SPINUP,
        R.REG_FAN_SETTING, R.REG_PWM_F, R.REG_PWM_D, R.REG_LUT_HYST,
        R.REG_FILTER]
for i in range(8):
    SNAP.append(R.REG_LUT_BASE + 2 * i)
    SNAP.append(R.REG_LUT_BASE + 2 * i + 1)

dev = build_device()
# Silicon quirk (D35): while PROG=0 the Fan Setting and LUT registers
# read back the LUT-driven duty instead of their stored contents, so
# capture them under a temporary PROG=1 and restore the mode after.
_fc_pre = dev.read_reg(R.REG_FAN_CFG)
if not (_fc_pre & R.FCFG_PROG):
    dev.write_reg(R.REG_FAN_CFG, bytes([_fc_pre | R.FCFG_PROG]))
    time.sleep(0.1)   # D36: let the fan-control read-out settle
snapshot = {}
for addr in SNAP:
    snapshot[addr] = dev.read_reg(addr)
if not (_fc_pre & R.FCFG_PROG):
    dev.write_reg(R.REG_FAN_CFG, bytes([_fc_pre]))
print("snapshot: %d registers captured" % len(snapshot))


def _restore_snapshot():
    """Raw byte-for-byte restore. Fan-domain registers are read-only
    while PROG=0, so write everything except FAN_CFG with PROG forced
    on, then restore the final mode byte."""
    dev.write_reg(R.REG_FAN_CFG,
                  bytes([snapshot[R.REG_FAN_CFG] | R.FCFG_PROG]))
    time.sleep(0.1)   # D36: let the fan-control read-out settle
    for addr in sorted(snapshot):
        if addr != R.REG_FAN_CFG:
            dev.write_reg(addr, bytes([snapshot[addr]]))
    dev.write_reg(R.REG_FAN_CFG, bytes([snapshot[R.REG_FAN_CFG]]))

restored_by_load = False
try:
    # ------------------------------------------------------------ identity
    expect(dev.probe(), "device answers at %#x" % R.ADDR_FIXED)
    pid = dev.verify()
    expect(pid == R.PRODUCT_ID_PLAIN or pid == R.PRODUCT_ID_R,
           "verify() returns a known product ID (#%#x)" % pid)
    expect(dev.part_info == (R.PRODUCT_ID_PLAIN, R.MANUF_ID_SMSC,
                             R.REVISION_EXPECTED)
           or dev.part_info[0] == R.PRODUCT_ID_R,
           "part_info identity trio sane: %r" % (dev.part_info,))
    expect(R.ADDR_FIXED in dev.scan(), "scan() finds %#x" % R.ADDR_FIXED)

    # -------------------------------------------------------- temperatures
    lt = dev.local_temp_c
    rt = dev.remote_temp_c
    expect(-10.0 <= lt <= 95.0, "local temp plausible (%.1f C)" % lt)
    expect(R.TEMP_RANGE_MIN_C <= rt <= R.TEMP_RANGE_MAX_C,
           "remote temp plausible (%.3f C)" % rt)

    # ---------------------------------------------------- manual duty sweep
    dev.tach_input_enabled = True      # RPM reporting needs the TACH input
    dev.manual = True
    prev_raw = -1
    monotonic = True
    for pct in (0, 25, 50, 75, 100):
        dev.set_duty_pct(pct)
        raw = dev.duty_cmd_raw
        want = R.duty_pct_to_setting(pct, pwm_f_of(dev))
        expect(raw == want, "duty %d%% -> raw %d (want %d)" % (pct, raw, want))
        if raw < prev_raw:
            monotonic = False
        prev_raw = raw
    expect(monotonic, "duty ramp monotonically increasing")

    # ------------------------------------------------------- RPM plausibility
    time.sleep(2.0)                    # let the fan settle at full drive
    rpm = dev.rpm()
    expect(rpm > 500, "settled RPM above plausibility floor (%.0f > 500)"
           % rpm)

    # ----------------------------------------------- persistence round trip
    smoke_path = os.path.join(BASE_DIR, "emc2101_smoke.json")
    orig_sp = dev.scratchpad_get(0)
    orig_lh = dev.local_high_c
    path = dev.save_config(smoke_path)
    expect(path == smoke_path, "save_config wrote %s" % smoke_path)
    dev.scratchpad_set(0, orig_sp ^ 0xFF)
    dev.local_high_c = 55              # clobber two persisted domains
    report = dev.load_config(smoke_path, strict=True)
    expect(not report["diff"], "strict load verified clean (no diff)")
    expect(dev.scratchpad_get(0) == orig_sp,
           "scratchpad restored by load (%#x)" % dev.scratchpad_get(0))
    expect(dev.local_high_c == orig_lh,
           "local high limit restored by load (%.0f C)" % dev.local_high_c)
    try:
        open(smoke_path)
        os.remove(smoke_path)
    except OSError:
        pass
    restored_by_load = True

finally:
    # ------------------------------------------------ safety-net restore
    if not restored_by_load:
        _restore_snapshot()
        bad = [a for a in sorted(snapshot)
               if dev.read_reg(a) != snapshot[a]]
        expect(not bad, "safety-net restore byte-for-byte (%d regs)"
               % len(snapshot))
        if bad:
            print("[info] mismatched after restore: %r"
                  % ["%#02x" % a for a in bad])
    else:
        # The load proved the persistence semantics; clean up the bench
        # with the raw snapshot (the saved profile legitimately carries
        # mid-test state such as PROG/ALT_TCH, so a full-snapshot
        # equality check here would be wrong by design).
        _restore_snapshot()
        bad = [a for a in sorted(snapshot)
               if dev.read_reg(a) != snapshot[a]]
        expect(not bad, "safety-net restore byte-for-byte (%d regs)"
               % len(snapshot))

dev.close()

if failures:
    print("HW SMOKE TEST: FAIL (%d failed checks)" % len(failures))
    sys.exit(1)
print("HW SMOKE TEST: PASS")
