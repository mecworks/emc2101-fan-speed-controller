# Operational notes

Chip behaviors that bite at system level, with mitigations. Register-level
facts cite the datasheet (Rev 2.54); bench-confirmed items say so.

## Cold-boot window

Between power-on and the first completed ADC conversion, temperature
readings are not valid, and the fan sits at its 0 %-setting floor speed
(typically a few hundred RPM for a real fan). This is physics, not a
driver bug: nothing runs before the host firmware boots, so **cold-boot
autonomy is impossible** on the plain part — the `-R` variant's EEPROM
auto-load exists precisely because the chip itself cannot wait for
software.

Mitigations, in order of effectiveness:

1. **Auto-load a saved profile at construction** (`config_file=` kwarg or
   `load_config()` early in your startup code). The window shrinks from
   "power-on to steady state" to "power-on to first I²C transaction".
2. **Spin-up configuration**: a sane `spin_up_*` setup drives the fan to
   a known duty for a bounded time right after control starts, covering
   the moment before the LUT settles.
3. **Floor-speed sanity check**: pick a fan whose 0 % floor speed is
   acceptable for the worst-case seconds-long window (most PC fans spin
   slowly but non-zero at 0 %).
4. In standby/mixed modes, `one_shot()` forces a single conversion when
   you need a fresh reading without continuous monitoring.

The E2E test plan includes a "cold boot with saved profile" scenario
(power-cycle, construct with `config_file=`, assert applied values).

## TCRIT lifecycle

TCRIT (19h, default 85 °C) trips the fan to full drive and latches the
TCRIT status bit. It is **locked**: writes are ignored until the
Config.TCRITOVRD unlock bit is set, and the unlock is **one-time** —
after the change, adjusting TCRIT again requires a power cycle
(datasheet §6.5; whether the bit auto-resets is unspecified, ambiguity
A5 — the driver conservatively assumes it stays set until power cycle).

Driver behavior:

- `tcrit_c` setter: silent best-effort. No-op when the value equals the
  current one (does not consume the unlock); otherwise arms TCRITOVRD
  and writes. If the one-time unlock was already consumed since the
  last power cycle the write does not take effect — verify by reading
  back.
- Persistence: see [Persistence](persistence.md#tcrit-special-case) —
  applying a file never consumes the unlock unnecessarily.
- Bench caution: any run that deliberately exercises TCRIT may leave the
  chip with TCRITOVRD set and a non-default TCRIT; a power cycle returns
  it to defaults. Self-restoring scripts snapshot/restore TCRIT bytes
  but cannot un-consume the unlock.

## ALERT / TACH pin trade-offs

The ALERT/TACH pin is one physical net with two software-selected roles
(Config.ALT_TCH):

| Role | Pin behaviour | Enabled by |
|---|---|---|
| ALERT output (default) | Open-drain; asserts on unmasked alarms (interrupt mode: latching, serviced by a Status read; comparator mode: level while condition holds) | `tach_input_enabled = False` |
| TACH input | Hi-Z; counts fan pulses for `rpm()` | `tach_input_enabled = True` |

Enabling the TACH input **disables the ALERT output function entirely**.
You cannot have both simultaneously. `configure_4wire_fan()` enables the
TACH input and states this trade-off in its docstring; if your design
needs interrupt-driven alarm servicing instead of RPM measurement, keep
the pin in ALERT mode and measure speed some other way (or accept the
trade-off consciously). Both roles need the receiver-side pull-up — see
[Wiring guide](wiring.md#pull-up-jumpers-critical).

## ARA general call

The chip also answers the SMBus Alternate Response Address general call
(ARA address `0x06`; on-wire `0x0C`/`0x0D`). Bench observation (M1,
Pico W leg): while the ARA conditions hold — interrupt mode configured
AND the ALERT pin asserted (an unmasked alarm latched) — a bus scan
reports `0x0C` alongside the device address `0x4C`; on a fresh,
alarm-free chip (RPi 3A+ leg) the scan shows `0x4C` only. Presence of
`0x0C` is therefore state-dependent, consistent with datasheet §4.6/
§5.4.2 (the chip answers the ARA only when configured as interrupt and
the pin is asserted); its absence does not indicate a fault. When
present, treat `0x0C` as part of the EMC2101's footprint, not a foreign
device. The exported `ARA_GENERAL_CALL` constant documents the address.

## Force-register testing technique

FanCfg.FORCE + the EXT_FORCE register (0Ch) let the host feed an
arbitrary temperature into the **LUT input only** — the limit/alarm
comparators still use the measured external temperature. Technique for
testing LUT behavior without heating the diode:

```python
dev.force_enabled = True
dev.forced_temp_c = 75        # pretend the diode reads 75 C
# observe the LUT engage the >=75 entry (fan ramps up)
dev.forced_temp_c = 30        # watch it step down through entries
dev.force_enabled = False     # restore measured-temp operation
```

This is how the M3 live probe exercised the whole curve on a cold bench.
Remember to clear FORCE afterwards — a forgotten forced temperature
makes the fan ignore reality.

## SMBus TIMEOUT

The chip's SMBus interface resets itself after ~25 ms of clock
inactivity (25–35 ms window, datasheet §4.8). On well-behaved hosts this
is invisible; on exotic or heavily-arbitrated buses it can abort slow
transactions. Escape hatch: `dis_to_enabled = True` disables the
watchdog. Leave it off unless you have a concrete reason.

## Retry ladder & error model

Every transport read/write retries with escalating delays
(`RETRY_DELAYS_MS`) before surfacing `OSError`. There is no EEPROM-busy
wait to worry about (no EEPROM on this part), so the ladder is short.
Error taxonomy:

| Condition | Exception |
|---|---|
| Out-of-range argument | `ValueError` |
| Bus failure after retry ladder | `OSError` |
| Diode open/short sentinels on external temp | `DiodeFaultError` (OSError subclass) |
| Invalid/unparseable config file | `ConfigFormatError` / `ConfigValidationError` (ValueError subclasses) |
| Bus failure mid-apply, or strict read-back mismatch | `ConfigApplyError` (OSError subclass) |

## Reset

There is **no software POR register** on this chip — unlike the
MAX31760 sibling. Returning to power-on defaults requires a power
cycle. Standby is not a reset: all registers survive it.
