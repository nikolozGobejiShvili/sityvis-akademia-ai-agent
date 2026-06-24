"""Phase 3.8 — LLM reply composer for PARENT discovery states.

Rewrites a fixed YAML template into a natural, context-aware Georgian reply
using the existing SYSTEM_PROMPT_BASE + SYSTEM_PROMPT_PARENT prompts and the
authoritative camp_2026.yaml knowledge file.

DESIGN CONTRACT — what this module is, and is not:

  * Backend is the brain. The composer is only the writer.
  * Before calling compose_parent_reply, the caller (parent_flow.py state
    handler) MUST have:
      1. stored the relevant lead field
      2. set conversation.state to the next state
      3. decided next_action
    The composer does not look at, change, or care about state machine state.
  * The composer never decides booking, never saves leads, never sends
    notifications, never parses phone numbers, never reads or writes
    calendar slots.
  * On ANY failure (feature flag off, OpenAI exception, empty output,
    hallucinated fact detected by post-check), the composer returns
    ``fallback_template`` verbatim. The flow continues normally.
  * The OpenAI call routes through ``openai_service.compose_reply`` so the
    existing test_agent.py mock pattern intercepts it.

OUTSIDE THIS PHASE'S SCOPE:
  * Composer is NOT applied to operational states (ASK_NAME, ASK_PHONE,
    OFFER_BOOKING, BOOKING_CONFIRMED, DONE). Phone parsing, slot picking,
    and booking confirmation stay byte-exact for now.
  * Composer does not solve factual interruptions ("რა თარიღია?",
    "ფასი?"). That is Phase 3.9.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Mapping

from app.agent.llm.prompt_loader import load_prompt
from app.agent.services.knowledge_loader import load_knowledge
from app.config import settings
from app.models.lead import Lead
from app.services import openai_service

logger = logging.getLogger(__name__)

# Maximum response tokens — discovery questions are short.
_MAX_TOKENS = 350
_TEMPERATURE = 0.7


# -- Fact-safety post-check ------------------------------------------------
#
# For the discovery states composed in Phase 3.8 (welcome / ask_challenge /
# ask_deeper / ask_desire) the LLM should NEVER produce a price, date, URL,
# or phone — those states are open questions about the child. Any token
# matching one of the patterns below means the LLM hallucinated a fact;
# discard and use fallback_template. This is the "minimum acceptable"
# post-check from the Phase 3.8 spec (item 7). Future phases that DO need
# the LLM to phrase facts (PRESENT_VALUE, PRICE) will need a per-state
# allow-list keyed off knowledge_facts; not in scope here.

_URL_PATTERN = re.compile(
    r"https?://\S+|\btinyurl\.com/\S+|\bbit\.ly/\S+|www\.\S+",
    re.IGNORECASE,
)

# Georgian phone shape (3-2-2-2 with separators, or +995 prefix)
_PHONE_PATTERN = re.compile(
    r"\+?995[\s-]?\d{3}|\b\d{3}[\s-]\d{2}[\s-]\d{2}[\s-]\d{2}\b",
)

# A 3-5 digit number immediately followed by a Lari token. Catches
# "2150 ლარი", "3000 GEL", "2200 ლ".
_PRICE_PATTERN = re.compile(
    r"\b\d{3,5}\s*(?:ლარი|gel|ლ\.|ლ)\b",
    re.IGNORECASE,
)

# Stem-based Georgian month names. Match "23-29 ივნისი", "5 ივლისს", etc.
_KA_MONTH_STEMS = (
    "იანვ", "თებერვ", "მარტ", "აპრილ", "მაის", "ივნის",
    "ივლის", "აგვისტ", "სექტ", "ოქტო", "ნოემ", "დეკემ",
)
_DATE_RANGE_PATTERN = re.compile(
    r"\d{1,2}\s*[-–—]\s*\d{1,2}\s+(?:" + "|".join(_KA_MONTH_STEMS) + r")\w*",
    re.IGNORECASE,
)
_SINGLE_DATE_PATTERN = re.compile(
    r"\b\d{1,2}\s+(?:" + "|".join(_KA_MONTH_STEMS) + r")\w*",
    re.IGNORECASE,
)


def _detect_hallucinated_fact(text: str) -> str | None:
    """Return a short reason string if ``text`` contains a forbidden fact
    pattern, else None.

    Used only for Phase 3.8 discovery states. These states must not mention
    price, dates, URLs, or phone numbers — they are open questions. Any
    match → caller discards LLM output and uses fallback_template.
    """
    if not text:
        return None
    if _URL_PATTERN.search(text):
        return "URL"
    if _PHONE_PATTERN.search(text):
        return "phone"
    if _PRICE_PATTERN.search(text):
        return "price"
    if _DATE_RANGE_PATTERN.search(text) or _SINGLE_DATE_PATTERN.search(text):
        return "date"
    return None


# -- Knowledge injection ---------------------------------------------------


def _format_knowledge_block(camp: Mapping[str, Any]) -> str:
    """Render the authoritative camp facts as a flat block for the LLM."""
    lines = [
        f"price_gel: {camp.get('price_gel')}",
        f"location: {camp.get('location')}",
        f"duration_days: {camp.get('duration_days')}",
        f"age_min: {camp.get('age_min')}",
        f"age_max: {camp.get('age_max')}",
        f"includes: {', '.join(camp.get('includes') or [])}",
        "streams:",
    ]
    # Camp Stream Date Filter — only inject streams that are still upcoming;
    # a stream whose start date has arrived is dropped so the LLM cannot
    # quote it back to the user.
    from app.services import admin_config_service
    for stream in admin_config_service.get_visible_camp_streams(
        camp.get("streams") or [], year=camp.get("year"),
    ):
        lines.append(f"  - {stream.get('name')}: {stream.get('dates_text')}")
    lines.append("discounts:")
    for d in camp.get("discounts") or []:
        lines.append(f"  - {d.get('name')}: {d.get('percent')}%")
    payment = camp.get("payment") or {}
    lines.append(
        f"payment: {payment.get('installments_months')} months "
        f"(banks: {', '.join(payment.get('banks') or [])})"
    )
    lines.append(f"registration_url: {camp.get('registration_url')}")
    lines.append(f"phone: {camp.get('phone')}")
    lines.append(f"focus_areas: {', '.join(camp.get('focus_areas') or [])}")
    return "\n".join(lines)


def _lead_field(value: str | None, fallback: str) -> str:
    text = (value or "").strip()
    return text if text else fallback


def build_payload(
    *,
    state: str,
    user_message: str,
    lead: Lead,
    fallback_template: str,
    next_action: str,
    knowledge: Mapping[str, Any] | None = None,
    conversation_history: list[dict[str, str]] | None = None,
    required_facts: list[str] | None = None,
    must_include: list[str] | None = None,
    must_not: list[str] | None = None,
) -> tuple[str, str]:
    """Build (system_prompt, user_payload) without calling the LLM.

    Exposed publicly so tests can verify the payload contains the right
    facts/lead fields/rules without needing to stub the OpenAI call.
    """
    company_name = getattr(settings, "COMPANY_NAME", "") or "სიტყვის აკადემია"
    base = load_prompt("system_base").format(company_name=company_name)
    system_prompt = f"{base}\n\n{load_prompt('system_parent')}"

    if knowledge is None:
        knowledge = load_knowledge("camp_2026")
    camp = knowledge.get("camp") or knowledge

    name_known = bool((lead.name or "").strip())

    # Order matters here: hard rules first, then context, then anchor. The
    # LLM tends to obey instructions it sees early and remembers the tone
    # anchor it sees just before being asked to write.
    blocks: list[str] = []

    blocks.append(
        "ROLE\n"
        "You only write the customer-facing reply text. You are NOT the brain.\n"
        "Backend already decided the next state, what to store, and whether to book."
    )

    hard_rules = [
        "1. You cannot change conversation state.",
        "2. You cannot decide booking.",
        "3. You cannot save leads.",
        "4. You cannot send notifications.",
        "5. You cannot parse phone numbers.",
        "6. You cannot invent facts.",
        "7. Use ONLY the AUTHORITATIVE CAMP FACTS block below. If a needed "
        "fact is missing, say \"გუნდი ზუსტად დაგიდასტურებთ\".",
        "8. Follow NEXT_ACTION exactly.",
        "9. Reply in natural, warm, concise Georgian. 1–3 short paragraphs.",
        "10. Do not start with \"გამარჯობა\" unless CURRENT_STATE indicates "
        "this is the very first turn.",
    ]
    if name_known:
        hard_rules.append(
            "11. NAME is already known from the Meta profile — DO NOT ask "
            "for the user's name."
        )
    hard_rules.extend([
        "12. Do not mention calendar slots, dates, price, registration URL, "
        "or phone numbers unless they appear in MUST INCLUDE below.",
        "13. Do not output JSON, labels, analysis, or explanations.",
        "14. Output ONLY the final customer-facing message — no preamble, "
        "no quotes around the message.",
    ])
    blocks.append("HARD RULES — never break:\n" + "\n".join(hard_rules))

    blocks.append(f"CURRENT_STATE:\n{state}")

    blocks.append(f"LATEST USER MESSAGE:\n\"{user_message}\"")

    lead_block = "\n".join([
        f"NAME: {_lead_field(lead.name, '(unknown — backend will not ask you to ask)')}",
        f"CHILD_AGE: {_lead_field(lead.child_age, '(not yet collected)')}",
        f"CHALLENGE: {_lead_field(lead.challenge, '(not yet collected)')}",
        f"DEEPER_CONCERN: {_lead_field(lead.deeper_concern, '(not yet collected)')}",
        f"DESIRED_CHANGE: {_lead_field(lead.desired_change, '(not yet collected)')}",
        f"PHONE: {_lead_field(lead.phone, '(not yet collected)')}",
    ])
    blocks.append("LEAD FIELDS KNOWN:\n" + lead_block)

    blocks.append(
        "AUTHORITATIVE CAMP FACTS (use ONLY these — do not invent):\n"
        + _format_knowledge_block(camp)
    )

    blocks.append(f"NEXT_ACTION (you must execute this in your reply):\n{next_action}")

    if required_facts:
        blocks.append(
            "REQUIRED FACTS (mention these verbatim if relevant):\n"
            + "\n".join(f"- {fact}" for fact in required_facts)
        )

    if must_include:
        blocks.append(
            "MUST INCLUDE:\n" + "\n".join(f"- {item}" for item in must_include)
        )

    must_not_lines = [
        "- Do not mention price, calendar slots, registration URL, phone "
        "numbers, or specific dates unless they appear in MUST INCLUDE.",
    ]
    if must_not:
        must_not_lines.extend(f"- {item}" for item in must_not)
    blocks.append("MUST NOT:\n" + "\n".join(must_not_lines))

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
        "TONE/STYLE ANCHOR (rewrite this naturally — do NOT copy verbatim):\n"
        + fallback_template
    )

    blocks.append(
        "OUTPUT INSTRUCTION:\n"
        "Now write the customer-facing reply in Georgian. 1–3 short paragraphs. "
        "Output ONLY the message text."
    )

    user_payload = "\n\n=====================================\n\n".join(blocks)
    return system_prompt, user_payload


# -- Public entry point ----------------------------------------------------


def _composer_enabled() -> bool:
    """Indirection so tests can monkeypatch without touching frozen Settings."""
    return bool(getattr(settings, "USE_LLM_COMPOSER", False))


def compose_parent_reply(
    *,
    state: str,
    user_message: str,
    lead: Lead,
    fallback_template: str,
    next_action: str,
    knowledge: Mapping[str, Any] | None = None,
    conversation_history: list[dict[str, str]] | None = None,
    required_facts: list[str] | None = None,
    must_include: list[str] | None = None,
    must_not: list[str] | None = None,
) -> str:
    """Compose a natural Georgian reply for a PARENT discovery state.

    Returns ``fallback_template`` (unchanged) whenever:
      * USE_LLM_COMPOSER is False
      * the OpenAI call raises (network, quota, missing mock attr, anything)
      * the LLM returns an empty or whitespace-only string
      * the LLM output trips the fact-safety post-check (URL/phone/price/date)

    Never raises. Never advances state. Never touches the lead/calendar/sheets.
    """
    if not _composer_enabled():
        return fallback_template

    try:
        system_prompt, user_payload = build_payload(
            state=state,
            user_message=user_message,
            lead=lead,
            fallback_template=fallback_template,
            next_action=next_action,
            knowledge=knowledge,
            conversation_history=conversation_history,
            required_facts=required_facts,
            must_include=must_include,
            must_not=must_not,
        )
    except Exception as exc:  # knowledge load failure, prompt load failure, etc.
        logger.warning(
            "[reply_composer] payload build failed (state=%s): %s — using fallback",
            state, exc,
        )
        return fallback_template

    try:
        raw = openai_service.compose_reply(
            system_prompt=system_prompt,
            user_payload=user_payload,
            max_tokens=_MAX_TOKENS,
            temperature=_TEMPERATURE,
        )
    except AttributeError as exc:
        # The openai_service module may be replaced by a test mock that
        # doesn't expose compose_reply — fall back silently.
        logger.warning(
            "[reply_composer] openai_service.compose_reply unavailable "
            "(state=%s): %s — using fallback", state, exc,
        )
        return fallback_template
    except Exception as exc:
        logger.warning(
            "[reply_composer] OpenAI call failed (state=%s): %s — using fallback",
            state, exc,
        )
        return fallback_template

    reply = (raw or "").strip()
    if not reply:
        logger.warning(
            "[reply_composer] LLM returned empty text (state=%s) — using fallback",
            state,
        )
        return fallback_template

    violation = _detect_hallucinated_fact(reply)
    if violation:
        logger.warning(
            "[reply_composer] fact-safety violation (%s) in LLM reply "
            "(state=%s) — discarding and using fallback. reply head=%r",
            violation, state, reply[:80],
        )
        return fallback_template

    logger.info(
        "[reply_composer] LLM reply accepted (state=%s, len=%d)",
        state, len(reply),
    )
    return reply


# =========================================================================
# P2 — post-booking response composer
# =========================================================================
#
# After a successful booking (conversation.state == "DONE") the user
# keeps talking — thanks, identity questions, "did I book correctly?",
# factual questions, etc. The state machine has nothing left to advance
# (booking is the terminal event), so we need a small, context-aware
# generator that produces natural Georgian for each event class without:
#
#   * inventing facts not in `allowed_facts`,
#   * confirming a NEW booking,
#   * triggering Calendar / Sheets / notification writes,
#   * repeating the previous assistant message verbatim,
#   * shipping robotic menu phrasing.
#
# Backend classifies the event (parent_flow._classify_done_event), then
# calls `compose_post_booking_response(event=…)`. Composer is the writer.

# Supported event labels — closed set. Anything outside this set
# short-circuits to the fallback.
SUPPORTED_POST_BOOKING_EVENTS: frozenset[str] = frozenset({
    "gratitude_after_booking",
    "repeated_gratitude",
    "identity_question",
    "name_question",
    "booking_status_question",
    "factual_question",
    "other_after_booking",
})


# Forbidden booking-confirmation stems — must NOT appear unless
# `calendar_success=True` is asserted by the caller. Kept here so the
# composer's safety validator does not need to import from
# `parent_turn_router` (and risk a circular import).
_FAKE_BOOKING_STEMS: tuple[str, ...] = (
    "დაგაჯავშნე",
    "დაჯავშნილია",
    "ჩაწერილი ხართ",
    "ჩაგწერეთ",
    "ჩავწერეთ",
    "დადასტურდა ჯავშანი",
    "ჯავშანი დადასტურდა",
)


# Forbidden robotic / menu phrases (PART 8 style guide).
_ROBOTIC_PHRASES: tuple[str, ...] = (
    "გნებავთ a თუ b",
    "გნებავთ A თუ B",
    "აირჩიეთ",
    "როგორ შემიძლია",
)


# Per-event minimal Georgian fallbacks. Used when the LLM is disabled,
# fails, returns empty text, or trips the safety validator. Phrasing is
# kept deliberately plain so it cannot accidentally repeat the booking
# confirmation template (which is what the DONE state previously did).
_POST_BOOKING_FALLBACKS: dict[str, str] = {
    "gratitude_after_booking": (
        "მადლობა თქვენ. კონსულტანტი მალე დაგიკავშირდებათ მოწერილ დროზე."
    ),
    "repeated_gratitude": (
        "მოხარული ვართ. თუ კიდევ რამე გჭირდებათ — გვითხარით."
    ),
    "identity_question": (
        "მე სიტყვის აკადემიის ონლაინ ასისტენტი ვარ. "
        "შემიძლია ბანაკზე გიპასუხოთ ან მენეჯერი დაგაკავშიროთ."
    ),
    "name_question": (
        "მე სიტყვის აკადემიის ონლაინ ასისტენტი ვარ. "
        "სახელი ცალკე არ მაქვს — შემიძლია დაგეხმაროთ რასაც გჭირდებათ."
    ),
    "booking_status_question": (
        "კი, კონსულტაცია უკვე დაჯავშნილია — კონსულტანტი დაგიკავშირდებათ "
        "მოწერილ დროზე."
    ),
    "factual_question": (
        "თუ რამე კონკრეტული გჭირდებათ ბანაკზე — გვითხარით და გაგიზიარებთ."
    ),
    "other_after_booking": (
        "თუ კიდევ რამე გჭირდებათ ბანაკზე ან კონსულტაციაზე — გვითხარით."
    ),
}


def _post_booking_system_prompt() -> str:
    """System prompt for the post-booking composer.

    Short and structural — the bulk of the per-turn context goes in the
    user payload (`_build_post_booking_payload`). Keeping the system
    prompt small avoids burning prompt-cache space when the composer
    fires many times in a row (multi-turn DONE conversations).
    """
    return (
        "You write a single short Georgian reply for a parent who has "
        "ALREADY successfully booked a consultation. Backend has decided "
        "the event class. You only write wording.\n"
        "\n"
        "HARD RULES:\n"
        "1. Georgian only. Natural, grammatically correct.\n"
        "2. 1–3 sentences. Maximum 1 emoji and only if natural.\n"
        "3. NEVER confirm a new booking, never say "
        "\"დაგაჯავშნეთ\" / \"დაჯავშნილია\" / \"ჩაწერილი ხართ\" / "
        "\"ჩაგწერეთ\" / \"დადასტურდა ჯავშანი\" — the booking already "
        "exists and you are NOT the one confirming it.\n"
        "4. Do NOT invent facts. Use only the values inside "
        "ALLOWED_FACTS in the user payload.\n"
        "5. Do NOT repeat the user's previous assistant messages "
        "verbatim — see PREVIOUS_ASSISTANT below.\n"
        "6. Do NOT use menu phrases: \"გნებავთ A თუ B?\", \"აირჩიეთ\", "
        "\"როგორ შემიძლია დაგეხმაროთ\".\n"
        "7. Follow REQUIRED_NEXT_STEP exactly.\n"
        "8. Output ONLY the message text. No JSON, no labels, no quotes.\n"
    )


# Per-event REQUIRED_NEXT_STEP — short, written like a co-worker brief
# rather than a system prompt. Tells the LLM what to actually do, in
# Georgian-aware terms.
_NEXT_STEP_BY_EVENT: dict[str, str] = {
    "gratitude_after_booking": (
        "Thank the parent warmly in one short sentence. Mention briefly "
        "that the consultant will reach out at the booked time. Do not "
        "list facts."
    ),
    "repeated_gratitude": (
        "Parent has thanked us a second time. Acknowledge politely, in "
        "a DIFFERENT phrasing from the previous assistant message. Offer "
        "to help with any further question."
    ),
    "identity_question": (
        "Briefly introduce yourself as the სიტყვის აკადემიის ონლაინ "
        "ასისტენტი (online assistant). One short line."
    ),
    "name_question": (
        "Briefly say you are the სიტყვის აკადემიის ონლაინ ასისტენტი — "
        "you do not have a personal name. Offer help."
    ),
    "booking_status_question": (
        "Confirm that the existing consultation is ALREADY booked — "
        "without saying \"დაგაჯავშნე\". Mention the booked time only "
        "if it appears in ALLOWED_FACTS. Reassure the parent that the "
        "consultant will reach out at that time."
    ),
    "factual_question": (
        "Answer the parent's factual question briefly using values from "
        "ALLOWED_FACTS only. Do not confirm a new booking. Keep it short."
    ),
    "other_after_booking": (
        "Acknowledge briefly and offer help with anything else the "
        "parent might need. Do not reset the conversation."
    ),
}


def _build_post_booking_payload(
    *,
    event: str,
    user_message: str,
    lead: Lead,
    conversation_history: list[dict[str, str]] | None,
    allowed_facts: Mapping[str, Any] | None,
    previous_assistant_messages: list[str] | None,
) -> str:
    """Assemble the user-payload string sent to the LLM.

    The payload is intentionally compact: backend-decided event + just
    enough lead/history/facts context for the model to produce a
    grammatical, non-repetitive reply. Notably we do NOT inject the
    entire task brief — premium tone guidance lives in the system
    prompt.
    """
    name_known = bool((lead.name or "").strip())
    facts_block_lines: list[str] = []
    if allowed_facts:
        for key, value in allowed_facts.items():
            if value is None or value == "":
                continue
            facts_block_lines.append(f"{key}: {value}")
    facts_block = "\n".join(facts_block_lines) if facts_block_lines else "(none)"

    history_block = ""
    if conversation_history:
        recent = conversation_history[-6:]
        history_lines: list[str] = []
        for turn in recent:
            if isinstance(turn, Mapping):
                role = turn.get("role", "?")
                content = (turn.get("content") or "")[:200]
                history_lines.append(f"{role}: {content}")
        history_block = "\n".join(history_lines)

    prev_block = ""
    if previous_assistant_messages:
        prev_block = "\n---\n".join(
            (msg or "")[:200] for msg in previous_assistant_messages[-3:]
        )

    next_step = _NEXT_STEP_BY_EVENT.get(event, _NEXT_STEP_BY_EVENT["other_after_booking"])
    name_rule = ""
    if name_known:
        name_rule = (
            f"\nThe parent's first name is known ({lead.name}). You may "
            "address them by name, but do not over-use it."
        )

    blocks: list[str] = [
        f"EVENT: {event}",
        f"LATEST_USER_MESSAGE:\n\"{user_message}\"",
        f"REQUIRED_NEXT_STEP:\n{next_step}{name_rule}",
        f"ALLOWED_FACTS (use ONLY these, verbatim if relevant):\n{facts_block}",
    ]
    if history_block:
        blocks.append(f"RECENT_HISTORY (oldest first):\n{history_block}")
    if prev_block:
        blocks.append(
            "PREVIOUS_ASSISTANT (do NOT repeat verbatim):\n" + prev_block
        )
    blocks.append(
        "OUTPUT_INSTRUCTION:\n"
        "Now write the reply in Georgian. 1–3 sentences. Output ONLY the "
        "message text."
    )
    return "\n\n=====================================\n\n".join(blocks)


def _validate_composed_response(
    response: str,
    context: Mapping[str, Any],
    previous_assistant_messages: list[str],
) -> bool:
    """Safety net for post-booking composer output.

    Returns True if the response is safe to ship, False otherwise.
    Checks (PART 8):

      1. No fake-booking confirmation if `calendar_success` is False.
      2. No exact repetition vs the last 3 assistant messages.
      3. No forbidden robotic / menu phrases.
      4. Length ≤ 600 chars.
      5. For NON-factual events, no hallucinated URL/phone/price/date
         tokens. (Factual events legitimately ship facts from the
         knowledge YAML, so we skip the fact scan for those.)

    The validator is called by ``compose_post_booking_response``; a
    False return triggers the per-event fallback.
    """
    if not response:
        return False

    text = response
    lowered = text.lower()

    # 1. fake booking confirmation
    if not context.get("calendar_success"):
        for stem in _FAKE_BOOKING_STEMS:
            if stem in text:
                logger.warning(
                    "[post_booking] reject: fake-booking stem %r without "
                    "calendar_success", stem,
                )
                return False

    # 2. exact repetition
    stripped = text.strip()
    for prev in (previous_assistant_messages or [])[-3:]:
        if (prev or "").strip() == stripped:
            logger.warning("[post_booking] reject: exact repetition of previous reply")
            return False

    # 3. robotic phrases
    for robotic in _ROBOTIC_PHRASES:
        if robotic in lowered:
            logger.warning("[post_booking] reject: robotic phrase %r", robotic)
            return False

    # 4. length
    if len(text) > 600:
        logger.warning("[post_booking] reject: too long (%d chars)", len(text))
        return False

    # 5. hallucinated facts — skip for factual_question (knowledge-driven)
    if context.get("event") != "factual_question":
        violation = _detect_hallucinated_fact(text)
        if violation:
            logger.warning("[post_booking] reject: hallucinated fact (%s)", violation)
            return False

    return True


def post_booking_fallback(event: str) -> str:
    """Public helper — minimal safe fallback for a given event class.

    Used by ``compose_post_booking_response`` internally and by
    ``parent_flow._classify_done_event`` as the default reply when the
    composer is disabled or unavailable. Public so tests and other
    callers can reference the same string set.
    """
    return _POST_BOOKING_FALLBACKS.get(
        event, _POST_BOOKING_FALLBACKS["other_after_booking"],
    )


_POST_BOOKING_MAX_TOKENS = 220
_POST_BOOKING_TEMPERATURE = 0.6


def compose_post_booking_response(
    *,
    event: str,
    user_message: str,
    lead: Lead,
    conversation_history: list[dict[str, str]] | None = None,
    fallback: str | None = None,
    allowed_facts: Mapping[str, Any] | None = None,
    previous_assistant_messages: list[str] | None = None,
    calendar_success: bool = True,
) -> str:
    """Compose a single post-booking reply.

    Backend has classified ``event`` already (the closed set above) and
    decided that no Calendar / Sheets / notification side-effects are
    appropriate. This function only writes wording.

    Failure modes — ALL return ``fallback`` (or the per-event default
    fallback if ``fallback`` is None):

      * USE_LLM_COMPOSER is False
      * ``event`` not in SUPPORTED_POST_BOOKING_EVENTS
      * payload build raises
      * the OpenAI call raises (network / quota / missing mock)
      * the LLM returns empty / whitespace-only text
      * the LLM output trips `_validate_composed_response`

    Never raises. Never advances state. Never touches lead/calendar/sheets.
    """
    chosen_fallback = fallback if fallback is not None else post_booking_fallback(event)

    if event not in SUPPORTED_POST_BOOKING_EVENTS:
        logger.warning("[post_booking] unsupported event %r — using fallback", event)
        return chosen_fallback

    if not _composer_enabled():
        return chosen_fallback

    try:
        system_prompt = _post_booking_system_prompt()
        user_payload = _build_post_booking_payload(
            event=event,
            user_message=user_message,
            lead=lead,
            conversation_history=conversation_history,
            allowed_facts=allowed_facts,
            previous_assistant_messages=previous_assistant_messages,
        )
    except Exception as exc:
        logger.warning(
            "[post_booking] payload build failed (event=%s): %s — fallback",
            event, exc,
        )
        return chosen_fallback

    try:
        raw = openai_service.compose_reply(
            system_prompt=system_prompt,
            user_payload=user_payload,
            max_tokens=_POST_BOOKING_MAX_TOKENS,
            temperature=_POST_BOOKING_TEMPERATURE,
        )
    except AttributeError as exc:
        # Test mocks may not expose compose_reply.
        logger.warning(
            "[post_booking] openai_service.compose_reply unavailable "
            "(event=%s): %s — fallback", event, exc,
        )
        return chosen_fallback
    except Exception as exc:
        logger.warning(
            "[post_booking] OpenAI call failed (event=%s): %s — fallback",
            event, exc,
        )
        return chosen_fallback

    reply = (raw or "").strip()
    if not reply:
        return chosen_fallback

    ok = _validate_composed_response(
        reply,
        {
            "event": event,
            "calendar_success": calendar_success,
            "allowed_facts": dict(allowed_facts or {}),
        },
        previous_assistant_messages or [],
    )
    if not ok:
        return chosen_fallback

    logger.info(
        "[post_booking] LLM reply accepted (event=%s, len=%d)", event, len(reply),
    )
    return reply
