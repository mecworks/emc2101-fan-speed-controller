# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the project
adheres to [Semantic Versioning](https://semver.org/) once 1.0 lands.

## [0.1.0] - Unreleased

Initial release of the cross-platform EMC2101 driver package.

### Added

- **Package** (`emc2101`): one API across three platforms — MicroPython
  on Raspberry Pi Pico W and ESP32-S3 (`emc2101.mp`), CPython/smbus2 on
  Raspberry Pi 3A+ (`emc2101.cp`). Fixed SMBus address `0x4C`.
- **Lifecycle & raw tier:** `verify()` (identity-trio check with `-R`
  part warning), `probe()`, `scan()`, `close()`, context manager,
  `read_reg`/`write_reg` over the single-byte SMBus protocol with retry
  ladder.
- **Identity:** `product_id`, `mfg_id`, `revision`, `part_info`.
- **Temperatures & limits:** internal die temp (1 °C steps), external
  diode temp (0.125 °C steps, MSB-first interlocked read, typed
  `DiodeFaultError` on open/short sentinels), local/remote high-low
  limits, TCRIT with the one-time unlock dance and hysteresis.
- **Status & alerts:** destructive-read discipline, active-alarm names,
  reserved-bit-preserving alert mask, interrupt/comparator modes,
  `service_alert()` / `clear_alert_mask()`, `diode_fault()`, `busy()`.
- **Manual duty & PWM:** percent duty quantized onto the live PWM_F
  grid, frequency solver over PWM_F/PWM_D/CLK_SEL/CLK_OVR (nearest
  achievable, max-resolution tie-break), drive inversion, DAC mode,
  raw-tier clock/divider accessors.
- **LUT:** eight `(temp_c, duty_pct)` entries with ascending validation,
  PROG dance with restore-on-failure, per-entry and bulk access, LUT
  hysteresis, force-register testing path.
- **Tachometer:** LSB-first interlocked RPM reads (5,400,000 divisor),
  tach limit + `min_rpm` convenience, ALT_TCH pin-role switching with
  the ALERT trade-off documented, TACH_M sub-minimum behavior control.
- **Spin-up:** enabled/drive/time/fast-tach composites over the
  three-field register.
- **Calibration:** ideality factor table (index/factor/nearest-match
  setter), beta autodetect + manual index.
- **Power & conversion control:** standby (+ fan standby), guarded
  `one_shot()`, table-driven conversion rate, averaging filter levels,
  SMBus-TIMEOUT disable, fault queue mode.
- **Presets:** `configure_4wire_fan(pwm_freq_hz)`.
- **Persistence ("virtual EEPROM"):** JSON schema v1
  (`save_config`/`load_config`) with full pre-apply validation, product-
  ID refusal, revision warnings, ordered apply with the TCRIT special
  case, strict post-apply read-back diff (on by default), atomic
  temp-file+rename writes, and constructor auto-load semantics
  (`config_file=` kwarg; missing file = silent no-op, corrupt file =
  raise before any register write). Default paths `/emc2101.json`
  (MicroPython) and `~/emc2101.json` (CPython).
- **Tooling:** `tools/api_coverage.py` (public-member coverage gate),
  `tests/lint_subset.py` (MicroPython-subset lint gate),
  `tools/deploy_mp.py` (mpremote-based package deployer), mock-backed
  unit suite (274 tests) with stateful fake transports.
- **Documentation:** `docs/` (quickstart, API reference, wiring guide,
  persistence, operational notes), `CONTRIBUTING.md`, this changelog.
