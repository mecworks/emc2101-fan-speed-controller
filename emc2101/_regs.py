"""Register map, bit-field constants, and fixed-point helpers for the
SMSC/Microchip EMC2101 SMBus fan controller.

Leaf module: imports nothing (no package imports, no third-party). Every
value is sourced from datasheet Rev 2.54 (06-16-09); section references are
given per group. Full extraction with citations: research/emc2101-register-map.md.

Protocol facts baked into this design (M1 live-silicon confirmed where noted):
- Fixed 7-bit SMBus address 0x4C; single-byte transactions only; the register
  pointer does NOT auto-increment across transactions.
- Over-long reads fail silently: the chip releases the bus after the first
  byte and the master reads 0xFF padding (M1, 2026-11-22). Callers must
  therefore enforce one-byte accesses by construction.
"""

# --- Bus / identity --------------------------------------------------------
ADDR_FIXED = 0x4C            # S4.7: fixed 7-bit SMBus slave address
ARA_GENERAL_CALL = 0x06      # S4.6: ARA general-call address (informational)

PRODUCT_ID_PLAIN = 0x16      # S6.24/Table 6.31: EMC2101
PRODUCT_ID_R = 0x28          # S6.24/Table 6.31: EMC2101-R
MANUF_ID_SMSC = 0x5D         # S6.25
REVISION_EXPECTED = 0x01     # S6.26

# Retry ladder (ms) applied by both transports around every transaction.
# Baseline per the sibling driver; retuned against M1 observations: rung 2
# (30 ms) exceeds the chip's ~25 ms SMBus TIMEOUT (S4.8), so a desynced
# chip-side interface state machine resets before the second retry (M1
# finding, 2026-11-22: bare Send Byte left the next transaction failing with
# EIO until the timeout window elapsed). len+1 attempts total.
RETRY_DELAYS_MS = (10, 30, 60, 100, 200, 400)

# --- Register addresses (S6; dual-address aliases noted) --------------------
REG_INT_TEMP = 0x00          # R: internal temperature
REG_EXT_TEMP_MSB = 0x01      # R: external temp MSB - read FIRST (interlock)
REG_STATUS = 0x02            # R: status (read has side effects, S6.4)
REG_CONFIG = 0x03            # R/W: configuration (alias 0x09)
REG_CONFIG_ALIAS = 0x09
REG_CONV_RATE = 0x04         # R/W: conversion rate (alias 0x0A)
REG_CONV_RATE_ALIAS = 0x0A
REG_INT_LIMIT = 0x05         # R/W: internal temp limit (alias 0x0B)
REG_INT_LIMIT_ALIAS = 0x0B
REG_EXT_HIGH_MSB = 0x07      # R/W: ext high limit MSB (alias 0x0D)
REG_EXT_HIGH_MSB_ALIAS = 0x0D
REG_EXT_LOW_MSB = 0x08       # R/W: ext low limit MSB (alias 0x0E)
REG_EXT_LOW_MSB_ALIAS = 0x0E
REG_EXT_FORCE = 0x0C         # R/W: forced LUT input temperature
REG_ONE_SHOT = 0x0F          # W: initiate conversion (self-clearing)
REG_EXT_TEMP_LSB = 0x10      # R: external temp fraction (.5/.25/.125 bits)
REG_SCRATCHPAD_1 = 0x11      # R/W: scratchpad (no function)
REG_SCRATCHPAD_2 = 0x12      # R/W: scratchpad (no function)
REG_EXT_HIGH_LSB = 0x13      # R/W: ext high limit fraction
REG_EXT_LOW_LSB = 0x14       # R/W: ext low limit fraction
REG_ALERT_MASK = 0x16        # R/W: alert mask (reserved bits read as 1)
REG_IDEALITY = 0x17          # R/W: ideality factor table index
REG_BETA = 0x18              # R/W: beta compensation
REG_TCRIT = 0x19             # R/W: TCRIT limit (locked until TCRITOVRD set)
REG_TCRIT_HYST = 0x21        # R/W: TCRIT hysteresis (1 LSB = 1 C)
REG_TACH_LO = 0x46           # R: TACH count low - read FIRST (interlock)
REG_TACH_HI = 0x47           # R: TACH count high
REG_TACH_LIMIT_LO = 0x48     # R/W: TACH limit low
REG_TACH_LIMIT_HI = 0x49     # R/W: TACH limit high
REG_FAN_CFG = 0x4A           # R/W: fan configuration
REG_SPINUP = 0x4B            # R/W: fan spin-up configuration
REG_FAN_SETTING = 0x4C       # R/W: fan drive level (RO while PROG=0)
REG_PWM_F = 0x4D             # R/W: PWM frequency numerator
REG_PWM_D = 0x4E             # R/W: PWM frequency divider (CLK_OVR=1 only)
REG_LUT_HYST = 0x4F          # R/W: LUT hysteresis (1 LSB = 1 C)
REG_LUT_BASE = 0x50          # R/W: LUT T1,S1 ... T8,S8 through REG_LUT_END
REG_LUT_END = 0x5F
REG_FILTER = 0xBF            # R/W: averaging filter / comparator select
REG_PRODUCT_ID = 0xFD        # R: product ID
REG_MANUF_ID = 0xFE          # R: manufacturer ID
REG_REVISION = 0xFF          # R: revision

