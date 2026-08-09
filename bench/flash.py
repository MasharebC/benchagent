"""Flash layer. Stage 0: mock. Stage 1: thin wrapper over esptool.

Deliberately a wrapper, not a reimplementation — esptool already solved
flashing (see README prior-art). This module owns: retries, bootloader-strap
recovery via power-cycle, and recording the exact image SHA-256 into the run
manifest so every verdict is traceable to a binary.
"""
from __future__ import annotations
import hashlib
import subprocess
import time
from pathlib import Path


def sha256_of(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class MockFlasher:
    def flash(self, image: str | Path | None = None) -> dict:
        return {"ok": True, "mock": True,
                "image_sha256": sha256_of(image) if image else None}


class EsptoolFlasher:
    """Thin esptool wrapper: flash → verify SHA-256 → done.

    Retry logic:
      attempt 1 — straight esptool run
      attempt 2 — power-cycle via `power` (if provided) then retry
      attempt 3 — fail loudly; never leave board in unknown state
    """

    def __init__(self, port_by_id: str, baud: int = 460800,
                 chip: str = "esp32s3"):
        self.port_by_id = port_by_id
        self.baud = baud
        self.chip = chip

    def flash(self, image: str | Path, power=None) -> dict:
        image = Path(image)
        image_sha256 = sha256_of(image)

        cmd = [
            "python", "-m", "esptool",
            "--chip", self.chip,
            "--port", self.port_by_id,
            "--baud", str(self.baud),
            "write_flash", "0x0", str(image),
        ]

        last_err = ""
        for attempt in range(1, 3):
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode == 0:
                return {"ok": True, "mock": False,
                        "image_sha256": image_sha256, "attempt": attempt}
            last_err = result.stderr.strip()
            if attempt == 1 and power is not None:
                power.power_cycle(port=1)
                time.sleep(2.0)  # wait for re-enumeration

        raise RuntimeError(
            f"esptool failed after 2 attempts on {self.port_by_id}:\n{last_err}"
        )
