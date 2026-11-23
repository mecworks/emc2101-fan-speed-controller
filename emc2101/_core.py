"""Shared device core for the EMC2101 (platform-neutral).

M3 scope: the full protocol-level API - identity, temperatures and
setpoints, status/alerts, manual duty, PWM output configuration, LUT,
tachometer/RPM, spin-up, calibration, scratchpad, power modes, presets,
and the raw-tier register accessors. M4 adds JSON persistence on top of
this surface; M5 adds live E2E validation.

The transport is a duck-typed object implementing the single-byte contract:
    read_byte(reg) -> int
    write_byte(reg, value) -> None
    probe() -> bool
    scan() -> iterable[int]
    delay_ms(ms) -> None
    close() -> None

Protocol facts relied upon here (datasheet Rev 2.54; M1 live-confirmed):
- Single-byte transactions only; the register pointer does NOT
  auto-increment across transactions.
- Data Read Interlock: external temp reads MSB-first (01h then 10h);
  TACH count reads LSB-first (46h then 47h).
- Reading Status (02h) has side effects: in interrupt mode it clears all
  latched bits and auto-sets MASK if any alarm bit was set. Every member
  that reads Status documents this.
- Fan Setting + LUT registers are RO while PROG=0 (LUT mode); writes to
  them require PROG=1 (the "PROG dance").
- TCRIT (19h) is locked at 85 C until Config.TCRITOVRD is set; the unlock
  permits exactly ONE modification, after which a power cycle re-locks it.
"""

from ._faults import DiodeFaultError
from ._regs import (ADDR_FIXED, AMSK_DEFINED, AMSK_HIGH, AMSK_INT, AMSK_LOW,
                    AMSK_TACH, AMSK_TCRIT, BETA_DISABLE_AUTODETECT,
                    BETA_ENABLE, BETA_FIELD_MASK, BASE_CLOCK_1P4K_HZ,
                    BASE_CLOCK_360K_HZ, CFG_ALT_TCH, CFG_DAC, CFG_DIS_TO,
                    CFG_FAN_STANDBY, CFG_MASK, CFG_QUEUE, CFG_STANDBY,
                    CFG_TCRITOVRD, FCFG_CLK_OVR, FCFG_CLK_SEL, FCFG_FORCE,
                    FCFG_POLARITY, FCFG_PROG, FCFG_TACH_M_MASK,
                    FLT_COMP, FLT_LEVEL_1, FLT_LEVEL_1_ALT, FLT_LEVEL_2,
                    FLT_LEVEL_MASK, FLT_LEVEL_OFF, LUT_ENTRIES,
                    MANUF_ID_SMSC, PRODUCT_ID_PLAIN, PRODUCT_ID_R,
                    REVISION_EXPECTED, REG_ALERT_MASK, REG_BETA, REG_CONFIG,
                    REG_CONV_RATE, REG_EXT_FORCE, REG_EXT_HIGH_LSB,
                    REG_EXT_HIGH_MSB, REG_EXT_LOW_LSB, REG_EXT_LOW_MSB,
                    REG_EXT_TEMP_LSB, REG_EXT_TEMP_MSB, REG_FAN_CFG,
                    REG_FAN_SETTING, REG_FILTER, REG_IDEALITY, REG_INT_LIMIT,
                    REG_INT_TEMP, REG_LUT_BASE, REG_LUT_HYST, REG_MANUF_ID,
                    REG_ONE_SHOT, REG_PRODUCT_ID, REG_PWM_D, REG_PWM_F,
                    REG_REVISION, REG_SCRATCHPAD_1, REG_SPINUP,
                    REG_STATUS, REG_TACH_HI, REG_TACH_LIMIT_HI,
                    REG_TACH_LIMIT_LO, REG_TACH_LO, REG_TCRIT, REG_TCRIT_HYST,
                    SENTINEL_OPEN_RAW, SENTINEL_SHORT_RAW, ST_BUSY,
                    ST_EEPROM, ST_EXT_HIGH, ST_EXT_LOW, ST_FAULT,
                    ST_INT_HIGH, ST_TACH, ST_TCRIT, SU_DRIVE_100,
                    SU_DRIVE_50, SU_DRIVE_75, SU_DRIVE_BYPASS, SU_FAST_TACH,
                    SU_SPIN_DRIVE_MASK, SU_SPIN_TIME_MASK,
                    ext_raw_to_temp, ext_temp_to_raw,
                    int_raw_to_temp, int_temp_to_raw, rpm_from_count,
                    setting_to_duty_pct, duty_pct_to_setting,
                    count_from_rpm)
from ._tables import (CONV_RATES_PER_S, IDEALITY_FACTORS,
                      IDEALITY_SETTINGS_MIN, SPINUP_TIMES_S, conv_rate_encode,
                      ideality_factor as _ideality_factor_lookup,
                      spinup_time as _spinup_time_decode)

# --- Public enum values ------------------------------------------------------
# alert_mode() / .alert_mode property values (Averaging Filter ALERT_COMP bit).
ALERT_MODE_INTERRUPT = 0     # default: latching ALERT pin, ARA handshake
ALERT_MODE_COMPARATOR = 1    # live-following ALERT pin; MASK ineffective

# averaging_filter() property values (FILTER[2:1], duplicated encoding folded).
FILTER_OFF = 0
FILTER_LEVEL_1 = 1
FILTER_LEVEL_2 = 2

# Spin-up drive percentages mapped onto SPIN_DRIVE[1:0] field encodings.
_DRIVE_PCTS = (0, 50, 75, 100)          # 0 == bypass
_DRIVE_FIELDS = (SU_DRIVE_BYPASS, SU_DRIVE_50, SU_DRIVE_75, SU_DRIVE_100)

# (status bit, mask bit, human name) for active_alarms(); BUSY/FAULT/EEPROM
# are excluded: BUSY never triggers an interrupt, FAULT is surfaced through
# diode_fault()/remote_temp_c(), EEPROM is always 0 on the plain part.
_ALARM_BITS = (
    (ST_INT_HIGH, AMSK_INT, "internal-high"),
    (ST_EXT_HIGH, AMSK_HIGH, "ext-high"),
    (ST_EXT_LOW, AMSK_LOW, "ext-low"),
    (ST_TCRIT, AMSK_TCRIT, "tcrit"),
    (ST_TACH, AMSK_TACH, "tach-slow"),
)


