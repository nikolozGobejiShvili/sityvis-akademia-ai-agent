"""Phase 3.9 — LLM Parent Turn Analyzer.

Classifies each incoming PARENT-flow user message into a structured dict so
the Python backend can decide what to do BEFORE the scripted state machine
advances. The analyzer is advisory:

  * Backend is the brain. Analyzer only analyzes.
  * Analyzer never mutates conversation state.
  * Analyzer never books slots, saves leads, sends notifications.
  * Analyzer never accepts a phone — it may extract a candidate, but the
    backend MUST still run the existing phone parser.
  * Analyzer never chooses a calendar slot — that stays in the existing
    slot-selection logic.

On ANY failure (flag off, OpenAI exception, invalid JSON, schema mismatch,
disallowed action) ``analyze_parent_turn`` returns ``None`` — the caller
treats this as "no useful classification, continue scripted flow." This is
distinct from a low-confidence result (which IS a useful classification
that tells the backend to ask a clarifying question).

The OpenAI call routes through ``openai_service.analyze_parent_turn`` so
the analyzer module has no direct OpenAI client dependency and tests can
mock that single surface.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Mapping

from app.agent.llm.prompt_loader import load_prompt
from app.agent.services.knowledge_loader import load_knowledge
from app.config import settings
from app.models.lead import Lead
from app.services import openai_service

logger = logging.getLogger(__name__)

_MAX_TOKENS = 400
_TEMPERATURE = 0.0  # JSON output — randomness is harmful

# Closed sets — anything outside these is rejected as a bad classification.
ALLOWED_INTENTS = frozenset({
    "answer_flow_question",
    "ask_price",
    "ask_dates",
    "ask_location",
    "ask_conditions",
    "ask_registration",
    "ask_manager",
    "provide_phone",
    "choose_slot",
    "no_concern",
    "unclear",
})

ALLOWED_ACTIONS = frozenset({
    "continue_flow",
    "answer_facts",
    "offer_manager",
    "ask_phone_for_callback",
    "show_registration",
    "stay_current_state",
    "proceed_to_booking",
    "ask_clarifying_question",
})

ALLOWED_FACT_TYPES = frozenset({
    "price", "dates", "location", "conditions", "registration",
})

_FIELD_NAMES = (
    "child_age", "phone", "name",
    "challenge", "deeper_concern", "desired_change",
)

# Confidence floor below which the backend should ask a clarifying question
# instead of silently routing to the analyzer's suggested action.
LOW_CONFIDENCE_THRESHOLD = 0.65


# -- knowledge summary -----------------------------------------------------


def _format_knowledge_summary(camp: Mapping[str, Any]) -> str:
    """Compact one-block summary of camp facts so the LLM can recognise fact
    questions without us pasting the entire YAML on every turn."""
    # Camp Stream Date Filter — only summarise streams that are still
    # upcoming, so the analyzer never reasons about a started stream.
    from app.services import admin_config_service
    streams = ", ".join(
        f"{s.get('name')} {s.get('dates_text')}"
        for s in admin_config_service.get_visible_camp_streams(
            camp.get("streams") or [], year=camp.get("year"),
        )
    )
    includes = ", ".join(camp.get("includes") or [])
    return (
        f"price_gel={camp.get('price_gel')}; "
        f"location={camp.get('location')}; "
        f"duration_days={camp.get('duration_days')}; "
        f"age_range={camp.get('age_min')}-{camp.get('age_max')}; "
        f"includes={includes}; "
        f"streams={streams}; "
        f"registration_url={camp.get('registration_url')}; "
        f"phone={camp.get('phone')}"
    )


def _lead_summary(lead: Lead) -> str:
    def _f(v: str | None) -> str:
        v = (v or "").strip()
        return v if v else "(none)"
    return "\n".join([
        f"NAME: {_f(lead.name)}",
        f"CHILD_AGE: {_f(lead.child_age)}",
        f"CHALLENGE: {_f(lead.challenge)}",
        f"DEEPER_CONCERN: {_f(lead.deeper_concern)}",
        f"DESIRED_CHANGE: {_f(lead.desired_change)}",
        f"PHONE: {_f(lead.phone)}",
    ])


# -- payload assembly ------------------------------------------------------


def build_payload(
    *,
    current_state: str,
    user_message: str,
    lead: Lead,
    conversation_history: list[dict[str, str]] | None = None,
    knowledge: Mapping[str, Any] | None = None,
) -> tuple[str, str]:
    """Build (system_prompt, user_payload) without calling the LLM.

    Exposed publicly so tests can verify the payload includes the state,
    user message, lead fields, and knowledge summary without stubbing the
    OpenAI call.
    """
    system_prompt = load_prompt("parent_turn_analyzer")

    if knowledge is None:
        knowledge = load_knowledge("camp_2026")
    camp = knowledge.get("camp") or knowledge

    blocks: list[str] = []
    blocks.append(f"CURRENT_STATE:\n{current_state}")
    blocks.append(f"LATEST USER MESSAGE:\n\"{user_message}\"")
    blocks.append("LEAD FIELDS KNOWN:\n" + _lead_summary(lead))
    blocks.append(
        "AUTHORITATIVE CAMP FACTS (for recognising fact questions only):\n"
        + _format_knowledge_summary(camp)
    )

    if conversation_history:
        recent = conversation_history[-6:]
        history_text = "\n".join(
            f"{turn.get('role', '?')}: {turn.get('content', '')}"
            for turn in recent
            if isinstance(turn, Mapping)
        )
        if history_text:
            blocks.append("RECENT CONVERSATION (most recent last):\n" + history_text)

    blocks.append(
        "OUTPUT INSTRUCTION:\n"
        "Return one JSON object matching the schema in the system prompt. "
        "No prose. No markdown fences. No commentary."
    )

    user_payload = "\n\n=====================================\n\n".join(blocks)
    return system_prompt, user_payload


# -- JSON extraction + validation -----------------------------------------


_JSON_BLOCK_PATTERN = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json_blob(raw: str) -> str | None:
    """Best-effort: pull the first {...} blob out of the LLM output.

    Handles the common cases where the model wraps the JSON in markdown
    fences (```json ... ```) or precedes it with a stray sentence. Returns
    None if nothing that looks like a JSON object is present.
    """
    if not raw:
        return None
    text = raw.strip()
    # Strip a markdown fence if present.
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    match = _JSON_BLOCK_PATTERN.search(text)
    return match.group(0) if match else None


def _coerce_provided_fields(raw: Any) -> dict[str, str | None]:
    """Return a dict with all expected field keys; strings or None.

    Strings are stripped; empty strings become None. Unexpected keys are
    dropped. Non-string non-null values are coerced to ``str`` (the LLM
    sometimes returns ``8`` instead of ``"8"`` for ages).
    """
    out: dict[str, str | None] = {name: None for name in _FIELD_NAMES}
    if not isinstance(raw, Mapping):
        return out
    for name in _FIELD_NAMES:
        value = raw.get(name)
        if value is None:
            continue
        if isinstance(value, bool):
            # bool is a subclass of int — but a phone of `True` is nonsense.
            continue
        text = str(value).strip()
        if text:
            out[name] = text
    return out


def _coerce_fact_types(raw: Any) -> list[str]:
    if not isinstance(raw, (list, tuple)):
        return []
    return [
        str(item) for item in raw
        if isinstance(item, str) and item in ALLOWED_FACT_TYPES
    ]


def _coerce_confidence(raw: Any) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 0.0
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _validate_result(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    """Validate the parsed JSON against the closed-set schema.

    Returns a normalised dict on success; returns None when:
      * primary_intent is missing or not in ALLOWED_INTENTS
      * suggested_backend_action is missing or not in ALLOWED_ACTIONS
    Other fields are coerced (provided_fields, fact_types_requested,
    booleans, confidence, reason_short) — out-of-shape values are quietly
    normalised rather than rejecting the whole result, because partial
    information is still useful.
    """
    intent = payload.get("primary_intent")
    if not isinstance(intent, str) or intent not in ALLOWED_INTENTS:
        return None

    action = payload.get("suggested_backend_action")
    if not isinstance(action, str) or action not in ALLOWED_ACTIONS:
        return None

    reason = payload.get("reason_short")
    if not isinstance(reason, str):
        reason = ""
    reason = reason.strip()[:120]

    return {
        "primary_intent": intent,
        "provided_fields": _coerce_provided_fields(payload.get("provided_fields")),
        "user_wants_human": bool(payload.get("user_wants_human")),
        "user_rejects_discovery": bool(payload.get("user_rejects_discovery")),
        "fact_types_requested": _coerce_fact_types(payload.get("fact_types_requested")),
        "suggested_backend_action": action,
        "confidence": _coerce_confidence(payload.get("confidence")),
        "reason_short": reason,
    }


# -- entry point -----------------------------------------------------------


def _analyzer_enabled() -> bool:
    """Indirection so tests can monkeypatch without touching frozen Settings."""
    return bool(getattr(settings, "USE_LLM_TURN_ANALYZER", False))


def analyze_parent_turn(
    *,
    current_state: str,
    user_message: str,
    lead: Lead,
    conversation_history: list[dict[str, str]] | None = None,
    knowledge: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Classify one PARENT-flow user message.

    Returns a normalised dict matching the analyzer schema on success.
    Returns None — meaning "no useful classification, continue scripted
    flow" — when:

      * USE_LLM_TURN_ANALYZER is False
      * payload assembly fails (e.g. missing prompt or knowledge file)
      * the OpenAI call raises (network, quota, missing mock attr)
      * the LLM returns empty / non-JSON text
      * the parsed JSON is not a mapping
      * primary_intent or suggested_backend_action is missing / disallowed

    Never raises. Never advances state. Never touches lead/calendar/sheets.

    Low-confidence classifications are NOT a hard failure — they return a
    normal dict with ``confidence`` below ``LOW_CONFIDENCE_THRESHOLD``. The
    backend chooses to ask a clarifying question in that case (per spec
    rule 4). This distinguishes "analyzer can't classify" (None → scripted
    flow) from "analyzer says message is ambiguous" (dict → clarifying
    question).
    """
    if not _analyzer_enabled():
        return None

    try:
        system_prompt, user_payload = build_payload(
            current_state=current_state,
            user_message=user_message,
            lead=lead,
            conversation_history=conversation_history,
            knowledge=knowledge,
        )
    except Exception as exc:
        logger.warning(
            "[turn_analyzer] payload build failed (state=%s): %s — returning None",
            current_state, exc,
        )
        return None

    try:
        raw = openai_service.analyze_parent_turn(
            system_prompt=system_prompt,
            user_payload=user_payload,
            max_tokens=_MAX_TOKENS,
            temperature=_TEMPERATURE,
        )
    except AttributeError as exc:
        logger.warning(
            "[turn_analyzer] openai_service.analyze_parent_turn unavailable "
            "(state=%s): %s — returning None",
            current_state, exc,
        )
        return None
    except Exception as exc:
        logger.warning(
            "[turn_analyzer] OpenAI call failed (state=%s): %s — returning None",
            current_state, exc,
        )
        return None

    blob = _extract_json_blob(raw or "")
    if not blob:
        logger.warning(
            "[turn_analyzer] no JSON object in LLM output (state=%s, head=%r)",
            current_state, (raw or "")[:80],
        )
        return None

    try:
        payload = json.loads(blob)
    except json.JSONDecodeError as exc:
        logger.warning(
            "[turn_analyzer] JSON decode failed (state=%s): %s — head=%r",
            current_state, exc, blob[:120],
        )
        return None

    if not isinstance(payload, Mapping):
        logger.warning(
            "[turn_analyzer] parsed JSON is not a mapping (state=%s): %s",
            current_state, type(payload).__name__,
        )
        return None

    result = _validate_result(payload)
    if result is None:
        logger.warning(
            "[turn_analyzer] schema validation failed (state=%s): intent=%r action=%r",
            current_state,
            payload.get("primary_intent"),
            payload.get("suggested_backend_action"),
        )
        return None

    logger.info(
        "[turn_analyzer] state=%s intent=%s action=%s conf=%.2f reason=%r",
        current_state,
        result["primary_intent"],
        result["suggested_backend_action"],
        result["confidence"],
        result["reason_short"][:60],
    )
    return result


