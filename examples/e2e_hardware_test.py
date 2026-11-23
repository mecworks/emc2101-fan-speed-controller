"""EMC2101 hardware E2E test — full public-API matrix on real silicon.

Self-restoring: snapshots every writable register at start and restores
plus verifies them byte-for-byte before exiting, so an interrupted run
leaves the chip at most temporarily misconfigured. Prints one PASS/FAIL
line per section and finally `E2E HARDWARE MATRIX: PASS` (exit 0) or
`E2E HARDWARE MATRIX: FAIL` (exit 1).

Board-aware: runs unchanged on all three dev platforms — RPi Pico W
(MicroPython, I2C0 GP0/GP1), ESP32-S3 (MicroPython, I2C0 GPIO41/42),
Raspberry Pi 3A+ (CPython/smbus2, bus 1).

Eleven sections: identity, temperatures/setpoints, manual/duty/PWM, LUT,
tach/RPM, faults/alerts, calibration, lifecycle, persistence (incl. the
cold-boot-with-profile scenario), presets, error model.

Cold boot on the MCU benches is two-phase: phase A saves a distinctive
profile, writes a flag file, and power-cycles the board with
machine.reset(); phase B (next run) constructs with config_file=<path>,
asserts the applied values, clears the flag, and then runs the full
matrix. On the Raspberry Pi leg the board cannot be power-cycled from
the host, so the cold-boot sub-test is approximated by constructing a
fresh driver instance against the live chip with the config_file kwarg.

Run:
    Pico W:     python -m mpremote connect port:COM16 run examples/e2e_hardware_test.py
    ESP32-S3:   python -m mpremote connect port:COM7 run examples/e2e_hardware_test.py
    RPi 3A+:    python3 examples/e2e_hardware_test.py        (on the Pi)
"""
import os
import sys
import time

from emc2101 import _regs as R
from emc2101._core import (ALERT_MODE_COMPARATOR, ALERT_MODE_INTERRUPT,
                          FILTER_LEVEL_2)
from emc2101._tables import IDEALITY_FACTORS, ideality_factor

FLAG_FILE = "/emc2101_e2e_coldboot.flag"
PROFILE_FILE = "/emc2101_e2e_profile.json"


def _exists(path):
    try:
        open(path)
        return True
    except OSError:
        return False


def build_device(config_file=None):
    """Construct an EMC2101 device for whichever platform we run on."""
    if sys.platform == "linux":
        from emc2101.cp import EMC2101
        return EMC2101(bus=1, config_file=config_file)
    import machine
    from emc2101.mp import EMC2101
    machine_name = os.uname().machine.upper()
    if "RP2" in machine_name:
        sda, scl = 0, 1            # Pico W I2C0
    else:
        sda, scl = 41, 42          # ESP32-S3 I2C0
    i2c = machine.I2C(0, sda=machine.Pin(sda), scl=machine.Pin(scl),
                      freq=100_000)
    return EMC2101(i2c, config_file=config_file)


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

failures = []
section_results = {}


def expect(cond, label):
    tag = "PASS" if cond else "FAIL"
    print("    [%s] %s" % (tag, label))
    if not cond:
        failures.append(label)


def expect_raises(exc_type, fn, label):
    try:
        fn()
    except exc_type:
        print("    [PASS] %s (raised %s)" % (label, exc_type.__name__))
        return
    except Exception as e:                     # noqa: broad on purpose
        print("    [FAIL] %s (wrong exception %s: %s)"
              % (label, type(e).__name__, e))
        failures.append(label)
        return
    print("    [FAIL] %s (no exception raised)" % label)
    failures.append(label)


def run_section(name, fn):
    print("--- section: %s ---" % name)
    try:
        fn()
        section_results[name] = "PASS"
    except Exception as e:                     # noqa: broad on purpose
        section_results[name] = "FAIL"
        failures.append("section %s crashed: %s: %s"
                        % (name, type(e).__name__, e))
        print("    [FAIL] section crashed: %s: %s"
              % (type(e).__name__, e))


