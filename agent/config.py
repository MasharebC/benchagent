"""Model routing + run configuration.

Escalation ladder (roadmap Stage 0):
    tier 1  Sonnet  — workhorse, every run starts here
    tier 2  Opus    — escalate when tier-1 confidence < CONFIDENCE_ESCALATE
    tier 3  Fable   — break-glass only; requires --allow-break-glass

NOTE: verify current model IDs in the Anthropic Console before first real
run — these strings go stale. They are pinned here (not scattered through
code) so a benchmark run can record exactly which models produced it.
"""

from __future__ import annotations
import os
from dataclasses import dataclass

MODEL_TIERS = [
    {"tier": 1, "name": "sonnet", "model_id": "claude-sonnet-4-6"},
    {"tier": 2, "name": "opus", "model_id": "claude-opus-4-6"},
    {"tier": 3, "name": "opus-break-glass", "model_id": "claude-opus-4-6", "break_glass": True},
]

CONFIDENCE_ESCALATE = 0.7   # below this, go up one tier
MAX_TOKENS = 2000
TEMPERATURE = 0.0           # benchmark rule: sampling pinned

API_KEY_ENV = "ANTHROPIC_API_KEY"


@dataclass
class RunConfig:
    mock: bool = True
    allow_break_glass: bool = False
    force_mock_llm: bool = False   # deterministic canned LLM for offline e2e
    runs_dir: str = "runs"
    prompt_version: str = "p0.1"   # prompts fixed and versioned (roadmap §3)

    @property
    def api_key(self) -> str | None:
        return os.environ.get(API_KEY_ENV)

    @property
    def llm_available(self) -> bool:
        return bool(self.api_key) and not self.force_mock_llm
