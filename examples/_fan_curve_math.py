"""Pure analysis core for fan-curve characterization.

Shared by the collector (examples/fan_characterize.py, which deploys this
module to the device) and the host-side renderer (tools/render_curve.py) so
the PNG annotations and the printed text summary can never drift apart.

Constraints: pure stdlib, MicroPython-safe (runs on Pico W / ESP32-S3
v1.29.0), no driver imports, no CPython-only modules. See
tests/lint_subset.py for the enforced subset.

A "row" is a tuple ``(pct, rpm_settled)`` or the full CSV quadruple
``(pct, rpm_settled, rpm_min, rpm_max)``; only the first two elements are
consumed. ``pct`` is the effective commanded duty (0..100, floats allowed
because the raw-setting grid is coarser than 1 %).

Degenerate inputs (empty series, all-zero series, a single nonzero row)
yield explicit ``None`` markers in the result instead of raising, so the
caller can print "unmeasurable" rather than crash mid-bench.
"""
import math

#: Exact header of the established bench-data CSV format.
CSV_HEADER = "pct,rpm_settled,rpm_min,rpm_max"

#: Default heuristic thresholds for :func:`analyze` (see each docstring).
ONSET_TOL_RPM = 10.0          #: absolute rise above the floor plateau
ONSET_FRAC = 0.02             #: ...or this fraction of the peak speed
SUSTAIN_ROWS = 3              #: consecutive rows above threshold => onset
NOISE_FLOOR_RPM_PER_PCT = 1.0 #: local slope below this counts as a plateau
PLATEAU_WINDOW_ROWS = 5       #: window used for the local-slope test


def effective_pct(setting, pwm_f):
    """Effective duty percent for a raw 6-bit Fan Setting on a given grid.

    eq.[6]: effective duty = S / (2*PWM_F) * 100 %, clamped at full scale
    (settings above 2*PWM_F clamp in hardware). Mirrors
    emc2101._regs.setting_to_duty_pct without importing the driver.
    """
    if not 1 <= pwm_f <= 31:
        raise ValueError("pwm_f must be 1..31")
    if not 0 <= setting <= 63:
        raise ValueError("setting must be 0..63")
    return min(setting, 2 * pwm_f) / (2.0 * pwm_f) * 100.0


def median(values):
    """Median of a non-empty numeric sequence (hand-rolled; MicroPython
    ships no ``statistics`` module). Even-length sequences average the two
    middle values."""
    vals = sorted(values)
    n = len(vals)
    if n == 0:
        raise ValueError("median of empty sequence")
    mid = n // 2
    if n % 2:
        return float(vals[mid])
    return (vals[mid - 1] + vals[mid]) / 2.0


def format_csv_row(pct, rpm_settled, rpm_min, rpm_max):
    """Assemble one CSV line in the established bench-data format
    (one decimal place, matching the reference files)."""
    return "%.1f,%.1f,%.1f,%.1f" % (pct, rpm_settled, rpm_min, rpm_max)


def _degenerate(turns_off=True):
    """Result skeleton for series that carry no usable information."""
    return {
        "turns_off": turns_off,
        "floor_rpm": None,
        "onset_pct": None,
        "onset_rpm": None,
        "linearity": None,
        "ceiling_pct": None,
        "zero_flag": None,
        "peak_rpm": 0.0,
    }


