"""M4 unit tests: JSON persistence layer ("virtual EEPROM").

Covers encode/decode round-trip stability and validation, collect_state
against populated fake register files, apply_state ordering rules
(PROG dance, TCRIT special cases, ascending re-check, strict read-back
diffs), and the core save_config/load_config glue using real temp files
on the host (first-boot semantics, product-ID refusal, revision
warnings, zero-register-touch on corrupt input, atomic-write hygiene).
"""
import json
import os
import shutil
import tempfile
import unittest

from fakes import FakeTransport, write_entries
from emc2101._core import EMC2101 as Core
from emc2101 import _persist
from emc2101._regs import (AMSK_INT, AMSK_TACH, BETA_ENABLE, CFG_ALT_TCH,
                           CFG_DIS_TO, CFG_QUEUE, CFG_TCRITOVRD,
                           FCFG_CLK_OVR, FCFG_POLARITY, FCFG_PROG,
                           FLT_COMP, FLT_LEVEL_2, REG_ALERT_MASK, REG_BETA,
                           REG_CONFIG, REG_CONV_RATE, REG_EXT_FORCE,
                           REG_EXT_HIGH_LSB, REG_EXT_HIGH_MSB,
                           REG_EXT_LOW_LSB, REG_EXT_LOW_MSB, REG_FAN_CFG,
                           REG_FAN_SETTING, REG_FILTER, REG_IDEALITY,
                           REG_INT_LIMIT, REG_LUT_BASE, REG_LUT_HYST,
                           REG_PWM_D, REG_PWM_F, REG_SCRATCHPAD_1,
                           REG_SCRATCHPAD_2, REG_SPINUP, REG_TACH_LIMIT_HI,
                           REG_TACH_LIMIT_LO, REG_TCRIT, REG_TCRIT_HYST,
                           SU_DRIVE_100, SU_DRIVE_75, SU_FAST_TACH,
                           duty_pct_to_setting, ext_temp_to_raw,
                           int_temp_to_raw, setting_to_duty_pct)
from emc2101._tables import SPINUP_TIMES_S, conv_rate_encode


def _time_enc(seconds):
    return next(i for i, t in enumerate(SPINUP_TIMES_S) if t == seconds)


def base_image():
    """A POR-like register file covering every persisted register."""
    r = {}
    r[REG_CONFIG] = 0x00
    r[REG_CONV_RATE] = 8                      # 16/s per Table 6.6
    r[REG_INT_LIMIT] = int_temp_to_raw(70)
    rh = ext_temp_to_raw(70.0)
    r[REG_EXT_HIGH_MSB] = rh >> 3
    r[REG_EXT_HIGH_LSB] = rh & 0x07
    rl = ext_temp_to_raw(0.0)
    r[REG_EXT_LOW_MSB] = rl >> 3
    r[REG_EXT_LOW_LSB] = rl & 0x07
    r[REG_EXT_FORCE] = int_temp_to_raw(25)
    r[REG_SCRATCHPAD_1] = 0xA5
    r[REG_SCRATCHPAD_2] = 0x5A
    r[REG_ALERT_MASK] = 0x00
    r[REG_IDEALITY] = 0x12
    r[REG_BETA] = BETA_ENABLE
    r[REG_TCRIT] = int_temp_to_raw(85)
    r[REG_TCRIT_HYST] = 10
    r[REG_TACH_LIMIT_LO] = 0xFF
    r[REG_TACH_LIMIT_HI] = 0xFF
    r[REG_FAN_CFG] = FCFG_PROG                # manual mode (PROG=1, POR default)
    r[REG_SPINUP] = SU_FAST_TACH | SU_DRIVE_100 | 0x07
    r[REG_FAN_SETTING] = 0x00
    r[REG_PWM_F] = 0x17                       # 23
    r[REG_PWM_D] = 0x01
    r[REG_LUT_HYST] = 4
    for i in range(8):
        r[REG_LUT_BASE + 2 * i] = int_temp_to_raw(127)
        r[REG_LUT_BASE + 2 * i + 1] = 0x3F
    r[REG_FILTER] = 0x00
    return r


