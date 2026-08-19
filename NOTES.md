# NOTES — did / broken / exact next step (never stop at a clean boundary)

## 2026-08-18 (session 7 — driver hardening: a dead sensor can no longer read as healthy)
**did:** closed the confident-but-wrong hole session 6 exposed. The BME280
wiring is untouched (user hasn't checked it yet), so the same failing part
is still on the bench — which made it the perfect regression fixture.
  - `bme280.h`: real return codes (`BME280_ERR_IO` / `_CHIP_ID` / `_CONFIG` /
    `_NO_DATA`) replacing the bare -1, plus `bme280_strerror()` so the serial
    log names the fault. Named the reset sentinels
    (`BME280_ADC_RESET_TP` 0x80000, `BME280_ADC_RESET_H` 0x8000).
  - `bme280.c`: added `reg_write_verify()` — every config register is read
    straight back; `read_raw()` + `raw_is_reset_default()` factored out of
    `bme280_read()`. `bme280_init()` now verifies ctrl_hum/ctrl_meas/config
    stuck AND waits up to 200 ms for the data registers to leave their reset
    defaults, so "configured" is no longer mistaken for "measuring".
    `bme280_read()` re-reads ctrl_meas every sample (one byte) and refuses
    to compensate the reset sentinel instead of turning it into 22.30C.
  - `main.c`: sensor_task used to silently drop failed reads — a dead sensor
    produced no line at all. Now logs every failure with a consecutive
    counter; app_main reports the init failure reason by name.
  - Verified on real silicon: built clean under ESP-IDF v6.0.1, flashed,
    power-cycled via MEGA4 (hub is `1-1.2.3` port 1 THIS session — it was
    `0-1.2.4` in session 5, so always re-resolve it), captured 61 lines
    through the real `RealSerial` class. Where session 6 printed a frozen,
    plausible `T=22.30C P=671.23hPa H=0.0%`, it now prints every second:
      `E bme280: ctrl_meas is 0x00, configured 0x27 — sensor reset`
      `E testsubject: sensor: read failed (config-lost) consecutive=24`
    That is the classifier-visible signal that did not exist before.
  - Human-in-the-loop tooling (user asked to watch work in real time):
    `tools/live.sh` tails `runs/live.log` in its own Terminal window;
    `tools/live-note` appends notes and, with `--run`, streams a command's
    output there too; `bench/serial_monitor.py` gained `live_write()`, which
    mirrors each captured serial line into `$BENCHAGENT_LIVE_LOG` as it
    arrives. Opt-in by env var, so CI and the 25 unit tests are unaffected
    (still 25/25 green).
**broken:** the BME280 itself is unchanged — still browning out, still
resetting ~1×/s, `consecutive=` climbs forever. That is now loud instead of
silent, but it is not fixed; the wiring check from session 6 is still owed.
Two new things found:
  - **Boot log gap is worse than noted.** The S3's USB-serial-JTAG only
    enumerates once the app runs, so `bme280_init()`'s verdict is never
    captured — this session's capture opened at t+15s. Tried four ways in
    (poll-and-attach, wait-for-node-gone, `idf.py monitor`, monitor under a
    pty); monitor needs a TTY and the pty attempt was not run. Runtime
    behavior is verified, init's own log line is still unobserved.
  - **`uhubctl -a off` returns before macOS drops the device node.** The
    node lingered >10 s with power cut, so a fast re-attach grabs a stale
    handle and dies with `OSError: [Errno 6] Device not configured`. If
    `bench/power.py` assumes the node is gone right after `power_cycle()`,
    it has this race — UNVERIFIED, power.py not yet read for it.
**exact next step:** (1) check the BME280 wiring — re-seat all 4 jumpers,
confirm VDD is on the devkit 3V3 pin, check whether the breakout wants VIN/5V
— then re-flash and watch for `consecutive=` to stop climbing and real
varying readings to appear. The hardened driver is now the test: if the
sensor is alive, the errors stop by themselves. (2) Audit `bench/power.py`
for the stale-node race above. (3) Still open from session 6: new planted
bug + failure class for silently-static telemetry. (4) Still open from
session 5: build the planted-bug variants and run the M1 acceptance test.
Session 6's diagnostic firmware remains in `git stash@{0}`, untouched.

## 2026-08-13 (session 6 — BME280 wired; sensor brown-out diagnosed, driver exonerated)
**did:** wired the BME280 (SDA→GPIO8, SCL→GPIO9) and got first contact:
bus scan finds exactly one device at 0x76, chip ID reads 0x60, calibration
blob reads back plausible (dig_T1=28376 dig_T2=26615 dig_T3=50
dig_P1=37961 dig_H1=75 dig_H2=358). bme280_init() returns 0. `sensor: T=`
lines finally appear — so bme280.c's I2C path, calibration parsing and
compensation math all execute against real silicon for the first time.
BUT the readings are wrong and frozen: T=22.30C P=671.23hPa H=0.0%,
byte-identical every second for 20+ s (671 hPa ≈ 3500 m altitude; 0.0%
RH is impossible indoors).
Root-caused it with a temporary in-firmware diagnostic (bus scan, register
dump, write→read-back, and a 10×500ms persistence loop):
  - at t+3.1s ctrl_hum/ctrl_meas/config all read 0x00 and data regs read
    80 00 00 80 00 00 80 00 — the power-on reset defaults. Sensor is in
    SLEEP and has never measured.
  - writing ctrl_meas=0x27 succeeds and reads straight back as 0x27, so
    writes are NOT broken.
  - but it decays: t+500/t+1000ms reads return I2C errors, and by
    t+1500ms ctrl_meas is 0x00 again and data regs are back to 0x80000,
    and stay there. Registers only clear like that on power loss/reset.
  ⇒ the sensor is browning out and resetting roughly once a second.
    Driver logic is exonerated: hand-computing compensate_T(0x80000) with
    the real calibration constants yields exactly 2230 → the observed
    22.30C. The frozen "plausible" numbers are arithmetic on blank
    registers, not measurements.
**broken:** BME280 not usable until the wiring/power issue is fixed — most
likely a loose VDD/GND jumper, or a breakout whose regulator needs ~5V and
browns out on 3V3. Unverified (user was to check physically): re-seat all
4 jumpers, confirm VDD is on the devkit 3V3 pin (not 5V, not a GPIO), and
check whether the module's power pin is VIN vs 3V3.
ALSO BROKEN, and more important than the sensor: **bme280_init() returned
rc=0 for a sensor that was actively failing**, and the bench then reported
clean-looking steady telemetry for a dead sensor. The classifier would
score this as clean-boot. That is a confident-but-wrong case of exactly
the kind FaultBench is supposed to expose, and it is currently
undetectable from the serial log alone — every line looks healthy.
**exact next step:** (1) fix the wiring, re-run the persistence loop, and
confirm ctrl_meas holds 0x27 and the raw ADC bytes actually change
between reads. (2) Then harden the driver so this can never pass silently:
verify ctrl_meas reads back after configuring it, and have bme280_read()
reject the reset-default sentinel (adc==0x80000 / 0x8000) instead of
compensating it into a plausible number. (3) Consider a new planted bug +
failure class for "sensor stuck / silently static telemetry" — the log is
otherwise indistinguishable from a healthy run, which makes it a good
FaultBench case. (4) Still pending from session 5: build the planted-bug
variants and run the M1 acceptance test.
The temporary diagnostic firmware (bus scan / register dump / persistence
loop, ~82 lines across bme280.c/.h and main.c) is NOT committed — it is
saved as a git stash, message "wip: BME280 bring-up diagnostics
(temporary, not for commit)". Restore with `git stash apply` (keep it in
the stash rather than popping, so it stays recoverable).

