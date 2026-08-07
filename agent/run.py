"""The agent loop.

Flow (identical for mock and real mode):
  1. bench captures serial              (deterministic)
  2. bench classifies → EvidenceBundle  (deterministic)
  3. agent presents bundle + tools to tier-1 model
  4. model may call tools, must end with emit_verdict
  5. confidence < threshold → escalate one tier and re-run
  6. archive everything under runs/<timestamp>/ (evidence, verdict, report)

The LLM is a passenger: it interprets and issues verdicts. It never controls
recovery, and the run ends in a known state whether or not the model behaves.
"""

from __future__ import annotations

import json
import time
import datetime as dt
from pathlib import Path

from bench.classify import classify, EvidenceBundle
from bench.serial_monitor import MockSerial
from bench.power import MockPower
from agent.config import RunConfig, MODEL_TIERS, CONFIDENCE_ESCALATE, MAX_TOKENS, TEMPERATURE
from agent.tools import TOOLS, ToolExecutor

SYSTEM_PROMPT = """You are the diagnosis component of an automated firmware test bench.
A deterministic layer has already captured serial output from an ESP32-S3 running
a FreeRTOS test-subject firmware, decoded reset reasons and panic frames, and
classified the failure. Your job is root-cause analysis: name the mechanism,
the likely code location, and a plausible fix, with a calibrated confidence.

Rules:
- Be chip-accurate. The ESP32-S3 has three watchdogs (task WDT, interrupt WDT,
  RTC WDT) and distinct reset reasons; name the right one.
- Ground every claim in the evidence bundle or tool results. If evidence is
  insufficient, say so and lower your confidence rather than guessing.
- Use read_source to check code before naming a location.
- End by calling emit_verdict exactly once. Confidence is a probability that
  your mechanism AND location are correct, not enthusiasm."""


# --------------------------------------------------------------------------
# LLM clients
# --------------------------------------------------------------------------

class AnthropicClient:
    """Minimal /v1/messages client with a tool-use loop. No SDK dependency —
    one fewer install step for a stranger reproducing the bench."""

    def __init__(self, api_key: str):
        self.api_key = api_key

    def diagnose(self, model_id: str, bundle: EvidenceBundle, executor: ToolExecutor,
                 max_rounds: int = 8) -> tuple[dict, dict]:
        import urllib.request

        messages = [{
            "role": "user",
            "content": ("Evidence bundle from the bench:\n\n```json\n"
                        + json.dumps(bundle.to_dict(), indent=2)
                        + "\n```\n\nDiagnose and emit a verdict."),
        }]
        usage_total = {"input_tokens": 0, "output_tokens": 0}

        for _ in range(max_rounds):
            body = json.dumps({
                "model": model_id,
                "max_tokens": MAX_TOKENS,
                "temperature": TEMPERATURE,
                "system": SYSTEM_PROMPT,
                "tools": TOOLS,
                "messages": messages,
            }).encode()
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=body,
                headers={
                    "content-type": "application/json",
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                },
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read())

            u = data.get("usage", {})
            usage_total["input_tokens"] += u.get("input_tokens", 0)
            usage_total["output_tokens"] += u.get("output_tokens", 0)

            tool_uses = [b for b in data.get("content", []) if b.get("type") == "tool_use"]
            verdicts = [t for t in tool_uses if t["name"] == "emit_verdict"]
            if verdicts:
                return verdicts[0]["input"], usage_total

            if not tool_uses:
                # Model answered in prose without a verdict — nudge once.
                messages.append({"role": "assistant", "content": data["content"]})
                messages.append({"role": "user",
                                 "content": "Call emit_verdict to finish."})
                continue

            messages.append({"role": "assistant", "content": data["content"]})
            results = []
            for t in tool_uses:
                fn = getattr(executor, t["name"], None)
                out = fn(**t["input"]) if fn else f"ERROR: unknown tool {t['name']}"
                results.append({"type": "tool_result",
                                "tool_use_id": t["id"], "content": str(out)})
            messages.append({"role": "user", "content": results})

        return ({"verdict": "FAIL", "failure_class": bundle.failure_class,
                 "mechanism": "Agent exceeded max tool rounds without a verdict.",
                 "confidence": 0.0}, usage_total)


