"""Deterministic failure classification. No LLM anywhere in this file.

Everything here is a pure function over captured serial text, so it is unit-
testable without hardware. The output is an EvidenceBundle: the *only* thing
the agent layer is allowed to see. The LLM interprets evidence; it never
parses raw logs itself.

Failure classes (rule-based):
    clean-boot | panic | boot-loop | watchdog-reset | brownout | silent-hang
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict

# --- Reset reason decode (ESP32-S3 ROM bootloader `rst:` line) --------------
# Chip-accurate names matter: a TG1WDT reset and a LoadProhibited panic are
# different stories, and the bench must tell them apart before the LLM does.
RESET_REASONS = {
    0x1: ("POWERON", "power-on reset"),
    0x3: ("RTC_SW_SYS_RST", "software system reset via RTC"),
    0x5: ("DEEPSLEEP_RESET", "wake from deep sleep"),
    0x7: ("TG0WDT_SYS_RST", "timer group 0 watchdog (task WDT escalation)"),
    0x8: ("TG1WDT_SYS_RST", "timer group 1 watchdog (interrupt WDT)"),
    0x9: ("RTCWDT_SYS_RST", "RTC watchdog system reset"),
    0xC: ("SW_CPU_RESET", "software CPU reset (abort/panic handler)"),
    0xD: ("RTCWDT_CPU_RST", "RTC watchdog CPU reset"),
    0xF: ("RTCWDT_BROWN_OUT_RST", "brownout detector reset"),
    0x10: ("RTCWDT_RTC_RST", "RTC watchdog reset (chip)"),
}

RST_RE = re.compile(r"rst:0x([0-9a-fA-F]+)\s*\(([A-Z0-9_]+)\)")
PANIC_RE = re.compile(
    r"Guru Meditation Error: Core\s+(\d) panic'ed \(([^)]+)\)"
)
REG_RE = re.compile(r"(PC|EXCCAUSE|EXCVADDR|A\d{1,2}|PS|SAR)\s*:\s*(0x[0-9a-fA-F]+)")
BACKTRACE_RE = re.compile(r"Backtrace:\s*((?:0x[0-9a-fA-F]+:0x[0-9a-fA-F]+\s*)+)")
TASK_WDT_RE = re.compile(r"task_wdt: Task watchdog got triggered")
TASK_WDT_CULPRIT_RE = re.compile(r"task_wdt:\s+-\s+(\S+)\s+\(CPU (\d)\)")
TASK_WDT_RUNNING_RE = re.compile(r"task_wdt: CPU (\d): (\S+)")
BROWNOUT_RE = re.compile(r"Brownout detector was triggered", re.IGNORECASE)
ABORT_RE = re.compile(r"abort\(\) was called at PC (0x[0-9a-fA-F]+) on core (\d)")
ELF_SHA_RE = re.compile(r"ELF file SHA256:\s*([0-9a-fA-F]+)")
BUG_FLAGS_RE = re.compile(r"BUG_FLAGS=(\S+)")
HEARTBEAT_RE = re.compile(r"heartbeat #(\d+)")
HEARTBEAT_HEAP_RE = re.compile(
    r"heartbeat #(\d+) uptime=([\d.]+)s free_heap=(\d+)"
)

# BUG_HEAP_LEAK detection hint (evals/bugs.yaml): free_heap slope < -100
# bytes/s sustained over a 10s window.
HEAP_LEAK_SLOPE_THRESHOLD = -100.0
HEAP_LEAK_MIN_WINDOW_S = 10.0

# EXCCAUSE decode (Xtensa LX7) — the subset that matters for the bug corpus.
EXCCAUSE = {
    0x00: "IllegalInstruction",
    0x03: "LoadStoreError (unaligned or invalid access size)",
    0x06: "IntegerDivideByZero",
    0x09: "LoadStoreAlignment",
    0x1C: "LoadProhibited (load from invalid/unmapped address)",
    0x1D: "StoreProhibited (store to invalid/unmapped address)",
    0x14: "InstFetchProhibited (jump/call to invalid address)",
}


@dataclass
class PanicFrame:
    core: int
    cause: str  # e.g. "LoadProhibited"
    pc: str | None = None
    exccause: str | None = None
    exccause_decoded: str | None = None
    excvaddr: str | None = None
    backtrace: list[str] = field(default_factory=list)


@dataclass
class EvidenceBundle:
    """Structured evidence handed to the agent. Never a raw log dump."""

    failure_class: str
    reset_history: list[dict]          # decoded rst: lines in order
    reset_count: int
    panic: dict | None                 # PanicFrame as dict, if any
    task_wdt: dict | None              # culprit + running tasks, if fired
    abort_pc: str | None
    elf_sha256: str | None
    bug_flags_reported: str | None     # what the firmware *claims* was compiled in
    last_heartbeat: int | None
    heap_trend: dict | None            # set when a sustained free_heap decline is seen
    serial_tail: list[str]             # last N lines, monotonic order
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def decode_resets(text: str) -> list[dict]:
    out = []
    for m in RST_RE.finditer(text):
        code = int(m.group(1), 16)
        name = m.group(2)
        known = RESET_REASONS.get(code)
        out.append({
            "code": hex(code),
            "name": name,
            "meaning": known[1] if known else "unknown reset reason",
        })
    return out


def parse_panic(text: str) -> PanicFrame | None:
    m = PANIC_RE.search(text)
    if not m:
        return None
    frame = PanicFrame(core=int(m.group(1)), cause=m.group(2))
    # Registers only from the dump following the panic line.
    dump = text[m.end():m.end() + 2000]
    regs = {k: v for k, v in REG_RE.findall(dump)}
    frame.pc = regs.get("PC")
    frame.exccause = regs.get("EXCCAUSE")
    if frame.exccause:
        frame.exccause_decoded = EXCCAUSE.get(int(frame.exccause, 16))
    frame.excvaddr = regs.get("EXCVADDR")
    bt = BACKTRACE_RE.search(dump)
    if bt:
        frame.backtrace = bt.group(1).split()
    return frame


def parse_task_wdt(text: str) -> dict | None:
    if not TASK_WDT_RE.search(text):
        return None
    return {
        "starved": [
            {"task": t, "cpu": int(c)} for t, c in TASK_WDT_CULPRIT_RE.findall(text)
        ],
        "running_at_trigger": [
            {"cpu": int(c), "task": t} for c, t in TASK_WDT_RUNNING_RE.findall(text)
        ],
    }


def parse_heartbeats(text: str) -> list[dict]:
    return [
        {"n": int(n), "uptime_s": float(t), "free_heap": int(h)}
        for n, t, h in HEARTBEAT_HEAP_RE.findall(text)
    ]


def detect_heap_leak(
    heartbeats: list[dict],
    *,
    slope_threshold: float = HEAP_LEAK_SLOPE_THRESHOLD,
    min_window_s: float = HEAP_LEAK_MIN_WINDOW_S,
) -> dict | None:
    """BUG_HEAP_LEAK signature: free_heap trends monotonically down at a
    sustained slope. A single dip or noisy jitter should not trigger this —
    require the window to span at least `min_window_s` and every sample to
    be non-increasing, matching the "sustained" language in the bug's
    detection hint (evals/bugs.yaml)."""
    if len(heartbeats) < 2:
        return None
    span = heartbeats[-1]["uptime_s"] - heartbeats[0]["uptime_s"]
    if span < min_window_s:
        return None
    monotonic = all(
        heartbeats[i]["free_heap"] >= heartbeats[i + 1]["free_heap"]
        for i in range(len(heartbeats) - 1)
    )
    if not monotonic:
        return None
    slope = (heartbeats[-1]["free_heap"] - heartbeats[0]["free_heap"]) / span
    if slope > slope_threshold:
        return None
    return {
        "slope_bytes_per_s": round(slope, 1),
        "window_s": round(span, 1),
        "start_free_heap": heartbeats[0]["free_heap"],
        "end_free_heap": heartbeats[-1]["free_heap"],
    }


def classify(
    text: str,
    *,
    capture_window_s: float | None = None,
    silence_deadline_s: float = 10.0,
    bootloop_threshold: int = 3,
    tail_lines: int = 40,
) -> EvidenceBundle:
    """Classify a serial capture into a failure class + evidence bundle."""
    lines = text.splitlines()
    resets = decode_resets(text)
    panic = parse_panic(text)
    task_wdt = parse_task_wdt(text)
    abort_m = ABORT_RE.search(text)
    sha_m = ELF_SHA_RE.search(text)
    flags_m = BUG_FLAGS_RE.search(text)
    heartbeats = [int(n) for n in HEARTBEAT_RE.findall(text)]
    heap_leak = detect_heap_leak(parse_heartbeats(text))
    notes: list[str] = []

    # Precedence: brownout > boot-loop > panic > watchdog > heap-leak > silent-hang > clean
    if BROWNOUT_RE.search(text):
        failure = "brownout"
    elif len(resets) >= bootloop_threshold:
        failure = "boot-loop"
        notes.append(
            f"{len(resets)} resets observed in one capture window "
            f"(threshold {bootloop_threshold})."
        )
        if task_wdt:
            notes.append("Task watchdog fired before each reset — WDT-driven boot loop.")
        if panic:
            notes.append("Panic precedes each reset — panic-driven boot loop.")
    elif panic:
        failure = "panic"
    elif task_wdt or any(r["name"].startswith(("TG0WDT", "TG1WDT", "RTCWDT")) for r in resets[1:]):
        failure = "watchdog-reset"
    elif heap_leak:
        failure = "heap-leak"
        notes.append(
            f"free_heap fell {heap_leak['start_free_heap'] - heap_leak['end_free_heap']} "
            f"bytes over {heap_leak['window_s']:.0f}s "
            f"({heap_leak['slope_bytes_per_s']:.1f} bytes/s, monotonic decline) — "
            f"device still alive, heading toward exhaustion. Missing free() likely."
        )
    elif _looks_silent(lines):
        failure = "silent-hang"
        notes.append(
            f"Output stopped and no further lines arrived before the "
            f"{silence_deadline_s:.0f}s deadline. No panic, no reset — "
            f"device is alive but wedged (or serial path died)."
        )
    else:
        failure = "clean-boot"

    return EvidenceBundle(
        failure_class=failure,
        reset_history=resets,
        reset_count=len(resets),
        panic=asdict(panic) if panic else None,
        task_wdt=task_wdt,
        abort_pc=abort_m.group(1) if abort_m else None,
        elf_sha256=sha_m.group(1) if sha_m else None,
        bug_flags_reported=flags_m.group(1) if flags_m else None,
        last_heartbeat=max(heartbeats) if heartbeats else None,
        heap_trend=heap_leak,
        serial_tail=lines[-tail_lines:],
        notes=notes,
    )


def _looks_silent(lines: list[str]) -> bool:
    """Mock-mode heuristic: a capture that ends shortly after boot with no
    steady-state output. Real mode replaces this with a wall-clock deadline
    in serial_monitor.py."""
    if len(lines) < 3:
        return True
    meaningful = [l for l in lines if l.strip()]
    # Booted, printed a handful of app lines, then nothing more.
    started = any("Calling app_main()" in l for l in meaningful)
    steady = sum(
        1 for l in meaningful
        if HEARTBEAT_RE.search(l) or re.search(r"sensor: T=", l)
    )
    return started and steady <= 1
