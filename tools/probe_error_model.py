"""Host-side dev utility: exercise the documented ValueError paths.

Runs on CPython only (no hardware needed; uses a fake transport). Prints
one line per case with the observed exception type/message. Used during
M6 to pin down the E2E error-model section's expectations; re-run after
any change to argument validation in emc2101/_core.py.

Usage: python tools/probe_error_model.py   (from the repository root)
"""
import sys
sys.path.insert(0, '.')
from emc2101._core import EMC2101


class FakeT:
    def __init__(self):
        self.mem = {0x00: 0x80, 0xFD: 0x16, 0xFE: 0x5D, 0xFF: 0x01}

    def read_byte(self, a):
        return self.mem.get(a, 0)

    def write_byte(self, a, v):
        self.mem[a] = v & 0xFF


dev = EMC2101.__new__(EMC2101)
dev._t = FakeT()
dev.config_path = None
cases = [
    ('set_duty_pct(101)', lambda: dev.set_duty_pct(101)),
    ('set_duty_pct(-1)', lambda: dev.set_duty_pct(-1)),
    ('local_high_c=128', lambda: setattr(dev, 'local_high_c', 128)),
    ('hysteresis_c=128', lambda: setattr(dev, 'hysteresis_c', 128)),
    ('pwm_freq_hz=0', lambda: setattr(dev, 'pwm_freq_hz', 0.0)),
    ('pwm_freq_hz=1e6 (clamp)', lambda: setattr(dev, 'pwm_freq_hz', 1e6)),
    ('scratchpad_set(3,1)', lambda: dev.scratchpad_set(3, 1)),
    ('conversion_rate=0', lambda: setattr(dev, 'conversion_rate', 0.0)),
    ('conversion_rate=99 (clamp)', lambda: setattr(dev, 'conversion_rate', 99.0)),
    ('one_shot normal mode', lambda: dev.one_shot()),
    ('lut non-ascending', lambda: setattr(dev, 'lut', [(20, 10), (10, 20)] + [(127, 100)] * 6)),
    ('lut wrong len', lambda: setattr(dev, 'lut', [(10, 10)])),
    ('lut_set_index(8,1,1)', lambda: dev.lut_set_index(8, 1, 1)),
    ('read_reg(0x100)', lambda: dev.read_reg(0x100, b'x')),
    ('write_reg empty buf', lambda: dev.write_reg(0x4A, b'')),
    ('min_rpm=-5', lambda: dev.min_rpm),
    ('tcrit_hysteresis_c=128', lambda: setattr(dev, 'tcrit_hysteresis_c', 128)),
    ('remote_low_c=-100', lambda: setattr(dev, 'remote_low_c', -100.0)),
    ('spin_up_time_s=99', lambda: setattr(dev, 'spin_up_time_s', 99.0)),
    ('ideality nearest 1.0', lambda: dev.set_ideality_factor(1.0)),
]
for name, f in cases:
    try:
        r = f()
        print('%-26s -> NO ERROR (%r)' % (name, r))
    except Exception as e:
        print('%-26s -> %s: %s' % (name, type(e).__name__, str(e)[:70]))
