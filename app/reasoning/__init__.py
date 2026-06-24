"""Reasoning Layer (Phase 1, 2026-06-23).

A gated, DETERMINISTIC structured intent analyzer for ambiguous PARENT turns.
It returns METADATA only (segment / topic / intent / flags / requested_action /
confidence / reason) — it NEVER generates user-facing text, NEVER calls the LLM,
NEVER has side effects, and NEVER overrides a high-confidence deterministic
handler. Behind ``settings.USE_REASONING_LAYER`` (default OFF).
"""

from app.reasoning.reasoning_layer import ReasoningAnalysis, analyze_parent_turn

__all__ = ["ReasoningAnalysis", "analyze_parent_turn"]