def _pwm_freq_hz(clk_sel, pwm_f, pwm_d, clk_ovr):
    """Achievable PWM frequency from the four governing fields.

    f = 360 kHz / (2*PWM_F)            (CLK_SEL=0)
    f = 1.4 kHz / (2*PWM_F)            (CLK_SEL=1)
    f = 360 kHz / (2*PWM_F*PWM_D)      (CLK_SEL=0, CLK_OVR=1; eq. [5])

    The datasheet documents the PWM_D divide for the 360 kHz base only;
    with CLK_SEL=1 the getter/solver ignore CLK_OVR (documented gap).
    Raises ValueError on degenerate divisors."""
    if not 1 <= pwm_f <= 31:
        raise ValueError("pwm_f must be 1..31")
    denom = 2 * pwm_f
    if clk_sel == 0:
        if clk_ovr:
            if not 1 <= pwm_d <= 0xFF:
                raise ValueError("pwm_d must be 1..255")
            denom *= pwm_d
        return float(BASE_CLOCK_360K_HZ) / denom
    return float(BASE_CLOCK_1P4K_HZ) / denom


def _solve_pwm(target_hz):
    """Nearest achievable (pwm_f, pwm_d, clk_sel, clk_ovr) for target_hz.

    Exhausts the documented space: both bases, PWM_F 1..31, and the
    CLK_OVR/PWM_D divide on the 360 kHz path (PWM_D 1..255). Ties resolve
    to the finer duty grid (larger denominator), then to the higher
    PWM_F, i.e. toward the recommended max-resolution path
    (PWM_F=31, CLK_OVR=1)."""
    best_key = None
    best = None
    for clk_sel in (0, 1):
        for pwm_f in range(1, 32):
            candidates = [(pwm_f, 1, 0)]
            if clk_sel == 0:
                for pwm_d in range(1, 256):
                    candidates.append((pwm_f, pwm_d, 1))
            for pwm_f_, pwm_d_, ovr in candidates:
                freq = _pwm_freq_hz(clk_sel, pwm_f_, pwm_d_, ovr)
                err = abs(freq - target_hz)
                denom = 2 * pwm_f_ * (pwm_d_ if ovr else 1)
                key = (err, -denom, -pwm_f_)
                if best_key is None or key < best_key:
                    best_key = key
                    best = (pwm_f_, pwm_d_, clk_sel, ovr)
    return best


