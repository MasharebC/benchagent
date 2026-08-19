"""Serial capture layer.

Two transports behind one interface, so the agent loop is identical in mock
and real mode:

  MockSerial  — replays a canned log file (Stage 0)
  RealSerial  — pyserial against /dev/serial/by-id/... (Stage 1)

Design rules (from the roadmap):
  * address ports by /dev/serial/by-id, never /dev/ttyACMn (S3 re-enumerates)
  * monotonic timestamps on every captured line
  * rolling buffer + silence deadline handled here, not in the agent
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path


def live_write(text: str) -> None:
    """Mirror a line to $BENCHAGENT_LIVE_LOG so a human can tail it.

    Opt-in and best-effort: with the variable unset -- CI, unit tests -- this
    is a no-op, and a failed write never disturbs the capture itself.
    """
    path = os.environ.get("BENCHAGENT_LIVE_LOG")
    if not path:
        return
    try:
        with open(path, "a", buffering=1) as fh:
            fh.write(text + "\n")
    except OSError:
        pass


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
    """pyserial capture against a /dev/serial/by-id path.

    Stops when any of these conditions is met (first wins):
      - window_s seconds elapsed since capture start
      - silence_s seconds pass with no new output (device wedged or done)
      - max_lines lines accumulated

    The by-id path is stable across ESP32-S3 USB re-enumerations.
    Set it up with a udev alias at bring-up (see docs/failure-modes.md).
    """

    def __init__(self, by_id_path: str, baud: int = 115200):
        self.by_id_path = by_id_path
        self.baud = baud

    def capture(self, *, window_s: float = 60.0, silence_s: float = 5.0,
                max_lines: int = 5000) -> Capture:
        import serial  # pyserial; lazy import so mock mode needs no install

        t0 = time.monotonic()
        lines: list[str] = []
        truncated = False
        last_line_mono = t0

        live_write(f"--- serial capture open: {self.by_id_path} @ {self.baud} ---")
        with serial.Serial(self.by_id_path, self.baud, timeout=1.0) as ser:
            while True:
                now = time.monotonic()

                if now - t0 >= window_s:
                    truncated = len(lines) >= max_lines
                    break

                if lines and (now - last_line_mono) >= silence_s:
                    break

                raw = ser.readline()
                if not raw:
                    continue

                line = raw.decode(errors="replace").rstrip("\r\n")
                lines.append(line)
                last_line_mono = time.monotonic()
                live_write(f"  serial| {line}")

                if len(lines) >= max_lines:
                    truncated = True
                    break

        text = "\n".join(lines)
        ended = time.monotonic()
        live_write(f"--- serial capture closed: {len(lines)} lines in "
                   f"{ended - t0:.1f}s{' (truncated)' if truncated else ''} ---")
        return Capture(
            text=text,
            lines=lines,
            started_mono=t0,
            ended_mono=ended,
            truncated=truncated,
        )