# -- Phase 2 reasoning loop — ANALYZE step (Task 2) ------------------------
#
# ``analyze_for_engine`` is a SEPARATE entrypoint from ``analyze_parent_turn``
# above. It backs the future ``USE_REASONING_PASS`` engine reasoning loop
# (analyze -> ground -> answer -> reflect) but is NOT wired into anything
# yet — Task 5 wires the caller + the flag gate. This function itself does
# not check any feature flag; the caller decides when to invoke it.
#
# Contract: produces a strict-JSON reasoning PLAN — never a user-facing
# answer, never a decided fact value (no price/date/age-range/phone/link).
# It only NAMES which fact types the eventual answer will need
# (``needed_facts``) so the backend can look them up. Returns the 7-field
# dict on success, or ``None`` on ANY failure (prompt load, OpenAI call,
# JSON parse, validation) — never raises. Pure: no lead mutation, no
# Calendar/Sheets/Redis access, no side effects.

# Closed set for `needed_facts`. NOTE: this intentionally does NOT reuse
# ALLOWED_FACT_TYPES above (which lacks "age" and "phone" and is relied on
# by the existing analyze_parent_turn / _validate_result contract) — a
# local closed set keeps the two schemas independent so a future change to
# one never silently changes the other.
_REASONING_FACT_TYPES = frozenset({
    "price", "dates", "location", "age", "registration", "conditions", "phone",
})

