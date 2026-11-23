# Bench Characterization — EMC2101

Milestone M1 output. Benches rotate per D25 (single physical controller):
Pico W first, then ESP32-S3, then RPi 3A+. Sections marked **PENDING** are
blocked on bench loadout (see "Bench state" below) and will be completed on
re-test.

Method: self-contained probe scripts under `scripts/pico/` (pure
`machine.I2C`, no driver imports), run via
`python -m mpremote connect port:COM16 run <script>.py`. All mutating probes
snapshot + restore registers and verify restoration.

## Pico W (COM16, MicroPython v1.29.0, I2C0 SDA=GP0/SCL=GP1)

Date: 2026-11-22. Firmware: MicroPython v1.29.0 (board stock image).

### Identity (`probe_id.py`)

| Register | Read | Expected (datasheet Rev 2.54) | Verdict |
|---|---|---|---|
| 0x00 internal temp | 0x16 (22 °C) | ambient | OK |
| 0xFD product ID | 0x16 | 0x16 (plain EMC2101) | MATCH |
| 0xFE manufacturer ID | 0x5D | 0x5D (SMSC) | MATCH |
| 0xFF revision | 0x01 | 0x01 | MATCH |

Plain EMC2101 confirmed; no revision deviation.

### Two-byte read attempt (`char_protocol.py`)

`readfrom_mem(0x4C, 0x00, n=2)` → **no exception**; returned `0x16, 0xFF`.
The chip transmits the requested register byte, then stops driving the bus;
the master's second byte reads the pulled-up line as 0xFF. Repeated runs gave
identical results. Consequences for the driver:

- The pessimistic pointer model holds: no auto-increment, no block-read
  behavior (resolves ambiguity A6 against the optimistic reading).
- Over-long reads fail *silently* with 0xFF padding — the transport cannot
  rely on exceptions to catch them and must enforce single-byte reads by
  construction (as planned). 0xFF is also a legal register value, so the
  padding is indistinguishable from data at the byte level.

### Receive Byte / Send Byte (one-off experiment, not scripted)

Attempted during M1 with a throwaway script (removed; see git history of
`char_protocol.py`'s first revision):

1. `writeto_mem(0x11, [0x11])` (Write Byte, sets pointer to 0x11), then bare
   `readfrom(0x4C, 1)` (Receive Byte protocol, no register phase) → returned
   **0x00**, not the pointed-at scratchpad content. The "current pointer"
   does not persist across transactions in any usable form.
2. Bare `writeto(0x4C, [0x22])` (Send Byte protocol) → accepted without
   error, did **not** modify the last addressed register (scratchpad 0x11
   still held 0x11 afterwards), and the *next* transaction failed with
   `OSError errno=5 (EIO)` — the chip's SMBus interface desynchronized.
3. Recovery: a fresh mpremote connection (fresh `machine.I2C` init) plus the
   chip's ~25 ms SMBus TIMEOUT reset fully restored communication;
   `health_check.py` then reported PASS with all config registers at POR.

Consequence: the driver uses only register-addressed Write Byte / Read Byte
transactions (`writeto_mem`/`readfrom_mem`). This empirically validates the
planned transport contract and forbids any future use of bare
Receive/Send Byte forms. Recorded as a standing rule in
`scripts/pico/char_protocol.py`'s docstring.

### Data-read interlocks (`char_protocol.py`)

External temperature decoded both ways, three trials each:

| Trial | MSB-first (0x01→0x10) | LSB-first (0x10→0x01) |
|---|---|---|
| 0 | 127.000 °C | 127.000 °C |
| 1 | 127.000 °C | 127.000 °C |
| 2 | 127.000 °C | 127.000 °C |

Both orders return the open-circuit sentinel (+127.000 °C, raw 0x7F/0x00) —
see "Bench state". Torn-pair behavior could not be exercised because the
channel carries no live conversion; the ordering rule stands on datasheet
§6.1 authority and will be re-exercised once a diode is connected. TACH
pair read LSB-first (0x46→0x47) returned 0xFFFF/0xFFFF with the input
disabled at POR, as expected.

### Status-register side effects (observed)

A diagnostic status read while EXT_HIGH was latched (diode-fault sentinel
above the 70 °C ext-high limit) **auto-set the MASK bit** (Config 0x03 went
0x00 → 0x80) — exactly the documented interrupt-mode behavior (§6.4: a
status read clears latches and auto-sets MASK if any non-BUSY/non-FAULT bit
was set). Empirically confirmed; the driver's `service_alert()` semantics
rest on this. MASK was cleared back to POR (0x00) after observation.

### TACH exercise & TACH_M sweep (`char_tach.py`) — ANOMALY

With ALT_TCH enabled (Config bit 2), TACH count read **0xFFFF at every
duty level**:

| Condition | Count | Implied RPM |
|---|---|---|
| Floor speed (POR Fan Setting 0x00) | 65535 | 82 (sentinel) |
| TACH_M = 0..3 sweep (360 kHz base) | 65535 each | 82 (sentinel) |
| Manual duty 22 % (S=0x0A) | 65535 | 82 (sentinel) |
| Manual duty 50 % (S=0x17) | 65535 | 82 (sentinel) |
| Manual duty 100 % (S=0x2E) | 65535 | 82 (sentinel) |

0xFFFF at 100 % drive rules out "fan slower than min detectable RPM"
(~82 RPM floor); the tach signal is simply not reaching the chip. Combined
with the open diode channel (below), the likely cause is bench loadout:
fan and/or diode not currently connected to the breakout. **PENDING** bench
verification and re-test. The TACH_M sweep is therefore inconclusive for
ambiguity A3 (CLK_OVR-divided clock vs Note 6.2 scope) — re-run with a
spinning fan.

Restore verification: PASS (cfg/fcfg/fsetting all returned to snapshot).

### BUSY cadence (`char_tach.py`) — confounded

40 status polls ~10 ms apart: BUSY high for one ~17 ms episode at the start,
low thereafter. With the diode open the 21 ms external conversion appears
not to run, leaving only the 3 ms internal conversion — too short to catch
reliably at 10 ms polling. **PENDING** re-test with diode connected
(expected: periodic BUSY episodes ≈ tCONV at 16/s rate, i.e. roughly every
62.5 ms).

## Bench state (blocking items)

Observed 2026-11-22 on the Pico W bench:

- External diode channel **OPEN**: raw 0x7F/0x00 (+127.000 °C sentinel),
  status FAULT bit set (status 0x16: FAULT + EXT_HIGH). The 2N3906 PNP
  diode is either not connected to DP/DN on the Adafruit 4808 breakout or
  its wiring is faulty.
- No tach pulses observed at any fan duty (TACH 0xFFFF throughout),
  consistent with the fan not being connected to the FAN output / ALERT-TACH
  pin, or not spinning.

Awaiting user confirmation of bench loadout before re-running the
diode-dependent and TACH-dependent sections.

## Pending rotations (per D25)

- ESP32-S3 (COM7): `probe_id.py` equivalent + repeat characterization when
  the controller rotates.
- RPi 3A+ (SMBus bus 1): `i2cdetect -y 1` + repeat characterization.