# ------------------------------------------------------- cold-boot phase
phase_b = _exists(FLAG_FILE)
if phase_b:
    dev = build_device(config_file=PROFILE_FILE)
else:
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

CURVE = [(30, 25), (40, 40), (50, 55), (60, 70),
         (70, 85), (80, 90), (90, 95), (100, 100)]


def quantized_pct(pct):
    """What the LUT getter reports after storing pct on the live grid."""
    pwm_f = dev.read_reg(R.REG_PWM_F) & 0x1F
    return R.setting_to_duty_pct(R.duty_pct_to_setting(pct, pwm_f), pwm_f)


# ------------------------------------------------------------------ S1
def sec_identity():
    expect(dev.probe(), "device answers at %#x" % R.ADDR_FIXED)
    pid = dev.verify()
    expect(pid == R.PRODUCT_ID_PLAIN,
           "verify() product ID plain part (#%#x)" % pid)
    expect((dev.product_id, dev.mfg_id, dev.revision)
           == (R.PRODUCT_ID_PLAIN, R.MANUF_ID_SMSC, R.REVISION_EXPECTED),
           "identity trio 0x16/0x5D/0x01")
    expect(dev.part_info == (R.PRODUCT_ID_PLAIN, R.MANUF_ID_SMSC,
                             R.REVISION_EXPECTED),
           "part_info tuple matches")
    found = dev.scan()
    expect(R.ADDR_FIXED in found, "scan() finds %#x" % R.ADDR_FIXED)
    ara_present = R.ARA_GENERAL_CALL in found
    print("    [info] scan footprint: %r (ARA general-call device address "
          "%#x%s)" % (found, R.ARA_GENERAL_CALL,
                     " present" if ara_present else " absent"))


# ------------------------------------------------------------------ S2
def sec_temps_setpoints():
    lt = dev.local_temp_c
    rt = dev.remote_temp_c
    expect(-10.0 <= lt <= 95.0, "local temp plausible (%.1f C)" % lt)
    expect(R.TEMP_RANGE_MIN_C <= rt <= R.TEMP_RANGE_MAX_C,
           "remote temp plausible (%.3f C)" % rt)
    orig_lh = dev.local_high_c
    dev.local_high_c = 65
    expect(dev.local_high_c == 65, "local high limit round trip (65 C)")
    dev.local_high_c = orig_lh
    orig_rh = dev.remote_high_c
    dev.remote_high_c = 75.0
    expect(abs(dev.remote_high_c - 75.0) < 0.125,
           "remote high limit round trip (75.0 C, got %.3f)"
           % dev.remote_high_c)
    dev.remote_high_c = orig_rh
    orig_rl = dev.remote_low_c
    dev.remote_low_c = 5.0
    expect(abs(dev.remote_low_c - 5.0) < 0.125,
           "remote low limit round trip (5.0 C, got %.3f)"
           % dev.remote_low_c)
    dev.remote_low_c = orig_rl
    tc = dev.tcrit_c
    expect(0 <= tc <= 127, "TCRIT readable and sane (%d C)" % tc)
    orig_th = dev.tcrit_hysteresis_c
    dev.tcrit_hysteresis_c = 12
    expect(dev.tcrit_hysteresis_c == 12,
           "TCRIT hysteresis round trip (12 C)")
    dev.tcrit_hysteresis_c = orig_th