_REASONING_MAX_TOKENS = 300


def _reasoning_format_list(items: list[str]) -> str:
    cleaned = [str(item).strip() for item in items if str(item).strip()]
    return ", ".join(cleaned) if cleaned else "(none)"


def _build_reasoning_user_payload(
    *,
    user_message: str,
    lead: Lead,
    history: list[dict[str, str]] | None,
) -> str:
    """Mirrors ``build_payload``'s block shape: message + compact recent
    history + known lead facts. Pure string assembly, no I/O."""
    blocks: list[str] = []
    blocks.append(f"LATEST USER MESSAGE:\n\"{user_message}\"")
    blocks.append("KNOWN LEAD FACTS:\n" + _lead_summary(lead))

    if history:
        recent = history[-6:]
        history_text = "\n".join(
            f"{turn.get('role', '?')}: {turn.get('content', '')}"
            for turn in recent
            if isinstance(turn, Mapping)
        )
        if history_text:
            blocks.append("RECENT CONVERSATION (most recent last):\n" + history_text)

    blocks.append(
        "OUTPUT INSTRUCTION:\n"
        "Return one JSON object matching the schema in the system prompt. "
        "No prose. No markdown fences. No commentary."
    )
    return "\n\n=====================================\n\n".join(blocks)


def _coerce_reasoning_needed_facts(raw: Any) -> list[str]:
    if not isinstance(raw, (list, tuple)):
        return []
    return [
        str(item) for item in raw
        if isinstance(item, str) and item in _REASONING_FACT_TYPES
    ]


