"""Flash layer. Stage 0: mock. Stage 1: thin wrapper over esptool.

Deliberately a wrapper, not a reimplementation — esptool already solved
flashing (see README prior-art). This module owns: retries, bootloader-strap
recovery via power-cycle, and recording the exact image SHA-256 into the run
manifest so every verdict is traceable to a binary.
"""
from __future__ import annotations
import hashlib
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
    """Stage 1: subprocess esptool with --port /dev/serial/by-id/..., retry
    once, then power-cycle + retry, then fail loudly. Never leave the board
    in an unknown state."""
    def __init__(self, port_by_id: str):
        self.port_by_id = port_by_id

    def flash(self, image):
        raise NotImplementedError("Stage 1 — needs hardware.")
