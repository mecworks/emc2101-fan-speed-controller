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

### Data-read interlocks (`char_protocol.py`, `char_interlock.py`)

Initial pass (diode open): both orders returned the open-circuit sentinel
(+127.000 °C, raw 0x7F/0x00) — see "Bench state".

Re-test 2026-11-22 after the diode was connected (live conversion,
external temp 28.0 °C):

| Probe | Result |
|---|---|
| 200 rapid MSB-first reads | min=max=28.0 °C, 1 distinct value |
| 100 rounds back-to-back MSB-first vs LSB-first | 0 rounds with delta > 1 °C |

No torn-pair behavior observable: the two bytes present a consistent pair
across rapid alternating-order reads (either updated atomically at
conversion completion, or slow thermal drift never straddled a conversion
boundary within a round). The MSB-first rule stands as the safe convention
per datasheet §6.1; the driver enforces it by construction. TACH pair read
LSB-first (0x46→0x47) returns 0xFFFF/0xFFFF with the input disabled at
POR, as expected.

### Status-register side effects (observed)

A diagnostic status read while EXT_HIGH was latched (diode-fault sentinel
above the 70 °C ext-high limit) **auto-set the MASK bit** (Config 0x03 went
0x00 → 0x80) — exactly the documented interrupt-mode behavior (§6.4: a
status read clears latches and auto-sets MASK if any non-BUSY/non-FAULT bit
was set). Empirically confirmed; the driver's `service_alert()` semantics
rest on this. MASK was cleared back to POR (0x00) after observation.

### TACH exercise & TACH_M sweep (`char_tach.py`) — STILL BLOCKED ON FAN

With ALT_TCH enabled (Config bit 2), TACH count reads **0xFFFF at every
duty level**, unchanged after the diode fix (re-run 2026-11-22):

| Condition | Count | Implied RPM |
|---|---|---|
| Floor speed (POR Fan Setting 0x00) | 65535 | 82 (sentinel) |
| TACH_M = 0..3 sweep (360 kHz base) | 65535 each | 82 (sentinel) |
| Manual duty 22 % (S=0x0A) | 65535 | 82 (sentinel) |
| Manual duty 50 % (S=0x17) | 65535 | 82 (sentinel) |
| Manual duty 100 % (S=0x2E) | 65535 | 82 (sentinel) |

0xFFFF at 100 % drive rules out "fan slower than min detectable RPM"
(~82 RPM floor); no tach signal reaches the chip. Since the diode channel
is now proven healthy, the fault isolates to the fan side: tach wire not
connected to the ALERT/TACH pin, or the fan motor unpowered (the FAN output
is PWM only — the fan needs its own supply). **PENDING** bench verification
and re-test. The TACH_M sweep is therefore inconclusive for ambiguity A3
(CLK_OVR-divided clock vs Note 6.2 scope) — re-run with a spinning fan.

Restore verification: PASS (cfg/fcfg/fsetting all returned to snapshot).

### BUSY cadence (`char_tach.py`) — MEASURED

1 ms polling over a 500 ms window (diode connected, default 16/s rate):

```
busy transitions: 0@1ms, 1@12ms, 0@38ms, 1@76ms, 0@102ms, 1@140ms,
                  0@166ms, 1@204ms, 0@231ms, 1@268ms, 0@295ms,
                  1@333ms, 0@359ms, 1@397ms, 0@423ms, 1@461ms, 0@487ms
```

- Period between rising edges: 64, 64, 64, 64, 65, 64, 64 ms → **~64 ms
  cadence ≈ 16 conversions/s** (default RATE), confirming the default
  sampling rate on live silicon.
- BUSY-high duration: 26–27 ms per episode (1 ms poll quantization) → the
  chip asserts BUSY for **~26 ms of every 64 ms window** (~40 %) around
  each external conversion.

Driver consequence: a Status read taken at random has ~40 % odds of seeing
BUSY=1; BUSY is purely informational — the result registers hold the last
completed sample throughout, so reads never need to wait on BUSY.

## Bench state (open items)

Observed 2026-11-22 on the Pico W bench:

- ~~External diode channel OPEN~~ **RESOLVED** (user re-seated the diode
  pins): raw 0x1C/0xC0 = 28.0 °C, status 0x00 (no FAULT), stable across
  200 reads.
- **Fan/tach still dead**: TACH 0xFFFF at every manual duty level even with
  the diode healthy. Suspects: tach wire not on the ALERT/TACH pin, or the
  fan motor unpowered (FAN output is PWM only). Awaiting bench check;
  blocks only the TACH-dependent sections above.

## Pending rotations (per D25)

- ESP32-S3 (COM7): `probe_id.py` equivalent + repeat characterization when
  the controller rotates.
- RPi 3A+ (SMBus bus 1): `i2cdetect -y 1` + repeat characterization.
