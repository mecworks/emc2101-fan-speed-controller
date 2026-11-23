"""M4 live acceptance probe (Pico W bench): JSON persistence against real
silicon.

Flow: verify identity -> save_config() to a flash path -> mutate a spread
of registers through the public API -> load_config() (strict post-apply
read-back ON) -> verify every mutated value returned to its saved
original -> delete the probe file.

Self-restoring: normally load_config's strict verification proves the
chip is back where it started. As a safety net (house rule inherited
from probe_m3), every persisted register is also snapshotted raw up
front and restored byte-for-byte in the finally block whenever the
load-based restore did not run or did not verify clean. No config file
is left on flash. TCRIT is deliberately NOT mutated: its one-time
unlock must not be consumed by a probe.

Prerequisite: package deployed via
    python tools/deploy_mp.py --port COM16
Run with:
    python -m mpremote connect port:COM16 run scripts/pico/probe_persist.py
"""
import machine
import os
import sys

from emc2101 import _regs as R
from emc2101.mp import EMC2101

PROBE_FILE = "/emc2101_probe.json"


def _exists(p):
    """MicroPython has no os.path; probe with open()."""
    try:
        f = open(p)
        f.close()
        return True
    except OSError:
        return False

i2c = machine.I2C(0, sda=machine.Pin(0), scl=machine.Pin(1), freq=100_000)
dev = EMC2101(i2c)

failures = []


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
snapshot = {}
for addr in SNAP:
    snapshot[addr] = dev.read_reg(addr)
print("snapshot: %d registers captured" % len(snapshot))

restored_by_load = False

try:
    # ------------------------------------------------------------ identity
    pid, mid, rev = dev.part_info
    expect(pid == 0x16 and mid == 0x5D and rev == 0x01,
           "part_info (%#x, %#x, %#x)" % (pid, mid, rev))

    # --------------------------------------------------------- originals
    orig_local_high = dev.local_high_c
    orig_duty_raw = dev.duty_cmd_raw
    orig_sp1 = dev.scratchpad_get(0)
    orig_sp2 = dev.scratchpad_get(1)
    orig_conv = dev.conversion_rate
    orig_hyst = dev.hysteresis_c
    orig_lut = dev.lut
    orig_freq = dev.pwm_freq_hz
    print("info: originals: local_high=%r duty_raw=%d sp=(%#x,%#x) "
          "conv=%r hyst=%r lut[0]=%r freq=%.1f Hz"
          % (orig_local_high, orig_duty_raw, orig_sp1, orig_sp2,
             orig_conv, orig_hyst, orig_lut[0], orig_freq))

    # -------------------------------------------------------------- save
    path = dev.save_config(PROBE_FILE)
    expect(path == PROBE_FILE, "save_config returned effective path")
    expect(_exists(PROBE_FILE), "config file exists on flash")
    leftovers = [f for f in os.listdir("/") if f.endswith(".tmp")]
    expect(leftovers == [], "no temp files left behind")

    # ------------------------------------------------------------- mutate
    dev.local_high_c = 60
    dev.set_duty_pct(50)
    dev.scratchpad_set(0, 0x5A)
    dev.scratchpad_set(1, 0xA5)
    dev.conversion_rate = 2.0
    dev.hysteresis_c = 6
    dev.lut = [(20, 10), (30, 20), (40, 30), (50, 40),
               (60, 50), (70, 60), (80, 70), (90, 80)]
    dev.pwm_freq_hz = 25000.0

    expect(dev.local_high_c == 60, "mutation: local_high_c = 60")
    expect(dev.duty_cmd_raw != orig_duty_raw,
           "mutation: duty raised (raw %d -> %d)"
           % (orig_duty_raw, dev.duty_cmd_raw))
    expect(dev.scratchpad_get(0) == 0x5A and dev.scratchpad_get(1) == 0xA5,
           "mutation: scratchpads swapped")
    expect(abs(dev.conversion_rate - 2.0) < 1e-9, "mutation: conv rate 2/s")
    expect(dev.hysteresis_c == 6, "mutation: hysteresis 6 C")
    expect(dev.lut[0][0] == 20 and dev.lut[7][0] == 90,
           "mutation: LUT curve programmed")
    expect(abs(dev.pwm_freq_hz - 25000.0) <= 25000.0 * 0.10
           and dev.pwm_freq_hz != orig_freq,
           "mutation: PWM solver moved to nearest grid point (%.1f Hz)"
           % dev.pwm_freq_hz)

    # --------------------------------------------------------------- load
    report = dev.load_config(PROBE_FILE)     # strict read-back ON
    expect(bool(report.get("applied")), "load_config applied")
    expect(not report.get("diff"), "strict post-apply read-back clean")
    if report.get("warnings"):
        print("info: warnings: %s" % "; ".join(report["warnings"]))

    # ----------------------------------------------------------- restored
    ok = (dev.local_high_c == orig_local_high
          and dev.duty_cmd_raw == orig_duty_raw
          and dev.scratchpad_get(0) == orig_sp1
          and dev.scratchpad_get(1) == orig_sp2
          and abs(dev.conversion_rate - orig_conv) < 1e-9
          and dev.hysteresis_c == orig_hyst
          and dev.lut == orig_lut
          and abs(dev.pwm_freq_hz - orig_freq) < 1e-6)
    expect(ok, "all mutated values restored to originals")
    if ok and not report.get("diff"):
        restored_by_load = True

    # ------------------------------------------------------------- cleanup
    if _exists(PROBE_FILE):
        os.remove(PROBE_FILE)
    expect(not _exists(PROBE_FILE), "probe file removed from flash")
except Exception as exc:                     # noqa: BLE001 - probe scope
    print("[FAIL] unexpected exception: %s: %s"
          % (type(exc).__name__, exc))
    failures.append("unexpected exception %s" % type(exc).__name__)
finally:
    # ---------------------------------------------------- safety-net restore
    if not restored_by_load:
        for addr in sorted(snapshot):
            dev.write_reg(addr, bytes([snapshot[addr]]))
        bad = [a for a in sorted(snapshot)
               if dev.read_reg(a) != snapshot[a]]
        if bad:
            print("[FAIL] safety-net restore mismatch at %s"
                  % ", ".join(hex(a) for a in bad))
            failures.append("safety-net restore mismatch")
        else:
            print("safety-net restore: all %d registers verified"
                  % len(snapshot))
    else:
        print("restore: proven by load_config strict read-back")
    if _exists(PROBE_FILE):
        os.remove(PROBE_FILE)
    dev.close()

if failures:
    print("M4 LIVE PROBE FAILED: %d issue(s)" % len(failures))
    for f in failures:
        print("  - %s" % f)
    sys.exit(1)
print("M4 LIVE PROBE PASSED")
