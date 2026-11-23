"""TACH channel diagnostics (M1 follow-up, 2026-11-22 evening).

Context: the chip reads TACH 0xFFFF at every duty although the fan is
verified spinning (~660 RPM floor speed) and the TACH net shows live
low-going pulses at the ALERT pin (multimeter continuity beeps on every
closure; nothing else on the net). This probe checks the chip-side
picture:

  1. Does ALT_TCH (Config bit 2) actually latch?
  2. Is the TACH counter frozen, or just presenting the sentinel?
  3. Are TACH_M writes honored at the 360 kHz base clock
     (empirical answer to ambiguity A3 / Note 6.2)?
  4. Does switching to the 1.4 kHz base clock (CLK_SEL=1) change anything?

Mutating: snapshots and restores Configuration (0x03), Fan Configuration
(0x4A) and Fan Setting (0x4C); verifies restoration. Everything else is
read-only. Self-contained (pure machine.I2C, no driver imports).

Bench: RPi Pico W (RP2040), USB-serial COM16, I2C0 SDA=GP0 / SCL=GP1.
Run:   python -m mpremote connect port:COM16 run scripts/pico/char_tach_diag.py
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


CFG, FCFG, FS = 0x03, 0x4A, 0x4C
snap_cfg, snap_fcfg, snap_fs = rb(CFG), rb(FCFG), rb(FS)
print("snapshot: cfg=%02x fcfg=%02x fsetting=%02x"
      % (snap_cfg, snap_fcfg, snap_fs))

# --- 1. ALT_TCH latch check -------------------------------------------------
before = rb(CFG)
want = before | 0x04
wb(CFG, want)
after = rb(CFG)
print("1. alt_tch: before=%02x wrote=%02x readback=%02x -> %s"
      % (before, want, after,
         "LATCHED" if (after & 0x04) else "NOT LATCHED"))

# --- 2. counter movement (two reads 1 s apart, ALT_TCH=1) -------------------
time.sleep_ms(500)
c1 = tach_count()
time.sleep_ms(1000)
c2 = tach_count()
print("2. tach with alt_tch=1: t0=%d (%s)  t+1s=%d (%s)"
      % (c1, "sentinel" if c1 == 0xFFFF else "",
         c2, "sentinel" if c2 == 0xFFFF else ""))

# --- 3. TACH_M write acceptance at 360 kHz base (A3) ------------------------
print("3. tachi_m write acceptance (base 360 kHz, clk_sel=0):")
for tm in range(4):
    wb(FCFG, (rb(FCFG) & 0xFC) | tm)
    got = rb(FCFG)
    field = got & 0x03
    time.sleep_ms(300)
    c = tach_count()
    print("   write=%d readback=%02x (field=%d) count=%d%s"
          % (tm, got, field, c,
             "  <- ignored" if field != tm else ""))

# --- 4. 1.4 kHz base clock trial (CLK_SEL=1, TACH_M=00) ----------------------
wb(FCFG, (rb(FCFG) & 0xF7) | 0x08)
got = rb(FCFG)
time.sleep_ms(1000)
c = tach_count()
print("4. clk_sel=1 trial: fcfg readback=%02x count=%d%s"
      % (got, c, "  (sentinel)" if c == 0xFFFF else ""))

# --- restore -----------------------------------------------------------------
wb(CFG, snap_cfg)
wb(FCFG, snap_fcfg)
wb(FS, snap_fs)
time.sleep_ms(50)
ok = (rb(CFG), rb(FCFG), rb(FS)) == (snap_cfg, snap_fcfg, snap_fs)
print("restore: %s (cfg=%02x fcfg=%02x fsetting=%02x)"
      % ("PASS" if ok else "FAIL", rb(CFG), rb(FCFG), rb(FS)))
