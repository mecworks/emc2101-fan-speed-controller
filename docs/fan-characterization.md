# Fan curve characterization

`examples/fan_characterize.py` sweeps the full raw duty grid of an EMC2101
bench and characterizes the speed-vs-duty curve of the connected fan. It
answers four questions about *your specific* fan:

1. Does the fan ever actually stop, or does it hold a minimum-speed floor?
2. At what commanded PWM duty does it start turning (or begin rising above
   its floor)?
3. How closely does it track the ideal linear duty→speed curve?
4. Is there a maximum duty above which speed stops increasing?

It also determines whether the fan's tach line needs an external pull-up
(~10 kΩ from TACH to 3V3) and records the verdict in the output metadata.

Two scripts cooperate:

| Script | Role | Runs on |
|---|---|---|
| `examples/fan_characterize.py` | Collector: tach pre-flight + 63-level sweep; CSV to **stdout**, everything else to **stderr** | MicroPython (Pico W / ESP32-S3) or CPython (RPi 3A+) |
| `tools/render_curve.py` | Renderer: CSV → annotated PNG + `.meta.json` sidecar | CPython + matplotlib (host only) |

Both share the analysis core `examples/_fan_curve_math.py`, so the PNG
annotations and the printed text summary can never drift apart.

## Prerequisites

- A real 4-wire fan on FAN+/FAN− **with its own supply** — the FAN output
  is PWM only. See [Wiring guide](wiring.md). The diode channel is not used
  by this utility.
- **MCU benches:** the package deployed first —
  `python tools/deploy_mp.py --port <PORT>` (MicroPython ≥ 1.29).
- **Raspberry Pi 3A+:** `smbus2` installed, I²C enabled, the user in the
  `i2c` group, and the repository importable (see
  [Quickstart](quickstart.md)).
- **Any host with Python 3 + matplotlib** for the render stage
  (`pip install matplotlib`).

Runtime is ~5.5–6 minutes (63 levels × 5 s dwell plus pre-flight).

## Running the collector

### Interactive prompts

With no flags the collector asks, in order:

| # | Prompt | Default |
|---|---|---|
| 1 | Fan name/model (metadata) | `Unknown fan` |
| 2 | Pulses per revolution (1..16) | `2` |
| 3 | Bench label | detected (e.g. `Pico W (MicroPython)`) |
| 4 | Is an external pull-up currently attached to the tach line? `[y/N]` | n |
| 5 | Test the tach line now? `[y/N]` | n |

The tach test drives the fan at 100 % and samples ~3 s: a live count
records `built-in` when no pull-up is attached and `external` when one is
(the wiring state is asked explicitly because a bench-installed resistor
makes any fan look built-in); a dead count offers up to 3 attach-and-retry
attempts, then **aborts** with diagnostics if the line stays dead — a sweep
without a working tach is worthless. Declining the test instead asks
"Does this fan require an external pull-up?" and runs a silent 100 % sanity
check that warns loudly if the line reads dead.

### Flags

Flags skip the corresponding prompts; constraints are validated
(`--settle-ms >= --sample-ms > 0`, `--discard-ms < --settle-ms`):

| Flag | Meaning | Default |
|---|---|---|
| `--name NAME` | fan name/model | prompt |
| `--ppr N` | pulses per revolution | prompt (2) |
| `--bench LABEL` | bench label | prompt (detected) |
| `--settle-ms MS` | dwell per level | 5000 |
| `--sample-ms MS` | sample interval | 250 |
| `--discard-ms MS` | transient discarded at each dwell's start | 500 |
| `--save PATH` | also write the CSV to a file (CPython only) | — |

### Remote run (MicroPython via mpremote)

Verified procedure on mpremote 1.29.0 (invoke it as `python -m mpremote`;
this version neither forwards redirected host stdin nor post-script
arguments to `run`, so answers come from a device-local file):

```powershell
# 1. Deploy the package (8 files to /lib/emc2101/)
python tools/deploy_mp.py --port COM16

# 2. Push the shared analysis module to the device ROOT. mpremote's
#    `fs cp` fails on the root FS, so use the same exec/base64 chunked
#    transfer that tools/deploy_mp.py uses (create/truncate, append
#    base64-decoded chunks, verify size/hash).

# 3. Stage the answer file (one line per prompt, in the order above;
#    extra blank lines are harmless — exhaustion falls back to defaults)
python -m mpremote connect port:COM16 exec "open('/char_answers.txt','w').write('Cooler Master SickleFlow 92\n2\nPico W (COM16)\ny\ny\n')"

# 4. Capture (~6 min). The MicroPython console is a single stream, so the
#    capture mixes CSV rows with the stderr chatter.
python -u -m mpremote connect port:COM16 run examples/fan_characterize.py > curve_raw.txt
```

Recover the pure CSV from the merged capture: keep the header line
(`pct,rpm_settled,rpm_min,rpm_max`) plus every line of four
comma-separated numbers. Keep `curve_raw.txt` too — it is the audit trail
(pre-flight verdicts, per-level progress, the four-answer summary, the
restore PASS line). On the ESP32-S3 substitute `port:COM7`.

### Native run (Raspberry Pi 3A+, on the Pi)

Here stdout/stderr separate cleanly, so `--save` yields a pure CSV
directly:

```bash
cd ~/fanchar                                  # repo checkout
export PYTHONPATH=$HOME/fanchar               # or: pip install -e .
python3 examples/fan_characterize.py --save curve.csv
```