# ------------------------------------------------------------------ S3
def sec_manual_duty_pwm():
    dev.tach_input_enabled = True
    dev.manual = True
    prev_raw = -1
    monotonic = True
    for pct in (0, 25, 50, 75, 100):
        dev.set_duty_pct(pct)
        raw = dev.duty_cmd_raw
        want = R.duty_pct_to_setting(pct, dev.read_reg(R.REG_PWM_F) & 0x1F)
        expect(raw == want, "duty %d%% -> raw %d (want %d)" % (pct, raw, want))
        if raw < prev_raw:
            monotonic = False
        prev_raw = raw
    expect(monotonic, "duty ramp monotonically increasing")
    dev.duty_cmd_raw = 5
    expect(dev.duty_cmd_raw == 5, "duty_cmd_raw direct round trip (5)")
    orig_freq = dev.pwm_freq_hz
    dev.pwm_freq_hz = 25000.0
    actual = dev.pwm_freq_hz
    expect(abs(actual - 25000.0) / actual < 0.10,
           "PWM solver: requested 25000 Hz, achieved %.1f Hz" % actual)
    dev.pwm_freq_hz = orig_freq
    expect(abs(dev.pwm_freq_hz - orig_freq) / orig_freq < 0.02,
           "PWM frequency restored to %.1f Hz" % dev.pwm_freq_hz)
    dev.fan_output_inverted = True
    expect(dev.fan_output_inverted is True, "fan output inversion on")
    dev.fan_output_inverted = False
    expect(dev.fan_output_inverted is False, "fan output inversion off")
    dev.dac_enabled = True
    expect(dev.dac_enabled is True, "DAC mode on")
    dev.dac_enabled = False
    expect(dev.dac_enabled is False, "DAC mode off")
    dev.manual = False
    dev.set_duty_pct(0)


# ------------------------------------------------------------------ S4
def sec_lut():
    dev.tach_input_enabled = True
    # Capture the original LUT under a temporary PROG=1: while PROG=0
    # the setting bytes read back the LUT-driven duty (D35), not the
    # stored contents.
    _fc = dev.read_reg(R.REG_FAN_CFG)
    if not (_fc & R.FCFG_PROG):
        dev.write_reg(R.REG_FAN_CFG, bytes([_fc | R.FCFG_PROG]))
        time.sleep(0.1)   # D36: let the fan-control read-out settle
    orig_lut_raw = []
    for i in range(8):
        orig_lut_raw.append(dev.read_reg(R.REG_LUT_BASE + 2 * i))
        orig_lut_raw.append(dev.read_reg(R.REG_LUT_BASE + 2 * i + 1))
    if not (_fc & R.FCFG_PROG):
        dev.write_reg(R.REG_FAN_CFG, bytes([_fc]))
    dev.manual = False

    def restore_lut_raw():
        # LUT registers are read-only while PROG=0 (D35); do the raw
        # restore under a temporary PROG=1 and keep the final mode.
        fc = dev.read_reg(R.REG_FAN_CFG)
        if not (fc & R.FCFG_PROG):
            dev.write_reg(R.REG_FAN_CFG, bytes([fc | R.FCFG_PROG]))
            time.sleep(0.1)   # D36: let the fan-control read-out settle
        for i in range(8):
            dev.write_reg(R.REG_LUT_BASE + 2 * i,
                          bytes([orig_lut_raw[2 * i]]))
            dev.write_reg(R.REG_LUT_BASE + 2 * i + 1,
                          bytes([orig_lut_raw[2 * i + 1]]))
        if not (fc & R.FCFG_PROG):
            dev.write_reg(R.REG_FAN_CFG, bytes([fc]))

    dev.lut = CURVE
    got = dev.lut
    ok = len(got) == 8
    for i in range(8):
        t_in, p_in = CURVE[i]
        if got[i][0] != t_in or abs(got[i][1] - quantized_pct(p_in)) > 0.01:
            ok = False
    expect(ok, "bulk LUT round trip (8 pairs, quantized to grid)")
    idx3 = dev.lut_get_index(3)
    expect(idx3[0] == 60 and abs(idx3[1] - quantized_pct(70)) < 0.01,
           "lut_get_index(3) == (60, ~70%%): %r" % (idx3,))
    dev.lut_set_index(3, 60, 65)
    idx3 = dev.lut_get_index(3)
    expect(idx3[0] == 60 and abs(idx3[1] - quantized_pct(65)) < 0.01,
           "lut_set_index(3, 60, 65%%) took effect: %r" % (idx3,))
    orig_hys = dev.hysteresis_c
    dev.hysteresis_c = 8
    expect(dev.hysteresis_c == 8, "LUT hysteresis round trip (8 C)")
    dev.hysteresis_c = orig_hys
    # Force-register path: feed a synthetic temperature into the LUT.
    dev.force_enabled = False
    rpm_ambient = dev.rpm()
    dev.force_enabled = True
    dev.forced_temp_c = 75
    time.sleep(2.0)
    rpm_forced = dev.rpm()
    dev.force_enabled = False
    expect(rpm_forced > rpm_ambient * 1.2,
           "forced 75 C drove the LUT up (%.0f -> %.0f RPM)"
           % (rpm_ambient, rpm_forced))
    # Raw restore: the property setter requires strictly ascending
    # thresholds, so a POR-uniform original cannot round-trip through it.
    restore_lut_raw()


