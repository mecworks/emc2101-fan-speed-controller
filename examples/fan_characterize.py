"""Characterize a fan's speed-vs-duty curve on an EMC2101 bench.

Interactive utility: senses whether the fan's tach line needs an external
pull-up, then sweeps the full raw Fan Setting grid (S=0..62 at PWM_F=31,
the chip's finest duty grid, ~1.6 % steps) holding each level for 5 s and
sampling the tach every 250 ms. Emits a CSV in the established bench-data
format (``pct,rpm_settled,rpm_min,rpm_max``) to **stdout** and everything
else -- prompts, progress, the four-answer summary, and a ready-to-paste
renderer command -- to **stderr**, so remote runs capture cleanly:

    Pico W (remote):
        python -m mpremote connect port:COM16 fsync examples
        python -m mpremote connect port:COM16 run examples/fan_characterize.py > curve.csv
    ESP32-S3 (remote):
        python -m mpremote connect port:COM7 fsync examples
        python -m mpremote connect port:COM7 run examples/fan_characterize.py > curve.csv
    Raspberry Pi 3A+ (native, on the Pi):
        python3 examples/fan_characterize.py --save curve.csv

The ``fsync examples`` step deploys the shared analysis module
(_fan_curve_math.py) next to this script on the device. Render the PNG on
any host with matplotlib using the command printed at the end of the run
(tools/render_curve.py). Self-restoring: snapshots the writable registers
and restores + verifies them byte-for-byte before exiting, even on
Ctrl-C. Runtime ~5.5 minutes. Prerequisites: a real 4-wire fan on
FAN+/FAN- with its own supply (see docs/wiring.md); the diode channel is
not used by this utility.
"""
import os
import sys
import time

from emc2101 import _regs as R


# --------------------------------------------------------------------------
# Portable import of the shared analysis core (same directory on both
# platforms; MicroPython does not prepend the script's directory).
# --------------------------------------------------------------------------
def _script_dir():
    f = globals().get("__file__", "")
    for sep in ("/", "\\"):
        if sep in f:
            return f.rsplit(sep, 1)[0]
    return ""


_here = _script_dir()
if _here and _here not in sys.path:
    sys.path.insert(0, _here)

from _fan_curve_math import (CSV_HEADER, analyze, effective_pct,
                             format_csv_row, format_summary, median)

PWM_F_TARGET = 31          # finest grid that still reaches 100 % (UC4)
SWEEP_MAX_SETTING = 62     # S=62 is exactly 100 % on the PWM_F=31 grid


class Aborted(Exception):
    """User-facing abort (dead tach line, bad identity) after restore."""


# --------------------------------------------------------------------------
# Platform helpers
# --------------------------------------------------------------------------
def eprint(line=""):
    """Emit a line on stderr (never contaminates the stdout CSV stream)."""
    sys.stderr.write(line + "\n")
    try:
        sys.stderr.flush()
    except AttributeError:
        pass


def build_device():
    """Construct an EMC2101 device for whichever platform we run on
    (same board detection as the shipped demos)."""
    if sys.platform == "linux":
        from emc2101.cp import EMC2101
        return EMC2101(bus=1)
    import machine
    from emc2101.mp import EMC2101
    machine_name = os.uname().machine.upper()
    if "RP2" in machine_name:
        sda, scl = 0, 1            # Pico W I2C0
    else:
        sda, scl = 41, 42          # ESP32-S3 I2C0
    i2c = machine.I2C(0, sda=machine.Pin(sda), scl=machine.Pin(scl),
                      freq=100_000)
    return EMC2101(i2c)


def detect_bench():
    if sys.platform == "linux":
        return "Linux host (CPython/smbus2)"
    try:
        m = os.uname().machine.upper()
    except (AttributeError, OSError):
        return "MicroPython board"
    if "RP2" in m:
        return "Pico W (MicroPython)"
    if "ESP32" in m:
        return "ESP32-S3 (MicroPython)"
    return "MicroPython board (%s)" % m


# --------------------------------------------------------------------------
# Non-interactive answers (UC12)
# --------------------------------------------------------------------------
# mpremote does not forward host stdin to the device when the host stdin
# is redirected (a piped answer file is never delivered), so input() would
# block forever on a remote run. When ANSWER_FILE exists on the device,
# answers are popped from it instead of stdin; once exhausted (or when the
# file is absent and stdin is closed) every prompt falls back to its
# default, which keeps every pre-flight path terminating.
ANSWER_FILE = "/char_answers.txt"

_ANSWERS = None


def load_answers(path=ANSWER_FILE):
    """Return the answer list from the device file, or None if absent."""
    try:
        with open(path) as f:
            lines = [ln.rstrip("\r\n") for ln in f.readlines()]
    except (OSError, IOError):
        return None
    eprint("non-interactive: %d answers from %s" % (len(lines), path))
    return lines


