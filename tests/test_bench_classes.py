"""Unit tests for the real bench classes (flash.py, power.py,
serial_monitor.py), written before hardware arrived. All subprocess/serial
I/O is mocked — these catch logic bugs (wrong CLI args, off-by-one retry/
truncation conditions) ahead of real bring-up, not hardware behavior itself.
"""
import subprocess
import sys
import types

import pytest

from bench.flash import EsptoolFlasher, MockFlasher, sha256_of
from bench.power import MockPower, UhubctlPower
from bench.serial_monitor import Capture, MockSerial, RealSerial


# --- flash.py ----------------------------------------------------------

def test_sha256_of(tmp_path):
    f = tmp_path / "img.bin"
    f.write_bytes(b"firmware bytes")
    import hashlib
    assert sha256_of(f) == hashlib.sha256(b"firmware bytes").hexdigest()


def test_mock_flasher_reports_sha(tmp_path):
    f = tmp_path / "img.bin"
    f.write_bytes(b"abc")
    result = MockFlasher().flash(f)
    assert result["ok"] is True
    assert result["mock"] is True
    assert result["image_sha256"] == sha256_of(f)


def test_esptool_flasher_succeeds_first_attempt(tmp_path, monkeypatch):
    img = tmp_path / "img.bin"
    img.write_bytes(b"abc")

    calls = []
    def fake_run(cmd, capture_output, text, timeout):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
    monkeypatch.setattr(subprocess, "run", fake_run)

    flasher = EsptoolFlasher(port_by_id="/dev/serial/by-id/usb-esp32", baud=460800)
    result = flasher.flash(img)

    assert result == {"ok": True, "mock": False,
                       "image_sha256": sha256_of(img), "attempt": 1}
    assert len(calls) == 1
    cmd = calls[0]
    assert "--port" in cmd and cmd[cmd.index("--port") + 1] == "/dev/serial/by-id/usb-esp32"
    assert "--baud" in cmd and cmd[cmd.index("--baud") + 1] == "460800"
    assert cmd[-3:] == ["write_flash", "0x0", str(img)]


def test_esptool_flasher_retries_via_power_cycle_then_succeeds(tmp_path, monkeypatch):
    img = tmp_path / "img.bin"
    img.write_bytes(b"abc")

    results = iter([
        subprocess.CompletedProcess([], returncode=1, stdout="", stderr="sync failed"),
        subprocess.CompletedProcess([], returncode=0, stdout="", stderr=""),
    ])
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: next(results))
    monkeypatch.setattr("bench.flash.time.sleep", lambda s: None)

    power = MockPower()
    flasher = EsptoolFlasher(port_by_id="/dev/serial/by-id/usb-esp32")
    result = flasher.flash(img, power=power)

    assert result["ok"] is True
    assert result["attempt"] == 2
    assert power.cycles == 1  # power-cycled once, between attempt 1 and 2


def test_esptool_flasher_fails_loudly_after_two_attempts(tmp_path, monkeypatch):
    img = tmp_path / "img.bin"
    img.write_bytes(b"abc")

    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess([], returncode=1, stdout="", stderr="no device found"),
    )
    monkeypatch.setattr("bench.flash.time.sleep", lambda s: None)

    flasher = EsptoolFlasher(port_by_id="/dev/serial/by-id/usb-esp32")
    with pytest.raises(RuntimeError, match="no device found"):
        flasher.flash(img, power=MockPower())


def test_esptool_flasher_does_not_power_cycle_without_power(tmp_path, monkeypatch):
    img = tmp_path / "img.bin"
    img.write_bytes(b"abc")

    call_count = {"n": 0}
    def fake_run(*a, **k):
        call_count["n"] += 1
        return subprocess.CompletedProcess([], returncode=1, stdout="", stderr="fail")
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr("bench.flash.time.sleep", lambda s: None)

    flasher = EsptoolFlasher(port_by_id="/dev/serial/by-id/usb-esp32")
    with pytest.raises(RuntimeError):
        flasher.flash(img, power=None)
    assert call_count["n"] == 2  # still retries once even with no power to cycle


# --- power.py ------------------------------------------------------------

def test_mock_power_counts_cycles():
    p = MockPower()
    p.power_cycle(port=1)
    r = p.power_cycle(port=2, off_s=1.5)
    assert r == {"ok": True, "mock": True, "port": 2, "off_s": 1.5, "cycle_count": 2}


def test_uhubctl_power_cycle_calls_off_then_on_in_order(monkeypatch):
    calls = []
    def fake_run(cmd, check, capture_output, timeout):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, returncode=0)
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr("bench.power.time.sleep", lambda s: None)

    power = UhubctlPower(hub_location="1-1.4")
    result = power.power_cycle(port=2, off_s=3.0)

    assert len(calls) == 2
    assert calls[0] == ["uhubctl", "-l", "1-1.4", "-p", "2", "-a", "off"]
    assert calls[1] == ["uhubctl", "-l", "1-1.4", "-p", "2", "-a", "on"]
    assert result == {"ok": True, "mock": False, "hub": "1-1.4", "port": 2, "off_s": 3.0}


