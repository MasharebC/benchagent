"""Tool schemas offered to the model, plus their deterministic executors.

Stage 0 set (one schema per weeknight, per the cadence):
  get_serial_tail   — more of the capture than the evidence bundle carried
  read_source       — read a file from the *bug-free* source tree
  power_cycle       — request a power cycle (bench executes it, bench owns recovery)
  emit_verdict      — the terminal tool: structured verdict ends the run

The model never gets raw shell. Every tool is a narrow, logged, deterministic
function; `emit_verdict` is how a run ends, so the loop can't wander.
"""

from __future__ import annotations
from pathlib import Path

TOOLS = [
    {
        "name": "get_serial_tail",
        "description": (
            "Return up to `lines` most recent lines of the captured serial "
            "output. Use when the evidence bundle's tail is not enough."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"lines": {"type": "integer", "minimum": 1, "maximum": 500}},
            "required": ["lines"],
        },
    },
    {
        "name": "read_source",
        "description": (
            "Read a file from the firmware source tree (the clean tree — the "
            "planted bug is enabled by a compile flag, so read the flagged "
            "sections carefully). Path is relative to firmware/testsubject/."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "power_cycle",
        "description": (
            "Request a power cycle of the device port. The bench executes the "
            "cycle and re-captures serial. Use only when evidence suggests a "
            "wedged state that a reset would clarify."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"reason": {"type": "string"}},
            "required": ["reason"],
        },
    },
    {
        "name": "emit_verdict",
        "description": "Emit the final structured verdict. This ends the run.",
        "input_schema": {
            "type": "object",
            "properties": {
                "verdict": {"type": "string", "enum": ["PASS", "FAIL"]},
                "failure_class": {
                    "type": "string",
                    "enum": ["clean-boot", "panic", "boot-loop",
                             "watchdog-reset", "brownout", "silent-hang"],
                },
                "mechanism": {
                    "type": "string",
                    "description": "One-paragraph root-cause mechanism, chip-accurate.",
                },
                "code_location": {
                    "type": "string",
                    "description": "Best-guess file:line or function, or 'unknown'.",
                },
                "suggested_fix": {"type": "string"},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
            "required": ["verdict", "failure_class", "mechanism", "confidence"],
        },
    },
]

FIRMWARE_ROOT = Path(__file__).resolve().parent.parent / "firmware" / "testsubject"


class ToolExecutor:
    """Deterministic executors. Logged by the caller; no side effects beyond
    the ones each tool documents."""

    def __init__(self, capture_text: str, power):
        self.capture_text = capture_text
        self.power = power

    def get_serial_tail(self, lines: int) -> str:
        return "\n".join(self.capture_text.splitlines()[-int(lines):])

    def read_source(self, path: str) -> str:
        p = (FIRMWARE_ROOT / path).resolve()
        if FIRMWARE_ROOT.resolve() not in p.parents and p != FIRMWARE_ROOT.resolve():
            return "ERROR: path escapes firmware tree"
        if not p.exists():
            listing = "\n".join(
                str(f.relative_to(FIRMWARE_ROOT))
                for f in sorted(FIRMWARE_ROOT.rglob("*")) if f.is_file()
            )
            return f"ERROR: not found. Available files:\n{listing}"
        return p.read_text(errors="replace")

    def power_cycle(self, reason: str) -> str:
        r = self.power.power_cycle(port=1)
        return f"power-cycled (mock={r.get('mock', False)}); reason logged: {reason}"