# ------------------------------------------------------------------ S5
def sec_tach_rpm():
    dev.tach_input_enabled = True
    dev.manual = True
    dev.set_duty_pct(100)
    time.sleep(2.0)
    rpm = dev.rpm()
    expect(rpm > 500, "settled RPM above plausibility floor (%.0f > 500)"
           % rpm)
    orig_thr = dev.tach_threshold
    dev.tach_threshold = 40000
    expect(dev.tach_threshold == 40000, "tach threshold round trip (40000)")
    expect(abs(dev.min_rpm - R.RPM_DIVISOR / 40000.0) < 0.01,
           "min_rpm view consistent with divisor (%.1f RPM)" % dev.min_rpm)
    dev.tach_threshold = orig_thr
    orig_tm = dev.tach_mode
    dev.tach_mode = R.TACH_M_SENTINEL_BELOW_MIN
    expect(dev.tach_mode == R.TACH_M_SENTINEL_BELOW_MIN,
           "TACH_M sentinel encoding round trip")
    dev.tach_mode = orig_tm
    dev.manual = False
    dev.set_duty_pct(0)


# ------------------------------------------------------------------ S6
def sec_faults_alerts():
    st = dev.status_raw()
    expect(isinstance(st, int) and 0 <= st <= 255,
           "status_raw() returns a raw byte (%d)" % st)
    alarms = dev.active_alarms()
    expect(isinstance(alarms, list), "active_alarms() returns a list: %r"
           % (alarms,))
    raw_before = dev.read_reg(R.REG_ALERT_MASK)
    dev.alert_mask = R.AMSK_INT | R.AMSK_HIGH
    raw_after = dev.read_reg(R.REG_ALERT_MASK)
    expect((raw_after & R.AMSK_DEFINED) == (R.AMSK_INT | R.AMSK_HIGH),
           "alert mask defined bits written")
    expect((raw_after & R.AMSK_RESERVED) == (raw_before & R.AMSK_RESERVED),
           "alert mask reserved bits preserved by RMW")
    dev.alert_mask = raw_before & R.AMSK_DEFINED
    dev.alert_mode = ALERT_MODE_COMPARATOR
    expect(dev.alert_mode == ALERT_MODE_COMPARATOR,
           "alert mode comparator")
    dev.alert_mode = ALERT_MODE_INTERRUPT
    expect(dev.alert_mode == ALERT_MODE_INTERRUPT,
           "alert mode interrupt")
    svc = dev.service_alert()
    expect(isinstance(svc, int), "service_alert() serviced (returned %d)"
           % svc)
    dev.clear_alert_mask()
    expect(True, "clear_alert_mask() completed")
    expect(dev.diode_fault() is False,
           "diode fault negative check (diode connected)")
    expect(isinstance(dev.busy(), bool), "busy() returns a bool")
    orig_cr = dev.conversion_rate
    dev.conversion_rate = 2.0
    expect(dev.conversion_rate == 2.0, "conversion rate round trip (2/s)")
    dev.conversion_rate = orig_cr
    orig_fl = dev.averaging_filter
    dev.averaging_filter = FILTER_LEVEL_2
    expect(dev.averaging_filter == FILTER_LEVEL_2,
           "averaging filter round trip (level 2)")
    dev.averaging_filter = orig_fl
    dev.dis_to_enabled = True
    expect(dev.dis_to_enabled is True, "DIS_TO on")
    dev.dis_to_enabled = False
    expect(dev.dis_to_enabled is False, "DIS_TO off")
    dev.fault_queue_enabled = True
    expect(dev.fault_queue_enabled is True, "fault queue on")
    dev.fault_queue_enabled = False
    expect(dev.fault_queue_enabled is False, "fault queue off")