def test_uhubctl_power_cycle_propagates_subprocess_error(monkeypatch):
    def fake_run(cmd, check, capture_output, timeout):
        raise subprocess.CalledProcessError(returncode=1, cmd=cmd)
    monkeypatch.setattr(subprocess, "run", fake_run)

    power = UhubctlPower(hub_location="1-1.4")
    with pytest.raises(subprocess.CalledProcessError):
        power.power_cycle(port=1)


# --- serial_monitor.py: Capture, MockSerial -------------------------------

def test_capture_duration_s():
    c = Capture(text="", lines=[], started_mono=10.0, ended_mono=12.5)
    assert c.duration_s == 2.5


def test_mock_serial_replays_file(tmp_path):
    f = tmp_path / "log.txt"
    f.write_text("line1\nline2\nline3\n")
    cap = MockSerial(f).capture()
    assert cap.lines == ["line1", "line2", "line3"]
    assert cap.truncated is False


def test_mock_serial_truncates_to_max_lines(tmp_path):
    f = tmp_path / "log.txt"
    f.write_text("\n".join(f"line{i}" for i in range(10)))
    cap = MockSerial(f).capture(max_lines=3)
    assert cap.lines == ["line7", "line8", "line9"]
    assert cap.truncated is True


# --- serial_monitor.py: RealSerial ----------------------------------------
# No pyserial installed (mock-only environment, matches Stage 0/1 dev
# machines) — RealSerial imports `serial` lazily inside capture(), so we
# inject a fake module under sys.modules["serial"] to drive it deterministically
# without a real device or the pyserial dependency.

class _FakeClock:
    def __init__(self):
        self.t = 0.0

    def monotonic(self):
        return self.t

    def advance(self, dt):
        self.t += dt
        return self.t


class _FakeSerialPort:
    """Scripted readline(): each entry is (time_to_advance, payload_bytes)."""

    def __init__(self, port, baudrate, timeout, *, clock, script, calls):
        calls.append({"port": port, "baudrate": baudrate, "timeout": timeout})
        self._clock = clock
        self._script = iter(script)

    def readline(self):
        delay, payload = next(self._script, (1.0, b""))
        self._clock.advance(delay)
        return payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def fake_serial_module(monkeypatch):
    """Installs a fake `serial` module and a fake monotonic clock shared by
    the module under test. Returns (clock, calls, set_script)."""
    clock = _FakeClock()
    calls = []
    script_holder = {"script": []}

    def make_serial(port, baudrate, timeout):
        return _FakeSerialPort(port, baudrate, timeout, clock=clock,
                                script=script_holder["script"], calls=calls)

    fake_module = types.SimpleNamespace(Serial=make_serial)
    monkeypatch.setitem(sys.modules, "serial", fake_module)
    monkeypatch.setattr("bench.serial_monitor.time.monotonic", clock.monotonic)

    def set_script(script):
        script_holder["script"] = script

    return clock, calls, set_script


def test_real_serial_stops_on_silence_deadline(fake_serial_module):
    clock, calls, set_script = fake_serial_module
    set_script([
        (0.1, b"boot\n"),
        (1.0, b""),
        (1.0, b""),
        (1.0, b""),  # would push well past silence_s if ever reached
    ])

    rs = RealSerial(by_id_path="/dev/serial/by-id/usb-esp32", baud=115200)
    cap = rs.capture(window_s=100.0, silence_s=2.0, max_lines=100)

    assert cap.lines == ["boot"]
    assert cap.truncated is False
    assert calls == [{"port": "/dev/serial/by-id/usb-esp32", "baudrate": 115200, "timeout": 1.0}]


def test_real_serial_stops_on_window_timeout_without_truncation(fake_serial_module):
    clock, calls, set_script = fake_serial_module
    set_script([(0.1, f"line{i}\n".encode()) for i in range(50)])

    rs = RealSerial(by_id_path="/dev/serial/by-id/usb-esp32")
    cap = rs.capture(window_s=0.25, silence_s=100.0, max_lines=100)

    assert cap.lines == ["line0", "line1", "line2"]
    assert cap.truncated is False  # window cut it short, not max_lines


def test_real_serial_truncates_at_max_lines(fake_serial_module):
    clock, calls, set_script = fake_serial_module
    set_script([(0.01, f"line{i}\n".encode()) for i in range(50)])

    rs = RealSerial(by_id_path="/dev/serial/by-id/usb-esp32")
    cap = rs.capture(window_s=100.0, silence_s=100.0, max_lines=2)

    assert cap.lines == ["line0", "line1"]
    assert cap.truncated is True


def test_real_serial_ignores_empty_reads_before_first_line(fake_serial_module):
    clock, calls, set_script = fake_serial_module
    set_script([(0.1, b""), (0.1, b""), (0.1, b"heartbeat #1\n")])

    rs = RealSerial(by_id_path="/dev/serial/by-id/usb-esp32")
    cap = rs.capture(window_s=100.0, silence_s=5.0, max_lines=100)

    assert cap.lines == ["heartbeat #1"]
