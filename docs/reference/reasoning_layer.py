"""
reasoning_layer.py — "analyze → ground → answer → reflect" for the PARENT engine.

This is a SCAFFOLD, not a drop-in module. Lines marked `# ── WIRE ──` call into
code you ALREADY have (parent_llm_engine, knowledge_loader, parent_tools,
parent_tool_executor, openai_service). Match the signatures to your real ones.

The single idea: give the model an explicit THINK pass that emits a structured
plan BEFORE it writes one user-facing word, then ground the answer in exactly the
knowledge that plan requires, then verify before sending.

Gate everything behind USE_REASONING_PASS and pin it OFF in tests/conftest.py
(exactly like USE_PARENT_LLM_ENGINE) so your 2753 tests keep passing untouched.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

# ── WIRE ────────────────────────────────────────────────────────────────────
# from app.services.openai_service import client                  # your OpenAI client
# from app.agent.services.knowledge_loader import load_knowledge  # cached YAML loader
# from app.agent.tools.parent_tools import PARENT_TOOL_NAMES      # 8 tool names
# from app.agent.llm.parent_llm_engine import (
#     _capture_turn_facts, _build_context_message, _build_sales_context,
#     run_parent_llm_turn as _legacy_run_parent_llm_turn,         # current behaviour
#     sanitise_response_wording,
# )
# from app.config import settings
#
# KNOWLEDGE_KEYS = ["camp_price", "camp_age_range", "camp_location", "camp_streams",
#                   "registration_url", "company_phone", "business_hours", ...]
# ─────────────────────────────────────────────────────────────────────────────


# 1. STRUCTURED PLAN ─ what the THINK pass produces. Decisions, never prose.
@dataclass
class TurnAnalysis:
    user_goal: str                                            # what they want THIS turn
    sentiment: str = "neutral"                                # price_objection|frustrated|ready_to_book|curious|declining
    needed_facts: list[str] = field(default_factory=list)     # knowledge keys required to answer
    missing_lead_fields: list[str] = field(default_factory=list)  # child_age|phone|name (only if needed next)
    contradictions: list[str] = field(default_factory=list)   # message vs known facts
    suggested_tool: str | None = None                         # get_camp_info|book_consultation|...|None
    should_greet: bool = False                                # true only on the very first assistant turn
    plan: str = ""                                            # one-line strategy for the answer

    @classmethod
    def from_json(cls, raw: str) -> "TurnAnalysis":
        d = json.loads(raw)
        return cls(
            user_goal=d.get("user_goal", ""),
            sentiment=d.get("sentiment", "neutral"),
            needed_facts=d.get("needed_facts", []),
            missing_lead_fields=d.get("missing_lead_fields", []),
            contradictions=d.get("contradictions", []),
            suggested_tool=d.get("suggested_tool") or None,
            should_greet=bool(d.get("should_greet", False)),
            plan=d.get("plan", ""),
        )


ANALYSIS_SYSTEM_PROMPT = """\
You are the planning brain of a sales agent. You do NOT talk to the user.
Given the conversation, decide — in strict JSON — what to do this turn.

Available knowledge keys: {knowledge_keys}
Available tools: {tool_names}
Known lead facts: {known_facts}

Return ONLY this JSON, nothing else:
{{
  "user_goal":            "<what the user wants this turn, one short phrase>",
  "sentiment":            "neutral|price_objection|frustrated|ready_to_book|curious|declining",
  "needed_facts":         ["<knowledge keys whose VALUES you must state to answer>"],
  "missing_lead_fields":  ["<child_age|phone|name — only what you need NEXT>"],
  "contradictions":       ["<user statement that conflicts with a known fact, if any>"],
  "suggested_tool":       "<tool name or null>",
  "should_greet":         <true ONLY if this is the very first assistant turn>,
  "plan":                 "<one sentence: how to respond>"
}}