# ------------------------------------------------------------------ S7
def sec_calibration():
    orig_idx = dev.ideality_factor_index
    dev.ideality_factor_index = 20
    expect(dev.ideality_factor_index == 20,
           "ideality index round trip (20)")
    factor = dev.ideality_factor
    expect(abs(factor - ideality_factor(20)) < 0.0005,
           "ideality factor decodes through table (%.4f)" % factor)
    nearest = dev.set_ideality_factor(1.0)
    expect(nearest in IDEALITY_FACTORS,
           "set_ideality_factor(1.0) nearest match (%.4f)" % nearest)
    orig_auto = dev.beta_auto_detect
    orig_beta = dev.beta_index
    dev.beta_auto_detect = False
    dev.beta_index = 3
    expect(dev.beta_auto_detect is False, "beta auto-detect off")
    expect(dev.beta_index == 3, "beta index round trip (3)")
    dev.beta_auto_detect = orig_auto
    dev.beta_index = orig_beta
    dev.ideality_factor_index = orig_idx


# ------------------------------------------------------------------ S8
def sec_lifecycle():
    dev.standby = True
    expect(dev.probe(), "chip still answers in standby")
    lt = dev.local_temp_c
    expect(-10.0 <= lt <= 95.0, "internal temp readable in standby (%.1f C)"
           % lt)
    dev.standby = False
    expect(dev.probe(), "chip answers after standby exit")
    expect_raises(ValueError, dev.one_shot,
                  "one_shot() refused outside standby/mixed mode")
    sp0 = dev.scratchpad_get(0)
    sp1 = dev.scratchpad_get(1)
    dev.scratchpad_set(0, 0x5A)
    dev.scratchpad_set(1, 0xA5)
    expect(dev.scratchpad_get(0) == 0x5A, "scratchpad 0 round trip (0x5A)")
    expect(dev.scratchpad_get(1) == 0xA5, "scratchpad 1 round trip (0xA5)")
    dev.scratchpad_set(0, sp0)
    dev.scratchpad_set(1, sp1)
    orig_en = dev.spin_up_enabled
    orig_drv = dev.spin_up_drive
    orig_tim = dev.spin_up_time_s
    orig_ft = dev.spin_up_fast_tach
    dev.spin_up_drive = 75
    dev.spin_up_time_s = 1.6
    dev.spin_up_fast_tach = False
    expect(dev.spin_up_enabled is True, "spin-up enabled (time set)")
    expect(dev.spin_up_drive == 75, "spin-up drive round trip (75%)")
    expect(dev.spin_up_time_s == 1.6, "spin-up time round trip (1.6 s)")
    expect(dev.spin_up_fast_tach is False, "spin-up fast-tach off")
    dev.spin_up_drive = orig_drv
    dev.spin_up_time_s = orig_tim
    dev.spin_up_fast_tach = orig_ft
    dev.fan_standby = True
    expect(dev.fan_standby is True, "fan standby on")
    dev.fan_standby = False
    expect(dev.fan_standby is False, "fan standby off")