def _coerce_reasoning_missing_lead_fields(raw: Any) -> list[str]:
    if not isinstance(raw, (list, tuple)):
        return []
    out: list[str] = []
    for item in raw:
        if isinstance(item, str):
            text = item.strip()
            if text:
                out.append(text)
    return out


def _coerce_reasoning_suggested_tool(raw: Any, *, tool_names: list[str]) -> str | None:
    if isinstance(raw, str):
        text = raw.strip()
        if text and text in tool_names:
            return text
    return None


def _coerce_reasoning_plan(raw: Any) -> str:
    if not isinstance(raw, str):
        return ""
    return raw.strip()[:200]


def _coerce_reasoning_sentiment(raw: Any) -> str:
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return "neutral"


def _coerce_reasoning_result(
    payload: Mapping[str, Any], *, tool_names: list[str],
) -> dict[str, Any]:
    """Normalise a parsed JSON payload into the full 7-field schema.

    Unknown ``needed_facts`` entries are dropped (closed set). An
    unrecognised ``suggested_tool`` (not in ``tool_names``) becomes None.
    Missing/malformed fields fall back to safe defaults — partial
    information from the LLM is still useful, so this never rejects the
    whole result the way ``_validate_result`` does for the older schema.
    """
    return {
        "user_goal": str(payload.get("user_goal") or "").strip(),
        "sentiment": _coerce_reasoning_sentiment(payload.get("sentiment")),
        "needed_facts": _coerce_reasoning_needed_facts(payload.get("needed_facts")),
        "missing_lead_fields": _coerce_reasoning_missing_lead_fields(
            payload.get("missing_lead_fields")
        ),
        "suggested_tool": _coerce_reasoning_suggested_tool(
            payload.get("suggested_tool"), tool_names=tool_names,
        ),
        # Only a real JSON boolean counts as True — a malformed string
        # "should_greet": "false" must NOT truthy-coerce to True (review Minor).
        "should_greet": payload.get("should_greet") is True,
        "plan": _coerce_reasoning_plan(payload.get("plan")),
    }