class EMC2101:
    """EMC2101 driver core bound to a transport object."""

    def __init__(self, transport, addr=ADDR_FIXED, config_file=None):
        """Bind a transport and record the configuration file path.

        addr must be the fixed SMBus address 0x4C (ValueError otherwise).
        config_file is the resolved JSON config path owned by the facade
        (save/load semantics land in M4; the attribute exists now so the
        public surface is stable from M2).
        """
        if addr != ADDR_FIXED:
            raise ValueError("EMC2101 SMBus address is fixed at %#x"
                             % ADDR_FIXED)
        self._t = transport
        self.addr = addr
        self.config_path = config_file

    # ------------------------------------------------------------------
    # Lifecycle & raw access
    # ------------------------------------------------------------------

    def verify(self):
        """Read the identity trio (FDh/FEh/FFh) and check it against the
        expected SMSC EMC2101 values.

        Returns the product-ID byte on success (0x16 plain / 0x28 -R; both
        share the register map, and the -R EEPROM auto-load is simulated by
        this driver's JSON persistence). Raises ValueError on an identity
        mismatch and OSError if the device does not respond.
        """
        product = self._t.read_byte(REG_PRODUCT_ID)
        manuf = self._t.read_byte(REG_MANUF_ID)
        revision = self._t.read_byte(REG_REVISION)
        if manuf != MANUF_ID_SMSC or revision != REVISION_EXPECTED \
                or product not in (PRODUCT_ID_PLAIN, PRODUCT_ID_R):
            raise ValueError("unexpected identity: fd=%#02x fe=%#02x "
                             "ff=%#02x" % (product, manuf, revision))
        return product

    def probe(self):
        """True if the device answers at its address (single attempt, no
        retry ladder - diagnostics must stay fast)."""
        return self._t.probe()

    def scan(self):
        """Addresses present on the bus (delegates to the transport)."""
        return self._t.scan()

    def close(self):
        """Release platform resources (no-op on MicroPython)."""
        self._t.close()

    def read_reg(self, reg, n=1):
        """Raw-tier read: n sequential single-byte reads over consecutive
        addresses reg..reg+n-1 (the pointer does not auto-increment).

        Debug/dump ergonomics only - the core API never uses this across
        interlock boundaries. Returns a single int for n=1, else a tuple.
        """
        if not 0 <= reg <= 0xFF:
            raise ValueError("register address must be 0..255")
        if n < 1:
            raise ValueError("n must be >= 1")
        vals = []
        for i in range(n):
            vals.append(self._t.read_byte((reg + i) & 0xFF))
        return vals[0] if n == 1 else tuple(vals)

    def write_reg(self, reg, buf):
        """Raw-tier write: sequential single-byte writes over consecutive
        addresses starting at reg. Same caveats as read_reg()."""
        if not 0 <= reg <= 0xFF:
            raise ValueError("register address must be 0..255")
        for i, b in enumerate(bytearray(buf)):
            self._t.write_byte((reg + i) & 0xFF, b)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False

    def __repr__(self):
        return "<emc2101.EMC2101 addr=%#02x>" % self.addr

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    @property
    def product_id(self):
        """Product ID byte FDh (0x16 plain / 0x28 -R)."""
        return self._t.read_byte(REG_PRODUCT_ID)

    @property
    def mfg_id(self):
        """Manufacturer ID byte FEh (0x5D SMSC)."""
        return self._t.read_byte(REG_MANUF_ID)

    @property
    def revision(self):
        """Revision byte FFh (0x01)."""
        return self._t.read_byte(REG_REVISION)

    @property
    def part_info(self):
        """Identity triple (product_id, mfg_id, revision)."""
        return (self.product_id, self.mfg_id, self.revision)

    # ------------------------------------------------------------------
    # Temperatures & setpoints
    # ------------------------------------------------------------------

    @property
    def local_temp_c(self):
        """Internal die temperature in C (8-bit signed, 1 C steps;
        guaranteed range 0..85 C per datasheet)."""
        return int_raw_to_temp(self._t.read_byte(REG_INT_TEMP))

    @property
    def remote_temp_c(self):
        """External diode temperature in C (11-bit, 0.125 C steps).

        Reads the interlock pair MSB-first (01h then 10h). Raises
        DiodeFaultError on the fault sentinels instead of returning
        +127.0/+127.875: those codes are reserved for open-circuit
        (raw 0x3F8) and short (raw 0x3FF) conditions, so a genuine
        reading at the extreme end of the scale is indistinguishable
        and treated as a fault (decision D13)."""
        msb = self._t.read_byte(REG_EXT_TEMP_MSB)
        lsb = self._t.read_byte(REG_EXT_TEMP_LSB)
        raw = ((msb & 0xFF) << 3) | (lsb & 0x07)
        if raw == SENTINEL_OPEN_RAW:
            raise DiodeFaultError(
                "external diode fault: open circuit (DP-DN open or "
                "DP-VDD short)")
        if raw == SENTINEL_SHORT_RAW:
            raise DiodeFaultError(
                "external diode fault: short (DN-GND or DN-DN short)")
        return ext_raw_to_temp(raw)

    @property
    def local_high_c(self):
        """Internal temperature high limit in C (05h, 8-bit signed)."""
        return int_raw_to_temp(self._t.read_byte(REG_INT_LIMIT))

    @local_high_c.setter
    def local_high_c(self, temp_c):
        self._t.write_byte(REG_INT_LIMIT, int_temp_to_raw(temp_c))

    @property
    def remote_high_c(self):
        """External high limit in C (07h+13h, 0.125 C steps)."""
        return self._read_ext_limit(REG_EXT_HIGH_MSB, REG_EXT_HIGH_LSB)

    @remote_high_c.setter
    def remote_high_c(self, temp_c):
        self._write_ext_limit(REG_EXT_HIGH_MSB, REG_EXT_HIGH_LSB, temp_c)

    @property
    def remote_low_c(self):
        """External low limit in C (08h+14h, 0.125 C steps)."""
        return self._read_ext_limit(REG_EXT_LOW_MSB, REG_EXT_LOW_LSB)

    @remote_low_c.setter
    def remote_low_c(self, temp_c):
        self._write_ext_limit(REG_EXT_LOW_MSB, REG_EXT_LOW_LSB, temp_c)

    @property
    def tcrit_c(self):
        """TCRIT critical limit in C (19h, 8-bit signed; trips the fan to
        full-on). Locked at 85 C after power-up."""
        return int_raw_to_temp(self._t.read_byte(REG_TCRIT))

    @tcrit_c.setter
    def tcrit_c(self, temp_c):
        """Set TCRIT, arming the one-time unlock when needed.

        HARDWARE RULE: TCRIT can be modified ONCE per power cycle. The
        first change arms Config.TCRITOVRD and consumes the unlock; any
        further change requires a power cycle. Writing the current value
        is a no-op and does NOT consume the unlock."""
        new = int_temp_to_raw(temp_c)
        cur = self._t.read_byte(REG_TCRIT)
        if new == cur:
            return
        cfg = self._t.read_byte(REG_CONFIG)
        if not (cfg & CFG_TCRITOVRD):
            self._t.write_byte(REG_CONFIG, cfg | CFG_TCRITOVRD)
        self._t.write_byte(REG_TCRIT, new)

    @property
    def tcrit_hysteresis_c(self):
        """TCRIT hysteresis in C (21h, 0..127; clear threshold =
        TCRIT - hysteresis)."""
        return self._t.read_byte(REG_TCRIT_HYST) & 0x7F

    @tcrit_hysteresis_c.setter
    def tcrit_hysteresis_c(self, value):
        if not 0 <= value <= 0x7F:
            raise ValueError("tcrit_hysteresis_c must be 0..127")
        reg = self._t.read_byte(REG_TCRIT_HYST)
        self._t.write_byte(REG_TCRIT_HYST, (reg & ~0x7F) | int(value))

    def _read_ext_limit(self, msb_reg, lsb_reg):
        msb = self._t.read_byte(msb_reg)
        lsb = self._t.read_byte(lsb_reg)
        return ext_raw_to_temp(((msb & 0xFF) << 3) | (lsb & 0x07))

    def _write_ext_limit(self, msb_reg, lsb_reg, temp_c):
        raw = ext_temp_to_raw(temp_c)
        self._t.write_byte(msb_reg, (raw >> 3) & 0xFF)
        self._t.write_byte(lsb_reg, raw & 0x07)

    # ------------------------------------------------------------------
    # Status & alerts
    # ------------------------------------------------------------------

    def status_raw(self):
        """Read the Status register (02h) and return the raw byte.

        DESTRUCTIVE READ: in interrupt mode this clears all latched bits
        and auto-sets the sticky MASK bit if any alarm bit was set; in
        comparator mode active bits persist. Call deliberately."""
        return self._t.read_byte(REG_STATUS)

    def active_alarms(self):
        """Names of currently active AND unmasked alarms.

        Performs the destructive Status read (see status_raw()), then
        filters each set bit through the Alert Mask register. Returns a
        list drawn from: internal-high, ext-high, ext-low, tcrit,
        tach-slow."""
        status = self._t.read_byte(REG_STATUS)
        mask = self._t.read_byte(REG_ALERT_MASK)
        names = []
        for st_bit, msk_bit, name in _ALARM_BITS:
            if (status & st_bit) and not (mask & msk_bit):
                names.append(name)
        return names

    @property
    def alert_mask(self):
        """Alert mask state, defined bits only (16h & 0x5B). Reserved
        bits (7,5,2) read back as 1 and are excluded here; the setter
        preserves them via read-modify-write."""
        return self._t.read_byte(REG_ALERT_MASK) & AMSK_DEFINED

    @alert_mask.setter
    def alert_mask(self, value):
        if not 0 <= value <= AMSK_DEFINED:
            raise ValueError("alert_mask must fit within %#x"
                             % AMSK_DEFINED)
        cur = self._t.read_byte(REG_ALERT_MASK)
        self._t.write_byte(REG_ALERT_MASK,
                           (cur & ~AMSK_DEFINED) | (value & AMSK_DEFINED))

    @property
    def alert_mode(self):
        """ALERT pin behaviour: ALERT_MODE_INTERRUPT (latching, default)
        or ALERT_MODE_COMPARATOR (live-following; MASK ineffective on the
        pin, ARA not answered)."""
        if self._t.read_byte(REG_FILTER) & FLT_COMP:
            return ALERT_MODE_COMPARATOR
        return ALERT_MODE_INTERRUPT

    @alert_mode.setter
    def alert_mode(self, mode):
        if mode not in (ALERT_MODE_INTERRUPT, ALERT_MODE_COMPARATOR):
            raise ValueError("alert_mode must be ALERT_MODE_INTERRUPT or "
                             "ALERT_MODE_COMPARATOR")
        reg = self._t.read_byte(REG_FILTER)
        if mode == ALERT_MODE_COMPARATOR:
            reg |= FLT_COMP
        else:
            reg &= ~FLT_COMP
        self._t.write_byte(REG_FILTER, reg)

    def service_alert(self):
        """ISR step: perform the Status read that services the ALERT pin
        (clears latches; auto-sets MASK in interrupt mode). Returns the
        status byte just read. Re-arm afterwards with clear_alert_mask()."""
        return self._t.read_byte(REG_STATUS)

    def clear_alert_mask(self):
        """Clear the sticky Config.MASK bit to re-arm the ALERT pin."""
        cfg = self._t.read_byte(REG_CONFIG)
        self._t.write_byte(REG_CONFIG, cfg & ~CFG_MASK)

    def diode_fault(self):
        """True if the FAULT status bit is set (destructive Status read;
        see status_raw()). Covers open-circuit and VDD-short conditions."""
        return bool(self._t.read_byte(REG_STATUS) & ST_FAULT)

    def busy(self):
        """True while the ADC is converting (Status.BUSY; destructive
        Status read, see status_raw())."""
        return bool(self._t.read_byte(REG_STATUS) & ST_BUSY)

    # ------------------------------------------------------------------
    # Manual mode & duty
    # ------------------------------------------------------------------

    @property
    def manual(self):
        """True when Fan Setting drives the fan directly (~PROG).

        NOTE: toggling this also flips the writability of the Fan Setting
        and LUT registers (RO while manual is False / LUT mode)."""
        return not (self._t.read_byte(REG_FAN_CFG) & FCFG_PROG)

    @manual.setter
    def manual(self, value):
        fc = self._t.read_byte(REG_FAN_CFG)
        if value:
            fc &= ~FCFG_PROG
        else:
            fc |= FCFG_PROG
        self._t.write_byte(REG_FAN_CFG, fc)

    def set_duty_pct(self, pct):
        """Drive the fan at pct percent (0..100), quantized onto the
        current PWM_F grid (effective duty = S/(2*PWM_F)). Applies
        immediately in manual mode; in LUT mode the Fan Setting register
        is read-only and the write has no effect."""
        pwm_f = self._t.read_byte(REG_PWM_F) & 0x1F
        s = duty_pct_to_setting(pct, pwm_f)
        self._t.write_byte(REG_FAN_SETTING, s)

    @property
    def duty_cmd_raw(self):
        """Raw 6-bit Fan Setting value (0..63)."""
        return self._t.read_byte(REG_FAN_SETTING) & 0x3F

    @duty_cmd_raw.setter
    def duty_cmd_raw(self, value):
        if not 0 <= value <= 0x3F:
            raise ValueError("duty_cmd_raw must be 0..63")
        self._t.write_byte(REG_FAN_SETTING, value & 0x3F)

    # ------------------------------------------------------------------
    # PWM / DAC output configuration
    # ------------------------------------------------------------------

    @property
    def pwm_freq_hz(self):
        """Actual PWM output frequency computed from the current
        PWM_F/PWM_D/CLK_SEL/CLK_OVR fields (eq. [5]/[6])."""
        fc = self._t.read_byte(REG_FAN_CFG)
        pwm_f = self._t.read_byte(REG_PWM_F) & 0x1F
        pwm_d = self._t.read_byte(REG_PWM_D) & 0xFF
        return _pwm_freq_hz(bool(fc & FCFG_CLK_SEL), pwm_f, pwm_d,
                            bool(fc & FCFG_CLK_OVR))

    @pwm_freq_hz.setter
    def pwm_freq_hz(self, target_hz):
        """Program the nearest achievable PWM frequency to target_hz.

        Solves across PWM_F (1..31), PWM_D (1..255), CLK_SEL and
        CLK_OVR; ties prefer the finer duty grid (max-resolution path).
        Achievable range approx. 22.8 Hz .. 180 kHz. Writes FAN_CFG
        first so the old PWM_F stays valid during the transition."""
        if target_hz <= 0:
            raise ValueError("frequency must be > 0")
        pwm_f, pwm_d, clk_sel, clk_ovr = _solve_pwm(float(target_hz))
        fc = self._t.read_byte(REG_FAN_CFG)
        fc = (fc & ~(FCFG_CLK_SEL | FCFG_CLK_OVR))
        if clk_sel:
            fc |= FCFG_CLK_SEL
        if clk_ovr:
            fc |= FCFG_CLK_OVR
        self._t.write_byte(REG_FAN_CFG, fc)
        self._t.write_byte(REG_PWM_F, pwm_f & 0x1F)
        if clk_ovr:
            self._t.write_byte(REG_PWM_D, pwm_d & 0xFF)

    @property
    def fan_output_inverted(self):
        """Drive inversion (FanCfg.POLARITY): True means 00h = max drive.
        Distinct from any counting-edge polarity concept - renamed from
        the sibling's pwm_polarity to avoid a semantic trap."""
        return bool(self._t.read_byte(REG_FAN_CFG) & FCFG_POLARITY)

    @fan_output_inverted.setter
    def fan_output_inverted(self, value):
        fc = self._t.read_byte(REG_FAN_CFG)
        if value:
            fc |= FCFG_POLARITY
        else:
            fc &= ~FCFG_POLARITY
        self._t.write_byte(REG_FAN_CFG, fc)

    @property
    def dac_enabled(self):
        """Linear 6-bit DAC output mode (Config.DAC) instead of PWM.

        EXPERIMENTAL: the bench has not exercised DAC mode; the hardware
        note applies - remove the FAN pull-up jumper before use."""
        return bool(self._t.read_byte(REG_CONFIG) & CFG_DAC)

    @dac_enabled.setter
    def dac_enabled(self, value):
        cfg = self._t.read_byte(REG_CONFIG)
        if value:
            cfg |= CFG_DAC
        else:
            cfg &= ~CFG_DAC
        self._t.write_byte(REG_CONFIG, cfg)

    @property
    def pwm_clk_sel(self):
        """Raw-tier: CLK_SEL bit (False = 360 kHz base, True = 1.4 kHz)."""
        return bool(self._t.read_byte(REG_FAN_CFG) & FCFG_CLK_SEL)

    @pwm_clk_sel.setter
    def pwm_clk_sel(self, value):
        fc = self._t.read_byte(REG_FAN_CFG)
        if value:
            fc |= FCFG_CLK_SEL
        else:
            fc &= ~FCFG_CLK_SEL
        self._t.write_byte(REG_FAN_CFG, fc)

    @property
    def pwm_div(self):
        """Raw-tier: PWM_D divider byte (used only when CLK_OVR=1)."""
        return self._t.read_byte(REG_PWM_D) & 0xFF

    @pwm_div.setter
    def pwm_div(self, value):
        if not 1 <= value <= 0xFF:
            raise ValueError("pwm_div must be 1..255")
        self._t.write_byte(REG_PWM_D, value & 0xFF)

    # ------------------------------------------------------------------
    # LUT
    # ------------------------------------------------------------------

    @property
    def lut(self):
        """The 8-entry LUT as a list of (temp_c, duty_pct) tuples.

        Thresholds are integer degrees C (signed 8-bit); duties are
        dequantized through the CURRENT PWM_F grid. Entries are ordered
        T1..T8 (ascending thresholds)."""
        pwm_f = self._t.read_byte(REG_PWM_F) & 0x1F
        pairs = []
        for i in range(LUT_ENTRIES):
            t = self._t.read_byte(REG_LUT_BASE + 2 * i)
            s = self._t.read_byte(REG_LUT_BASE + 2 * i + 1)
            t_signed = t if t < 0x80 else t - 0x100
            pairs.append((float(t_signed),
                          setting_to_duty_pct(s & 0x3F, pwm_f)))
        return pairs

    @lut.setter
    def lut(self, pairs):
        """Program all 8 LUT entries from a list of (temp_c, duty_pct).

        Thresholds must ascend strictly (equal thresholds make later
        entries unreachable). Duties quantize onto the current PWM_F
        grid. Uses the PROG dance: if the chip is in LUT mode (PROG=0,
        registers RO) PROG is temporarily set, the 16 bytes written, and
        the original Fan Configuration restored."""
        encoded = self._encode_lut(pairs)
        self._with_prog_writable(lambda: self._write_lut_bytes(encoded))

    def lut_get_index(self, index):
        """One LUT entry as (temp_c, duty_pct); index 0..7."""
        if not 0 <= index < LUT_ENTRIES:
            raise ValueError("index must be 0..%d" % (LUT_ENTRIES - 1))
        pwm_f = self._t.read_byte(REG_PWM_F) & 0x1F
        t = self._t.read_byte(REG_LUT_BASE + 2 * index)
        s = self._t.read_byte(REG_LUT_BASE + 2 * index + 1)
        t_signed = t if t < 0x80 else t - 0x100
        return (float(t_signed), setting_to_duty_pct(s & 0x3F, pwm_f))

    def lut_set_index(self, index, temp_c, duty_pct):
        """Program one LUT entry (same validation/PROG dance as the bulk
        setter, minus the ascending check)."""
        if not 0 <= index < LUT_ENTRIES:
            raise ValueError("index must be 0..%d" % (LUT_ENTRIES - 1))
        pwm_f = self._t.read_byte(REG_PWM_F) & 0x1F
        t = int_temp_to_raw(temp_c)
        s = duty_pct_to_setting(duty_pct, pwm_f)
        self._with_prog_writable(
            lambda: self._t.write_byte(REG_LUT_BASE + 2 * index, t))
        self._with_prog_writable(
            lambda: self._t.write_byte(REG_LUT_BASE + 2 * index + 1, s))

    @property
    def hysteresis_c(self):
        """LUT hysteresis in C (4Fh, 0..127): once an entry engages, the
        next-lower entry is checked only below threshold - hysteresis."""
        return self._t.read_byte(REG_LUT_HYST) & 0x7F

    @hysteresis_c.setter
    def hysteresis_c(self, value):
        if not 0 <= value <= 0x7F:
            raise ValueError("hysteresis_c must be 0..127")
        reg = self._t.read_byte(REG_LUT_HYST)
        self._t.write_byte(REG_LUT_HYST, (reg & ~0x7F) | int(value))

    @property
    def force_enabled(self):
        """True when the LUT input is forced to the EXT_FORCE register
        instead of the measured external temperature (limits still use
        the measured value)."""
        return bool(self._t.read_byte(REG_FAN_CFG) & FCFG_FORCE)

    @force_enabled.setter
    def force_enabled(self, value):
        fc = self._t.read_byte(REG_FAN_CFG)
        if value:
            fc |= FCFG_FORCE
        else:
            fc &= ~FCFG_FORCE
        self._t.write_byte(REG_FAN_CFG, fc)

    @property
    def forced_temp_c(self):
        """Forced LUT-input temperature in C (0Ch, 8-bit signed)."""
        return int_raw_to_temp(self._t.read_byte(REG_EXT_FORCE))

    @forced_temp_c.setter
    def forced_temp_c(self, temp_c):
        self._t.write_byte(REG_EXT_FORCE, int_temp_to_raw(temp_c))

    def _encode_lut(self, pairs):
        """Validate and encode a full LUT; returns 16 (addr, value) pairs.

        All validation happens BEFORE any bus traffic so a bad profile
        cannot leave a partially-written LUT behind."""
        if len(pairs) != LUT_ENTRIES:
            raise ValueError("lut must contain exactly %d pairs"
                             % LUT_ENTRIES)
        pwm_f = self._t.read_byte(REG_PWM_F) & 0x1F
        encoded = []
        prev_t = None
        for i in range(LUT_ENTRIES):
            try:
                temp_c, duty_pct = pairs[i]
            except (TypeError, ValueError):
                raise ValueError("lut entry %d is not a (temp, duty) "
                                 "pair" % i)
            t = int_temp_to_raw(temp_c)
            s = duty_pct_to_setting(duty_pct, pwm_f)
            t_val = int(round(float(temp_c)))
            if prev_t is not None and t_val <= prev_t:
                raise ValueError("lut thresholds must ascend strictly "
                                 "(entry %d: %r after %r)"
                                 % (i, temp_c, prev_t))
            prev_t = t_val
            encoded.append((REG_LUT_BASE + 2 * i, t))
            encoded.append((REG_LUT_BASE + 2 * i + 1, s))
        return encoded

    def _write_lut_bytes(self, encoded):
        for addr, value in encoded:
            self._t.write_byte(addr, value)

    def _with_prog_writable(self, fn):
        """Run fn while guaranteeing PROG=1 (Fan Setting/LUT writable).

        If the chip was in LUT mode (PROG=0) the original Fan
        Configuration byte is restored afterwards, even if fn raises."""
        fc = self._t.read_byte(REG_FAN_CFG)
        if fc & FCFG_PROG:
            fn()
            return
        self._t.write_byte(REG_FAN_CFG, fc | FCFG_PROG)
        try:
            fn()
        finally:
            self._t.write_byte(REG_FAN_CFG, fc)

    # ------------------------------------------------------------------
    # Tachometer & RPM
    # ------------------------------------------------------------------

    def rpm(self, pulses_per_rev=2):
        """Fan speed in RPM from the TACH counter.

        Reads the interlock pair LSB-first (46h then 47h). Formula:
        RPM = 5,400,000/count x 2/pulses_per_rev (the counter assumes 2
        pulses/rev). Returns 0.0 for a zero count or the FFFFh sentinel
        (input disabled / fan stopped / below min detectable RPM)."""
        if pulses_per_rev < 1:
            raise ValueError("pulses_per_rev must be >= 1")
        lo = self._t.read_byte(REG_TACH_LO)
        hi = self._t.read_byte(REG_TACH_HI)
        count = ((hi & 0xFF) << 8) | (lo & 0xFF)
        r = rpm_from_count(count)
        if r == 0.0:
            return 0.0
        return r * (2.0 / float(pulses_per_rev))

    @property
    def tach_threshold(self):
        """TACH limit count (48h/49h, 16-bit): alarm when the count
        EXCEEDS this value (fan slower than expected). Default FFFFh =
        effectively disabled."""
        lo = self._t.read_byte(REG_TACH_LIMIT_LO)
        hi = self._t.read_byte(REG_TACH_LIMIT_HI)
        return ((hi & 0xFF) << 8) | (lo & 0xFF)

    @tach_threshold.setter
    def tach_threshold(self, count):
        if not 0 <= count <= 0xFFFF:
            raise ValueError("tach_threshold must be 0..65535")
        self._t.write_byte(REG_TACH_LIMIT_LO, count & 0xFF)
        self._t.write_byte(REG_TACH_LIMIT_HI, (count >> 8) & 0xFF)

    @property
    def min_rpm(self):
        """Convenience view of tach_threshold in RPM (via 5,400,000).
        Returns 0.0 when the guard is disabled (FFFFh)."""
        count = self.tach_threshold
        if count == 0xFFFF:
            return 0.0
        return rpm_from_count(count)

    @min_rpm.setter
    def min_rpm(self, rpm_value):
        if rpm_value <= 0:
            raise ValueError("min_rpm must be > 0 (write tach_threshold "
                             "= 0xFFFF to disable the guard)")
        count = count_from_rpm(rpm_value)
        if count > 0xFFFF:
            raise ValueError("min_rpm %r is below the detectable range "
                             "(count would exceed 65535)" % (rpm_value,))
        self.tach_threshold = count

    @property
    def tach_input_enabled(self):
        """True when the ALERT/TACH pin is switched to a hi-Z TACH input
        (Config.ALT_TCH). WARNING: enabling this DISABLES THE ALERT
        OUTPUT FUNCTION ENTIRELY (interrupt/comparator signalling lost,
        ARA ignored); an external pull-up may be required."""
        return bool(self._t.read_byte(REG_CONFIG) & CFG_ALT_TCH)

    @tach_input_enabled.setter
    def tach_input_enabled(self, value):
        cfg = self._t.read_byte(REG_CONFIG)
        if value:
            cfg |= CFG_ALT_TCH
        else:
            cfg &= ~CFG_ALT_TCH
        self._t.write_byte(REG_CONFIG, cfg)

    @property
    def tach_mode(self):
        """TACH_M[1:0] (0..3): 00 = false readings below min detectable
        RPM (default; forced at the 360 kHz base clock per Note 6.2 -
        though M1 found all encodings latch on this silicon); 01/10/11 =
        TACH reads FFFFh below min detectable RPM."""
        return self._t.read_byte(REG_FAN_CFG) & FCFG_TACH_M_MASK

    @tach_mode.setter
    def tach_mode(self, mode):
        if not 0 <= mode <= 3:
            raise ValueError("tach_mode must be 0..3")
        fc = self._t.read_byte(REG_FAN_CFG)
        self._t.write_byte(REG_FAN_CFG,
                           (fc & ~FCFG_TACH_M_MASK) | int(mode))

    # ------------------------------------------------------------------
    # Spin-up
    # ------------------------------------------------------------------

    @property
    def spin_up_enabled(self):
        """Composite: True when SPIN_TIME is not the bypass encoding.
        Enabling from bypass restores the POR default duration (3.2 s)."""
        return (self._t.read_byte(REG_SPINUP) & SU_SPIN_TIME_MASK) != 0

    @spin_up_enabled.setter
    def spin_up_enabled(self, value):
        reg = self._t.read_byte(REG_SPINUP)
        if value:
            if not (reg & SU_SPIN_TIME_MASK):
                reg |= 0x07          # POR default: 3.2 s
        else:
            reg &= ~SU_SPIN_TIME_MASK
        self._t.write_byte(REG_SPINUP, reg)

    @property
    def spin_up_drive(self):
        """Spin-up drive level as a percentage: 0 (bypass), 50, 75 or
        100."""
        reg = self._t.read_byte(REG_SPINUP)
        idx = (reg & SU_SPIN_DRIVE_MASK) // 8
        return _DRIVE_PCTS[idx]

    @spin_up_drive.setter
    def spin_up_drive(self, pct):
        if pct not in _DRIVE_PCTS:
            raise ValueError("spin_up_drive must be one of %r"
                             % (_DRIVE_PCTS,))
        reg = self._t.read_byte(REG_SPINUP)
        field = _DRIVE_FIELDS[_DRIVE_PCTS.index(pct)]
        self._t.write_byte(REG_SPINUP, (reg & ~SU_SPIN_DRIVE_MASK) | field)

    @property
    def spin_up_time_s(self):
        """Spin-up duration in seconds (0.05..3.2), or None when
        bypassed."""
        enc = self._t.read_byte(REG_SPINUP) & SU_SPIN_TIME_MASK
        return _spinup_time_decode(enc)

    @spin_up_time_s.setter
    def spin_up_time_s(self, seconds):
        if seconds is None or seconds == 0:
            enc = 0
        else:
            enc = None
            for i, v in enumerate(SPINUP_TIMES_S):
                if v is not None and abs(v - float(seconds)) < 1e-6:
                    enc = i
                    break
            if enc is None:
                raise ValueError("spin_up_time_s must be one of %r "
                                 "(or None/0 for bypass)"
                                 % (SPINUP_TIMES_S[1:],))
        reg = self._t.read_byte(REG_SPINUP)
        self._t.write_byte(REG_SPINUP, (reg & ~SU_SPIN_TIME_MASK) | enc)

    @property
    def spin_up_fast_tach(self):
        """FAST_TACH: abort spin-up early when the TACH count drops below
        the limit. Ignored while the TACH input is disabled."""
        return bool(self._t.read_byte(REG_SPINUP) & SU_FAST_TACH)

    @spin_up_fast_tach.setter
    def spin_up_fast_tach(self, value):
        reg = self._t.read_byte(REG_SPINUP)
        if value:
            reg |= SU_FAST_TACH
        else:
            reg &= ~SU_FAST_TACH
        self._t.write_byte(REG_SPINUP, reg)

    # ------------------------------------------------------------------
    # Calibration
    # ------------------------------------------------------------------

    @property
    def ideality_factor_index(self):
        """Ideality factor table index (17h, 6-bit; Table 6.13 defines
        0x08..0x37 only)."""
        return self._t.read_byte(REG_IDEALITY) & 0x3F

    @ideality_factor_index.setter
    def ideality_factor_index(self, index):
        _ideality_factor_lookup(index)   # validates table membership
        reg = self._t.read_byte(REG_IDEALITY)
        self._t.write_byte(REG_IDEALITY, (reg & ~0x3F) | (index & 0x3F))

    @property
    def ideality_factor(self):
        """Current ideality factor as a float (decoded through Table
        6.13)."""
        return _ideality_factor_lookup(self.ideality_factor_index)

    def set_ideality_factor(self, factor):
        """Nearest-match: write the table index whose factor is closest
        to the requested value. Returns the achieved factor."""
        best_idx = 0
        best_err = None
        for i, f in enumerate(IDEALITY_FACTORS):
            err = abs(f - float(factor))
            if best_err is None or err < best_err:
                best_idx = i
                best_err = err
        self.ideality_factor_index = IDEALITY_SETTINGS_MIN + best_idx
        return IDEALITY_FACTORS[best_idx]

    @property
    def beta_auto_detect(self):
        """Beta-compensation autodetect (18h ENABLE bit; default on).
        To disable compensation for diode-connected transistors /
        2-terminal CPU diodes: set this to False and set beta_index to
        BETA_DISABLE_AUTODETECT (0x07)."""
        return bool(self._t.read_byte(REG_BETA) & BETA_ENABLE)

    @beta_auto_detect.setter
    def beta_auto_detect(self, value):
        reg = self._t.read_byte(REG_BETA)
        if value:
            reg |= BETA_ENABLE
        else:
            reg &= ~BETA_ENABLE
        self._t.write_byte(REG_BETA, reg)

    @property
    def beta_index(self):
        """Manual BETA[2:0] index (0..7; meaningful only with autodetect
        off). See BETA_MINIMUM_VALUES for the covered substrate betas."""
        return self._t.read_byte(REG_BETA) & BETA_FIELD_MASK

    @beta_index.setter
    def beta_index(self, index):
        if not 0 <= index <= 7:
            raise ValueError("beta_index must be 0..7")
        reg = self._t.read_byte(REG_BETA)
        self._t.write_byte(REG_BETA, (reg & ~BETA_FIELD_MASK) | int(index))

    # ------------------------------------------------------------------
    # Scratchpad
    # ------------------------------------------------------------------

    def scratchpad_get(self, index):
        """Read scratchpad byte (11h/12h; index 0 or 1). No function -
        software compatibility only, and NOT persisted across power."""
        if index not in (0, 1):
            raise ValueError("scratchpad index must be 0 or 1")
        return self._t.read_byte(REG_SCRATCHPAD_1 + index)

    def scratchpad_set(self, index, value):
        """Write scratchpad byte (11h/12h; index 0 or 1)."""
        if index not in (0, 1):
            raise ValueError("scratchpad index must be 0 or 1")
        if not 0 <= value <= 0xFF:
            raise ValueError("value must be 0..255")
        self._t.write_byte(REG_SCRATCHPAD_1 + index, value)

    # ------------------------------------------------------------------
    # Power modes & conversion control
    # ------------------------------------------------------------------

    @property
    def standby(self):
        """Low-power standby (Config.STANDBY): monitoring off; fan
        follows fan_standby."""
        return bool(self._t.read_byte(REG_CONFIG) & CFG_STANDBY)

    @standby.setter
    def standby(self, value):
        cfg = self._t.read_byte(REG_CONFIG)
        if value:
            cfg |= CFG_STANDBY
        else:
            cfg &= ~CFG_STANDBY
        self._t.write_byte(REG_CONFIG, cfg)

    @property
    def fan_standby(self):
        """Fan inactive during standby (Config.FAN_STANDBY)."""
        return bool(self._t.read_byte(REG_CONFIG) & CFG_FAN_STANDBY)

    @fan_standby.setter
    def fan_standby(self, value):
        cfg = self._t.read_byte(REG_CONFIG)
        if value:
            cfg |= CFG_FAN_STANDBY
        else:
            cfg &= ~CFG_FAN_STANDBY
        self._t.write_byte(REG_CONFIG, cfg)

    def one_shot(self):
        """Initiate a single conversion (self-clearing 0Fh write).

        Only meaningful in standby or mixed mode (STANDBY set), where it
        wakes the ADC for one sample; in normal operation conversions
        run continuously. Raises ValueError outside standby/mixed."""
        if not (self._t.read_byte(REG_CONFIG) & CFG_STANDBY):
            raise ValueError("one_shot requires standby or mixed mode")
        self._t.write_byte(REG_ONE_SHOT, 0x00)

    @property
    def conversion_rate(self):
        """Conversion rate in conversions/second (Table 6.6: 1/16..32)."""
        idx = self._t.read_byte(REG_CONV_RATE) & 0x0F
        return CONV_RATES_PER_S[idx]

    @conversion_rate.setter
    def conversion_rate(self, rate_per_s):
        """Set the nearest supported conversion rate (ties resolve to
        the slower rate)."""
        idx = conv_rate_encode(rate_per_s)
        reg = self._t.read_byte(REG_CONV_RATE)
        self._t.write_byte(REG_CONV_RATE, (reg & ~0x0F) | idx)

    @property
    def averaging_filter(self):
        """Input averaging filter level: FILTER_OFF, FILTER_LEVEL_1 or
        FILTER_LEVEL_2 (the datasheet's duplicated Level-1 encoding is
        folded into FILTER_LEVEL_1)."""
        lvl = self._t.read_byte(REG_FILTER) & FLT_LEVEL_MASK
        if lvl == FLT_LEVEL_OFF:
            return FILTER_OFF
        if lvl in (FLT_LEVEL_1, FLT_LEVEL_1_ALT):
            return FILTER_LEVEL_1
        return FILTER_LEVEL_2

    @averaging_filter.setter
    def averaging_filter(self, level):
        if level == FILTER_OFF:
            field = FLT_LEVEL_OFF
        elif level == FILTER_LEVEL_1:
            field = FLT_LEVEL_1       # canonical 01 encoding
        elif level == FILTER_LEVEL_2:
            field = FLT_LEVEL_2
        else:
            raise ValueError("averaging_filter must be FILTER_OFF, "
                             "FILTER_LEVEL_1 or FILTER_LEVEL_2")
        reg = self._t.read_byte(REG_FILTER)
        self._t.write_byte(REG_FILTER, (reg & ~FLT_LEVEL_MASK) | field)

    @property
    def dis_to_enabled(self):
        """SMBus TIMEOUT disabled (Config.DIS_TO). Escape hatch for
        exotic buses; the chip resets its interface after ~25 ms of
        clock inactivity otherwise."""
        return bool(self._t.read_byte(REG_CONFIG) & CFG_DIS_TO)

    @dis_to_enabled.setter
    def dis_to_enabled(self, value):
        cfg = self._t.read_byte(REG_CONFIG)
        if value:
            cfg |= CFG_DIS_TO
        else:
            cfg &= ~CFG_DIS_TO
        self._t.write_byte(REG_CONFIG, cfg)

    @property
    def fault_queue_enabled(self):
        """Queue mode (Config.QUEUE): alert after 3 consecutive
        out-of-limit samples instead of 1 (external channel only)."""
        return bool(self._t.read_byte(REG_CONFIG) & CFG_QUEUE)

    @fault_queue_enabled.setter
    def fault_queue_enabled(self, value):
        cfg = self._t.read_byte(REG_CONFIG)
        if value:
            cfg |= CFG_QUEUE
        else:
            cfg &= ~CFG_QUEUE
        self._t.write_byte(REG_CONFIG, cfg)

    # ------------------------------------------------------------------
    # Presets
    # ------------------------------------------------------------------

    def configure_4wire_fan(self, pwm_freq_hz=25000.0):
        """Prepare the chip for a standard 4-wire fan: set the PWM output
        frequency, switch the ALERT/TACH pin to TACH input, and ensure
        sane spin-up (POR defaults: FAST_TACH, 100 % drive, 3.2 s).

        WARNING: enabling the TACH input disables the ALERT output
        function entirely (see tach_input_enabled)."""
        self.pwm_freq_hz = pwm_freq_hz
        cfg = self._t.read_byte(REG_CONFIG)
        self._t.write_byte(REG_CONFIG, cfg | CFG_ALT_TCH)
        su = self._t.read_byte(REG_SPINUP)
        sane = SU_FAST_TACH | SU_DRIVE_100 | 0x07
        if su != sane:
            self._t.write_byte(REG_SPINUP, sane)
