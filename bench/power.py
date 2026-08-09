"""Power control. Stage 0: mock. Stage 1: uhubctl against the UUGear MEGA4.

Rule from the roadmap: recovery is a deterministic state machine owned by the
bench. The LLM may *request* a power cycle as a tool call; it never controls
the recovery sequencing itself.
"""
from __future__ import annotations
import subprocess
import time


class MockPower:
    def __init__(self):
        self.cycles = 0

    def power_cycle(self, port: int = 1, off_s: float = 2.0) -> dict:
        self.cycles += 1
        return {"ok": True, "mock": True, "port": port, "off_s": off_s,
                "cycle_count": self.cycles}


class UhubctlPower:
    """uhubctl wrapper for per-port VBUS control on the UUGear MEGA4.

    Verify actual VBUS cut with a multimeter on first bring-up — many hubs
    only toggle a signal line, not the rail (see docs/failure-modes.md).

    hub_location: the `-l` argument from `uhubctl` output, e.g. "1-1.4"
    """

    def __init__(self, hub_location: str):
        self.hub_location = hub_location

    def power_cycle(self, port: int, off_s: float = 2.0) -> dict:
        port_s = str(port)

        subprocess.run(
            ["uhubctl", "-l", self.hub_location, "-p", port_s, "-a", "off"],
            check=True, capture_output=True, timeout=10,
        )
        time.sleep(off_s)
        subprocess.run(
            ["uhubctl", "-l", self.hub_location, "-p", port_s, "-a", "on"],
            check=True, capture_output=True, timeout=10,
        )

        return {"ok": True, "mock": False,
                "hub": self.hub_location, "port": port, "off_s": off_s}