def analyze_for_engine(
    *,
    user_message: str,
    lead: Lead,
    conversation: Any,
    knowledge_keys: list[str] | None = None,
    tool_names: list[str] | None = None,
) -> dict[str, Any] | None:
    """ANALYZE step of the Phase 2 reasoning loop — produces a strict-JSON
    reasoning plan (NOT a user-facing answer).

    Returns a dict with exactly these 7 keys on success: ``user_goal``,
    ``sentiment``, ``needed_facts``, ``missing_lead_fields``,
    ``suggested_tool``, ``should_greet``, ``plan``.

    Returns ``None`` on ANY failure — prompt load/format error, the
    OpenAI call raising, empty/non-JSON output, or a parsed result that
    isn't a JSON object. Never raises. Does not check
    ``settings.USE_REASONING_PASS`` — the caller (Task 5) is responsible
    for the flag gate. Pure: never mutates ``lead``/``conversation``,
    never touches Calendar/Sheets/Redis, never produces user-facing text.
    """
    try:
        knowledge_keys = list(knowledge_keys or [])
        tool_names = list(tool_names or [])

        system_prompt = load_prompt("parent_reasoning").format(
            knowledge_keys=_reasoning_format_list(knowledge_keys),
            tool_names=_reasoning_format_list(tool_names),
            known_facts=_lead_summary(lead),
        )

        history = getattr(conversation, "history", None)
        user_payload = _build_reasoning_user_payload(
            user_message=user_message,
            lead=lead,
            history=history,
        )

        raw = openai_service.analyze_parent_turn(
            system_prompt=system_prompt,
            user_payload=user_payload,
            max_tokens=_REASONING_MAX_TOKENS,
            temperature=_TEMPERATURE,
        )
    except Exception as exc:
        logger.warning(
            "[reasoning] analyze_for_engine setup/call failed: %s — returning None",
            exc,
        )
        return None

    try:
        blob = _extract_json_blob(raw or "")
        if not blob:
            logger.warning(
                "[reasoning] no JSON object in analyze_for_engine output "
                "(head=%r)", (raw or "")[:80],
            )
            return None

        payload = json.loads(blob)
        if not isinstance(payload, Mapping):
            logger.warning(
                "[reasoning] parsed JSON is not a mapping: %s",
                type(payload).__name__,
            )
            return None

        return _coerce_reasoning_result(payload, tool_names=tool_names)
    except Exception as exc:
        logger.warning(
            "[reasoning] analyze_for_engine parse/validate failed: %s — "
            "returning None", exc,
        )
        return None