Non-interactive (ssh forwards host stdin fine, so answers pipe straight
in — the answer file is only needed for mpremote):

```bash
printf 'y\ny\n' | python3 -u examples/fan_characterize.py \
  --name 'Cooler Master SickleFlow 92' --ppr 2 \
  --bench 'RPi 3A+ (SMBus bus 1)' --save curve.csv
```

(The two `y`s answer the pull-up-attached and test-the-tach prompts.)

### Safety

The collector is self-restoring: it snapshots every writable register up
front and restores + verifies them byte-for-byte before exiting, even on
Ctrl-C. Watch for the closing lines:

```
FAN CHARACTERIZATION: DONE
[PASS] safety-net restore byte-for-byte (40 regs)
```

An abort (dead tach, bad identity, failed PWM_F latch) prints
`FAN CHARACTERIZATION: ABORTED - <reason>` after restoring, and exits
nonzero; a partial CSV already streamed to the host is still usable.

## Viewing the results

### The CSV

Header `pct,rpm_settled,rpm_min,rpm_max`, one row per raw setting
(S=0..62 at PWM_F=31, effective duty = S/(2·31)·100 %, ~1.6 % steps):

| Column | Meaning |
|---|---|
| `pct` | effective commanded duty, 1 decimal |
| `rpm_settled` | median of the dwell's surviving samples (first 500 ms discarded as transient/stale-latch) |
| `rpm_min` / `rpm_max` | extremes over the same window |

`0.0` means the tach sentinel (input disabled / fan stopped / below the
minimum detectable RPM).

### Rendering the PNG

The collector prints a ready-to-paste command at the end of the run;
equivalently:

```bash
python3 tools/render_curve.py curve.csv \
  --out curve.png --fan "Cooler Master SickleFlow 92" \
  --bench "Pico W (COM16)" --pullup external --ppr 2 --date 2026-11-24
```

All flags are optional — missing values render as `-` in the footer and
sidecar, so re-rendering from the CSV alone always works. The renderer
writes `<stem>.png` and a `<stem>.meta.json` sidecar next to it.

What the chart shows:

- **Measured (settled)** — the swept curve.
- **Min-to-max reference** (dashed) — exactly the chord the deviations
  were measured against (onset point → last/ceiling point).
- **Green dotted vertical** — the onset marker, labeled `onset ~P%`.
- **Red circle + annotation** — only when the 0 % row disagrees with the
  low-duty plateau (stale-latch / tach-gating hint).
- **Max-deviation callout** — worst deviation from the reference chord
  (rpm and % of span) plus RMS.
- **Footer strip** — fan, bench, date, tach pull-up verdict, pulses/rev,
  duty-grid note. Structurally below the axes, so it can never obscure
  data.

### The sidecar

`<stem>.meta.json` carries the same metadata machine-readably, plus the
full analysis dict: `turns_off`, `floor_rpm`, `onset_pct`/`onset_rpm`,
`linearity` (`max_dev_rpm`, `max_dev_pct_of_span`, `at_pct`, `rms_rpm`,
`ref_line`), `ceiling_pct`, `zero_flag`, `peak_rpm`.

### Where artifacts go

Commit runs under the per-DUT convention documented in
[`bench-data/README.md`](../bench-data/README.md):

```
bench-data/<Fan Make Model>/<platform>/duty_curve_<YYYY-MM-DD>.*
```

(platform ∈ `pico` | `esp32` | `rpi`; the date prefix keeps repeat runs
from overwriting each other).

## Interpreting the four answers

The heuristics are named constants in `examples/_fan_curve_math.py`
(overridable via kwargs), applied to the settled column:

- **Floor baseline** — median of the first third of the curve; robust to a
  stale-latch spike in the 0 % row.
- **Onset** — the first row where speed exceeds
  `baseline + max(10 rpm, 2 % of the dynamic range (peak − floor))`
  sustained over 3 consecutive rows (for stopping fans: the first nonzero
  row). Span-relative scaling keeps the tolerance honest across DUTs:
  keyed to the absolute peak it would swallow the early climb of a
  high-speed fan. Quoted to the nearest grid step (~1.6 %).
- **Linearity** — deviations versus the straight chord joining the onset
  point and the last (or ceiling) point; reports the worst deviation (rpm
  and % of span) and the RMS.
- **Ceiling** — walked down from 100 % while the local slope stays under
  1 rpm/% over a 5-row window; reported only on a genuine rising→flat
  transition, otherwise "still increasing at 100 %".
- **0 % anomaly flag** — raised when the 0 % row disagrees with the
  plateau by more than the onset threshold (possible stale-latch artifact
  or tach gating at zero duty).

Example (Cooler Master SickleFlow 92, Pico W leg, 2026-11-24):

```
Fan curve summary - Cooler Master SickleFlow 92
-----------------------------------------------
1) Fan NEVER STOPS: holds a ~682 rpm floor at 0 % drive.
2) Speed begins rising above its ~682 rpm floor at ~22.6 % PWM.
3) Linearity: max deviation +15 rpm (1.0 % of span) at 98.4 % duty; RMS 7 rpm vs the ideal linear curve.
4) Speed still increasing at 100 % PWM (no saturation observed).
```

Caveats: settled values are medians of ~18 samples, so a lone stale-latch
spike can leak into `rpm_max` without affecting `rpm_settled`; the pull-up
verdict records the fan's requirement *as seen under the current wiring*;
and the coarse grid means onset/ceiling edges carry ±1 step of quantization.
