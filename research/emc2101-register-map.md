# EMC2101 Register Map & Protocol Facts

Extracted from SMSC EMC2101 datasheet Rev 2.54 (06-16-09). Authoritative source: `../EMC2101_datasheet.pdf`.
This document is the single reference for driver design; every entry cites the datasheet section.

## 1. Identity & bus facts

| Fact | Value | Source |
|---|---|---|
| SMBus slave address (7-bit) | **`0x4C`** (`100_1100b`) | §4.7 |
| ARA general call address | `0x06` (`000_1100b`); on-wire 8-bit `0x0C`/`0x0D` | §4.6 |
| Supported protocols | Write Byte, Read Byte, Send Byte, Receive Byte, ARA. **No block read/write.** | §4.1–4.6 |
| Clock stretching | Device will **not** stretch SMCLK | §4.1 |
| Bus speed | 10–400 kHz | Table 3.3 |
| SMBus TIMEOUT | Interface resets after ~25 ms of clock inactivity (25–35 ms window); disable via Config `DIS_TO` bit | §4.8, §6.5 |
| Product ID (`FDh`) | `0x16` = EMC2101, `0x28` = EMC2101-R | §6.24, Table 6.31 |
| Manufacturer ID (`FEh`) | `0x5D` (SMSC) | §6.25 |
| Revision (`FFh`) | `0x01` | §6.26 |
| Supply | 3.0–3.6 V (3.3 V nominal); 5 V-tolerant I/O pins | Ch. 3 |
| Power modes | Normal / Standby / Mixed (STANDBY + FAN_STANDBY bits) | §5.3 |

**Receive Byte semantics (§4.5):** reads the register at the *current* pointer without re-addressing —
used for "consecutive reads of the same register". Combined with Adafruit's tested observation that
the chip does no multi-byte access, the working model is: **one transaction per byte; the pointer
does not auto-increment across transactions.** (Verify empirically in P0.)

## 2. Register map (hex order)

Dual-address registers: writing/reading either alias hits the same internal register (§6 intro).

| Addr | R/W | Name | Default | Notes |
|---|---|---|---|---|
| `00h` | R | Internal Temperature | `00h` | 8-bit signed, 1 °C steps, −64..+127 format; guaranteed 0..85 °C (§6.3) |
| `01h` | R | External Temp High Byte | `00h` | 11-bit value MSB; **read first** (interlock, §6.1) |
| `02h` | R | Status | `00h` | See §3; read has side effects |
| `03h`,`09h` | R/W | Configuration | `00h` | See §4 |
| `04h`,`0Ah` | R/W | Conversion Rate | `08h` (=16/s) | See §9 |
| `05h`,`0Bh` | R/W | Internal Temp Limit | `46h` (70 °C) | 8-bit signed |
| `07h`,`0Dh` | R/W | Ext High Limit MSB | `46h` (70 °C) | 11-bit w/ `13h` fraction |
| `08h`,`0Eh` | R/W | Ext Low Limit MSB | `00h` (0 °C) | 11-bit w/ `14h` fraction |
| `0Ch` | R/W | External Temp Force | `00h` | Forces LUT input temp when FanCfg.FORCE=1 (§6.8) |
| `0Fh` | W | One Shot | — | Initiates conversion; meaningful in standby/mixed; self-clearing (§6.9) |
| `10h` | R | External Temp Low Byte | `00h` | Fractional bits `.5 .25 .125`; shadow-copied on `01h` read |
| `11h`,`12h` | R/W | Scratchpad ×2 | `00h` | No function; software compatibility (§6.10) |
| `13h` | R/W | Ext High Limit LSB | `00h` | Fractional |
| `14h` | R/W | Ext Low Limit LSB | `00h` | Fractional |
| `16h` | R/W | Alert Mask | `A4h` | See §5; **reserved bits 7,5,2 read as 1** |
| `17h` | R/W | External Ideality Factor | `12h` (1.0080) | 6-bit table index, Table 6.13 |
| `18h` | R/W | Beta Compensation | `08h` (auto-detect on) | ENABLE bit3, BETA[2:0]; write `07h` to disable autodetect for diode-connected transistors/2-terminal CPU diodes (§6.13) |
| `19h` | R/W | TCRIT Temp Limit | `55h` (85 °C) | **Locked until TCRITOVRD set; changeable once, then power-cycle required** (§6.5 bit1) |
| `21h` | R/W | TCRIT Hysteresis | `0Ah` (10 °C) | 1 LSB = 1 °C; clear threshold = TCRIT − hyst (§6.7 eq.[2]) |
| `46h` | R | TACH Reading Low | `FFh` | **Read first** (interlock, §6.1); TACH[7:0] |
| `47h` | R | TACH Reading High | `FFh` | TACH[15:8]; shadow-copied on `46h` read |
| `48h` | R/W | TACH Limit Low | `FFh` | Max count before TACH alarm (fan-too-slow guard) |
| `49h` | R/W | TACH Limit High | `FFh` | Default `FFFFh` ⇒ effectively off |
| `4Ah` | R/W | Fan Configuration | `20h` (PROG=1) | See §6 |
| `4Bh` | R/W | Fan Spin-Up Config | `3Fh` | See §7 |
| `4Ch` | R/W | Fan Setting | `00h` | 6-bit drive level; **RO while PROG=0**; applied immediately while PROG=1 (§6.18) |
| `4Dh` | R/W | PWM Frequency | `17h` | PWM_F[4:0]; see §8 |
| `4Eh` | R/W | PWM Freq Divide | `01h` | PWM_D[7:0]; used only when CLK_OVR=1 |
| `4Fh` | R/W | LUT Hysteresis | `04h` (4 °C) | 7-bit, 1 LSB = 1 °C |
| `50h`–`5Fh` | R/W | LUT T1,S1 … T8,S8 | T=`7Fh`, S=`3Fh` | Paired at even/odd offsets; **RO while PROG=0** (Note 6.1); temps must ascend (§6.22) |
| `BFh` | R/W | Averaging Filter | `00h` | FILTER[2:1], ALERT_COMP(0); see §10 |
| `FDh` | R | Product ID | `16h`/`28h` | |
| `FEh` | R | Manufacturer ID | `5Dh` | |
| `FFh` | R | Revision | `01h` | |