Rules:
- needed_facts: list ONLY keys you must quote. Do not guess facts yourself.
- Never decide a price, date, age range, or link here — those come from facts later.
- If the message conflicts with a known fact, flag it instead of silently overwriting.
"""


def analyze_turn(conversation, message, *, known_facts: dict,
                 knowledge_keys: list[str], tool_names: list[str],
                 model: str = "gpt-4.1-mini") -> TurnAnalysis:
    """THINK. One cheap strict-JSON call. No user-facing text ever leaves here."""
    system = ANALYSIS_SYSTEM_PROMPT.format(
        knowledge_keys=", ".join(knowledge_keys),
        tool_names=", ".join(tool_names),
        known_facts=json.dumps(known_facts, ensure_ascii=False),
    )
    history = _recent_turns(conversation, n=6)          # keep short for cost
    resp = client.chat.completions.create(              # ── WIRE ──
        model=model,
        messages=[{"role": "system", "content": system},
                  *history,
                  {"role": "user", "content": message}],
        response_format={"type": "json_object"},        # reliable parsing
        max_tokens=300,
        temperature=0,
    )
    try:
        return TurnAnalysis.from_json(resp.choices[0].message.content)
    except (json.JSONDecodeError, KeyError):
        # Analysis must NEVER break the turn — fall through to a no-plan answer.
        return TurnAnalysis(user_goal="", plan="answer normally")


def select_knowledge(analysis: TurnAnalysis) -> dict:
    """GROUND. Load ONLY the facts the plan asked for — nothing else."""
    facts: dict = {}
    for key in analysis.needed_facts:
        value = load_knowledge(key)                     # ── WIRE ── (cached)
        if value is not None:
            facts[key] = value
    return facts


def verify_against_facts(response: str, facts: dict, analysis: TurnAnalysis) -> str:
    """REFLECT. Extends your existing url/phone/price/date regex post-check.
    If the reply asserts a number/date/link absent from the grounded facts,
    do not ship a hallucination — repair or fall back."""
    haystack = " ".join(str(v) for v in facts.values())
    for token in _extract_factual_tokens(response):     # prices, dates, URLs, age ranges
        if token not in haystack:
            log_fact_mismatch(token, analysis.plan)     # minimum: log the miss
            return _safe_fallback(analysis)             # or re-ask the model with a correction
    return response


def _plan_to_directive(analysis: TurnAnalysis, facts: dict) -> str:
    """Turn the structured plan into a short system directive for the ANSWER call.
    This is what replaces guesswork: the model is TOLD the goal, the verified
    facts, and the strategy — so it decides well the first time, which is why you
    can start retiring the mechanical sanitizers."""
    lines = [
        f"User goal: {analysis.user_goal}",
        f"Sentiment: {analysis.sentiment} — adapt tone to it.",
        f"Verified facts you may state (and ONLY these): "
        f"{json.dumps(facts, ensure_ascii=False)}",
        f"Still missing from lead: {', '.join(analysis.missing_lead_fields) or 'nothing'}",
        "Greet warmly." if analysis.should_greet else "Do NOT greet again.",
        f"Strategy: {analysis.plan}",
    ]
    if analysis.contradictions:
        lines.append("Clarify gently — contradiction: " + "; ".join(analysis.contradictions))
    return "\n".join(lines)


# 2. ORCHESTRATION ─ where the four steps slot into your existing turn.
def run_parent_llm_turn_v2(conversation, message) -> str:
    _capture_turn_facts(conversation, message)          # ── WIRE ── pre-turn capture (age, phone)
    known_facts = _known_lead_facts(conversation)

    if not settings.USE_REASONING_PASS:                 # flag-gated, OFF in tests
        return _legacy_run_parent_llm_turn(conversation, message)

    # 1. THINK
    analysis = analyze_turn(
        conversation, message,
        known_facts=known_facts,
        knowledge_keys=KNOWLEDGE_KEYS,
        tool_names=PARENT_TOOL_NAMES,
    )

    # 2. GROUND
    facts = select_knowledge(analysis)

    # 3. ANSWER — your tool loop, now steered by the plan + armed with verified facts
    answer = _run_tool_loop(                             # ── WIRE ── your existing OpenAI tool loop
        conversation, message,
        context=_build_context_message(conversation, message),
        sales_context=_build_sales_context(conversation, analysis),   # pass analysis in
        extra_system=_plan_to_directive(analysis, facts),            # inject plan + facts
    )

    # 4. REFLECT
    answer = verify_against_facts(answer, facts, analysis)
    answer = sanitise_response_wording(answer)          # KEEP — but it should shrink over time
    return answer


# ── small helpers you provide (trivial; shown for completeness) ───────────────
def _recent_turns(conversation, n=6) -> list[dict]: ...        # last n history items as messages
def _known_lead_facts(conversation) -> dict: ...               # {child_age, phone, name, ...} from lead
def _extract_factual_tokens(text: str) -> list[str]: ...       # reuse your url/phone/price/date regex
def _safe_fallback(analysis: TurnAnalysis) -> str: ...         # your existing safe template
def log_fact_mismatch(token: str, plan: str) -> None: ...      # masked log line
def _run_tool_loop(*a, **k) -> str: ...                        # your current engine loop