## 2026-08-13 (session 5 — first real flash+boot on hardware; 4 build bugs fixed)
**did:** BME280 sensor arrived, so all hardware is now in hand. User confirmed
this Mac is the bring-up host for now (industry-standard dedicated bench
machine to come later). Wired up ESP32-S3-DevKitC-1 through the UUGear
MEGA4 into this Mac. Installed uhubctl (brew) and pytest/pyserial/esptool
(pip, matching CI's `pip install pytest pyserial esptool`) — 25/25 unit
tests still pass. Validated all three real bench classes end-to-end against
actual hardware for the first time:
  - esptool connectivity (the shape EsptoolFlasher wraps): `chip_id`
    succeeded after one manual BOOT+RESET to force download mode — ESP32-S3
    (QFN56 rev v0.2), WiFi/BLE, 16MB PSRAM, MAC 38:44:be:cc:d3:34.
  - RealSerial.capture(): captured real boot-ROM text
    (`ESP-ROM:esp32s3-20210327`, reset-reason line) at 115200 baud.
  - UhubctlPower.power_cycle(): full VBUS cut/restore on hub `0-1.2.4`
    port 1 via the actual class — board fully disappeared and
    re-enumerated.
Found a port-churn nuance not previously documented: the device node is
STABLE across RTS-line resets (stayed /dev/cu.usbmodem124101 through
repeated esptool resets and manual BOOT-mode entry) but CHANGES on a full
VBUS power-cycle via the MEGA4 (.usbmodem1234561 before/after a power
cycle vs .usbmodem124101 during RTS-only resets). Logged in
docs/failure-modes.md.
Then installed ESP-IDF v6.0.1 (~5GB, ~/esp/esp-idf + ~/.espressif) and got
the firmware building and running on real silicon for the first time. Four
real bugs surfaced that only a real build/flash could expose — CI only ran
cppcheck, never a full compile, so all four had been invisible:
  1. main.c called esp_timer_get_time() with no #include "esp_timer.h"
     (previously pulled in transitively; not true on IDF v6).
  2. main/CMakeLists.txt listed only the legacy `driver` component; the
     new i2c_master API needs esp_driver_i2c in PRIV_REQUIRES.
  3. bme280.c declared s_dev as i2c_device_handle_t — no such type in
     IDF v6; it is i2c_master_dev_handle_t. (Cascaded into 3 more errors.)
  4. bench/flash.py hardcoded "python" (resolved to Anaconda here, no
     esptool) → now sys.executable; and captured only stderr for its
     error message, but esptool writes fatal errors to stdout, so real
     failures raised a blank RuntimeError. Now captures both.
Also added firmware/testsubject/sdkconfig.defaults (NEW, tracked): sdkconfig
is gitignored, so console routing was never pinned and fell back to IDF's
stock UART0 default — unwired on the DevKitC-1, so app logs went nowhere.
Pinned CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG=y.
Validated end-to-end on hardware after that: EsptoolFlasher.flash() wrote
merged.bin (attempt 1, sha recorded), and a full
UhubctlPower.power_cycle() → re-resolve port → RealSerial.capture() cycle
returns live app telemetry:
  I (2202) testsubject: heartbeat #2 uptime=2.1s free_heap=391788
free_heap flat across 14 heartbeats — correct for a no-bug build.
25/25 unit tests and all 5 mock-loop smoke classes still pass.
**broken:** BME280 not physically wired yet (needs jumper wires to
GPIO8/GPIO9), so no `sensor: T=` lines — bme280.c's I2C path is compiled
and linked but still unexercised against the real bus. Boot banner lines
(including the "BME280 probe failed" message) are LOST on this board: they
print before USB-Serial-JTAG enumerates, so capture reliably starts around
heartbeat #2. That matters for the classifier — anything keying off boot
banner text will not see it over native USB. Manual BOOT+RESET also
latches download mode until VBUS is cut (see docs/failure-modes.md); the
bench must power-cycle after any manual boot-mode entry or it will read
zero bytes and look like a silent-hang.
**exact next step:** wire the BME280 (SDA→GPIO8, SCL→GPIO9, 3V3, GND) and
confirm `sensor: T=` lines appear, which is the first real exercise of
bme280.c against hardware. Then build the planted-bug variants
(idf.py -DBUG=WDT_STARVE reconfigure && idf.py build, likewise
BUG_HEAP_LEAK / BUG_BUF_OVF) and run the M1 acceptance test: flash → watch
→ power-cycle → verdict, 3 planted bugs diagnosed unassisted. Note the
boot-banner loss above when checking classifier behavior on real captures.

## 2026-08-12 (hardware status: MEGA4 + cables in hand, sensor tomorrow)
**did:** acquired two USB-A-to-Micro-USB cables (one short, one long).
UUGear MEGA4 hub arrived. Arrival order flipped from the original
estimate — MEGA4 landed before the sensor instead of after it; BME280
sensor now expected 2026-08-13. So as of today: ESP32-S3 devkit + cables
+ MEGA4 are all physically in hand; only the sensor is still outstanding.
Checked this machine (dev laptop) for the board/hub — nothing enumerated
over USB yet, and no ESP-IDF/esptool/uhubctl installed here.
**broken:** real-hardware validation still hasn't started. Not fully
blocked on the sensor anymore, though — main.c handles a missing BME280
gracefully (logs the probe failure, keeps running), so
flash/serial-capture/power-cycle validation could start on the ESP32-S3 +
MEGA4 alone without waiting on the sensor, once everything is physically
wired up on the actual bring-up machine.
**exact next step:** confirm which machine is the bring-up host, wire up
the ESP32-S3 through the MEGA4 there, install esptool/uhubctl (+ ESP-IDF
if flashing custom firmware), and validate RealSerial/EsptoolFlasher/
UhubctlPower against real hardware — doesn't need to wait on the sensor.
Once the sensor arrives (~8/13), fold it in and run the full M1
acceptance test (flash → watch → power-cycle → verdict, 3 planted bugs
diagnosed unassisted).

## 2026-08-10 (cable mix-up, resolved — board is fine)
**did:** chased down a false alarm. Initially misidentified the ESP32-S3
devkit's (Amazon B0FDG3WJDX, ESP32-S3-DevKitC-1-N32R16V) port as USB-A,
which didn't match Espressif's official USB-C reference design and
looked like a wrong/counterfeit board. Corrected: the port is actually
Micro-USB, matching the listing's "USB Micro-B" spec field all along —
no board mismatch, just a port misidentification. Amazon's "Memory
Storage Capacity: 32 bytes" field is still a garbage/auto-generated
listing artifact, unrelated to this.
**broken:** still can't flash or serial-capture on real hardware — the
actual blocker is simply not having a USB-A-to-Micro-USB cable on hand
(a common, cheap cable). Sensor arrives 8/11, MEGA4 arrives 8/13.
**exact next step:** get a USB-A-to-Micro-USB cable (no need to contact
the seller — board is legitimate). Once cable + sensor + MEGA4 are all
in hand, validate RealSerial/EsptoolFlasher/UhubctlPower end-to-end and
run the M1 acceptance test.

## 2026-08-10 (session 4 — unit tests for real bench classes, hardware-independent)
**did:** wrote tests/test_bench_classes.py — 16 new unit tests for
EsptoolFlasher, UhubctlPower, MockFlasher/MockPower, MockSerial, and
RealSerial, all with mocked subprocess/serial I/O (no pyserial installed,
no device required). Covers: esptool retry-via-power-cycle path and
2-attempt failure, exact uhubctl CLI args and off→on ordering, subprocess
error propagation, MockSerial max_lines truncation, and RealSerial's three
stop conditions (silence deadline, window timeout, max_lines) via a fake
monotonic clock + scripted fake serial port injected through
sys.modules["serial"]. All 25 tests pass (9 classifier + 16 new); no logic
bugs found, but the coverage is now in place to catch retry/truncation/
timing regressions before real hardware is on the bench. Also closed a
related gap: CI's mock-loop smoke test only checked 3 of 5 failure
classes (missing silent-hang and the new heap-leak) — added both.
**broken:** nothing new. Bench classes still logically untested against an
*actual* device — mocks characterize the intended behavior, not hardware
reality (USB re-enumeration, real port timeouts, etc. per
docs/failure-modes.md). Sensor arrives 2026-08-11, MEGA4 arrives
2026-08-13.
**exact next step:** BUG_DEADLOCK and BUG_STACK_OVF firmware
implementation is next on the hardware-independent list, but blocked here
— no ESP-IDF toolchain installed on this machine, so the C can't be
verified to compile -Wall -Wextra -Werror clean. Either install ESP-IDF
first, or hold that task until hardware arrives and it can be verified on
the actual bring-up machine. Once hardware arrives (~8/13): validate
RealSerial/EsptoolFlasher/UhubctlPower end-to-end against the real board,
then run the M1 acceptance test.

## 2026-08-10 (session 3 — BUG_HEAP_LEAK classifier support, hardware-independent)
**did:** added free_heap trend detection to bench/classify.py —
`parse_heartbeats`/`detect_heap_leak` decode the heartbeat_task telemetry
line and flag a new `heap-leak` failure class when free_heap declines
monotonically by >100 bytes/s over a >=10s window (matches the detection
hint in evals/bugs.yaml for BUG_HEAP_LEAK). Added `heap_trend` field to
EvidenceBundle. New fixture fixtures/logs/heap_leak.log (~128 bytes/s
decline, matches the firmware comment). 3 new unit tests (5/5 fixtures now
covered: clean-boot, boot-loop, panic, silent-hang, heap-leak). Also fixed
MockLLM.CANNED, which had no entry for "heap-leak" and was silently
falling back to the silent-hang canned diagnosis — added a proper canned
mechanism/fix and confidence entry. Verified end-to-end with
`./benchagent run --mock fixtures/logs/heap_leak.log --mock-llm`.
**broken:** nothing new. Bench classes and bme280.c still unvalidated
against real hardware, blocked on the sensor (arrives 2026-08-11) and
MEGA4 (arrives 2026-08-13).
**exact next step:** more hardware-independent work while waiting:
implement the two remaining "planned" bugs (BUG_DEADLOCK, BUG_STACK_OVF)
in firmware behind compile flags; write unit tests for the real bench
classes (flash.py/power.py/serial_monitor.py) with mocked
serial/subprocess calls. Once hardware arrives: validate
RealSerial/EsptoolFlasher/UhubctlPower end-to-end, then run the M1
acceptance test.

## 2026-08-10 (hardware status check)
**did:** confirmed arrival status of the hardware order. Rest of the Amazon
BOM has arrived. Two items still in transit: the sensor (arriving
2026-08-11) and the UUGear MEGA4 hub (arriving 2026-08-13).
**broken:** nothing new — bench classes (RealSerial/EsptoolFlasher/
UhubctlPower) and bme280.c remain unvalidated against real hardware,
blocked on these two parts.
**exact next step:** while waiting, do hardware-independent Stage 1/2 work:
add free_heap trend detection to bench/classify.py for BUG_HEAP_LEAK (no
classifier support yet, no fixture/test); implement the two "planned"
bugs (BUG_DEADLOCK, BUG_STACK_OVF) in firmware behind compile flags; write
unit tests for the real bench classes with mocked serial/subprocess calls.
Once the sensor and MEGA4 arrive (~2026-08-13): validate
RealSerial/EsptoolFlasher/UhubctlPower end-to-end, then run the M1
acceptance test.

## 2026-08-09 (session 2 — Stage 1 software: BME280 driver, real bench classes)
**did:** wrote bme280.c register-level driver from the datasheet (no longer a
stub, 249 lines); implemented real bench classes — flash.py, power.py,
serial_monitor.py (RealSerial/EsptoolFlasher/UhubctlPower equivalents);
added 2 new planted bugs to evals/bugs.yaml. Commit f998f33.
**broken:** real bench classes are untested against actual hardware — no
board on hand yet. bme280.c untested on real I2C bus, only compiles clean.
**exact next step:** place hardware order (BOM in README — ~$200). Once it
arrives: validate RealSerial/EsptoolFlasher/UhubctlPower end-to-end, then
run the M1 acceptance test (flash → watch → power-cycle → verdict, 3 planted
bugs diagnosed unassisted).

## 2026-08-09 (session 1 — CI fix, model IDs, real API validated)
**did:** fixed CI smoke test grep patterns (** is invalid BRE — added -F flag);
corrected stale model IDs in config.py (claude-opus-4-8 → claude-opus-4-6,
claude-fable-5 → claude-opus-4-6 for break-glass); CI green on main.
Real API validated on all 4 fixtures — AnthropicClient tool loop works:
  bootloop: FAIL conf 0.99 (no escalation, 18s)
  panic:     FAIL conf 0.91 (no escalation, 46s)
  silent_hang: FAIL conf 0.72 (no escalation, just above threshold — correct)
  clean_boot: PASS conf 0.98 (no escalation, 23s)
**broken:** bme280.c still a stub; RealSerial/EsptoolFlasher/UhubctlPower
still NotImplemented until hardware arrives.
**exact next step:** place hardware order (BOM in README — ~$200);
while waiting: write bme280.c register-level driver from datasheet.

## 2026-08-07 (session 0 — repo bootstrap)
**did:** repo skeleton; mock loop e2e green on all 4 failure classes
(clean-boot / boot-loop / panic / silent-hang); classifier + 6 unit tests
passing; escalation path verified (tier1 0.55 -> tier2 0.92 on bootloop);
runs/ archiving verdict.json + evidence.json + report.md; firmware
scaffolded with BUG_WDT_STARVE and BME280 driver interface.
**broken:** bme280.c is a stub (deliberate — I write it from the datasheet);
RealSerial/EsptoolFlasher/UhubctlPower are NotImplemented until hardware;
mock LLM is canned — real API path untested end-to-end.
**exact next step:** export ANTHROPIC_API_KEY and run
`./benchagent run --mock fixtures/logs/bootloop.log` WITHOUT --mock-llm;
fix whatever breaks in AnthropicClient tool loop. Then: place hardware order.
