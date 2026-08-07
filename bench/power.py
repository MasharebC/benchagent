"""Power control. Stage 0: mock. Stage 1: uhubctl against the UUGear MEGA4.

Rule from the roadmap: recovery is a deterministic state machine owned by the
bench. The LLM may *request* a power cycle as a tool call; it never controls
the recovery sequencing itself.
"""
from __future__ import annotations
import time


class MockPower:
    def __init__(self):
        self.cycles = 0

    def power_cycle(self, port: int = 1, off_s: float = 2.0) -> dict:
        self.cycles += 1
        return {"ok": True, "mock": True, "port": port, "off_s": off_s,
                "cycle_count": self.cycles}


class UhubctlPower:
    """Stage 1: `uhubctl -l <hub> -p <port> -a cycle -d <off_s>`.
    Verify actual VBUS cut with a multimeter once (roadmap, Stage 1 risks)."""
    def __init__(self, hub_location: str):
        self.hub_location = hub_location

    def power_cycle(self, port: int, off_s: float = 2.0):
        raise NotImplementedError("Stage 1 — needs the MEGA4.")