# --- Status register bits (S6.4) --------------------------------------------
ST_BUSY = 0x80               # ADC converting (never triggers interrupt)
ST_INT_HIGH = 0x40           # internal temp >= limit
ST_EEPROM = 0x20             # -R EEPROM not found at boot (always 0 on plain)
ST_EXT_HIGH = 0x10           # ext diode >= high limit
ST_EXT_LOW = 0x08            # ext diode <= low limit
ST_FAULT = 0x04              # external diode fault (open/VDD-short)
ST_TCRIT = 0x02              # ext diode >= TCRIT
ST_TACH = 0x01               # TACH count > limit (fan too slow)

# --- Configuration register bits (S6.5) --------------------------------------
CFG_MASK = 0x80              # ALERT pin masked (sticky until cleared)
CFG_STANDBY = 0x40           # low-power standby
CFG_FAN_STANDBY = 0x20       # fan inactive during standby
CFG_DAC = 0x10               # linear DAC output instead of PWM
CFG_DIS_TO = 0x08            # disable SMBus timeout
CFG_ALT_TCH = 0x04           # ALERT/TACH pin becomes hi-Z TACH input
CFG_TCRITOVRD = 0x02         # unlock TCRIT (modifiable once, then power cycle)
CFG_QUEUE = 0x01             # alert after 3 consecutive out-of-limit samples

# --- Alert mask register (S6.11) ---------------------------------------------
# Default 0xA4: reserved bits 7,5,2 read back as 1 and must be preserved in
# any read-modify-write (mask writes to the defined field only).
AMSK_INT = 0x40              # INT_MSK
AMSK_HIGH = 0x10             # HIGH_MSK
AMSK_LOW = 0x08              # LOW_MSK
AMSK_TCRIT = 0x02            # TCRIT_MSK
AMSK_TACH = 0x01             # TACH_MSK
AMSK_DEFINED = 0x5B          # union of defined bits (RMW target field)
AMSK_RESERVED = 0xA4         # bits that read as 1 and must be preserved

# --- Fan configuration register bits (S6.16) ---------------------------------
FCFG_FORCE = 0x40            # LUT input = EXT_FORCE register
FCFG_PROG = 0x20             # 1: manual (Fan Setting drives fan); 0: LUT mode
FCFG_POLARITY = 0x10         # 1: inverted drive (00h = max)
FCFG_CLK_SEL = 0x08          # 1: 1.4 kHz base clock; 0: 360 kHz
FCFG_CLK_OVR = 0x04          # 1: base clock divided by PWM_D
FCFG_TACH_M_MASK = 0x03      # TACH_M[1:0]
TACH_M_FALSE_BELOW_MIN = 0x00    # default; false readings below min RPM
TACH_M_SENTINEL_BELOW_MIN = 0x01  # 01/10/11: FFFFh below min detectable RPM

# --- Spin-up register fields (S6.17) -----------------------------------------
SU_FAST_TACH = 0x20          # abort spin-up early when TACH < limit
SU_SPIN_DRIVE_MASK = 0x18    # SPIN_DRIVE[1:0]
SU_SPIN_TIME_MASK = 0x07     # SPIN_TIME[2:0]
SU_DRIVE_BYPASS = 0x00
SU_DRIVE_50 = 0x08
SU_DRIVE_75 = 0x10
SU_DRIVE_100 = 0x18
SU_SPIN_TIME_POR = 0x07      # POR default SPIN_TIME encoding (3.2 s)

# --- Averaging filter register (S6.23) ---------------------------------------
FLT_LEVEL_MASK = 0x06        # FILTER[2:1]
FLT_LEVEL_OFF = 0x00
FLT_LEVEL_1 = 0x02
FLT_LEVEL_1_ALT = 0x04       # duplicated encoding per datasheet
FLT_LEVEL_2 = 0x06
FLT_COMP = 0x01              # 1: comparator mode (live-following ALERT pin)

# --- Beta compensation register (S6.13) --------------------------------------
BETA_ENABLE = 0x08           # 1: autodetect on (default); BETA[2:0] ignored
BETA_FIELD_MASK = 0x07       # BETA[2:0]
BETA_DISABLE_AUTODETECT = 0x07  # value to write for diode-connected transistors