# ------------------------------------------------------------------ S9
def sec_persistence():
    smoke_path = "/emc2101_e2e_smoke.json"
    orig_sp = dev.scratchpad_get(0)
    orig_lh = dev.local_high_c
    path = dev.save_config(smoke_path)
    expect(path == smoke_path, "save_config wrote %s" % smoke_path)
    dev.scratchpad_set(0, orig_sp ^ 0xFF)
    dev.local_high_c = 55
    report = dev.load_config(smoke_path, strict=True)
    expect(not report["diff"], "strict load verified clean (no diff)")
    expect(dev.scratchpad_get(0) == orig_sp,
           "scratchpad restored by load (%#x)" % dev.scratchpad_get(0))
    expect(dev.local_high_c == orig_lh,
           "local high limit restored by load (%.0f C)" % dev.local_high_c)
    missing = "/emc2101_e2e_missing_xyz.json"
    expect_raises(OSError, lambda: dev.load_config(missing),
                  "explicit load of a missing file raises OSError")
    corrupt_path = "/emc2101_e2e_corrupt.json"
    f = open(corrupt_path, "w")
    f.write("{ this is not json ]]")
    f.close()
    regs_before = [dev.read_reg(a) for a in (R.REG_CONFIG, R.REG_INT_LIMIT,
                                             R.REG_SCRATCHPAD_1)]
    expect_raises(ValueError, lambda: dev.load_config(corrupt_path),
                  "corrupt file rejected before any register write")
    regs_after = [dev.read_reg(a) for a in (R.REG_CONFIG, R.REG_INT_LIMIT,
                                            R.REG_SCRATCHPAD_1)]
    expect(regs_before == regs_after,
           "registers untouched by the rejected corrupt load")
    for p in (smoke_path, corrupt_path):
        try:
            os.remove(p)
        except OSError:
            pass
    # Cold-boot-with-profile scenario.
    if sys.platform == "linux":
        cb_path = os.path.expanduser("~/emc2101_e2e_cb.json")
        dev.save_config(cb_path)
        dev.scratchpad_set(0, dev.scratchpad_get(0) ^ 0xFF)
        dev2 = build_device(config_file=cb_path)
        expect(dev2.scratchpad_get(0) == dev.scratchpad_get(0) ^ 0xFF,
               "fresh instance auto-loaded the profile (approximation: no "
               "board power-cycle possible from the host)")
        dev2.close()
        try:
            os.remove(cb_path)
        except OSError:
            pass
    elif phase_b:
        expect(dev.local_high_c == 65,
               "cold boot: constructor auto-load applied local high (65 C)")
        expect(dev.scratchpad_get(0) == 0xAB,
               "cold boot: constructor auto-load applied scratchpad 0 (0xAB)")
        expect(dev.lut_get_index(0)[0] == 30,
               "cold boot: constructor auto-load applied LUT entry 0 (30 C)")
        try:
            os.remove(FLAG_FILE)
        except OSError:
            pass
        try:
            os.remove(PROFILE_FILE)
        except OSError:
            pass
    else:
        # Phase A: stage the profile, then power-cycle the board.
        dev.local_high_c = 65
        dev.scratchpad_set(0, 0xAB)
        dev.lut = CURVE
        dev.save_config(PROFILE_FILE)
        f = open(FLAG_FILE, "w")
        f.write("phase-b pending\n")
        f.close()
        print("    [info] staged profile + flag; power-cycling the board.")
        print("    [info] re-run this script once the board is back:")
        print("           python -m mpremote connect port:<PORT> "
              "run examples/e2e_hardware_test.py")
        import machine
        machine.reset()
        raise SystemExit(0)


# ----------------------------------------------------------------- S10
def sec_presets():
    dev.configure_4wire_fan(pwm_freq_hz=25000)
    expect(dev.tach_input_enabled is True,
           "preset switched ALERT/TACH pin to TACH input")
    actual = dev.pwm_freq_hz
    expect(abs(actual - 25000.0) / actual < 0.10,
           "preset applied PWM frequency (%.1f Hz)" % actual)
    expect(dev.spin_up_enabled is True, "preset spin-up enabled")
    expect(dev.spin_up_drive == 100, "preset spin-up drive 100%")
    expect(dev.spin_up_time_s == 3.2, "preset spin-up time 3.2 s")
    expect(dev.spin_up_fast_tach is True, "preset spin-up fast-tach on")


