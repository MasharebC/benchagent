"""Serial capture layer.

Two transports behind one interface, so the agent loop is identical in mock
and real mode:

  MockSerial  — replays a canned log file (Stage 0)
  RealSerial  — pyserial against /dev/serial/by-id/... (Stage 1; stub here)

Design rules (from the roadmap):
  * address ports by /dev/serial/by-id, never /dev/ttyACMn (S3 re-enumerates)
  * monotonic timestamps on every captured line
  * rolling buffer + silence deadline handled here, not in the agent
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Capture:
    text: str
    lines: list[str]
    started_mono: float
    ended_mono: float
    truncated: bool = False

    @property
    def duration_s(self) -> float:
        return self.ended_mono - self.started_mono


class MockSerial:
    """Replay a canned log through the same interface RealSerial will have."""

    def __init__(self, log_path: str | Path):
        self.log_path = Path(log_path)

    def capture(self, *, window_s: float = 60.0, max_lines: int = 5000) -> Capture:
        t0 = time.monotonic()
        text = self.log_path.read_text(errors="replace")
        lines = text.splitlines()
        truncated = len(lines) > max_lines
        if truncated:
            lines = lines[-max_lines:]
            text = "\n".join(lines)
        return Capture(
            text=text,
            lines=lines,
            started_mono=t0,
            ended_mono=time.monotonic(),
            truncated=truncated,
        )


class RealSerial:
    """Stage 1. pyserial against a by-id path with a rolling buffer,
    per-line monotonic timestamps, and a silence deadline. Stub for now so
    the interface is fixed before hardware arrives."""

    def __init__(self, by_id_path: str, baud: int = 115200):
        self.by_id_path = by_id_path
        self.baud = baud

    def capture(self, *, window_s: float = 60.0, max_lines: int = 5000) -> Capture:
        raise NotImplementedError(
            "RealSerial lands in Stage 1 (hardware bring-up). "
            "Run with --mock until the bench exists."
        )
