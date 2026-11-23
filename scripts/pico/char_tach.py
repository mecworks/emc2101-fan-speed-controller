"""TACH / TACH_M / BUSY characterization for the Pico W bench (M1).

Bench: RPi Pico W (RP2040), USB-serial COM16, I2C0 SDA=GP0 / SCL=GP1.
Run:   python -m mpremote connect port:COM16 run scripts/pico/char_tach.py

Self-contained (pure machine.I2C, no driver imports). Mutating probe:
snapshots Configuration (0x03), Fan Configuration (0x4A) and Fan Setting
(0x4C) at start, exercises ALT_TCH, the TACH_M field and manual duty, then
restores and verifies all three registers. Leaves the chip at its power-on
defaults. Requires the bench fan to be connected (FAN output, tach to the
ALERT/TACH pin).
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


def rpm_of(count):
    return 5400000.0 / count if count else 0.0


CFG, FCFG, FS = 0x03, 0x4A, 0x4C
snap_cfg, snap_fcfg, snap_fs = rb(CFG), rb(FCFG), rb(FS)
print("snapshot: cfg=%02x fcfg=%02x fsetting=%02x" % (snap_cfg, snap_fcfg, snap_fs))

# --- enable TACH input (ALT_TCH, config bit 2) ---------------------------
wb(CFG, snap_cfg | 0x04)
time.sleep_ms(150)
c = tach_count()
print("floor speed (POR defaults, ALT_TCH on): count=%d rpm=%.0f" % (c, rpm_of(c)))

# --- TACH_M sweep ---------------------------------------------------------
print("tachi_m sweep (base clock 360 kHz, CLK_SEL=0):")
for tm in range(4):
    wb(FCFG, (snap_fcfg & 0xFC) | tm)
    time.sleep_ms(150)
    c = tach_count()
    tag = "  (ffffh sentinel)" if c == 0xFFFF else ""
    print("  tachi_m=%d: count=%d rpm=%.0f%s" % (tm, c, rpm_of(c), tag))
wb(FCFG, snap_fcfg)

# --- manual duty sweep ----------------------------------------------------
pwm_f = rb(0x4D) & 0x1F
print("manual duty sweep (prog=1, pwm_f=%d, full scale s=%d):" % (pwm_f, 2 * pwm_f))
for s in (0x0A, 0x17, 0x2E):
    wb(FS, s)
    time.sleep_ms(800)
    c = tach_count()
    print("  s=%02x (%.0f%%): count=%d rpm=%.0f" % (s, s / (2.0 * pwm_f) * 100.0, c, rpm_of(c)))

# --- BUSY cadence ---------------------------------------------------------
print("busy cadence (40 status polls, ~10 ms apart):")
runs = []
prev = None
start = time.ticks_ms()
for _ in range(40):
    b = (rb(0x02) >> 7) & 1
    if b != prev:
        runs.append("%d@%dms" % (b, time.ticks_diff(time.ticks_ms(), start)))
        prev = b
print("  busy transitions: %s" % ", ".join(runs))

# --- restore --------------------------------------------------------------
wb(CFG, snap_cfg)
wb(FCFG, snap_fcfg)
wb(FS, snap_fs)
time.sleep_ms(50)
ok = (rb(CFG), rb(FCFG), rb(FS)) == (snap_cfg, snap_fcfg, snap_fs)
print("restore: %s (cfg=%02x fcfg=%02x fsetting=%02x)"
      % ("PASS" if ok else "FAIL", rb(CFG), rb(FCFG), rb(FS)))
