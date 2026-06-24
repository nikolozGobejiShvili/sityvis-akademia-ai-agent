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