def modified_image():
    """The base image with every domain changed at once."""
    r = base_image()
    r[REG_CONFIG] = CFG_ALT_TCH | CFG_QUEUE | CFG_DIS_TO
    r[REG_CONV_RATE] = conv_rate_encode(2.0)
    r[REG_INT_LIMIT] = int_temp_to_raw(60)
    rh = ext_temp_to_raw(65.5)
    r[REG_EXT_HIGH_MSB] = rh >> 3
    r[REG_EXT_HIGH_LSB] = rh & 0x07
    rl = ext_temp_to_raw(-10.25)
    r[REG_EXT_LOW_MSB] = rl >> 3
    r[REG_EXT_LOW_LSB] = rl & 0x07
    r[REG_EXT_FORCE] = int_temp_to_raw(30)
    r[REG_SCRATCHPAD_1] = 0x11
    r[REG_SCRATCHPAD_2] = 0x22
    r[REG_ALERT_MASK] = AMSK_INT | AMSK_TACH
    r[REG_IDEALITY] = 0x10
    r[REG_BETA] = 0x03                        # autodetect off, index 3
    r[REG_TCRIT] = int_temp_to_raw(90)
    r[REG_TCRIT_HYST] = 12
    tl = 30000
    r[REG_TACH_LIMIT_LO] = tl & 0xFF
    r[REG_TACH_LIMIT_HI] = tl >> 8
    r[REG_FAN_CFG] = FCFG_PROG | FCFG_POLARITY | FCFG_CLK_OVR
    r[REG_SPINUP] = SU_DRIVE_75 | _time_enc(1.6)
    r[REG_FAN_SETTING] = duty_pct_to_setting(50.0, 7)
    r[REG_PWM_F] = 7
    r[REG_PWM_D] = 4
    temps = (20, 30, 40, 50, 60, 70, 80, 90)
    duties = (10, 20, 30, 40, 50, 60, 70, 80)
    for i in range(8):
        r[REG_LUT_BASE + 2 * i] = int_temp_to_raw(temps[i])
        r[REG_LUT_BASE + 2 * i + 1] = duty_pct_to_setting(duties[i], 7)
    r[REG_LUT_HYST] = 6
    r[REG_FILTER] = FLT_COMP | FLT_LEVEL_2
    return r


class SabotagingTransport(object):
    """Wraps a stateful FakeTransport and flips one register after its
    write so strict read-back sees a mismatch."""

    def __init__(self, inner, victim):
        self._inner = inner
        self._victim = victim

    def read_byte(self, reg):
        return self._inner.read_byte(reg)

    def write_byte(self, reg, value):
        self._inner.write_byte(reg, value)
        if reg == self._victim:
            self._inner.registers[self._victim] ^= 0xFF

    def probe(self):
        return True

    def scan(self):
        return [0x4C]

    def delay_ms(self, ms):
        pass

    def close(self):
        pass


