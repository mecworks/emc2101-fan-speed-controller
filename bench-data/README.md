# Bench data

Live characterization artifacts, one set per bench run, named
`<artifact>_<bench>.{csv,png,meta.json,raw.txt}`:

| File | Contents |
|---|---|
| `*.csv` | The pure CSV stream (`pct,rpm_settled,rpm_min,rpm_max`, established bench-data format) — on remote runs, extracted from the merged capture below. |
| `*.png` | Annotated curve rendered by `tools/render_curve.py` (reference style; metadata footer). |
| `*.meta.json` | Machine-readable render metadata sidecar (fan, bench, date, pull-up, ppr, duty grid). |
| `*.raw.txt` | The full host-side capture of a remote run: device stdout + stderr interleaved on one stream (mpremote relays the single MicroPython console), including pre-flight verdicts, per-level progress, the four-answer summary, and the restore PASS line. Kept as the audit trail. |

## Runs

| Artifact | Date | Bench | Fan | Notes |
|---|---|---|---|---|
| `curve_pico.*` | 2026-11-24 | Pico W @ COM16 (I2C0 GP0/GP1) | Cooler Master SickleFlow 92 | U4 live validation of `examples/fan_characterize.py`. Tach pre-flight test path: live at 100 % without a pull-up (2382 rpm) → built-in. Never stops (~682 rpm floor); onset ~24.2 %; max deviation +16 rpm (1.0 % of span), RMS 6 rpm; no saturation at 100 %. Restore PASS byte-for-byte (40 regs). |
