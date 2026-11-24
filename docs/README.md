# emc2101 documentation

One Python package (`emc2101`), one API, three machines: drive the
SMSC/Microchip **EMC2101** SMBus fan controller from MicroPython on a
Raspberry Pi Pico W or an ESP32-S3, or from CPython/smbus2 on a
Raspberry Pi 3A+. The chip address is fixed at `0x4C`.

| Document | What it covers |
|---|---|
| [Quickstart](quickstart.md) | Install per platform, first program for both facades, saving/loading a config |
| [API reference](api-reference.md) | Every public member: signatures, ranges, exceptions, side effects |
| [Wiring guide](wiring.md) | STEMMA QT/Qwiic and raw I²C connections, per-platform pin tables, pull-up rules, DAC-mode caveat |
| [Persistence](persistence.md) | JSON schema v1, `save_config`/`load_config`, auto-load semantics, strict read-back, TCRIT interaction |
| [Operational notes](operational-notes.md) | Cold-boot window, TCRIT lifecycle, ALERT/TACH trade-offs, ARA, force-register testing, SMBus TIMEOUT, retry ladder |
| [Fan curve characterization](fan-characterization.md) | Collector + renderer workflow: tach pull-up pre-flight, raw-grid sweep, CSV/PNG/meta.json artifacts, interpreting the four answers |

Ground rules that apply to every document:

- **Single-byte protocol.** The EMC2101 supports only Write Byte / Read
  Byte / Send Byte / Receive Byte / ARA — no block transfers, and the
  register pointer does not auto-increment between transactions.
- **Destructive reads.** Reading Status (02h) clears latched alarm bits;
  reading external temperature MSB (01h) refreshes the LSB shadow. The
  driver's verbs make these side effects visible at the call site.
- **Interlocks.** External temperature must be read MSB-first
  (01h → 10h); the TACH counter must be read LSB-first (46h → 47h).
  The driver enforces both orders internally.
- **Errors.** `ValueError` for out-of-range arguments, `OSError` for bus
  failures after the retry ladder, `DiodeFaultError` (an `OSError`
  subclass) for open/short diode sentinels, and the persistence-layer
  `ConfigFormatError` / `ConfigValidationError` (`ValueError` subclasses)
  plus `ConfigApplyError` (`OSError` subclass).

The authoritative datasheet is SMSC EMC2101 Rev 2.54
(<https://ww1.microchip.com/downloads/en/DeviceDoc/2101.pdf>). Register
facts in this repository are cross-checked against it in
[`research/emc2101-register-map.md`](../research/emc2101-register-map.md).