class MirrorTransport(object):
    """Wraps a stateful FakeTransport and models the live-observed
    PROG quirk (D35, research note): while PROG=0 (LUT mode) the Fan
    Setting register reads back the EFFECTIVE LUT-DRIVEN duty (the
    active entry's setting, quantized onto the current PWM_F grid, at a
    fixed simulated temperature) instead of its stored content, and
    writes to the Fan Setting and LUT registers are silently dropped.
    Everything else passes through untouched.

    Also models the read-out lag (D36): right after a LUT->manual
    PROG-bit transition the Fan Setting read-out keeps reporting the
    LUT-driven duty until one conversion window elapses; call
    ``settled()`` (or let the patched _persist._settle_ms do it) to
    advance past that window.
    """

    _instances = []

    def __init__(self, inner, sim_temp_c=27.0):
        self._inner = inner
        self._sim_temp = sim_temp_c
        self._stale_value = None
        MirrorTransport._instances.append(self)

    def settled(self):
        """Advance simulated time past one conversion window."""
        self._stale_value = None

    def _drive(self):
        regs = self._inner.registers
        if regs.get(REG_FAN_CFG, 0) & FCFG_PROG:
            return None
        pwm_f = regs.get(REG_PWM_F, 1) or 1
        idx = 0
        for i in range(8):
            t_raw = regs.get(REG_LUT_BASE + 2 * i, 0x7F)
            t = t_raw if t_raw < 0x80 else t_raw - 0x100
            if self._sim_temp >= t:
                idx = i
        s = regs.get(REG_LUT_BASE + 2 * idx + 1, 0) & 0x3F
        return duty_pct_to_setting(setting_to_duty_pct(s, pwm_f), pwm_f)

    @staticmethod
    def _gated(reg):
        return (reg == REG_FAN_SETTING
                or REG_LUT_BASE <= reg <= REG_LUT_BASE + 15)

    def read_byte(self, reg):
        if reg == REG_FAN_SETTING:
            if self._inner.registers.get(REG_FAN_CFG, 0) & FCFG_PROG:
                if self._stale_value is not None:
                    self._inner.log.append(("read", reg))
                    return self._stale_value
                return self._inner.read_byte(reg)
            drive = self._drive()
            if drive is not None:
                self._inner.log.append(("read", reg))
                return drive
        return self._inner.read_byte(reg)

    def write_byte(self, reg, value):
        if reg == REG_FAN_CFG:
            old_prog = bool(
                self._inner.registers.get(REG_FAN_CFG, 0) & FCFG_PROG)
            if not old_prog and bool(value & FCFG_PROG):
                # LUT -> manual: arm the stale read-out window (D36);
                # the value latched is the drive still in effect NOW,
                # i.e. before this write lands.
                self._stale_value = self._drive()
        if (not (self._inner.registers.get(REG_FAN_CFG, 0) & FCFG_PROG)
                and self._gated(reg)):
            self._inner.log.append(("write", reg, value))  # dropped
            return
        self._inner.write_byte(reg, value)

    def probe(self):
        return self._inner.probe_result

    def scan(self):
        return self._inner.scan()

    def delay_ms(self, ms):
        pass

    def close(self):
        self._inner.close()


# D36: substitute the real settling pause with instant simulated-time
# advance so the suite never sleeps; every live MirrorTransport moves
# past its stale read-out window when _persist settles.
def _fake_settle(ms):
    for m in MirrorTransport._instances:
        m.settled()


_persist._settle_ms = _fake_settle


