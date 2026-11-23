"""TACH-vs-PWM gating check (M1 follow-up, 2026-11-22 evening, round 2).

Context: with a 10 kOhm pull-up added to the TACH net, char_tach_diag.py
reads a live count (~7959 => ~678 RPM) although Fan Setting is 00h.
Reported caveat: some fans gate their tach output at 0% PWM duty, so the
tach may not be readable unless the drive is non-zero. This probe
quantifies the TACH count at the as-found Fan Setting (00h) versus a
known 50% drive to confirm whether the tach channel depends on
non-zero drive on this bench.

Method:
  A. Snapshot Configuration (0x03), Fan Configuration (0x4A),
     Fan Setting (0x4C).
  B. Enable ALT_TCH (Config bit 2); 1 s warm-up for the period
     measurement to lock.
  C. Phase A: sample TACH count 3x, 1 s apart, at the as-found setting.
  D. Write Fan Setting = 0x23 (50% at default PWM_F=0x17, eq. [6]);
     wait 4 s (spin-up drives 100% for 3.2 s on a 0->nonzero
     transition, SPIN_TIME=111 default).
  E. Phase B: sample TACH count 3x, 1 s apart.
  F. Restore snapshot; verify.

Interpretation: count is a live speed indicator, RPM = 5,400,000/count
(§13 / eq. [3]). Higher fan speed => LOWER count. If phase A shows a
stable non-sentinel count, the tach is readable at 0% drive on this
bench and the reported caveat does not apply here.

Mutating: Configuration (0x03), Fan Setting (0x4C). Self-restoring.
Self-contained (pure machine.I2C, no driver imports).
Bench: RPi Pico W (RP2040), USB-serial COM16, I2C0 SDA=GP0 / SCL=GP1.
Run:   python -m mpremote connect port:COM16 run scripts/pico/char_tach_pwm_gate.py
"""
import machine
import time

ADDR = 0x4C
i2c = machine.I2C(0, sda=machine.Pin(0), scl=machine.Pin(1), freq=100_000)


def rb(reg):
    return i2c.readfrom_mem(ADDR, reg, 1)[0]


def wb(reg, val):
    i2c.writeto_mem(ADDR, reg, bytes((val,)))


def tach_count():
    lo = rb(0x46)          # LSB first (interlock)
    hi = rb(0x47)
    return (hi << 8) | lo


def rpm(c):
    return None if c == 0xFFFF else 5_400_000 // c


CFG, FCFG, FS = 0x03, 0x4A, 0x4C
snap_cfg, snap_fcfg, snap_fs = rb(CFG), rb(FCFG), rb(FS)
print("snapshot: cfg=%02x fcfg=%02x fsetting=%02x"
      % (snap_cfg, snap_fcfg, snap_fs))

# --- enable ALT_TCH ----------------------------------------------------------
wb(CFG, rb(CFG) | 0x04)
print("alt_tch enabled; warming up 1 s")
time.sleep_ms(1000)


def sample(tag):
    for i in range(3):
        c = tach_count()
        r = rpm(c)
        print("  %s%d: count=%d%s"
              % (tag, i, c,
                 "" if r is None else "  (~%d RPM)" % r))
        time.sleep_ms(1000)


# --- phase A: as-found setting ----------------------------------------------
print("phase A: fs=%02x (as found)" % rb(FS))
sample("A ")

# --- phase B: 50% drive -------------------------------------------------------
wb(FS, 0x23)               # 50% at default PWM_F=0x17 (eq. [6])
print("wrote fs=23 (50%% drive); waiting 4 s (spin-up 3.2 s)")
time.sleep_ms(4000)
print("phase B: fs=%02x" % rb(FS))
sample("B ")

# --- restore ------------------------------------------------------------------
wb(CFG, snap_cfg)
wb(FS, snap_fs)
time.sleep_ms(50)
ok = (rb(CFG), rb(FCFG), rb(FS)) == (snap_cfg, snap_fcfg, snap_fs)
print("restore: %s (cfg=%02x fcfg=%02x fsetting=%02x)"
      % ("PASS" if ok else "FAIL", rb(CFG), rb(FCFG), rb(FS)))
