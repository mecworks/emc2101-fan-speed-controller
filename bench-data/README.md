# Bench data

Live characterization artifacts, organized **per device under test (DUT)**:
one directory per fan make/model, one subdirectory per bench platform, and
artifacts prefixed with the run date so repeated runs never overwrite each
other:

```
bench-data/
  <Fan Make Model>/                 # e.g. "Cooler Master SickleFlow 92"
    <platform>/                     # pico | esp32 | rpi
      duty_curve_<YYYY-MM-DD>.csv         pure CSV stream
      duty_curve_<YYYY-MM-DD>.png         annotated curve
      duty_curve_<YYYY-MM-DD>.meta.json   render-metadata sidecar
      duty_curve_<YYYY-MM-DD>.raw.txt     full host-side capture (audit trail)
```

Artifact contents:

| File | Contents |
|---|---|
| `*.csv` | The pure CSV stream (`pct,rpm_settled,rpm_min,rpm_max`, established bench-data format). On remote runs, extracted from the merged capture below. |
| `*.png` | Annotated curve rendered by `tools/render_curve.py` (reference style; metadata footer). |
| `*.meta.json` | Machine-readable render metadata sidecar (fan, bench, date, pull-up, ppr, duty grid, analysis). |
| `*.raw.txt` | The full host-side capture of a remote run: device stdout + stderr interleaved on one stream (mpremote relays the single MicroPython console), including pre-flight verdicts, per-level progress, the four-answer summary, and the restore PASS line. Kept as the audit trail — it records what the tooling printed *at that time*, including any verdict later superseded by a tooling fix. |

## Runs

| DUT | Platform | Date | Notes |
|---|---|---|---|
| Cooler Master SickleFlow 92 | pico (COM16) | 2026-11-24 | U4 live validation of `examples/fan_characterize.py`. Tach pre-flight: live at 100 % (2382 rpm) **with the bench-installed external pull-up** → recorded `external`. This fan has no built-in tach pull-up (determined during the MAX31760 driver build); the ~10 kOhm resistor is permanently installed on the bench breadboard. Never stops (~682 rpm floor); onset ~24.2 %; max deviation +16 rpm (1.0 % of span), RMS 6 rpm vs the ideal line; no saturation at 100 %. Restore PASS byte-for-byte (40 regs). Note: the `.raw.txt` capture predates the UC13 wiring-state question and contains the superseded "pull-up = built-in" line; the corrected verdict is `external` (see PNG footer / meta.json). |
| Cooler Master SickleFlow 92 | rpi (SMBus bus 1) | 2026-11-24 | U4 native leg on the RPi 3A+ bench (marc@192.168.1.225, smbus2). Non-interactive background run (answers piped via ssh; no `/char_answers.txt` needed off mpremote), RC=0, restore PASS byte-for-byte (40 regs). Agrees with the Pico leg within noise: never stops (~682 rpm floor); onset ~22.6 % (UC15 span-relative tolerance confirmed on the second platform); max deviation +12 rpm (0.7 % of span) @ 58.1 %, RMS 5 rpm; no saturation (2373.6 rpm at 100 %); verdict `external`. |
