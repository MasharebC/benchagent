"""Classifier unit tests — pure functions, no hardware, run in CI."""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from bench.classify import classify, decode_resets, parse_panic, parse_task_wdt

FIX = pathlib.Path(__file__).resolve().parent.parent / "fixtures" / "logs"

def _load(name):
    return (FIX / name).read_text()

def test_clean_boot():
    b = classify(_load("clean_boot.log"))
    assert b.failure_class == "clean-boot"
    assert b.reset_count == 1
    assert b.reset_history[0]["name"] == "POWERON"
    assert b.last_heartbeat == 5

def test_bootloop_wdt():
    b = classify(_load("bootloop.log"))
    assert b.failure_class == "boot-loop"
    assert b.reset_count >= 3
    assert b.task_wdt is not None
    assert any(s["task"] == "IDLE0" for s in b.task_wdt["starved"])
    assert any(r["task"] == "sensor_task" for r in b.task_wdt["running_at_trigger"])
    assert b.bug_flags_reported == "BUG_WDT_STARVE"

def test_panic_loadprohibited():
    b = classify(_load("panic.log"))
    assert b.failure_class == "panic"
    p = b.panic
    assert p["cause"] == "LoadProhibited"
    assert p["exccause"] == "0x0000001c"
    assert "LoadProhibited" in p["exccause_decoded"]
    assert p["excvaddr"] == "0x00000020"
    assert len(p["backtrace"]) == 4

def test_silent_hang():
    b = classify(_load("silent_hang.log"))
    assert b.failure_class == "silent-hang"

def test_heap_leak_trend():
    b = classify(_load("heap_leak.log"))
    assert b.failure_class == "heap-leak"
    assert b.bug_flags_reported == "BUG_HEAP_LEAK"
    assert b.heap_trend is not None
    assert b.heap_trend["window_s"] == 14.0
    assert b.heap_trend["start_free_heap"] == 340212
    assert b.heap_trend["end_free_heap"] == 338420
    assert -130 <= b.heap_trend["slope_bytes_per_s"] <= -125

def test_heap_leak_needs_sustained_window():
    from bench.classify import detect_heap_leak
    # Span under the 10s minimum window should not trigger, even if declining.
    short = [
        {"n": 1, "uptime_s": 1.0, "free_heap": 10000},
        {"n": 2, "uptime_s": 5.0, "free_heap": 9000},
    ]
    assert detect_heap_leak(short) is None
    # A single dip that recovers (non-monotonic) should not trigger.
    noisy = [
        {"n": i, "uptime_s": float(i), "free_heap": h}
        for i, h in enumerate([10000, 8000, 12000, 8000, 4000, 2000, 500, 100, 50, 20, 5], start=1)
    ]
    assert detect_heap_leak(noisy) is None

def test_clean_boot_has_no_heap_trend():
    b = classify(_load("clean_boot.log"))
    assert b.heap_trend is None

def test_reset_decode_unknown_code_does_not_crash():
    out = decode_resets("rst:0x2 (WEIRD_RST),boot:0x8")
    assert out[0]["meaning"] == "unknown reset reason"

def test_no_panic_returns_none():
    assert parse_panic("just some lines") is None
    assert parse_task_wdt("just some lines") is None