def analyze(rows, onset_tol_rpm=ONSET_TOL_RPM, onset_frac=ONSET_FRAC,
            sustain=SUSTAIN_ROWS,
            noise_floor_rpm_per_pct=NOISE_FLOOR_RPM_PER_PCT,
            plateau_window=PLATEAU_WINDOW_ROWS):
    """Derive the four characterization answers from a swept curve.

    Inputs
    ------
    rows : sequence of ``(pct, rpm_settled)`` or full CSV quadruples, in
           ascending duty order (the collector's emission order).
    onset_tol_rpm / onset_frac : a floor-holding fan counts as "beginning
           to rise" once its speed exceeds the low-duty plateau baseline by
           at least ``max(onset_tol_rpm, onset_frac * peak)``.
    sustain : the excess must hold for this many consecutive rows before
           the first such row is reported as the onset.
    noise_floor_rpm_per_pct : local slope (rpm per percent of duty) below
           which the curve counts as saturated.
    plateau_window : number of rows spanning the local-slope window.

    Returns a dict:
      turns_off   -- False iff the 0 % row shows live speed (floor fan).
      floor_rpm   -- low-duty plateau baseline (median of the first third
                     of the curve; robust to a stale-latch 0 % artifact),
                     or None when the fan stops.
      onset_pct   -- duty where the fan starts turning (stopping fans) or
                     begins rising above its floor (floor fans); None when
                     unmeasurable.
      onset_rpm   -- settled speed at the onset row (annotation aid).
      linearity   -- dict(max_dev_rpm, max_dev_pct_of_span, at_pct, rms_rpm)
                     versus the straight line joining the onset point and
                     the ceiling point; None when fewer than three points
                     or a non-positive span makes the fit meaningless.
      ceiling_pct -- duty above which the speed plateaus (walked down from
                     100 % while the local slope stays under the noise
                     floor); None when the curve is still rising at 100 %.
      zero_flag   -- reason string when the 0 % row disagrees with the
                     low-duty plateau (stale-latch / tach-gating hint),
                     else None.
      peak_rpm    -- maximum settled speed seen.
    """
    data = [tuple(r) for r in rows]
    n = len(data)
    if n == 0:
        return _degenerate()
    pcts = [float(r[0]) for r in data]
    settled = [float(r[1]) for r in data]
    peak = max(settled)
    if peak <= 0.0:
        return _degenerate()

    s0 = settled[0]
    turns_off = s0 <= 0.0

    # Low-duty plateau baseline: median of the first third of the curve.
    # The median absorbs a stale-latch spike in the 0 % row and the early
    # part of a gradual rise.
    plat_n = max(1, (n + 2) // 3)
    baseline = median(settled[:plat_n])

    # ---- Q1/Q2: stop-vs-floor and onset -------------------------------
    if turns_off:
        floor_rpm = None
        onset_idx = None
        for i in range(n):
            if settled[i] > 0.0:
                onset_idx = i
                break
    else:
        floor_rpm = baseline
        thr = baseline + max(onset_tol_rpm, onset_frac * peak)
        onset_idx = None
        run = 0
        for i in range(n):
            if settled[i] > thr:
                run += 1
                if run >= sustain:
                    onset_idx = i - run + 1
                    break
            else:
                run = 0

    # ---- Q4: saturation ceiling ---------------------------------------
    # Walk down from 100 % while the local slope stays under the noise
    # floor. A ceiling is reported only on a genuine rising->flat
    # transition: an all-flat or all-stopped tail (loop exhausted without
    # ever seeing a rising slope) carries no information.
    idx = n - 1
    found_transition = False
    while idx - plateau_window >= 0:
        dp = pcts[idx] - pcts[idx - plateau_window]
        ds = settled[idx] - settled[idx - plateau_window]
        slope = ds / dp if dp > 0.0 else 0.0
        if slope < noise_floor_rpm_per_pct:
            idx -= 1
        else:
            found_transition = True
            break
    ceiling_idx = idx
    ceiling_pct = (pcts[idx] if found_transition and idx < n - 1
                   else None)

    # ---- Q3: linearity vs the onset->ceiling reference line -----------
    linearity = None
    if onset_idx is not None and ceiling_idx - onset_idx >= 2:
        x0, y0 = pcts[onset_idx], settled[onset_idx]
        x1, y1 = pcts[ceiling_idx], settled[ceiling_idx]
        span = y1 - y0
        if x1 > x0 and span > 0.0:
            slope = (y1 - y0) / (x1 - x0)
            worst = 0.0
            worst_at = x0
            sq_sum = 0.0
            m = 0
            for i in range(onset_idx, ceiling_idx + 1):
                d = settled[i] - (y0 + slope * (pcts[i] - x0))
                sq_sum += d * d
                m += 1
                if abs(d) > abs(worst):
                    worst = d
                    worst_at = pcts[i]
            linearity = {
                "max_dev_rpm": worst,
                "max_dev_pct_of_span": abs(worst) / span * 100.0,
                "at_pct": worst_at,
                "rms_rpm": math.sqrt(sq_sum / m),
            }

    # ---- 0 % anomaly flag ---------------------------------------------
    zero_flag = None
    if s0 > 0.0 and abs(s0 - baseline) > max(onset_tol_rpm,
                                             onset_frac * peak):
        zero_flag = ("0%% reading (%.0f rpm) disagrees with the low-duty "
                     "plateau (~%.0f rpm): possible stale-latch artifact "
                     "or tach gating at zero duty" % (s0, baseline))

    return {
        "turns_off": turns_off,
        "floor_rpm": floor_rpm,
        "onset_pct": None if onset_idx is None else pcts[onset_idx],
        "onset_rpm": None if onset_idx is None else settled[onset_idx],
        "linearity": linearity,
        "ceiling_pct": ceiling_pct,
        "zero_flag": zero_flag,
        "peak_rpm": peak,
    }


def format_summary(res, fan_name=""):
    """Render the four answers as human-readable lines (shared by the
    collector's stderr summary and any other consumer). ``res`` is the
    dict returned by :func:`analyze`."""
    lines = []
    title = "Fan curve summary" + ((" - " + fan_name) if fan_name else "")
    lines.append(title)
    lines.append("-" * len(title))

    # Q1
    if res["turns_off"]:
        if res["onset_pct"] is None:
            lines.append("1) Fan never turned during the sweep.")
        else:
            lines.append("1) Fan stops: speed reaches 0 below "
                         "%.1f %% drive." % res["onset_pct"])
    else:
        lines.append("1) Fan NEVER STOPS: holds a ~%.0f rpm floor at "
                     "0 %% drive." % res["floor_rpm"])

    # Q2
    if res["onset_pct"] is None:
        if res["turns_off"]:
            lines.append("2) Onset: unmeasurable (fan never started).")
        else:
            lines.append("2) Onset: no measurable rise above the floor "
                         "within the sweep.")
    elif res["turns_off"]:
        lines.append("2) Fan starts turning at ~%.1f %% PWM."
                     % res["onset_pct"])
    else:
        lines.append("2) Speed begins rising above its ~%.0f rpm floor at "
                     "~%.1f %% PWM." % (res["floor_rpm"], res["onset_pct"]))

    # Q3
    lin = res["linearity"]
    if lin is None:
        lines.append("3) Linearity: unmeasurable (insufficient data).")
    else:
        lines.append("3) Linearity: max deviation %+.0f rpm (%.1f %% of "
                     "span) at %.1f %% duty; RMS %.0f rpm vs the ideal "
                     "linear curve." % (lin["max_dev_rpm"],
                                        lin["max_dev_pct_of_span"],
                                        lin["at_pct"], lin["rms_rpm"]))

    # Q4
    if res["ceiling_pct"] is None:
        lines.append("4) Speed still increasing at 100 %% PWM (no "
                     "saturation observed).")
    else:
        lines.append("4) Speed plateaus above ~%.1f %% PWM (no further "
                     "increase to 100 %%)." % res["ceiling_pct"])

    if res.get("zero_flag"):
        lines.append("!  " + res["zero_flag"])
    return "\n".join(lines)