class TestEncodeDecode(unittest.TestCase):
    def setUp(self):
        img_t = FakeTransport(registers=base_image())
        self.state = _persist.collect_state(img_t.read_byte,
                                            img_t.write_byte)

    def _mutate(self, fn):
        data = json.loads(_persist.encode(self.state))
        fn(data)
        return _persist.encode(data)

    def test_round_trip_stability(self):
        text1 = _persist.encode(self.state)
        state2 = _persist.decode(text1)
        text2 = _persist.encode(state2)
        self.assertEqual(text1, text2)
        self.assertEqual(self.state, state2)

    def test_encode_is_readable_json(self):
        text = _persist.encode(self.state)
        self.assertIn('"schema_version"', text)
        self.assertEqual(json.loads(text)["schema_version"], 1)

    def test_decode_rejects_malformed_json(self):
        with self.assertRaises(ValueError):
            _persist.decode("{not json")

    def test_decode_rejects_non_object_root(self):
        with self.assertRaises(ValueError):
            _persist.decode("[1, 2]")

    def test_decode_rejects_unknown_version(self):
        with self.assertRaisesRegex(ValueError, "version"):
            _persist.decode(self._mutate(
                lambda d: d.update(schema_version=2)))

    def test_decode_rejects_missing_section(self):
        with self.assertRaisesRegex(ValueError, "fan"):
            _persist.decode(self._mutate(lambda d: d.pop("fan")))

    def test_decode_rejects_unknown_top_key(self):
        with self.assertRaisesRegex(ValueError, "extra"):
            _persist.decode(self._mutate(lambda d: d.update(extra=1)))

    def test_decode_rejects_unknown_section_key(self):
        with self.assertRaisesRegex(ValueError, "bogus"):
            _persist.decode(self._mutate(
                lambda d: d["limits"].update(bogus=1)))

    def test_decode_rejects_bool_where_int_expected(self):
        with self.assertRaises(ValueError):
            _persist.decode(self._mutate(
                lambda d: d["limits"].update(local_high_c=True)))

    def test_decode_rejects_out_of_range_tcrit(self):
        with self.assertRaises(ValueError):
            _persist.decode(self._mutate(
                lambda d: d["limits"].update(tcrit_c=200)))

    def test_decode_rejects_bad_external_step(self):
        with self.assertRaisesRegex(ValueError, "step"):
            _persist.decode(self._mutate(
                lambda d: d["limits"].update(remote_high_c=70.03)))

    def test_decode_rejects_lut_wrong_count(self):
        with self.assertRaises(ValueError):
            _persist.decode(self._mutate(
                lambda d: d["lut"]["entries"].pop()))

    def test_decode_rejects_descending_lut(self):
        with self.assertRaisesRegex(ValueError, "descend"):
            _persist.decode(self._mutate(
                lambda d: d["lut"]["entries"][3].update(temp_c=10)))

    def test_decode_rejects_bad_conversion_rate(self):
        with self.assertRaises(ValueError):
            _persist.decode(self._mutate(
                lambda d: d["misc"].update(conversion_rate_per_s=3.0)))

    def test_decode_rejects_bad_spin_time(self):
        with self.assertRaises(ValueError):
            _persist.decode(self._mutate(
                lambda d: d["fan"]["spin_up"].update(time_s=1.0)))

    def test_decode_rejects_inconsistent_frequency(self):
        with self.assertRaisesRegex(ValueError, "pwm_freq_hz"):
            _persist.decode(self._mutate(
                lambda d: d["fan"].update(pwm_freq_hz=12345.0)))

    def test_decode_rejects_bad_device_stamp(self):
        with self.assertRaises(ValueError):
            _persist.decode(self._mutate(
                lambda d: d["device"].update(product_id="16")))

    def test_decode_rejects_spinup_enabled_time_disagreement(self):
        with self.assertRaisesRegex(ValueError, "disagree"):
            _persist.decode(self._mutate(
                lambda d: d["fan"]["spin_up"].update(enabled=False)))

    def test_decoded_values_match_source(self):
        s = _persist.decode(_persist.encode(self.state))
        self.assertEqual(s["device"]["product_id"], "0x16")
        self.assertEqual(s["device"]["mfg_id"], "0x5d")
        self.assertEqual(s["device"]["revision"], "0x01")
        self.assertEqual(s["limits"]["local_high_c"], 70)
        self.assertEqual(s["limits"]["tcrit_c"], 85)
        self.assertEqual(s["fan"]["pwm_f"], 23)
        self.assertAlmostEqual(s["fan"]["pwm_freq_hz"],
                               360000.0 / (2 * 23), delta=1e-6)
        self.assertEqual(s["fan"]["spin_up"],
                         {"enabled": True, "drive_pct": 100,
                          "time_s": 3.2, "fast_tach": True})
        self.assertEqual(s["misc"]["scratchpad"], [0xA5, 0x5A])
        self.assertEqual(s["calibration"]["ideality_index"], 0x12)
        self.assertTrue(s["calibration"]["beta_auto_detect"])
        self.assertEqual(s["config"]["alert_mode"], "interrupt")
        self.assertEqual(s["lut"]["entries"][0]["temp_c"], 127)
        self.assertAlmostEqual(s["lut"]["entries"][0]["duty_pct"], 100.0)