Unmapped addresses: no response / ignored (invalid protocol leaves registers unaffected, §4.7).

## 3. Status register (`02h`) — §6.4

| Bit | Name | Meaning | Clear behavior |
|---|---|---|---|
| 7 | BUSY | ADC converting | Never triggers interrupt |
| 6 | INT_HIGH | Internal temp ≥ limit | Auto-clears when condition removed |
| 5 | EEPROM | -R EEPROM-not-found at boot | **Always 0 on plain EMC2101** |
| 4 | EXT_HIGH | Ext diode ≥ high limit | As above |
| 3 | EXT_LOW | Ext diode ≤ low limit | As above |
| 2 | FAULT | External diode fault (open/VDD-short) | As above |
| 1 | TCRIT | Ext diode ≥ TCRIT | Clears below TCRIT−hyst |
| 0 | TACH | TACH count > TACH limit (fan too slow) | As above |

**Side effects of reading (critical for driver design):**
- Interrupt mode: a status read **clears all latched bits** and **auto-sets MASK** if any bit
  (except BUSY/FAULT) was set. If the error persists, bits re-set at end of next conversion.
- Comparator mode: a status read does **not** clear active bits (except EEPROM/FAULT); they clear
  when the condition removes itself.
- The ARA command sets MASK only when no status bits are set; it does not clear the status register.

## 4. Configuration register (`03h`/`09h`) — §6.5

| Bit | Name | 0 (default) | 1 |
|---|---|---|---|
| 7 | MASK | ALERT pin asserts on any status bit (sticky until cleared) | Pin masked; status still updates. Manual set/clear discouraged (§6.5 note) |
| 6 | STANDBY | Operational | Low-power standby (monitoring off; fan per FAN_STANDBY) |
| 5 | FAN_STANDBY | Fan stays active in standby | Fan inactive in standby |
| 4 | DAC | PWM output | Linear DAC output (remove FAN pull-up; 6-bit, VDD-scaled) |
| 3 | DIS_TO | SMBus timeout enabled | SMBus timeout disabled |
| 2 | ALT_TCH | ALERT/TACH = open-drain active-low interrupt | ALERT/TACH = hi-Z **TACH input** (ALERT function lost; ARA ignored; may need external pull-up) |
| 1 | TCRITOVRD | TCRIT locked at default 85 °C | TCRIT unlocked — **modifiable once**, then power cycle to unlock again |
| 0 | QUEUE | Alert after 1 out-of-limit sample | Alert after 3 consecutive out-of-limit samples (ext channel only, §5.7) |

