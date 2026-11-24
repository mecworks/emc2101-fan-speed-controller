"""Render a fan-curve PNG (and metadata sidecar) from a characterization CSV.

Host-side second stage of the fan-curve utility: reads the CSV produced by
examples/fan_characterize.py (header ``pct,rpm_settled,rpm_min,rpm_max``)
and draws the annotated curve in the established bench-data style --
measured curve, min-to-max reference chord, onset marker, 0 % anomaly
flag, max-deviation annotation -- with the fan's metadata in a footer
strip below the axes so it can never obscure chart data. Also writes a
``<stem>.meta.json`` sidecar next to the PNG for machine-readable
metadata. CPython + matplotlib only (MicroPython has no matplotlib); run
it on whatever host has Python 3 and matplotlib.

Usage:
    python3 tools/render_curve.py CURVE_CSV [--out OUT.png] \
        [--fan NAME] [--bench LABEL] \
        [--pullup built-in|external|unknown] [--ppr N] [--date YYYY-MM-DD]

Metadata flags are optional; missing values render as "-" in the footer
and the sidecar. The analysis is shared with the collector via
examples/_fan_curve_math.py (imported through the sys.path bootstrap
below), so the annotations always match the printed text summary.
"""
import argparse
import json
import os
import sys

# Documented bootstrap: the shared analysis core lives in examples/
# (it deploys there alongside the collector); this tool is CPython-only,
# so plain os.path is available.
_HERE = os.path.dirname(os.path.abspath(__file__))
_EXAMPLES = os.path.join(os.path.dirname(_HERE), "examples")
if _EXAMPLES not in sys.path:
    sys.path.insert(0, _EXAMPLES)

from _fan_curve_math import analyze  # noqa: E402

GRID_NOTE = "duty grid: raw S=0..62 @ PWM_F=31 (~1.6 % steps)"


def parse_args(argv):
    p = argparse.ArgumentParser(
        description="Render a fan-curve PNG + metadata sidecar from a "
                    "characterization CSV.")
    p.add_argument("csv", help="path to the characterization CSV")
    p.add_argument("--out", default=None,
                   help="output PNG path (default: <csv stem>_curve.png)")
    p.add_argument("--fan", default=None, help="fan name/model")
    p.add_argument("--bench", default=None, help="bench label")
    p.add_argument("--pullup", default=None,
                   choices=["built-in", "external", "unknown"],
                   help="tach pull-up requirement")
    p.add_argument("--ppr", type=int, default=None,
                   help="pulses per revolution used during the sweep")
    p.add_argument("--date", default=None, help="sweep date (YYYY-MM-DD)")
    return p.parse_args(argv)


def read_csv(path):
    """Parse the established bench-data CSV into row tuples."""
    rows = []
    with open(path, "r") as f:
        header = f.readline().strip()
        if header != "pct,rpm_settled,rpm_min,rpm_max":
            raise ValueError("unexpected CSV header: %r" % header)
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(",")
            if len(parts) != 4:
                raise ValueError("malformed CSV row: %r" % line)
            rows.append(tuple(float(v) for v in parts))
    if not rows:
        raise ValueError("CSV contains no data rows")
    return rows


def dash(value, fmt="%s"):
    """Footer value or '-' placeholder."""
    return fmt % value if value not in (None, "") else "-"


