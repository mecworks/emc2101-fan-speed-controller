# EMC2101 Driver Research

Research phase for a cross-platform (MicroPython + CPython) driver for the SMSC/Microchip
**EMC2101** SMBus fan controller, targeting parity in *method* (not forced API identity) with
the existing **MAX31760** driver at `..\..\FanSpeedController`.

Date: 2026-11-21 · Status: complete, pending review · No code written (per scope).

## Target context (locked during interview)

| Item | Decision |
|---|---|
| Chip | Plain **EMC2101** (Product ID `0x16`), not the `-R` EEPROM-loading variant (`0x28`) |
| Hardware | Adafruit EMC2101 breakout (product 4808, STEMMA QT/Qwiic); must also work on equivalent boards (same chip, fixed address `0x4C`) |
| Platforms | RPi Pico W (MicroPython v1.29.0), ESP32-S3 (MicroPython v1.29.0), Raspberry Pi 3A+ (CPython/smbus2) |
| Approach | Clean-room implementation; Adafruit CircuitPython lib mined for *knowledge* (quirks/timing), not copied |
| API parity goal | Option B — common core, honest edges; no forcing nonexistent features |
| Persistence | On-disk JSON config file mimicking the -R's EEPROM auto-load: `save_config()`/`load_config()` with default path + positional override kwarg; whole-config only for v1 |
| Effort model | Phase-based (developer-authored code; no man-hour estimates) |

## Documents

| File | Contents |
|---|---|
| [emc2101-register-map.md](emc2101-register-map.md) | Full register map extracted from the datasheet (Rev 2.54, 06-16-09): addresses, bits, defaults, encodings, formulas, interlock rules. Supporting appendix for all other docs. |
| [01-feasibility-effort.md](01-feasibility-effort.md) | Cross-platform feasibility verdict, transport-layer analysis, SMBus specifics, chip-quirk catalog, power-on defaults, **phased effort plan (P0–P6)**. |
| [02-api-parity-mapping.md](02-api-parity-mapping.md) | Field-by-field MAX31760 → EMC2101 mapping with verdicts (IDENTICAL / ADAPTED / DIVERGED / NEW / N-A) under the Option-B policy. |
| [03-persistence-opinion.md](03-persistence-opinion.md) | Honest go/no-go opinion on the on-disk config-file "virtual EEPROM": practicality, conventions, risks, boot-window analysis, final design, alternatives considered. |
| [04-reference-notes.md](04-reference-notes.md) | Reference-implementation survey (Adafruit lib deep-dive incl. defects found, ESPHome, miner firmware, OctoPrint plugin, etc.), datasheet ambiguities, silicon-marking note, source links. |
| [05-architecture-sketch.md](05-architecture-sketch.md) | Proposed repo/package layout mirroring `FanSpeedController`, module responsibilities, adapted transport contract, persistence seam, test strategy, licensing. |

## TL;DR answers to the three research questions

### Q1 — What will it take to build the driver?

**Fully feasible, low-to-moderate risk.** Every target platform has already run this exact chip
under an equivalent runtime: MicroPython on Pico-class hardware (third-party port of the Adafruit
lib exists), ESP32 (ESPHome component + multiple miner firmwares), and Linux SMBus (OctoPrint
plugin using py-smbus). There is **no Linux kernel driver**, so there is no upstream authority to
defer to — the datasheet plus the surveyed implementations are the reference set.

The dominant design constraint is that the EMC2101 supports **single-byte transactions only**
(no multi-byte/block reads or writes; the register pointer does not auto-increment). The sibling
driver's `burst_read/burst_write` transport contract therefore adapts to a single-byte contract
(`read_byte/write_byte`), with the core composing multi-register sequences explicitly. Everything
else — dual-facade packaging, mock-backed test suite, lint gates, error model — transfers almost
verbatim from `FanSpeedController`.

Effort is organized into seven phases (P0 bench bring-up → P6 hardware E2E matrix); see
[01-feasibility-effort.md §7](01-feasibility-effort.md).

### Q2 — Can the two drivers share API for the same functionality?

**Yes, substantially — under the agreed Option-B policy.** Of the ~45 members in the overlapping
functional domain, ~35 carry over with identical or adapted names/semantics (probe/verify, temps,
setpoints, manual duty, LUT programming, hysteresis, PWM frequency, RPM, tach threshold, spin-up,
alert service sequence, ideality factor, standby, raw access, error model, packaging). Genuinely
non-transferable areas (fan-fail force circuitry, pulse stretching, software POR, per-port tach,
actual-duty feedback) are marked N/A rather than faked. Three items diverge by name deliberately
(LUT structure, polarity semantics, overtemp→TCRIT). Full table:
[02-api-parity-mapping.md](02-api-parity-mapping.md).

Portability illustration — this block runs unchanged against both drivers:

```python
dev.verify()
print(dev.local_temp_c, dev.remote_temp_c)
dev.manual = True
dev.set_duty_pct(50.0)
print(dev.rpm())
dev.manual = False
dev.save_config()      # MAX31760: chip EEPROM · EMC2101: JSON file
dev.load_config()
```

### Q3 — Is the on-disk "virtual EEPROM" a good idea?

**Verdict: GO — practical, conventional when properly isolated, and it closes the autonomy gap to
one line of application code.** It is a superset feature (nothing in the driver's core depends on
it), it follows established embedded-config patterns (versioned, validated, driver-owned schema),
and its main hazards (flash wear, corruption, stale/mismatched files, the cold-boot window) have
cheap mitigations. The one honest limitation: true power-on autonomy is impossible without
bootloader involvement — the chip sits at POR defaults (fan at 0% setting ≈ minimum speed on most
modern fans) until `load_config()` executes. Details, risks, and the final design:
[03-persistence-opinion.md](03-persistence-opinion.md).

## Sources

- **Primary:** `../EMC2101_datasheet.pdf` — SMSC EMC2101 Rev 2.54 (06-16-09), 57 pp. (extracted text cached at `research/../emc2101_datasheet.txt` during research; treat the PDF as authoritative).
- **Sibling driver:** `..\..\FanSpeedController` (max31760 package, v0.1.1) — architecture and API template.
- **Reference implementations:** Adafruit CircuitPython `adafruit_emc2101` (MIT), ESPHome `emc2101` component, bitaxeorg/ESP-Miner, 256foundation/mujina-miner, WildernessLabs/Meadow.Foundation, kvasir-io/kvasir_devices, j9brown/poppy (OctoPrint), AccelerationConsortium/ac-dev-lab — surveyed in [04-reference-notes.md](04-reference-notes.md).
- **Web:** Adafruit product page 4808; Microchip-hosted datasheet copy; GitHub code search (kernel-driver absence verified).