## 5. Alert mask register (`16h`) — §6.11

Defined bits: `INT_MSK`(6), `HIGH_MSK`(4), `LOW_MSK`(3), `TCRIT_MSK`(1), `TACH_MSK`(0).
Default `A4h`: reserved bits 7, 5, 2 read back as 1 → **RMW must preserve them** (mask writes to
the defined field only). Status register updates regardless of masks.

## 6. Fan configuration register (`4Ah`) — §6.16

| Bit | Name | Effect |
|---|---|---|
| 6 | FORCE | LUT input = External Temp Force register (`0Ch`) instead of measured ext temp (limits still use measured temp) |
| 5 | **PROG** | `1` (default): Fan Setting + LUT registers writable; Fan Setting drives fan directly (manual). `0`: LUT drives fan; Fan Setting + LUT registers **read-only** |
| 4 | POLARITY | `0` (default): non-inverted — `00h` = min drive. `1`: inverted — `00h` = max drive. (Plain part: software-controlled; -R: set by pull-up at boot) |
| 3 | CLK_SEL | `0`: 360 kHz base clock; `1`: 1.4 kHz base clock |
| 2 | CLK_OVR | `1` (recommended): base clock from PWM_D divide register (max resolution path) |
| 1:0 | TACH_M | `00`: false readings below min detectable RPM (default; forced when base=360 kHz, Note 6.2); `01/10/11`: TACH reads `FFFFh` below min detectable RPM |

**PROG ordering rule (drives save/load sequencing):** LUT can only be *written* with PROG=1 and
only *governs* the fan with PROG=0. Applying a saved profile therefore requires: write LUT while
PROG=1 → finally set PROG to the stored value. (Same interaction noted for the -R EEPROM loader, §4.9.)

## 7. Spin-up (`4Bh`) — §6.17

Triggered on any transition **from `00h` to a higher setting** (not at power-up).

| Field | Values |
|---|---|
| FAST_TACH (bit 5, default 1) | Abort spin-up early when TACH < limit (implies 100% drive during spin-up); ignored if ALT_TCH=0 |
| SPIN_DRIVE[1:0] (bits 4:3, default `11`) | `00` bypass · `01` 50% · `10` 75% · `11` 100% |
| SPIN_TIME[2:0] (bits 2:0, default `111`) | `000` bypass · `001` 0.05 s · `010` 0.1 s · `011` 0.2 s · `100` 0.4 s · `101` 0.8 s · `110` 1.6 s · `111` 3.2 s |

## 8. PWM frequency & duty math — §6.19/6.20, Appendix A

- Fan Setting raw `S` ∈ 0..63 always means min→max drive (POLARITY-independent, §6.18).
- Effective duty = `S / (2·PWM_F) × 100%` (eq. [6]); effective resolution = `100/(2·PWM_F)%` (eq. [7]).
  Full scale reached at `S = 2·PWM_F` (or `S > 2·PWM_F` ⇒ 100%).
- Frequencies: `f = 360k/(2·PWM_F)` (CLK_SEL=0) or `f = 1.4k/(2·PWM_F)` (CLK_SEL=1); with CLK_OVR=1:
  `f = 360k/(2·PWM_F·PWM_D)` (eq. [5]). Recommended max-resolution setup: **PWM_F = 31 (`1Fh`)**,
  tune PWM_D (e.g. 30 Hz ⇒ PWM_D = `C1h`). Range ≈ 22.8 Hz … 180 kHz.
- DAC mode ignores PWM_F/PWM_D entirely: `V_DAC = S/64 × VDD` (eq. [4]), 64 steps, ±5 % TUE.
- PWM output is open-drain (needs pull-up); DAC mode wants the FAN pull-up removed (§5.6.1).

## 9. Conversion rate (`04h`/`0Ah`) — Table 6.6

CONV[3:0]: `0`=1/16 s⁻¹, `1`=1/8, `2`=1/4, `3`=1/2, `4`=1, `5`=2, `6`=4, `7`=8, `8`=16 (default),
`9`=32, others=32. tCONV: internal 3 ms, external 21 ms.

