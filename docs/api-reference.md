# API reference

Complete public surface of `emc2101`. Both facades (`emc2101.mp`,
`emc2101.cp`) export the identical `__all__`; the class below is shared.
Constants and helpers are importable from either facade. Ranges are
enforced at the call site; violations raise `ValueError`. Bus failures
after the retry ladder raise `OSError`.

## Construction & lifecycle

| Member | Description |
|---|---|
| `EMC2101(i2c, addr=0x4C, config_file=None)` *(mp)* | Bind to a caller-built `machine.I2C` instance. `addr` must be `0x4C` (`ValueError` otherwise). `config_file` overrides the default JSON path **and** enables auto-load at construction (see [Persistence](persistence.md)). |
| `EMC2101(bus=1, addr=0x4C, handle=None, config_file=None)` *(cp)* | Open SMBus bus `bus` via smbus2, or adopt an existing `smbus2.SMBus` object as `handle`. Same `config_file` semantics. |
| `verify()` | Read the identity trio (FDh/FEh/FFh) and check it against expectations (plain or `-R` product, SMSC manufacturer, expected revision). Returns the product ID byte. Raises `OSError` if the device NACKs, `ValueError` on an unexpected identity. |
| `probe()` | `True` if the device answers at its address (single attempt, no retries). |
| `scan()` | Addresses present on the bus (delegates to the transport). Note: a healthy EMC2101 also answers its ARA general-call address `0x0C` — see [Operational notes](operational-notes.md#ara-general-call). |
| `close()` | Release platform resources (no-op on MicroPython). Context-manager supported. |
| `read_reg(reg, n=1)` / `write_reg(reg, buf)` | Raw tier. `n > 1` performs sequential single-byte transactions over consecutive addresses (the pointer does not auto-increment). Never crosses interlock boundaries inside the core. |

## Identity

| Member | Description |
|---|---|
| `product_id` | FDh: `0x16` plain / `0x28` -R. |
| `mfg_id` | FEh: `0x5D` (SMSC). |
| `revision` | FFh: expected `0x01` per datasheet Rev 2.54. |
| `part_info` | Triple `(product_id, mfg_id, revision)`. |

## Temperatures & limits

| Member | Range / notes |
|---|---|
| `local_temp_c` | Die temperature, °C, 1 °C steps; guaranteed 0..+85 °C. |
| `remote_temp_c` | External diode, °C, 0.125 °C steps, −64..+127.875. MSB-first interlocked read; raises `DiodeFaultError` on the open/short sentinels instead of returning a clamped value. |
| `local_high_c` (rw) | Internal high limit, 05h, 8-bit signed, 1 °C. Alarm when die temp exceeds it. |
| `remote_high_c` (rw) | External high limit, 07h+13h, 0.125 °C steps. |
| `remote_low_c` (rw) | External low limit, 08h+14h, 0.125 °C steps. |
| `tcrit_c` (rw) | TCRIT critical limit, 19h, 8-bit signed. Trips the fan to full drive. **One-time unlock**: changing it arms the TCRITOVRD bit; further changes need a power cycle. The setter attempts the unlock dance only when needed and reports via the return value; see [Operational notes](operational-notes.md#tcrit-lifecycle). |
| `tcrit_hysteresis_c` (rw) | 21h, 0..127 °C. Clear threshold = TCRIT − hysteresis. |

## Status, alerts & faults

| Member | Description |
|---|---|
| `status_raw()` | Destructive read of Status (02h): clears latched alarm bits. Bits: BUSY, INT_HIGH, EXT_HIGH, EXT_LOW, FAULT, TCRIT, TACH (EEPROM bit always 0 on this part). |
| `active_alarms()` | Names of currently active AND unmasked alarms (destructive status read underneath). |
| `alert_mask` (rw) | Defined alert-mask bits only (16h & 0x5B); reserved bits are preserved on write. |
| `alert_mode` (rw) | `ALERT_MODE_INTERRUPT` (latching, default) or `ALERT_MODE_COMPARATOR`. Interrupt mode: reading Status services the pin and auto-sets the sticky MASK bit; comparator mode asserts ALERT while any unmasked condition holds. |
| `service_alert()` | ISR step: perform the Status read that services the ALERT pin in interrupt mode. |
| `clear_alert_mask()` | Clear the sticky Config.MASK bit to re-arm the ALERT pin after servicing. |
| `diode_fault()` | `True` if the FAULT status bit is set (destructive read). Covers open/short diode conditions. |
| `busy()` | `True` while the ADC is converting (Status.BUSY; destructive read). |

Alert-mask constants: `AMSK_INT`, `AMSK_HIGH`, `AMSK_LOW`, `AMSK_TCRIT`,
`AMSK_TACH` (defined bits), plus `AMSK_DEFINED` / `AMSK_RESERVED` masks.

## Manual duty & PWM output

| Member | Range / notes |
|---|---|
| `manual` (rw) | `True` when Fan Setting drives the fan directly (~PROG). Toggling also flips LUT/Fan-Setting writability (PROG dance handled internally). |
| `set_duty_pct(pct)` | Drive at `pct` percent (0..100), quantized onto the live PWM_F grid: effective duty = S/(2·PWM_F). `ValueError` outside 0..100. |
| `duty_cmd_raw` (rw) | Raw 6-bit Fan Setting, 0..63. |
| `pwm_freq_hz` (rw) | Getter: actual frequency computed from PWM_F/PWM_D/CLK_SEL/CLK_OVR (≈22.8 Hz–180 kHz). Setter: programs the nearest achievable frequency to the target via the solver (tie-break toward the max-resolution path). |
| `fan_output_inverted` (rw) | Drive inversion (FanCfg.POLARITY): `True` means 00h = max drive. |
| `dac_enabled` (rw) | Linear 6-bit DAC output mode instead of PWM. **Hardware caveat:** cut the FAN-pin pull-up jumper first — see [Wiring guide](wiring.md#dac-mode-caveat). |
| `pwm_clk_sel` (rw) | Raw tier: CLK_SEL bit (False = 360 kHz base, True = 1.4 kHz). |
| `pwm_div` (rw) | Raw tier: PWM_D divider byte (used only when CLK_OVR=1). |

## Lookup table (LUT)

Eight `(temp_c, duty_pct)` pairs; the chip indexes on the external diode
channel.

| Member | Range / notes |
|---|---|
| `lut` (rw) | Bulk get/set. Setter validates strictly ascending thresholds (equal thresholds shadow each other in hardware), applies via the PROG dance with restore-on-failure. `ValueError` on bad shape/order/range. |
| `lut_get_index(index)` | One entry as `(temp_c, duty_pct)`; index 0..7. |
| `lut_set_index(index, temp_c, duty_pct)` | Program one entry (same validation/PROG dance as bulk). |
| `hysteresis_c` (rw) | LUT hysteresis, 4Fh, 0..127 °C: once an entry engages it holds until temp < threshold − hysteresis. |
| `force_enabled` (rw) | Force the LUT input to the EXT_FORCE register (limits still use measured temp). Testing tool — see [Operational notes](operational-notes.md#force-register-testing-technique). |
| `forced_temp_c` (rw) | Forced LUT-input temperature, 0Ch, 8-bit signed. |

Factory POR curve: uniformly 127 °C / max inactive (legal, non-ascending
— persistence accepts it, the write path does not; see
[Persistence](persistence.md#lut-ordering-rule)).

## Tachometer & RPM

| Member | Range / notes |
|---|---|
| `rpm(pulses_per_rev=2)` | Fan speed in RPM from the TACH counter (LSB-first interlocked read). Formula: 5,400,000/count × 2/pulses_per_rev. Sentinel/zero count ⇒ 0.0 (unmeasurable). |
| `tach_threshold` (rw) | TACH limit count, 48h/49h, 16-bit: alarm when the count *exceeds* the limit (fan-too-slow guard). Default 0xFFFF ⇒ off. |
| `min_rpm` (rw) | Convenience view of `tach_threshold` in RPM (via 5,400,000). |
| `tach_input_enabled` (rw) | Switch the ALERT/TACH pin to a hi-Z TACH input (ALT_TCH). **Disables the ALERT output function** — see [Operational notes](operational-notes.md#alert--tach-pin-trade-offs). |
| `tach_mode` (rw) | TACH_M[1:0], 0..3: what sub-minimum-RPM readings report (false readings vs forced sentinel). |

TACH_M constants: `TACH_M_FALSE_BELOW_MIN`, `TACH_M_SENTINEL_BELOW_MIN`
(plus the two intermediate encodings exported raw).

## Spin-up

Composite over the three-field spin-up register (4Bh).

| Member | Range / notes |
|---|---|
| `spin_up_enabled` (rw) | `True` when SPIN_TIME is not the bypass encoding. |
| `spin_up_drive` (rw) | Drive level during spin-up: 0 (bypass), 50, 75 or 100 %. |
| `spin_up_time_s` (rw) | Duration 0.05..3.2 s (table-driven), or `None` for bypass. |
| `spin_up_fast_tach` (rw) | Abort spin-up early when the TACH count drops below minimum. Ignored while TACH input is disabled. |

Spin-up constants: `SU_FAST_TACH`, `SU_DRIVE_BYPASS/50/75/100`, mask
constants, and the `SPINUP_TIMES_S` table + `spinup_time(seconds)`
helper.

## Calibration

| Member | Range / notes |
|---|---|
| `ideality_factor_index` (rw) | Ideality setting, 17h, 6-bit (Table 6.13 defines settings 0x08–0x37, 48 codes, factors 0.9949–1.0566; other codes are undefined). |
| `ideality_factor` | Current factor as a float (decoded through the table). |
| `set_ideality_factor(factor)` | Nearest-match: writes the table index whose factor is closest. |
| `beta_auto_detect` (rw) | Beta-compensation autodetect (18h ENABLE bit; default on). |
| `beta_index` (rw) | Manual BETA[2:0], 0..7 (meaningful only with autodetect off). Write `07h` to disable autodetect for diode-connected transistors / 2-terminal CPU diodes. |

Helpers: `IDEALITY_FACTORS`, `ideality_factor(index)`,
`BETA_MINIMUM_VALUES`, `BETA_DISABLE_AUTODETECT`.

## Scratch memory

| Member | Description |
|---|---|
| `scratchpad_get(index)` | Read scratchpad byte (11h/12h; index 0 or 1). No function — software compatibility only. |
| `scratchpad_set(index, value)` | Write scratchpad byte (index 0 or 1, 0..255). |

## Power modes & conversion control

| Member | Range / notes |
|---|---|
| `standby` (rw) | Low-power standby (Config.STANDBY): monitoring off; fan output follows `fan_standby`. |
| `fan_standby` (rw) | Fan inactive during standby (Config.FAN_STANDBY). |
| `one_shot()` | Initiate a single conversion (self-clearing 0Fh write). Legal only in standby or mixed mode (`ValueError` otherwise). |
| `conversion_rate` (rw) | Conversions/second, table-driven (1/16 .. 32; default 16). Setter picks the nearest supported rate (ties → slower). |
| `averaging_filter` (rw) | `FILTER_OFF`, `FILTER_LEVEL_1` or `FILTER_LEVEL_2` (the datasheet's duplicated Level-1 encoding is folded into LEVEL_1). |
| `dis_to_enabled` (rw) | Disable the SMBus TIMEOUT watchdog (escape hatch for exotic buses — see [Operational notes](operational-notes.md#smbus-timeout)). |
| `fault_queue_enabled` (rw) | Queue mode (Config.QUEUE): alert after 3 consecutive fault samples instead of 1. |

Conversion-rate helpers: `CONV_RATES_PER_S`, `conv_rate_encode(rate)`,
`TCONV_INTERNAL_MS`, `TCONV_EXTERNAL_MS`.

## Presets

| Member | Description |
|---|---|
| `configure_4wire_fan(pwm_freq_hz=25000)` | Prepare the chip for a standard 4-wire fan: set the PWM frequency, enable the TACH input (disabling ALERT output — stated in the docstring), and apply sane spin-up defaults. |

## Persistence ("virtual EEPROM")

| Member | Description |
|---|---|
| `save_config(path=None)` | Snapshot the current chip configuration to a JSON file (schema v1). Effective path: argument, else `config_path`. Atomic write (temp file + rename where the port supports it). Returns the effective path. |
| `load_config(path=None, *, strict=True)` | Apply a saved JSON configuration. Validates before any register write; refuses product-ID mismatches; warns on revision mismatch; ordered apply with the TCRIT special case; optional strict post-apply read-back diff (ON by default — raises `ValueError` listing mismatches). Returns the apply report dict. |
| `config_path` | Attribute: the effective default path for this instance. |

Exceptions: `ConfigFormatError` / `ConfigValidationError` (`ValueError`
subclasses) for unreadable/invalid files; `ConfigApplyError` (`OSError`
subclass) for bus failures mid-apply. Full semantics in
[Persistence](persistence.md).

## Module-level helpers (fixed-point conversions)

| Helper | Direction |
|---|---|
| `int_temp_to_raw(temp_c)` / `int_raw_to_temp(raw)` | Internal temp, 8-bit signed, 1 °C steps. |
| `ext_temp_to_raw(temp_c)` / `ext_raw_to_temp(raw)` | External temp, 11-bit two's complement, 0.125 °C steps (guaranteed −64..+127.875 enforced on encode). |
| `duty_pct_to_setting(pct, pwm_f)` / `setting_to_duty_pct(setting, pwm_f)` | Percent ↔ 6-bit setting on a given PWM_F grid (effective duty = S/(2·PWM_F)). |
| `rpm_from_count(count)` / `count_from_rpm(rpm)` | Via the 5,400,000 divisor. |

Sentinel constants: `SENTINEL_OPEN_RAW` (0x3F8), `SENTINEL_SHORT_RAW`
(0x3FF), `TACH_SENTINEL` (0xFFFF). Step/range constants:
`EXT_TEMP_STEP_C`, `INT_TEMP_STEP_C`, `TEMP_RANGE_MIN_C`,
`TEMP_RANGE_MAX_C`, `RPM_DIVISOR`. Clock/grid constants:
`BASE_CLOCK_360K_HZ`, `BASE_CLOCK_1P4K_HZ`, `PWM_F_MAX`, `LUT_ENTRIES`,
`LUT_PAIR_STRIDE`.

## Register & bit-field constants

Every register address and bit field used by the driver is exported
verbatim from `_regs.py`: `REG_*` addresses (including dual-address
aliases such as `REG_CONFIG_ALIAS`), `ST_*` status bits, `CFG_*` config
bits, `AMSK_*` alert-mask bits, `FCFG_*` fan-config bits, `SU_*`
spin-up fields, `FLT_*` filter encodings, `BETA_*` beta fields, and the
identity constants `ADDR_FIXED`, `ARA_GENERAL_CALL`,
`PRODUCT_ID_PLAIN`, `PRODUCT_ID_R`, `MANUF_ID_SMSC`,
`REVISION_EXPECTED`, `RETRY_DELAYS_MS`. Use them for raw-tier work so
your code tracks the driver's map.