def render(rows, args, out_path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    res = analyze(rows)
    pct = [r[0] for r in rows]
    settled = [r[1] for r in rows]

    fig, ax = plt.subplots(figsize=(10, 6.5), dpi=150)
    fig.subplots_adjust(bottom=0.14, top=0.90)  # footer strip + title room

    fan = args.fan or "Unknown fan"
    title = "%s - duty vs RPM\n(EMC2101, %s, %s)" % (
        fan, dash(args.bench), dash(args.date))
    fig.suptitle(title, fontsize=13)
    ax.set_xlabel("Commanded PWM duty (%)")
    ax.set_ylabel("Fan speed (RPM)")
    ax.grid(True, alpha=0.3)

    # Measured curve
    ax.plot(pct, settled, "o-", color="#1f5fbf", markersize=3,
            linewidth=1.2, label="Measured (settled)")

    # Min-to-max reference chord (exactly the line deviations were
    # measured against, per the shared analysis core)
    lin = res["linearity"]
    if lin is not None:
        x0, y0, x1, y1 = lin["ref_line"]
        ax.plot([x0, x1], [y0, y1], "--", color="#888888", linewidth=1.2,
                label="Min-to-max reference (%.0f@%.0f%% -> %.0f@%.0f%%)"
                      % (y0, x0, y1, x1))
        chord_y = y0 + (y1 - y0) / (x1 - x0) * (lin["at_pct"] - x0)
        ax.annotate("max dev: %+.0f rpm @ %.0f%%\nRMS %.0f rpm"
                    % (lin["max_dev_rpm"], lin["at_pct"], lin["rms_rpm"]),
                    xy=(lin["at_pct"], chord_y),
                    xytext=(-70, 40), textcoords="offset points",
                    fontsize=9,
                    arrowprops=dict(arrowstyle="->", color="#555555"))

    # Onset marker (Q2): where the fan starts turning / begins rising
    if res["onset_pct"] is not None:
        ax.axvline(res["onset_pct"], color="#2e8b57", linestyle=":",
                   linewidth=1.4)
        _, ytop = ax.get_ylim()
        ax.text(res["onset_pct"] + 0.8, ytop * 0.97,
                "onset ~%.0f%%" % res["onset_pct"], fontsize=9,
                color="#2e8b57", va="top", ha="left")

    # 0 % anomaly flag (stale latch / tach gating hint)
    if res["zero_flag"] is not None:
        s0 = settled[0]
        ax.scatter([pct[0]], [s0], facecolors="none", edgecolors="#cc0000",
                   s=140, zorder=5, label="0%%: %.0f rpm (anomaly flag)"
                              % s0)
        ax.annotate("%.0f rpm at 0%% disagrees with the plateau" % s0,
                    xy=(pct[0], s0), xytext=(12, -10),
                    textcoords="offset points", fontsize=9,
                    arrowprops=dict(arrowstyle="->", color="#cc0000"))

    handles, labels = ax.get_legend_handles_labels()
    ax.legend(handles, labels, loc="lower right", fontsize=9)

    # Metadata footer: a fig.text strip BELOW the axes, structurally
    # incapable of overlapping chart data (UC5).
    footer = ("Fan: %s    Bench: %s    Date: %s    Tach pull-up: %s    "
              "Pulses/rev: %s    %s") % (
        dash(args.fan), dash(args.bench), dash(args.date),
        dash(args.pullup), dash(args.ppr, "%d"), GRID_NOTE)
    fig.text(0.5, 0.015, footer, ha="center", fontsize=9,
             bbox=dict(boxstyle="round,pad=0.4", fc="#f5f5f5",
                       ec="#bbbbbb"))

    fig.savefig(out_path)
    plt.close(fig)

    # Machine-readable sidecar next to the PNG
    meta = {
        "fan": args.fan,
        "bench": args.bench,
        "date": args.date,
        "pullup": args.pullup,
        "ppr": args.ppr,
        "grid": GRID_NOTE,
        "source_csv": os.path.abspath(args.csv),
        "analysis": res,
    }
    meta_path = os.path.splitext(out_path)[0] + ".meta.json"
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    return meta_path


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        rows = read_csv(args.csv)
    except (OSError, ValueError) as exc:
        print("error: cannot read %s: %s" % (args.csv, exc), file=sys.stderr)
        return 1
    out_path = args.out or (os.path.splitext(args.csv)[0] + "_curve.png")
    try:
        meta_path = render(rows, args, out_path)
    except ImportError:
        print("error: matplotlib is required (pip install matplotlib)",
              file=sys.stderr)
        return 1
    except OSError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1
    print("wrote %s" % out_path)
    print("wrote %s" % meta_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
