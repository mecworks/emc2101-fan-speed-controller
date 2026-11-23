"""TACH net signal probe (read-only; no chip access).

M1 follow-up (2026-11-22): the chip reads TACH 0xFFFF at every duty even
although the fan is verified powered and spinning (~660 RPM at the floor
setting, far above the ~82 RPM detection floor). This probe decides WHERE
the signal dies by observing the TACH net directly:

  - no periodic edges  -> signal ABSENT at the pin: stuck level, dead fan
                          tach stage, or missing pull-up on the net
  - steady pulse train -> signal ALIVE at the pin: fault lies in the
                          chip's TACH input stage or its configuration

Setup: jumper the TACH net (fan connector TACH pin, board TACH test point,
or the chip's ALERT pin -- any point on the net) to the Pico GPIO named
below. Common GND is already shared. Disconnect nothing from the chip.
If the net is pulled up to 5 V, the Pico GPIO tolerates it; if in doubt,
put a 1 kohm series resistor between the net and the probe pin.

Read-only: touches no EMC2101 registers. Self-restoring: releases the
probe pin on exit.

Run: python -m mpremote connect port:COM16 run probe_tach_signal.py
"""

import time
from machine import Pin

PROBE_PIN = 2         # free Pico GPIO to tap the TACH net onto
SAMPLE_SECONDS = 3    # observation window
MAX_PERIODS = 1000    # stored-interval cap (fast-noise guard)


def main():
    # Plain input, NO pull resistors: observe the net exactly as it is.
    # An internal pull-up here would mask a missing external one.
    p = Pin(PROBE_PIN, Pin.IN)

    deadline = time.ticks_add(time.ticks_ms(), SAMPLE_SECONDS * 1000)
    prev = p.value()
    rises = 0
    falls = 0
    periods = []       # us between successive RISING edges
    last_rise_us = None
    highs = 0
    lows = 0

    while time.ticks_diff(deadline, time.ticks_ms()) > 0:
        v = p.value()
        if v:
            highs += 1
        else:
            lows += 1
        if v != prev:
            if v:
                rises += 1
                now = time.ticks_us()
                if last_rise_us is not None:
                    dt = time.ticks_diff(now, last_rise_us)
                    if 0 < dt < 1000000 and len(periods) < MAX_PERIODS:
                        periods.append(dt)
                last_rise_us = now
            else:
                falls += 1
            prev = v

    total = highs + lows
    print("probe pin: GP%d   window: %ds   samples: %d"
          % (PROBE_PIN, SAMPLE_SECONDS, total))
    if total:
        print("level: %.1f%% high / %.1f%% low"
              % (100.0 * highs / total, 100.0 * lows / total))
    print("edges: %d rising / %d falling" % (rises, falls))

    if rises < 2:
        print("VERDICT: no periodic signal at the pin.")
        print("  -> stuck level, dead fan tach stage, or missing pull-up")
        print("     on the TACH net (try a temporary 10 kohm pull-up to 3.3 V)")
        return

    ps = sorted(periods)
    med = ps[len(ps) // 2]
    hz = 1e6 / med
    print("rise period: min %d us  median %d us  max %d us"
          % (ps[0], med, ps[-1]))
    print("pulse rate ~= %.1f Hz" % hz)
    for ppr in (1, 2):
        print("implied RPM (%d pulse/rev): %.0f" % (ppr, hz * 60.0 / ppr))
    print("VERDICT: signal ALIVE at the pin.")
    print("  -> fault is in the chip's TACH input stage or configuration")
    print("     (verify ALT_TCH read-back; compare against char_tach.py)")


main()