## 10. Averaging filter (`BFh`) — §6.23

FILTER[2:1]: `00` disabled (default) · `01` Level 1 · `10` Level 1 (**duplicated encoding**) · `11` Level 2.
ALERT_COMP(0): `0` interrupt mode (default) · `1` comparator mode (live-following ALERT pin; MASK bit ineffective on pin; ARA not responded).

## 11. Temperature data formats — §5.5.1

- Range −64 .. +127.875 °C, two's complement. Internal: 8-bit, 1 °C steps. External: 11-bit
  (MSB `01h` + fractional LSB `10h` bits `.5/.25/.125`), 0.125 °C steps.
- **Fault sentinels:** open DP-DN or DP-VDD short ⇒ data forced **+127 °C** (`0x7F8` raw) and FAULT bit set.
  DN-DN short or DN-GND short ⇒ **+127.875 °C** (`0x7FF` raw), FAULT bit *not* set.
- Accuracy: ext ±1 °C (60–100 °C diode range); int ±2 °C. REC corrects up to 100 Ω series resistance
  (+0.7 °C/Ω otherwise). Beta autodetect + programmable ideality (Table 6.13, 64 entries, 0.9949–1.0566).

## 12. Data Read Interlock — §6.1 (ordering is mandatory)

| Quantity | Snapshot trigger | Correct read order |
|---|---|---|
| External temperature | Reading `01h` (MSB) copies current LSB into shadow | **`01h` then `10h`** |
| TACH count | Reading `46h` (LSB) copies current MSB into shadow | **`46h` then `47h`** |

The two pairs snapshot in **opposite directions**. Getting the order wrong risks a torn 11/16-bit
value across a conversion boundary. (Adafruit lib gets one of these wrong — see 04-reference-notes.md.)

## 13. TACH monitor — §5.6.3, §6.14/6.15, Appendix B

- Counts counter-clock pulses between **five edges** of the TACH signal; assumes the tach signal
  produces **2 pulses per revolution** (standard 4-wire fan).
- **RPM = 5,400,000 / TACH_COUNT** (eq. [3]; verified against Appendix B tables).
- Counter clock nominally 90 kHz (Table 3.2); accuracy ±10 %.
- TACH limit (`48h/49h`): alarm (status bit 0) when count **exceeds** limit ⇒ fan slower than expected.
  Default `FFFFh` ⇒ effectively disabled. With TACH_M ≠ 00, readings below min detectable RPM force `FFFFh`.
- Enabling TACH input (ALT_TCH=1) disables the ALERT output function entirely (§5.4 app note).

## 14. Power-on defaults (plain EMC2101)

| Item | POR value |
|---|---|
| Fan output | **0 % duty** (Fan Setting `00h`, POLARITY=0, PROG=1 ⇒ manual, LUT inactive) |
| Mode | Manual (PROG=1); LUT all entries T=127 °C / S=max (inactive) |
| Limits | Int high 70 °C · Ext high 70 °C · Ext low 0 °C · TCRIT 85 °C (locked) · TCRIT hyst 10 °C |
| Conversion rate | 16/s |
| ALERT/TACH pin | Interrupt mode (ALERT output), TACH input off |
| Queue / filter / masks | 1-sample trigger · filter off · all alert sources unmasked (defined bits) |
| PWM | PWM_F=`17h`, PWM_D=`01h`, CLK_SEL=0, CLK_OVR=0 |
| Spin-up | 100 % drive for 3.2 s, FAST_TACH on |
| Calibration | Ideality idx `12h` (1.0080) · Beta autodetect on |

Practical consequence: at cold boot the fan sits at its 0 %-setting floor speed (typically a few
hundred RPM on modern DC fans — user-measured ~660 RPM on last tested fan) until software configures
it. See 03-persistence-opinion.md §Boot window.

## 15. ARA handshake (host-side, informational) — §4.6, §5.4.2

Host polls general-call `0x06` when ALERT asserted; device answers with its client address only if
configured as interrupt AND pin asserted; answering sets MASK iff no status bits pending. A driver
for this project does **not** need to implement ARA (it is a host-initiated protocol); polling
`status_raw()` suffices. Documented so the omission is deliberate.