def ask(prompt, default=""):
    """Prompt on stderr; read the answer from the answer file when loaded,
    else from stdin. Exhausted answers / closed stdin (EOF) fall back to
    the default so non-interactive runs always terminate."""
    sys.stderr.write(prompt)
    try:
        sys.stderr.flush()
    except AttributeError:
        pass
    if _ANSWERS is not None:
        line = _ANSWERS.pop(0) if _ANSWERS else ""
    else:
        try:
            line = input()
        except EOFError:
            line = ""
    line = line.strip()
    return line if line else default


def ask_yn(question, default_yes=False):
    ans = ask(question + (" [Y/n] " if default_yes else " [y/N] "), "").lower()
    if not ans:
        return default_yes
    return ans.startswith("y")


def ask_int(prompt, default, lo, hi):
    while True:
        raw = ask(prompt + " [%d] " % default)
        if not raw:
            return default
        try:
            val = int(raw)
        except ValueError:
            eprint("  please enter a whole number")
            continue
        if lo <= val <= hi:
            return val
        eprint("  out of range (%d..%d)" % (lo, hi))


# --------------------------------------------------------------------------
# Sampling
# --------------------------------------------------------------------------
def sample_median_rpm(dev, ppr, seconds, sample_ms=250):
    """Median RPM over a fixed window (iteration-counted, clock-free)."""
    n = max(1, int(seconds * 1000) // sample_ms)
    vals = []
    for _ in range(n):
        time.sleep(sample_ms / 1000.0)
        vals.append(dev.rpm(ppr))
    return median(vals)


def dwell_sample(dev, ppr, settle_ms, sample_ms, discard_ms):
    """Hold the current duty for settle_ms, sampling every sample_ms;
    discard the first discard_ms as transient/stale-latch (UC7). Returns
    (settled, min, max) over the surviving samples."""
    total = max(1, settle_ms // sample_ms)
    discard = min(discard_ms // sample_ms, total - 1)
    vals = []
    for i in range(total):
        time.sleep(sample_ms / 1000.0)
        if i >= discard:
            vals.append(dev.rpm(ppr))
    if not vals:
        return 0.0, 0.0, 0.0
    return median(vals), min(vals), max(vals)


# --------------------------------------------------------------------------
# Tach pre-flight (UC6)
# --------------------------------------------------------------------------
def _probe_live(dev, ppr):
    """Median RPM at the current (full) drive; >0 means a live signal."""
    return sample_median_rpm(dev, ppr, 3.0)


def _attach_pullup_prompt(attempt):
    eprint("No tach signal detected (attempt %d of 3)." % attempt)
    eprint("Attach a 10 kOhm pull-up from the TACH line to 3.3 V,")
    eprint("then press Enter once it is connected...")
    ask("", "")


def resolve_pullup(dev, ppr):
    """Establish the fan's pull-up requirement. Returns 'built-in' or
    'external'; raises Aborted if the line stays dead after retries."""
    if not ask_yn("Test the tach line now?", default_yes=False):
        needs = ask_yn("Does this fan require an external pull-up on the "
                       "tach line?")
        pullup = "external" if needs else "built-in"
        eprint("Recorded: pull-up = %s (unverified)." % pullup)
        med = _probe_live(dev, ppr)
        if med > 0.0:
            eprint("Sanity check: tach live at %.0f rpm. Proceeding."
                   % med)
            return pullup
        eprint("WARNING: tach reads DEAD at 100 %% drive despite the "
               "recorded configuration.")
        if not ask_yn("Jump into the tach-line test now?", default_yes=True):
            raise Aborted("tach line dead; user declined the test path")
    # Test path: fan connected with NO pull-up on the tach line.
    eprint("Driving the fan at 100 %; sensing the tach line...")
    med = _probe_live(dev, ppr)
    if med > 0.0:
        eprint("Tach live WITHOUT a pull-up (%.0f rpm): the fan provides "
               "its own. Recorded: pull-up = built-in." % med)
        return "built-in"
    for attempt in (1, 2, 3):
        _attach_pullup_prompt(attempt)
        time.sleep(1.0)
        med = _probe_live(dev, ppr)
        if med > 0.0:
            eprint("Tach live WITH the pull-up (%.0f rpm). Recorded: "
                   "pull-up = external." % med)
            return "external"
    raise Aborted(
        "tach line still dead after 3 pull-up attempts. Check: fan power "
        "(the FAN output is PWM only - the fan needs its own supply), "
        "tach wiring to the ALERT/TACH pin, and the breakout's TACH "
        "pull-up jumper (ships disabled on some boards)")


# --------------------------------------------------------------------------
# Snapshot / restore (hw_smoke_test.py pattern, D35/D36 quirks)
# --------------------------------------------------------------------------
SNAP = [R.REG_CONFIG, R.REG_CONV_RATE, R.REG_INT_LIMIT,
        R.REG_EXT_HIGH_MSB, R.REG_EXT_LOW_MSB, R.REG_EXT_HIGH_LSB,
        R.REG_EXT_LOW_LSB, R.REG_EXT_FORCE, R.REG_SCRATCHPAD_1,
        R.REG_SCRATCHPAD_2, R.REG_ALERT_MASK, R.REG_IDEALITY, R.REG_BETA,
        R.REG_TCRIT, R.REG_TCRIT_HYST, R.REG_TACH_LIMIT_LO,
        R.REG_TACH_LIMIT_HI, R.REG_FAN_CFG, R.REG_SPINUP,
        R.REG_FAN_SETTING, R.REG_PWM_F, R.REG_PWM_D, R.REG_LUT_HYST,
        R.REG_FILTER]
for _i in range(8):
    SNAP.append(R.REG_LUT_BASE + 2 * _i)
    SNAP.append(R.REG_LUT_BASE + 2 * _i + 1)


def take_snapshot(dev):
    """Capture every writable register. Silicon quirk (D35): while
    PROG=0 the Fan Setting and LUT registers read back the LUT-driven
    duty, so capture them under a temporary PROG=1 and restore the mode
    afterwards."""
    fc_pre = dev.read_reg(R.REG_FAN_CFG)
    if not (fc_pre & R.FCFG_PROG):
        dev.write_reg(R.REG_FAN_CFG, bytes([fc_pre | R.FCFG_PROG]))
        time.sleep(0.1)   # D36: let the fan-control read-out settle
    snap = {}
    for addr in SNAP:
        # Store the ORIGINAL FAN_CFG (not the PROG-toggled read-back) so
        # restore leaves the chip in the exact mode it started in.
        snap[addr] = fc_pre if addr == R.REG_FAN_CFG else dev.read_reg(addr)
    if not (fc_pre & R.FCFG_PROG):
        dev.write_reg(R.REG_FAN_CFG, bytes([fc_pre]))
    eprint("snapshot: %d registers captured" % len(snap))
    return snap


def restore_snapshot(dev, snap):
    """Raw byte-for-byte restore. Fan-domain registers are read-only
    while PROG=0, so write everything except FAN_CFG with PROG forced
    on, then restore the final mode byte."""
    dev.write_reg(R.REG_FAN_CFG,
                  bytes([snap[R.REG_FAN_CFG] | R.FCFG_PROG]))
    time.sleep(0.1)   # D36: let the fan-control read-out settle
    for addr in sorted(snap):
        if addr != R.REG_FAN_CFG:
            dev.write_reg(addr, bytes([snap[addr]]))
    dev.write_reg(R.REG_FAN_CFG, bytes([snap[R.REG_FAN_CFG]]))
    bad = [a for a in sorted(snap) if dev.read_reg(a) != snap[a]]
    tag = "PASS" if not bad else "FAIL"
    eprint("[%s] safety-net restore byte-for-byte (%d regs)"
           % (tag, len(snap)))
    if bad:
        eprint("[info] mismatched after restore: %r"
               % ["%#02x" % a for a in bad])


# --------------------------------------------------------------------------
# Argument parsing (argparse is unavailable on MicroPython)
# --------------------------------------------------------------------------
USAGE = ("usage: fan_characterize.py [--name NAME] [--ppr N] "
         "[--bench LABEL]\n"
         "                           [--settle-ms MS] [--sample-ms MS] "
         "[--discard-ms MS]\n"
         "                           [--save PATH]")


def parse_opts(argv):
    opts = {"name": None, "ppr": None, "bench": None,
            "settle_ms": 5000, "sample_ms": 250, "discard_ms": 500,
            "save": None}
    flags = {"--name": "name", "--ppr": "ppr", "--bench": "bench",
             "--settle-ms": "settle_ms", "--sample-ms": "sample_ms",
             "--discard-ms": "discard_ms", "--save": "save"}
    i = 1
    while i < len(argv):
        a = argv[i]
        if a in ("-h", "--help"):
            eprint(USAGE)
            sys.exit(0)
        elif a in flags:
            if i + 1 >= len(argv):
                eprint("error: %s needs a value" % a)
                sys.exit(2)
            opts[flags[a]] = argv[i + 1]
            i += 1
        else:
            eprint("warning: unknown option %r ignored" % a)
        i += 1
    for key in ("ppr", "settle_ms", "sample_ms", "discard_ms"):
        if opts[key] is not None:
            try:
                opts[key] = int(opts[key])
            except ValueError:
                eprint("error: %s must be a whole number" % key)
                sys.exit(2)
    if opts["sample_ms"] <= 0 or opts["settle_ms"] < opts["sample_ms"]:
        eprint("error: need --settle-ms >= --sample-ms > 0")
        sys.exit(2)
    if opts["discard_ms"] >= opts["settle_ms"]:
        eprint("error: need --discard-ms < --settle-ms")
        sys.exit(2)
    return opts


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main(argv):
    opts = parse_opts(argv)
    dev = build_device()
    if not dev.probe():
        eprint("No EMC2101 answering at %#x - check wiring/bus."
               % R.ADDR_FIXED)
        return 1
    info = dev.part_info
    eprint("EMC2101 found: product %#x, mfg %#x, rev %#x"
           % (info[0], info[1], info[2]))
    try:
        dev.verify()
    except (OSError, ValueError) as exc:
        eprint("Identity check failed: %s" % exc)
        return 1

    snap = take_snapshot(dev)
    rc = 0
    csv_lines = [CSV_HEADER]
    try:
        global _ANSWERS
        _ANSWERS = load_answers()
        # ------------------------------------------------------ metadata
        bench_default = detect_bench()
        fan_name = opts["name"] or ask("Fan name/model (metadata): ",
                                       "Unknown fan")
        ppr = opts["ppr"] if opts["ppr"] else ask_int(
            "Pulses per revolution", 2, 1, 16)
        bench = opts["bench"] or ask("Bench label", bench_default)

        # ---------------------------------------------- tach pre-flight
        dev.tach_input_enabled = True
        dev.manual = True
        dev.spin_up_enabled = False
        dev.duty_cmd_raw = SWEEP_MAX_SETTING   # 100 % drive for sensing
        eprint("Waiting 3 s for the fan to reach full speed...")
        time.sleep(3.0)
        pullup = resolve_pullup(dev, ppr)

        # ------------------------------------------------- finest grid
        dev.write_reg(R.REG_PWM_F, bytes([PWM_F_TARGET]))
        got = dev.read_reg(R.REG_PWM_F) & 0x1F
        if got != PWM_F_TARGET:
            raise Aborted("PWM_F write did not latch (got %#x)" % got)
        eprint("Duty grid: PWM_F=%d -> %.2f %% steps (~%.1f kHz base)"
               % (PWM_F_TARGET, 100.0 / (2 * PWM_F_TARGET),
                  R.BASE_CLOCK_360K_HZ / (2.0 * PWM_F_TARGET)))

        # -------------------------------------------------------- sweep
        eprint("Sweeping S=0..%d (%d levels x %d ms dwell)... Ctrl-C "
               "aborts safely." % (SWEEP_MAX_SETTING,
                                   SWEEP_MAX_SETTING + 1,
                                   opts["settle_ms"]))
        print(CSV_HEADER)                 # stdout: CSV stream only
        sys.stdout.flush()
        rows = []
        for s in range(SWEEP_MAX_SETTING + 1):
            dev.duty_cmd_raw = s
            pct = effective_pct(s, PWM_F_TARGET)
            settled, rmin, rmax = dwell_sample(dev, ppr, opts["settle_ms"],
                                               opts["sample_ms"],
                                               opts["discard_ms"])
            rows.append((pct, settled, rmin, rmax))
            line = format_csv_row(pct, settled, rmin, rmax)
            csv_lines.append(line)
            print(line)                    # stdout: CSV stream only
            sys.stdout.flush()             # survive block-buffered pipes
            eprint("  level %2d/%d  %5.1f %%  settled %7.1f rpm"
                   % (s, SWEEP_MAX_SETTING, pct, settled))

        # ----------------------------------------------------- summary
        res = analyze(rows)
        eprint("")
        eprint(format_summary(res, fan_name=fan_name))
        date = time.strftime("%Y-%m-%d")
        eprint("")
        eprint("Save the CSV stream (CURVE.csv below) and render the PNG "
               "on any host with matplotlib:")
        eprint('python3 tools/render_curve.py CURVE.csv --fan "%s" '
               '--bench "%s" --pullup %s --ppr %d --date %s'
               % (fan_name, bench, pullup, ppr, date))
        if opts["save"]:
            if hasattr(os, "path"):
                with open(opts["save"], "w") as f:
                    f.write("\n".join(csv_lines) + "\n")
                eprint("CSV also written to %s" % opts["save"])
            else:
                eprint("note: --save unsupported on this platform; the "
                       "stdout stream carries the CSV")
        eprint("FAN CHARACTERIZATION: DONE")
    except Aborted as exc:
        eprint("")
        eprint("FAN CHARACTERIZATION: ABORTED - %s" % exc)
        rc = 1
    except KeyboardInterrupt:
        eprint("")
        eprint("Interrupted - restoring chip state...")
        rc = 130
    except OSError as exc:
        eprint("")
        eprint("Bus error: %s" % exc)
        eprint("Any partial CSV already reached stdout/the host.")
        rc = 1
    finally:
        restore_snapshot(dev, snap)
        dev.close()
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv))