class TestCollectState(unittest.TestCase):
    def test_collect_base_image(self):
        t = FakeTransport(registers=base_image())
        s = _persist.collect_state(t.read_byte, t.write_byte)
        self.assertRegex(s["saved_at_utc"],
                         r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        self.assertEqual(s["device"]["mfg_id"], "0x5d")
        self.assertEqual(s["device"]["revision"], "0x01")
        self.assertTrue(s["fan"]["manual"])
        self.assertAlmostEqual(s["fan"]["duty_pct"], 0.0)
        self.assertEqual(s["misc"]["tach_limit_count"], 0xFFFF)
        self.assertEqual(s["misc"]["averaging_filter"], "off")
        self.assertEqual(s["misc"]["conversion_rate_per_s"], 16.0)

    def test_collect_modified_image(self):
        t = FakeTransport(registers=modified_image())
        s = _persist.collect_state(t.read_byte, t.write_byte)
        self.assertEqual(s["limits"]["local_high_c"], 60)
        self.assertEqual(s["limits"]["remote_high_c"], 65.5)
        self.assertEqual(s["limits"]["remote_low_c"], -10.25)
        self.assertEqual(s["limits"]["tcrit_c"], 90)
        self.assertTrue(s["config"]["tach_input"])
        self.assertTrue(s["config"]["queue_3sample"])
        self.assertTrue(s["config"]["dis_to"])
        self.assertEqual(s["config"]["alert_mode"], "comparator")
        self.assertTrue(s["config"]["alert_mask"]["int"])
        self.assertTrue(s["config"]["alert_mask"]["tach"])
        self.assertFalse(s["config"]["alert_mask"]["high"])
        self.assertTrue(s["fan"]["output_inverted"])
        self.assertTrue(s["fan"]["clk_ovr"])
        self.assertEqual(s["fan"]["pwm_div"], 4)
        self.assertAlmostEqual(s["fan"]["pwm_freq_hz"],
                               360000.0 / (2 * 7 * 4), delta=1e-6)
        self.assertEqual(s["fan"]["spin_up"],
                         {"enabled": True, "drive_pct": 75,
                          "time_s": 1.6, "fast_tach": False})
        self.assertEqual(s["fan"]["force"],
                         {"enabled": False, "temp_c": 30})
        self.assertEqual(s["calibration"]["ideality_index"], 0x10)
        self.assertFalse(s["calibration"]["beta_auto_detect"])
        self.assertEqual(s["calibration"]["beta_index"], 3)
        self.assertEqual(s["misc"]["conversion_rate_per_s"], 2.0)
        self.assertEqual(s["misc"]["averaging_filter"], "level2")
        self.assertEqual(s["misc"]["tach_limit_count"], 30000)
        self.assertEqual(s["misc"]["scratchpad"], [0x11, 0x22])
        self.assertEqual(s["lut"]["hysteresis_c"], 6)
        self.assertEqual(s["lut"]["entries"][0]["temp_c"], 20)
        self.assertAlmostEqual(s["lut"]["entries"][0]["duty_pct"],
                               setting_to_duty_pct(
                                   duty_pct_to_setting(10.0, 7), 7),
                               delta=1e-9)


class TestApplyState(unittest.TestCase):
    def test_apply_restores_modified_image(self):
        target = FakeTransport(registers=base_image())
        src = FakeTransport(registers=modified_image())
        state = _persist.collect_state(src.read_byte, src.write_byte)
        report = _persist.apply_state(target.write_byte,
                                      target.read_byte, state)
        self.assertTrue(report["applied"])
        self.assertEqual(report["warnings"], [])
        self.assertEqual(report["diff"], {})
        # The TCRIT unlock dance legitimately leaves TCRITOVRD set in
        # Config (it clears only on power cycle).
        expected = modified_image()
        expected[REG_CONFIG] |= CFG_TCRITOVRD
        self.assertEqual(target.registers, expected)

    def test_tcrit_skip_when_unlock_consumed(self):
        img = base_image()
        img[REG_TCRIT] = int_temp_to_raw(90)      # unlock already used
        target = FakeTransport(registers=img)
        src = FakeTransport(registers=base_image())
        state = _persist.collect_state(src.read_byte, src.write_byte)
        # tcrit 85
        report = _persist.apply_state(target.write_byte,
                                      target.read_byte, state)
        self.assertEqual(len(report["warnings"]), 1)
        self.assertIn("power cycle", report["warnings"][0])
        self.assertEqual(target.registers[REG_TCRIT], int_temp_to_raw(90))
        self.assertFalse(target.registers[REG_CONFIG] & CFG_TCRITOVRD)

    def test_tcrit_unlock_attempted_from_locked(self):
        target = FakeTransport(registers=base_image())
        src = FakeTransport(registers=modified_image())
        state = _persist.collect_state(src.read_byte, src.write_byte)
        # 90
        _persist.apply_state(target.write_byte, target.read_byte, state)
        self.assertEqual(target.registers[REG_TCRIT], int_temp_to_raw(90))
        self.assertTrue(target.registers[REG_CONFIG] & CFG_TCRITOVRD)

    def test_tcrit_noop_when_equal(self):
        target = FakeTransport(registers=base_image())
        state = _persist.collect_state(target.read_byte,
                                       target.write_byte)
        _persist.apply_state(target.write_byte, target.read_byte, state)
        self.assertFalse(any(e[0] == "write" and e[1] == REG_TCRIT
                             for e in target.log))

    def test_prog_dance_ends_with_stored_prog_value(self):
        img = modified_image()
        img[REG_FAN_CFG] = FCFG_POLARITY | FCFG_CLK_OVR  # LUT mode start
        source = FakeTransport(registers=img)
        state = _persist.collect_state(source.read_byte,
                                       source.write_byte)
        state["fan"]["manual"] = False            # stored PROG = 0
        target = FakeTransport(registers=dict(img))
        _persist.apply_state(target.write_byte, target.read_byte, state)
        seq = [v for _, v in write_entries(target.log, REG_FAN_CFG)]
        self.assertEqual(seq[0] & 0xF0, 0x30)     # temp PROG=1 + polarity
        self.assertEqual(seq[-1] & 0xF0, 0x10)    # final: polarity only
        self.assertEqual(seq[-1] & FCFG_PROG, 0)

    def test_lut_ascending_rechecked_before_any_write(self):
        target = FakeTransport(registers=base_image())
        src = FakeTransport(registers=modified_image())
        state = _persist.collect_state(src.read_byte, src.write_byte)
        state["lut"]["entries"][3]["temp_c"] = 10
        with self.assertRaisesRegex(ValueError, "descend"):
            _persist.apply_state(target.write_byte, target.read_byte,
                                 state)
        self.assertFalse(any(e[0] == "write" for e in target.log))

    def test_strict_diff_reported_and_raised_by_glue(self):
        inner = FakeTransport(registers=base_image())
        sabo = SabotagingTransport(inner, REG_IDEALITY)
        src = FakeTransport(registers=modified_image())
        state = _persist.collect_state(src.read_byte, src.write_byte)
        # apply_state itself never raises on a diff - it reports.
        report = _persist.apply_state(sabo.write_byte, sabo.read_byte,
                                      state, strict=True)
        self.assertEqual(sorted(report["diff"]), ["0x17"])
        exp, act = report["diff"]["0x17"]
        self.assertNotEqual(exp, act)
        # strict=False skips the read-back entirely: empty diff, no raise.
        inner2 = FakeTransport(registers=base_image())
        sabo2 = SabotagingTransport(inner2, REG_IDEALITY)
        report2 = _persist.apply_state(sabo2.write_byte, sabo2.read_byte,
                                       state, strict=False)
        self.assertEqual(report2["diff"], {})


class TestCorePersistenceGlue(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="emc2101-persist-")
        self.path = os.path.join(self.tmp, "cfg.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _dev(self, image=None, **kw):
        t = FakeTransport(registers=image or base_image())
        return Core(t, config_file=self.path, **kw), t

    def test_save_then_load_roundtrip_via_disk(self):
        dev, t = self._dev(modified_image())
        returned = dev.save_config()
        self.assertEqual(returned, self.path)
        self.assertTrue(os.path.exists(self.path))
        self.assertFalse([f for f in os.listdir(self.tmp)
                          if f.endswith(".tmp")])
        dev.local_high_c = 65                     # mutate one register
        self.assertEqual(dev.local_high_c, 65)
        report = dev.load_config()
        self.assertTrue(report["applied"])
        self.assertEqual(report["diff"], {})
        self.assertEqual(dev.local_high_c, 60)    # restored

    def test_save_positional_override(self):
        dev, _ = self._dev()
        alt = os.path.join(self.tmp, "alt.json")
        self.assertEqual(dev.save_config(alt), alt)
        self.assertTrue(os.path.exists(alt))

    def test_explicit_load_of_missing_file_raises(self):
        dev, _ = self._dev()
        missing = os.path.join(self.tmp, "nope.json")
        with self.assertRaises(OSError):
            dev.load_config(missing)

    def test_corrupt_file_touches_no_registers(self):
        with open(self.path, "w") as f:
            f.write("garbage {{{")
        dev, t = self._dev()
        with self.assertRaises(ValueError):
            dev.load_config()
        self.assertFalse(any(e[0] == "write" for e in t.log))

    def test_product_id_mismatch_refused_before_writes(self):
        src = FakeTransport(registers=modified_image())
        state = _persist.collect_state(src.read_byte, src.write_byte)
        state["device"]["product_id"] = "0x28"
        with open(self.path, "w") as f:
            f.write(_persist.encode(state))
        dev, t = self._dev()
        with self.assertRaisesRegex(ValueError, "product ID mismatch"):
            dev.load_config()
        self.assertFalse(any(e[0] == "write" for e in t.log))

    def test_revision_mismatch_warns_but_applies(self):
        src = FakeTransport(registers=modified_image())
        state = _persist.collect_state(src.read_byte, src.write_byte)
        state["device"]["revision"] = "0x02"
        with open(self.path, "w") as f:
            f.write(_persist.encode(state))
        dev, _ = self._dev()
        report = dev.load_config()
        self.assertTrue(report["applied"])
        self.assertTrue(any("revision mismatch" in w
                            for w in report["warnings"]))

    def test_constructor_autoload_missing_file_is_noop(self):
        t = FakeTransport(registers=base_image())
        missing = os.path.join(self.tmp, "absent.json")
        dev = Core(t, config_file=missing, auto_load=True)
        self.assertEqual(dev.config_path, missing)
        self.assertFalse(any(e[0] == "write" for e in t.log))

    def test_constructor_autoload_applies_existing_file(self):
        src_dev, _ = self._dev(modified_image())
        src_dev.save_config()
        dst_t = FakeTransport(registers=base_image())
        Core(dst_t, config_file=self.path, auto_load=True)
        expected = modified_image()
        expected[REG_CONFIG] |= CFG_TCRITOVRD
        self.assertEqual(dst_t.registers, expected)

    def test_constructor_autoload_corrupt_file_raises(self):
        with open(self.path, "w") as f:
            f.write("{{{")
        t = FakeTransport(registers=base_image())
        with self.assertRaises(ValueError):
            Core(t, config_file=self.path, auto_load=True)
        self.assertFalse(any(e[0] == "write" for e in t.log))

    def test_strict_readback_failure_raises_value_error(self):
        dev, _ = self._dev(modified_image())
        dev.save_config()
        inner = FakeTransport(registers=base_image())
        dev._t = SabotagingTransport(inner, REG_IDEALITY)
        with self.assertRaisesRegex(ValueError, "verification failed"):
            dev.load_config(strict=True)
        report = dev.load_config(strict=False)
        self.assertEqual(report["diff"], {})      # read-back skipped


class TestProgQuirkModel(unittest.TestCase):
    """Regression tests for the live-observed PROG quirk (D35): while
    PROG=0 the Fan Setting register mirrors the LUT-driven duty and
    fan-domain writes are dropped. Collection and strict verification
    must both capture/compare TRUE stored contents."""

    def _lut_mode_image(self):
        img = base_image()
        img[REG_FAN_CFG] = 0x00                  # LUT mode, no other bits
        img[REG_FAN_SETTING] = 0x2E              # stored 100 % (raw 46)
        img[REG_LUT_BASE + 1] = 0x0C             # entry 0 drive: raw 12
        return img

    def test_collect_in_lut_mode_captures_stored_contents(self):
        t = FakeTransport(registers=self._lut_mode_image())
        mt = MirrorTransport(t, sim_temp_c=27.0)
        state = _persist.collect_state(mt.read_byte, mt.write_byte)
        # Stored FS is 46 (100 %) even though the mirror would report
        # the active entry's drive (raw 12 ~= 26 %).
        self.assertEqual(state["fan"]["duty_pct"], 100.0)
        self.assertFalse(state["fan"]["manual"])
        seq = write_entries(t.log, REG_FAN_CFG)
        self.assertEqual(len(seq), 2)
        self.assertEqual(seq[0][1] & FCFG_PROG, FCFG_PROG)  # dance opens
        self.assertEqual(seq[1][1], 0x00)                   # mode restored

    def test_collect_skips_dance_when_manual(self):
        t = FakeTransport(registers=base_image())   # PROG=1 at POR
        _persist.collect_state(t.read_byte, t.write_byte)
        self.assertEqual(write_entries(t.log, REG_FAN_CFG), [])

    def test_apply_strict_clean_ending_in_lut_mode(self):
        src_img = self._lut_mode_image()
        src = FakeTransport(registers=dict(src_img))
        state = _persist.collect_state(src.read_byte, src.write_byte)
        target = FakeTransport(registers=dict(base_image()))
        mt = MirrorTransport(target, sim_temp_c=27.0)
        report = _persist.apply_state(mt.write_byte, mt.read_byte,
                                      state, strict=True)
        # Without the read-back dance this diff would show 0x4c:
        # expected 0x2e got 0x0c (the mirror value).
        self.assertEqual(report["diff"], {})
        self.assertEqual(target.registers[REG_FAN_CFG], 0x00)
        self.assertEqual(target.registers[REG_FAN_SETTING], 0x2E)

    # -- D36: read-out lag after a PROG transition -----------------------

    def test_collect_settles_stale_readout(self):
        # Chip sits in LUT mode; the stored FS (raw 46) differs from the
        # LUT drive (raw 12). The dance's PROG-on transition arms the
        # stale window; only a settling pause before the fan-domain reads
        # yields the true stored content.
        t = FakeTransport(registers=self._lut_mode_image())
        mt = MirrorTransport(t, sim_temp_c=27.0)
        settles = []
        real = _persist._settle_ms

        def fake_settle(ms):
            settles.append(ms)
            mt.settled()

        _persist._settle_ms = fake_settle
        try:
            state = _persist.collect_state(mt.read_byte, mt.write_byte)
        finally:
            _persist._settle_ms = real
        self.assertTrue(settles)                     # dance triggered it
        self.assertEqual(state["fan"]["duty_pct"], 100.0)

    def test_apply_strict_retry_absorbs_stale_readout(self):
        # State ends MANUAL while the chip starts in LUT mode: the step-2
        # PROG transition arms the stale window early in the apply, so
        # the first strict pass can catch the stale mirror even though no
        # read-back dance runs. The settle-and-retry must absorb it.
        src = FakeTransport(registers=self._lut_mode_image())
        state = _persist.collect_state(src.read_byte, src.write_byte)
        data = json.loads(_persist.encode(state))
        data["fan"]["manual"] = True                 # end in manual mode
        state = _persist.decode(_persist.encode(data))
        target = FakeTransport(registers=dict(self._lut_mode_image()))
        mt = MirrorTransport(target, sim_temp_c=27.0)
        report = _persist.apply_state(mt.write_byte, mt.read_byte,
                                      state, strict=True)
        self.assertEqual(report["diff"], {})
        self.assertEqual(target.registers[REG_FAN_CFG] & FCFG_PROG,
                         FCFG_PROG)

    def test_apply_strict_real_mismatch_survives_retry(self):
        # A register the transport refuses to actually change must STILL
        # fail strict verification after the retry - the settle path may
        # mask read-out lag, never genuine corruption.
        src = FakeTransport(registers=self._lut_mode_image())
        state = _persist.collect_state(src.read_byte, src.write_byte)
        target = FakeTransport(registers=dict(self._lut_mode_image()))
        mt = MirrorTransport(target, sim_temp_c=27.0)
        sabotage = SabotagingTransport(target, REG_IDEALITY)
        report = _persist.apply_state(sabotage.write_byte, mt.read_byte,
                                      state, strict=True)
        self.assertIn("%#02x" % REG_IDEALITY, report["diff"])


if __name__ == "__main__":
    unittest.main()