class MockLLM:
    """Deterministic canned diagnoses so the e2e loop runs offline.
    Tier 1 deliberately returns low confidence on boot-loop to exercise the
    escalation path (that's the M0 finish-line requirement)."""

    CANNED = {
        "boot-loop": {
            "verdict": "FAIL",
            "failure_class": "boot-loop",
            "mechanism": ("Task watchdog (TG0 escalation) fires ~4s after the last "
                          "heartbeat; task_wdt names IDLE0 starved while sensor_task "
                          "runs on CPU 0. A busy-wait in the sensor polling path never "
                          "yields, IDLE0 can't feed the WDT, abort() → SW_CPU_RESET, "
                          "repeating every boot: WDT-driven boot loop."),
            "code_location": "main/sensor.c: polling loop in sensor_task",
            "suggested_fix": ("Replace the busy-wait with vTaskDelay()/event wait, or "
                              "feed the task WDT if the wait is genuinely required."),
        },
        "panic": {
            "verdict": "FAIL",
            "failure_class": "panic",
            "mechanism": ("Guru Meditation LoadProhibited on core 0, EXCCAUSE 0x1c, "
                          "EXCVADDR 0x20 — a load through a near-NULL pointer "
                          "(struct field offset 0x20 off a NULL base), consistent "
                          "with an off-by-one memcpy corrupting an adjacent pointer."),
            "code_location": "main/sensor.c: memcpy bounds in read path",
            "suggested_fix": "Fix the copy length to sizeof(dst); add a static_assert.",
        },
        "silent-hang": {
            "verdict": "FAIL",
            "failure_class": "silent-hang",
            "mechanism": ("Output stops after early heartbeats with no panic and no "
                          "reset — device alive but wedged. Serial evidence alone "
                          "cannot distinguish deadlock from a spinning high-prio task; "
                          "JTAG task-state inspection needed (Stage 4)."),
            "code_location": "unknown",
            "suggested_fix": "Attach debugger; inspect task states and held mutexes.",
        },
        "clean-boot": {
            "verdict": "PASS",
            "failure_class": "clean-boot",
            "mechanism": ("Single POWERON reset, app_main reached, heartbeats and "
                          "sensor reads steady, free heap flat. No fault signature."),
            "code_location": "n/a",
            "suggested_fix": "n/a",
        },
    }
    # Per-tier confidence: tier 1 is unsure about the boot loop → escalation.
    CONFIDENCE = {
        ("boot-loop", 1): 0.55, ("boot-loop", 2): 0.92,
        ("panic", 1): 0.85,
        ("silent-hang", 1): 0.45, ("silent-hang", 2): 0.5, ("silent-hang", 3): 0.5,
        ("clean-boot", 1): 0.97,
    }

    def diagnose(self, model_id: str, bundle, executor, tier: int = 1):
        base = dict(self.CANNED.get(bundle.failure_class, self.CANNED["silent-hang"]))
        base["confidence"] = self.CONFIDENCE.get(
            (bundle.failure_class, tier), 0.5)
        return base, {"input_tokens": 0, "output_tokens": 0, "mock_llm": True}


# --------------------------------------------------------------------------
# Run orchestration
# --------------------------------------------------------------------------

def run_mock(log_path: str, cfg: RunConfig) -> Path:
    t0 = time.monotonic()
    capture = MockSerial(log_path).capture()
    bundle = classify(capture.text)
    power = MockPower()
    executor = ToolExecutor(capture.text, power)

    attempts = []
    verdict = None
    for tier_info in MODEL_TIERS:
        tier = tier_info["tier"]
        if tier_info.get("break_glass") and not cfg.allow_break_glass:
            break
        if cfg.llm_available:
            client = AnthropicClient(cfg.api_key)
            v, usage = client.diagnose(tier_info["model_id"], bundle, executor)
        else:
            v, usage = MockLLM().diagnose(tier_info["model_id"], bundle, executor, tier=tier)
        attempts.append({"tier": tier, "model_id": tier_info["model_id"],
                         "confidence": v.get("confidence"), "usage": usage})
        verdict = v
        if v.get("confidence", 0) >= CONFIDENCE_ESCALATE:
            break

    wall_s = time.monotonic() - t0
    run_dir = _archive(cfg, log_path, bundle, verdict, attempts, wall_s)
    return run_dir


def _archive(cfg, log_path, bundle, verdict, attempts, wall_s) -> Path:
    ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = Path(cfg.runs_dir) / ts
    run_dir.mkdir(parents=True, exist_ok=True)

    (run_dir / "evidence.json").write_text(json.dumps(bundle.to_dict(), indent=2))
    manifest = {
        "timestamp": ts,
        "mode": "mock",
        "input_log": str(log_path),
        "prompt_version": cfg.prompt_version,
        "elf_sha256": bundle.elf_sha256,
        "escalation": attempts,
        "wall_time_s": round(wall_s, 2),
        "verdict": verdict,
    }
    (run_dir / "verdict.json").write_text(json.dumps(manifest, indent=2))
    (run_dir / "report.md").write_text(_render_report(manifest, bundle))
    return run_dir


def _render_report(m: dict, bundle: EvidenceBundle) -> str:
    v = m["verdict"]
    esc = " → ".join(
        f"tier {a['tier']} ({a['model_id']}, conf {a['confidence']})"
        for a in m["escalation"])
    resets = ", ".join(f"{r['name']}" for r in bundle.reset_history) or "none"
    lines = [
        f"# BenchAgent RCA — {m['timestamp']}",
        "",
        f"**Verdict:** {v['verdict']}   **Class:** {v['failure_class']}   "
        f"**Confidence:** {v.get('confidence')}",
        "",
        f"- Mode: {m['mode']}  ·  input: `{m['input_log']}`",
        f"- ELF SHA-256: `{m.get('elf_sha256') or 'n/a'}`  ·  "
        f"prompt {m['prompt_version']}  ·  wall {m['wall_time_s']}s",
        f"- Escalation: {esc}",
        f"- Resets observed: {resets} ({bundle.reset_count} total)",
        "",
        "## Mechanism",
        v.get("mechanism", ""),
        "",
        "## Code location",
        v.get("code_location", "unknown"),
        "",
        "## Suggested fix",
        v.get("suggested_fix", ""),
        "",
        "## Bench notes (deterministic layer)",
    ]
    lines += [f"- {n}" for n in bundle.notes] or ["- none"]
    if bundle.panic:
        p = bundle.panic
        lines += ["", "## Decoded panic frame",
                  f"- cause: {p['cause']} (EXCCAUSE {p.get('exccause')}"
                  f" = {p.get('exccause_decoded')})",
                  f"- PC {p.get('pc')}  ·  EXCVADDR {p.get('excvaddr')}",
                  f"- backtrace: {' '.join(p.get('backtrace', [])[:6])}"]
    if bundle.task_wdt:
        w = bundle.task_wdt
        starved = ", ".join(f"{s['task']}(CPU{s['cpu']})" for s in w["starved"])
        running = ", ".join(f"CPU{r['cpu']}:{r['task']}" for r in w["running_at_trigger"])
        lines += ["", "## Task watchdog detail",
                  f"- starved: {starved}", f"- running at trigger: {running}"]
    lines.append("")
    return "\n".join(lines)
