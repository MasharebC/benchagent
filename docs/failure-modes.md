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
- **2026-08-13 (bring-up, macOS host):** confirmed the by-id/udev workaround
  above is Linux-only — macOS has no /dev/serial/by-id equivalent. The
  device node name tracks which USB identity the chip is currently
  presenting, which depends on what is running on it:
    ROM download mode → 303a:4001 "Espressif Device 123456"
                        → /dev/cu.usbmodem1234561
    app running (USB-Serial-JTAG console)
                        → 303a:1001 "USB JTAG/serial debug unit" <MAC>
                        → /dev/cu.usbmodem124101
  So the node changes on any mode transition, not on a fixed rule about
  resets vs power-cycles. Implication for the bench on macOS: re-resolve
  the port by enumerating /dev/cu.usbmodem* after every flash, power-cycle,
  or mode change rather than caching a path. (An earlier version of this
  entry claimed node stability was tied to RTS-resets vs VBUS-cycles —
  that was inferred from two data points and is wrong; the USB identity
  is the actual variable.)
- **2026-08-13 (bring-up):** manual BOOT+RESET download-mode entry LATCHES
  until VBUS is cut — the chip stayed in download mode across esptool's
  post-flash hard reset and across manual RTS toggling, so the freshly
  flashed app never started and serial capture read zero bytes for 15 s
  (looks exactly like a silent-hang, but is a bench artifact, not a
  firmware fault). Fix: after any manual BOOT-button download-mode entry,
  power-cycle via UhubctlPower before expecting the app to run. Worth
  encoding in the flash→watch sequence so the bench never misclassifies
  this as a device failure.