# ----------------------------------------------------------------- S11
def sec_error_model():
    expect_raises(ValueError, lambda: dev.set_duty_pct(101),
                  "set_duty_pct(101) rejected")
    expect_raises(ValueError, lambda: dev.set_duty_pct(-1),
                  "set_duty_pct(-1) rejected")
    expect_raises(ValueError, lambda: setattr(dev, "local_high_c", 128),
                  "local_high_c=128 rejected")
    expect_raises(ValueError, lambda: setattr(dev, "hysteresis_c", 128),
                  "hysteresis_c=128 rejected")
    expect_raises(ValueError,
                  lambda: setattr(dev, "tcrit_hysteresis_c", 128),
                  "tcrit_hysteresis_c=128 rejected")
    expect_raises(ValueError, lambda: setattr(dev, "pwm_freq_hz", 0.0),
                  "pwm_freq_hz=0 rejected")
    expect_raises(ValueError, lambda: dev.scratchpad_set(3, 1),
                  "scratchpad_set(3, 1) rejected")
    expect_raises(ValueError,
                  lambda: setattr(dev, "conversion_rate", 0.0),
                  "conversion_rate=0 rejected")
    bad_lut = [(20, 10), (10, 20)] + [(127, 100)] * 6
    expect_raises(ValueError, lambda: setattr(dev, "lut", bad_lut),
                  "non-ascending LUT rejected")
    expect_raises(ValueError, lambda: setattr(dev, "lut", [(10, 10)]),
                  "short LUT rejected")
    expect_raises(ValueError, lambda: dev.lut_set_index(8, 1, 1),
                  "lut_set_index(8, ...) rejected")
    expect_raises(ValueError, lambda: dev.read_reg(0x100),
                  "read_reg(0x100) rejected")
    expect_raises(ValueError,
                  lambda: setattr(dev, "remote_low_c", -100.0),
                  "remote_low_c=-100 rejected")
    expect_raises(ValueError,
                  lambda: setattr(dev, "spin_up_time_s", 99.0),
                  "spin_up_time_s=99 rejected")


# ------------------------------------------------------------------- run
if phase_b:
    print("phase B: verifying the cold-boot auto-load, then running the "
          "full matrix")
try:
    run_section("identity", sec_identity)
    run_section("temperatures_setpoints", sec_temps_setpoints)
    run_section("manual_duty_pwm", sec_manual_duty_pwm)
    run_section("lut", sec_lut)
    run_section("tach_rpm", sec_tach_rpm)
    run_section("faults_alerts", sec_faults_alerts)
    run_section("calibration", sec_calibration)
    run_section("lifecycle", sec_lifecycle)
    run_section("persistence", sec_persistence)
    run_section("presets", sec_presets)
    run_section("error_model", sec_error_model)
finally:
    # ---------------------------------------------- safety-net restore
    bad = [a for a in sorted(snapshot)
           if dev.read_reg(a) != snapshot[a]]
    if bad:
        # Fan-domain registers are read-only while PROG=0 (D35): repair
        # under a temporary PROG=1, then restore the final mode byte.
        dev.write_reg(R.REG_FAN_CFG,
                      bytes([snapshot[R.REG_FAN_CFG] | R.FCFG_PROG]))
        for a in bad:
            dev.write_reg(a, bytes([snapshot[a]]))
        dev.write_reg(R.REG_FAN_CFG, bytes([snapshot[R.REG_FAN_CFG]]))
        time.sleep(0.1)   # D36: let the read-out settle before verifying
        bad2 = [a for a in sorted(snapshot)
                if dev.read_reg(a) != snapshot[a]]
        expect(not bad2, "safety-net restore repaired %d drifted register(s)"
               % len(bad))
    else:
        expect(True, "final state matches pre-run snapshot (%d registers)"
               % len(snapshot))
    dev.close()

print("")
for name in ("identity", "temperatures_setpoints", "manual_duty_pwm",
             "lut", "tach_rpm", "faults_alerts", "calibration",
             "lifecycle", "persistence", "presets", "error_model"):
    print("section %-24s %s" % (name, section_results.get(name, "SKIP")))

if failures:
    print("E2E HARDWARE MATRIX: FAIL (%d failed checks)" % len(failures))
    sys.exit(1)
print("E2E HARDWARE MATRIX: PASS")
