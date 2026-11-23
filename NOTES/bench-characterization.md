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

### TACH re-test 2026-11-22 evening (`char_tach_diag.py`) — chip side exonerated

User bench data before this run: multimeter continuity beeps on every tach
closure at the board TACH point (electrically the chip's ALERT pin; nothing
else on the net — no LED, no visible pull-up); fan powered and spinning at
~660 RPM floor. Post-power-cycle diagnostics:

| Check | Result |
|---|---|
| Health check (fresh POR) | PASS — id trio 0x16/0x5D/0x01, cfg=00 fcfg=20 fsetting=00 |
| ALT_TCH latch (Config bit 2) | LATCHED (wrote 0x04, readback 0x04) |
| TACH count, ALT_TCH=1, reads 1 s apart | 0xFFFF → 0xFFFF (stable sentinel) |
| TACH_M write acceptance @ 360 kHz base | All four encodings latch (readback field 0..3) — Note 6.2 "forcing" does NOT manifest at register level |
| CLK_SEL=1 (1.4 kHz base) trial | fcfg=0x2B latched; count still 0xFFFF |
| Restore | PASS |

Chip side is fully exonerated: configuration latches, TACH_M is writable at
the 360 kHz base (partial answer to A3), the counter is alive but starved.
Remaining suspect: the HIGH state of the TACH net. The continuity test
proves the low-going closures but biases the line itself during the test;
if nothing pulls the net high between pulses (no visible pull-up on the
breakout; internal pull-up unverified), the chip's edge detector sees a
clean fall followed by a slow/noisy float-rise and rejects the pair.
Discriminating experiments (bench, user's hands):

1. Bridge a temporary 10 kohm from the TACH net to 3.3 V (or the board's
   positive rail), re-run `char_tach_diag.py`: a real count (~8k at
   660 RPM, 1 ppr) confirms the missing pull-up as root cause.
2. Alternatively tap the net onto GP2 through a 1 kohm series resistor
   and run `probe_tach_signal.py` to measure the idle high level and edge
   quality directly.

Secondary consequence: the same missing pull-up leaves the ALERT output
(open-drain, ALT_TCH=0) unable to define its idle-high state — interrupt
use on this breakout will need the external pull-up as well.

### TACH resolution 2026-11-22 (round 2) — root cause confirmed: missing receiver-side pull-up

User bridged a 10 kOhm resistor from the TACH net to 3.3 V (now permanent on
the bench). Re-ran `char_tach_diag.py` unchanged:

| Check | Before pull-up | After pull-up |
|---|---|---|
| ALT_TCH latch | LATCHED | LATCHED |
| TACH count @ FS=00 | 0xFFFF (sentinel) | 7959 → 7963 over 1 s (live, ~678 RPM) |
| TACH_M write acceptance | All four latched | All four latched (count live throughout) |
| CLK_SEL=1 trial | fcfg=0x2B, 0xFFFF | fcfg=0x2B, 7959 (live) |
| Restore | PASS | PASS |

Root cause: the open-collector tach output had no receiver-side pull-up; the
net's HIGH state floated between pulses and defeated the chip's edge
detector. The low-going closures were present all along (multimeter
continuity beeps) — consistent with every prior symptom. Secondary
consequence also cured: the ALERT open-drain output now has a defined
idle-high on this bench.

PWM-gating check (`char_tach_pwm_gate.py`): reported caveat that some fans
gate their tach output at 0 % PWM duty. Tested on this bench:

| Phase | Fan Setting | Drive | Count | Implied RPM |
|---|---|---|---|---|
| A (as found) | 0x00 | 0 % | 7955 (stable ×3) | ~678 |
| B | 0x23 | 50 % (PWM_F=0x17) | 2887–2899 (stable ×3) | ~1862–1870 |

The tach reads stably at 0 % drive — this fan does NOT gate its tach output
at zero duty; the caveat does not apply here (kept as a general warning for
other fans). Control loop responds monotonically (0 % → ~678 RPM,
50 % → ~1865 RPM). Live validation of the RPM formula (eq. [3]):
5,400,000/7955 ≈ 679 RPM matches the user-measured ~660 RPM floor within the
±10 % tolerance. Closes ambiguity A7 early.

Restore verification: PASS (cfg/fcfg/fsetting returned to snapshot).

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

## Ambiguity dispositions (A1–A8, per `research/04-reference-notes.md` §3)

M1 acceptance requires every ambiguity item explicitly resolved or
deferred-with-reason:

| # | Item | Disposition | Evidence / reason |
|---|------|-------------|-------------------|
| A1 | FILTER encoding duplication | Resolved by design; empirical shape check deferred to M7 | Encoder emits `00/01/11` for OFF/L1/L2 and decodes `10`→L1 (driver rule); live filter-response-shape verification folds into M7 E2E section 6 (`averaging_filter` round trip). |
| A2 | Status bit 5 text (typo for -R) | Resolved by design | Bit treated as always-0 on the plain part and ignored in mask handling; bit 5 was clear in every live M1 status read (0x16, 0x00). |
| A3 | Note 6.2 scope (CLK_OVR-divided clocks) | **Partially resolved — behavioral distinction unreachable on this bench** | 2026-11-22 evening: TACH_M field confirmed WRITABLE at the 360 kHz base (all four encodings latch; Note 6.2 forcing absent at register level). Round 2 (post-pull-up): a live signal now reaches the pin, but distinguishing the modes requires running BELOW min detectable RPM (~82); the fan's mechanical floor (~678 RPM at 0 % drive) makes that unreachable without stalling the motor. Deferred to M7 (or dropped there if deemed unobservable). |
| A4 | POLARITY default paragraph | Resolved by datasheet cross-check | Plain-part polarity is software-controlled, default 0; Table 6.18 POR default `20h` confirms it, and the post-desync `health_check.py` run read FAN_CFG at its POR value. |
| A5 | TCRIT unlock lifecycle | **Deferred — deliberately not consumed** | Consuming the one-time unlock during characterization interacts ambiguously with restoration (per plan); it is exercised only in M7 where persistence needs it. Driver conservatively assumes TCRITOVRD stays set until power cycle. |
| A6 | Receive Byte / pointer increment | **Resolved empirically** | No auto-increment; bare Receive/Send Byte forms desynchronize the SMBus interface (EIO, recovery on reconnect) — see Receive Byte section. Transport contract: register-addressed Write/Read Byte only. |
| A7 | TACH counter clock (90 kHz vs implied 36 kHz) | **Resolved empirically** | 2026-11-22 round 2 (post-pull-up): live count 7955 at 0 % drive ⇒ 5,400,000/7955 ≈ 679 RPM vs the user-measured ~660 RPM floor (within ±10 %); 50 % drive ⇒ ~1865 RPM with monotonic response. Formula validated on live silicon. See the TACH-resolution section. |
| A8 | Spin-up FAST_TACH interaction | Resolved by documentation | Precedence documented as bypass > fast-tach-abort > timed; no bench experiment required. |

Physical checks deferred with reason (M1 scope items c and g):

- **ALERT pin idle state (interrupt mode)**: not measured — the bench wiring does
  not expose the ALERT/TACH net to a Pico GPIO, and the fan-side wire is dead (see
  Bench state). Interrupt-mode *logic* is nonetheless proven by the status
  side-effect observation above; the pin-level check folds into M7 section 6
  (faults/alerts) once the loadout is repaired.
- **Breakout photograph / pull-up inventory**: not taken — photograph at the next
  bench session; the DAC-mode caveat (FAN pull-up removal) is already documented
  from the datasheet and the breakout product page, so nothing downstream is
  blocked.

## Bench state (open items)

Observed 2026-11-22 on the Pico W bench:

- ~~External diode channel OPEN~~ **RESOLVED** (user re-seated the diode
  pins): raw 0x1C/0xC0 = 28.0 °C, status 0x00 (no FAULT), stable across
  200 reads.
- ~~Fan/tach dead~~ **RESOLVED 2026-11-22 (round 2)**: root cause was the
  missing receiver-side pull-up on the TACH net. User added a 10 kOhm
  pull-up from the TACH net to 3.3 V (now permanent on the bench); the chip
  immediately reads live speed (~678 RPM at 0 % drive, ~1865 RPM at 50 %).
  See the TACH-resolution section above. Remaining deferred items per
  D26/D27: A3 behavioral distinction (needs a sub-min-RPM stall,
  unreachable on this bench), ALERT-pin idle-state measurement (folds into
  M7 section 6), breakout photograph.

## Pending rotations (per D25)

- ESP32-S3 (COM7): `probe_id.py` equivalent + repeat characterization when
  the controller rotates.
- RPi 3A+ (SMBus bus 1): `i2cdetect -y 1` + repeat characterization.
