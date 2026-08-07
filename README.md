# BenchAgent

An open-source, ~$200-reproducible hardware test bench that flashes firmware
onto real ESP32-S3 boards, watches how the device actually behaves — decoded
reset reasons, panic frames, watchdog forensics — and produces a PASS/FAIL
verdict with a root-cause diagnosis. Plus **FaultBench**: a public benchmark
of planted, compile-flag-gated bugs that grades how well AI models debug real
hardware.

This is firmware test/validation infrastructure first. The bench is a
deterministic state machine: flash, capture, classify, recover, archive. An
LLM rides on top as the diagnosis component — it interprets a structured
evidence bundle and issues verdicts. It never drives recovery, and every run
ends in a known state. The LLM is treated as a component under test: the
benchmark publishes false positives, false negatives, confusion matrices, and
a gallery of confident-but-wrong diagnoses alongside the wins.

## Status: Stage 0 (mock loop, pre-hardware)

```
./benchagent run --mock fixtures/logs/bootloop.log --mock-llm
```

produces, offline and deterministically:

> **FAIL / boot-loop** — task watchdog (TG0 escalation) fires ~4s after the
> last heartbeat; task_wdt names IDLE0 starved while sensor_task runs on
> CPU 0; busy-wait never yields; abort() → SW_CPU_RESET, repeating.

with model escalation (tier 1 low confidence → tier 2), an archived evidence
bundle, and a Markdown RCA report under `runs/`. Drop an `ANTHROPIC_API_KEY`
in the environment and remove `--mock-llm` for real diagnosis.

## Prior art (read this before assuming novelty)

This project claims to be the open **reference implementation** of the
flash-observe-diagnose loop and the only **public planted-bug hardware
benchmark** — not the first mover. Commercial and adjacent work:

- **BootLoop** (YC S25, closed-source) — commercial autonomous firmware
  diagnosis; shipped June 2026.
- **Embedder** (YC S25, closed-source) — commercial embedded AI tooling.
- **agentic-hil** — agent-driven HIL, ARM-focused.
- **esparagus** — ESP hardware-in-the-loop rigs.
- **labgrid / Jumpstarter** — mature lab/board orchestration frameworks.
- **Espressif's ESP-IDF MCP server** — first-party tool access for models.
- **pytest-embedded** — Espressif's embedded test plugin (planned
  integration target, Stage 5).

Built on, not rebuilt: `esptool` (flashing is a solved problem),
`esp-idf-monitor`/`pyserial` (capture), `esp-idf-panic-decoder` (panic
parse), `espcoredump` (core dumps), `uhubctl` + UUGear MEGA4 (per-port VBUS
control), `openocd-esp32` + GDB (Stage 4). One honest reason each: they work,
they're maintained, and rebuilding plumbing reads junior.

## Architecture

```
bench/     deterministic layer — flash, serial capture, power, classify.
           Pure-function classifier: reset-reason decode, panic-frame parse
           (EXCCAUSE/EXCVADDR), task-WDT forensics, boot-loop & silence
           detection. Unit-tested, no LLM anywhere.
agent/     the passenger — evidence bundle in, verdict out. Model routing:
           Sonnet workhorse → Opus below 0.7 confidence → Fable break-glass
           (off by default). Tools are narrow and logged: serial tail,
           source read, power-cycle request, emit_verdict.
firmware/  the test subject — real ESP-IDF/FreeRTOS work: ISR→queue→task
           pipeline, register-level BME280 driver written from the
           datasheet (no libraries), explicit stack sizing, deliberate
           task-WDT subscription. Builds -Wall -Wextra -Werror.
           Planted bugs are compile-flag gated: ground truth is falsifiable
           by anyone with ~$200 of hardware.
evals/     FaultBench harness + bugs.yaml registry (chip-accurate signature
           per bug: which watchdog, which reset reason, which EXCCAUSE).
runs/      every run archived: evidence.json, verdict.json (with ELF
           SHA-256, prompt version, model IDs, token/time cost), report.md.
           Any verdict can be re-derived later.
```

## Milestones

- **M0 (here):** mock loop end-to-end with correct escalation. ✅
- **M1:** real closed loop on ESP32-S3 — one command: flash → watch →
  power-cycle → verdict, three planted bugs diagnosed unassisted.
- **M2:** FaultBench — 8–10 bugs, eval harness, `BENCHMARK.md` with
  per-bug confusion matrix, ablations, and a failure gallery.
- **M3:** `benchagent bisect` — git-bisect × flash × LLM verdict on real
  hardware, overnight and unattended.
- **M4:** JTAG/GDB depth — silent-failure diagnosis, serial-vs-JTAG delta.
- **M5:** second architecture (STM32, CFSR/HFSR/BFAR decode) + first
  outside user.

## Reproducing

Stage 0 needs only Python 3.11+ and pytest:

```
python -m pytest tests/ -q
./benchagent run --mock fixtures/logs/panic.log --mock-llm
```

Hardware BOM (~$200–230) and full bring-up docs land with Stage 1. Software
pins: ESP-IDF ≥ v6.0.1, openocd-esp32 ≥ 2026-07 release.

## License

MIT.