# --- Physical constants -------------------------------------------------------
RPM_DIVISOR = 5400000        # eq.[3]: RPM = 5,400,000 / TACH_COUNT
EXT_TEMP_STEP_C = 0.125      # external channel resolution
INT_TEMP_STEP_C = 1.0        # internal channel resolution
TEMP_RANGE_MIN_C = -64.0
TEMP_RANGE_MAX_C = 127.875
SENTINEL_OPEN_RAW = 0x3F8    # +127.0 C: open DP-DN or DP-VDD short (FAULT set)
SENTINEL_SHORT_RAW = 0x3FF   # +127.875 C: DN-GND/DN-DN short (FAULT not set)
TACH_SENTINEL = 0xFFFF       # count sentinel: input disabled / stopped
BASE_CLOCK_360K_HZ = 360000  # CLK_SEL=0
BASE_CLOCK_1P4K_HZ = 1400    # CLK_SEL=1
PWM_F_MAX = 31               # recommended max-resolution setting (S6.19)
LUT_ENTRIES = 8              # T1,S1 .. T8,S8
LUT_PAIR_STRIDE = 2          # even offset = T, odd offset = S


# --- Fixed-point helpers ------------------------------------------------------

def ext_temp_to_raw(temp_c):
    """Encode degrees Celsius into the 11-bit two's-complement external
    temperature format (0.125 C steps, range -64.0..+127.875).

    Raises ValueError outside the datasheet-guaranteed range. (The raw
    field is 11 bits wide and could encode down to -128.0, but the
    datasheet only guarantees -64.0..+127.875, so the tighter bound is
    enforced.)"""
    steps = int(round(float(temp_c) * 8.0))
    steps_min = int(round(TEMP_RANGE_MIN_C * 8.0))    # -512
    steps_max = int(round(TEMP_RANGE_MAX_C * 8.0))    # 1023
    if steps < steps_min or steps > steps_max:
        raise ValueError("external temp %r out of range -64.0..+127.875 C"
                         % (temp_c,))
    return steps & 0x7FF


def ext_raw_to_temp(raw):
    """Decode an 11-bit two's-complement raw external temperature to C."""
    v = raw & 0x7FF
    if v >= 0x400:
        v -= 0x800
    return v * EXT_TEMP_STEP_C


def int_temp_to_raw(temp_c):
    """Encode degrees Celsius into the 8-bit signed internal temperature
    format (1 C steps, range -128..+127).

    Raises ValueError outside the representable range."""
    t = int(round(float(temp_c)))
    if t < -128 or t > 127:
        raise ValueError("internal temp %r out of range -128..+127 C"
                         % (temp_c,))
    return t & 0xFF


def int_raw_to_temp(raw):
    """Decode an 8-bit signed raw internal temperature to C."""
    v = raw & 0xFF
    if v >= 0x80:
        v -= 0x100
    return float(v)


def duty_pct_to_setting(pct, pwm_f):
    """Quantize a percent duty (0..100) onto the current PWM_F grid.

    Effective duty = S / (2*pwm_f) * 100% (eq.[6]); full scale is reached at
    S = 2*pwm_f and higher requests clamp there (datasheet: S > 2*PWM_F =>
    100%). Raises ValueError on bad inputs."""
    if not 1 <= pwm_f <= PWM_F_MAX:
        raise ValueError("pwm_f must be 1..%d" % PWM_F_MAX)
    if pct < 0.0 or pct > 100.0:
        raise ValueError("duty must be 0..100 %%")
    s = int(round(float(pct) * (2.0 * pwm_f) / 100.0))
    return min(s, 2 * pwm_f)


def setting_to_duty_pct(setting, pwm_f):
    """Dequantize a raw Fan Setting value to its effective duty percentage.

    Values above 2*pwm_f report 100.0 (the hardware clamps them)."""
    if not 1 <= pwm_f <= PWM_F_MAX:
        raise ValueError("pwm_f must be 1..%d" % PWM_F_MAX)
    if setting < 0:
        raise ValueError("setting must be >= 0")
    return min(setting, 2 * pwm_f) / (2.0 * pwm_f) * 100.0


def rpm_from_count(count):
    """Convert a TACH count to RPM (eq.[3]).

    Returns 0.0 for a zero count or the FFFFh sentinel (stopped /
    unmeasurable) per decision O6."""
    if count <= 0 or count >= TACH_SENTINEL:
        return 0.0
    return float(RPM_DIVISOR) / count


def count_from_rpm(rpm):
    """Inverse of rpm_from_count: counter value for a target RPM.

    Returns 0 for non-positive rpm."""
    if rpm <= 0:
        return 0
    return int(round(float(RPM_DIVISOR) / rpm))
