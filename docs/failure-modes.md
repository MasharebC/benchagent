# Bench failure modes — errata sheet

Every way the bench itself has broken, and the workaround. Errata culture is
embedded culture: this file only grows.

## Known before hardware (from research, to verify on the bench)
- **USB port churn:** ESP32-S3 re-enumerates on every reset; /dev/ttyACMn is
  unstable. Workaround: address by /dev/serial/by-id + udev alias per board.
  Status: designed in (serial_monitor.py), verify at bring-up.
- **Hub doesn't cut VBUS:** many "power-switchable" hubs only signal, don't
  cut. MEGA4 does per research — verify with a multimeter once at bring-up.
- **arm64 ninja bug:** ESP-IDF < v6.0.1 ships a broken arm64 ninja entry on
  the Pi. Workaround: pin IDF >= v6.0.1 everywhere.
- **USB-Serial-JTAG dies on sleep / USB misconfig:** recovery is hub
  power-cycle; out-of-band CP2102 on UART pins is the fallback console.
  Firmware rule: no sleep modes until an external probe exists (Stage 5).

## Encountered
- **2026-08-07 (Stage 0):** silent-hang misclassified as clean-boot: the
  steady-state heuristic matched the substring "heartbeat" in the task-name
  banner ("heartbeat_task"), not just telemetry lines. Fix: match telemetry
  patterns ("heartbeat #N", "sensor: T=") explicitly. Regression test added.
