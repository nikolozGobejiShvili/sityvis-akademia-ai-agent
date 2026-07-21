"""Engine-reach + tool-effect assertions — the Phase-3.0 anti-confound guards.

reached_engine: did the LLM engine actually run this turn, or did a deterministic
interceptor short-circuit it? A case that means to measure the model MUST assert
this, or it silently grades a template (the Phase-4 / 3.0b failure).
"""
from evals.harness import chk


def reached_engine(h) -> bool:
    return getattr(h, "engine_invocations", 0) >= 1


def chk_reached_engine(h):
    return chk("reached the LLM engine (not a canned interceptor)",
               reached_engine(h), "engine_invocations>=1",
               f"engine_invocations={getattr(h, 'engine_invocations', 0)}")


def tool_ran(h, tool_name: str) -> bool:
    """EFFECT check: the tool actually executed this turn (not merely named in the reply)."""
    return any(t == tool_name for t, _ in getattr(h, "last_tool_calls", []))


def chk_tool_ran(h, tool_name: str):
    tools = [t for t, _ in getattr(h, "last_tool_calls", [])]
    return chk(f"tool `{tool_name}` actually ran (effect, not text)",
               tool_ran(h, tool_name), f"{tool_name} in tool_calls", f"tools={tools}")
