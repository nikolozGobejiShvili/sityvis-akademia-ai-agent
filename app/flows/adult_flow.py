import logging
import re

from app.config import settings
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import admin_config_service, notification_service, openai_service, sheets_service
from app.services.session_key_service import conversation_cache_key
from data.prompts import (
    ADULT_BOOKING_FORWARDED,
    ADULT_CLARIFY_EVENT,
    ADULT_DEFAULT_ATMOSPHERE,
    ADULT_DEFAULT_EVENT_ATMOSPHERE_TBD,
    ADULT_DEFAULT_EVENT_GUEST,
    ADULT_DEFAULT_EVENT_LOCATION,
    ADULT_DEFAULT_EVENT_NAME,
    ADULT_DEFAULT_EVENT_THEME,
    ADULT_DONE_CONTEXT,
    ADULT_EVENT_CONTEXT,
    ADULT_EVENT_DETAILS,
    ADULT_EVENT_LIST_ITEM,
    ADULT_EVENT_NAME_PLACEHOLDER,
    ADULT_EVENT_PLACEHOLDER,
    ADULT_SEND_BOOKING,
    ADULT_SUMMARY_FALLBACK,
    ADULT_WELCOME,
)

logger = logging.getLogger(__name__)


def _trace_adult_decision(**fields) -> None:
    try:
        from app.reasoning import conversation_trace as _trace

        payload = {
            "route_owner": "adult_flow",
            "domain": "adult_events",
            "used_llm": False,
            "used_tool": False,
        }
        payload.update(fields)
        _trace.set_route_decision(**payload)
    except Exception:  # pragma: no cover - trace must never affect replies
        pass

selected_events = {}


def _no_active_events_reply() -> str:
    return admin_config_service.ADULT_NO_ACTIVE_EVENTS_REPLY


def _selected_event_keys(conversation: Conversation) -> list[str]:
    keys = [conversation_cache_key(conversation)]
    raw_sender = str(getattr(conversation, "sender_id", "") or "").strip()
    if raw_sender and raw_sender not in keys:
        keys.append(raw_sender)
    return keys


def _clear_selected_event(conversation: Conversation) -> None:
    for key in _selected_event_keys(conversation):
        selected_events.pop(key, None)


def _visible_events(events: list[dict[str, str]]) -> list[dict[str, str]]:
    return [event for event in events if event.get("name") or event.get("theme")]

# P3-C PATCH 7 — global intent guard for the deterministic adult state
# machine. Live QA showed the SHOW_EVENTS / ANSWER_QUESTIONS states
# looping back to "რომელი საღამო გიზიდავთ" for identity, greeting,
# thanks, and decline questions. Catching those at the top of handle()
# keeps the state machine focused on event-related input.

_ADULT_IDENTITY_STEMS: tuple[str, ...] = (
    "შენ ვინ ხარ",
    "ვინ ხარ",
    "ვინ ხართ",
    "შენ რა გქვია",
    "რა გქვია",
    "ვინ მწერს",
    "ეს ვინ არის",
    "ვინ ხართ?",
    "რობოტი ხარ",
    "ბოტი ხარ",
    "ადამიანი ხარ",
    "რა ხარ",
    "რა ხართ",
)

_ADULT_HUMAN_VS_BOT_STEMS: tuple[str, ...] = (
    "ადამიანი ხარ თუ რობოტი",
    "რობოტი ხარ თუ ადამიანი",
    "ადამიანი ხართ თუ რობოტი",
)

_ADULT_GREETING_STEMS: tuple[str, ...] = (
    "გამარჯობა", "სალამი", "გაუმარჯოს", "მოგესალმებით",
    "ჰაი", "ჰელო", "hi", "hello", "hey",
)

_ADULT_THANKS_STEMS: tuple[str, ...] = (
    "მადლობა", "გმადლობ", "thanks", "thank you",
)

_ADULT_DECLINE_STEMS: tuple[str, ...] = (
    "არა მადლობა", "მადლობა, აღარ მინდა", "მადლობა აღარ მინდა",
    "არ მინდა", "მოგწერთ მერე", "მოგწერთ მოგვიანებით",
    "ჯერ არ მინდა", "ახლა არ მინდა",
)

_ADULT_MANAGER_STEMS: tuple[str, ...] = (
    "მენეჯერ", "ცოცხალ ადამიან", "დამირეკ", "დამიკავშირდე",
    "ვის დაველაპარაკო", "კონსულტაცია მინდა",
)

_GEORGIAN_LETTER_RE = re.compile(r"[ა-ჰ]")


def _is_bare_greeting(text: str) -> bool:
    """A short message whose only Georgian content is a greeting stem."""
    stripped = text.strip().strip("!.,?:;")
    if not stripped:
        return False
    if stripped in _ADULT_GREETING_STEMS:
        return True
    # Allow trailing punctuation / emoji.
    return len(stripped) <= 16 and any(s in stripped for s in _ADULT_GREETING_STEMS)


def _is_bare_thanks(text: str) -> bool:
    stripped = text.strip().strip("!.,?:;")
    if not stripped:
        return False
    if any(stripped == s for s in _ADULT_THANKS_STEMS):
        return True
    # "მადლობა" + filler is acceptable, but "მადლობა" + decline is
    # routed below by the decline branch first.
    if "მადლობა" in stripped and len(stripped) <= 30 and not any(
        d in stripped for d in _ADULT_DECLINE_STEMS
    ):
        return True
    return False


def _maybe_handle_adult_global_intent(
    conversation: Conversation, lead: Lead, message: str,
) -> str | None:
    """Return a deterministic reply when the user's message is a global
    intent (identity / greeting / thanks / decline / manager request)
    that the event state machine should not handle. Returns None
    otherwise so the state machine continues.

    Order matters — identity > greeting > thanks > decline > manager.
    """
    if not message:
        return None
    text = message.lower().strip()
    if not text:
        return None

    # Human-vs-robot first (more specific than identity).
    if any(stem in text for stem in _ADULT_HUMAN_VS_BOT_STEMS):
        logger.info(
            "[adult_flow] global intent: human-vs-robot (sender=%s)",
            conversation.sender_id,
        )
        _trace_adult_decision(
            intent="adult_global",
            sub_intent="identity",
            answer_source="deterministic_handler",
            deterministic_reason="adult_global_human_vs_robot",
        )
        return (
            "მე ონლაინ ასისტენტი ვარ, მაგრამ დაგეხმარებით ზუსტად იმ "
            "ინფორმაციაში, რაც სიტყვის აკადემიის ღონისძიებებს ეხება."
        )

    if any(stem in text for stem in _ADULT_IDENTITY_STEMS):
        logger.info(
            "[adult_flow] global intent: identity (sender=%s)",
            conversation.sender_id,
        )
        _trace_adult_decision(
            intent="adult_global",
            sub_intent="identity",
            answer_source="deterministic_handler",
            deterministic_reason="adult_global_identity",
        )
        return (
            "მე სიტყვის აკადემიის ონლაინ ასისტენტი ვარ. შემიძლია "
            "დაგეხმაროთ ზრდასრულთა კულტურული საღამოების შესახებ "
            "ინფორმაციის მიღებაში და საჭიროების შემთხვევაში მენეჯერთან "
            "დაკავშირებაში."
        )

    # Decline must come before plain "thanks" because "მადლობა, აღარ
    # მინდა" contains both stems.
    if any(stem in text for stem in _ADULT_DECLINE_STEMS):
        logger.info(
            "[adult_flow] global intent: decline (sender=%s)",
            conversation.sender_id,
        )
        _trace_adult_decision(
            intent="adult_global",
            sub_intent="decline",
            answer_source="deterministic_handler",
            deterministic_reason="adult_global_decline",
        )
        return (
            "გასაგებია. თუ მომავალში დაგჭირდებათ ინფორმაცია, "
            "სიამოვნებით დაგეხმარებით."
        )

    if _is_bare_thanks(text):
        logger.info(
            "[adult_flow] global intent: thanks (sender=%s)",
            conversation.sender_id,
        )
        _trace_adult_decision(
            intent="adult_global",
            sub_intent="thanks",
            answer_source="deterministic_handler",
            deterministic_reason="adult_global_thanks",
        )
        return (
            "სიამოვნებით. თუ კიდევ რაიმე კითხვა გაგიჩნდებათ, მომწერეთ."
        )

    if any(stem in text for stem in _ADULT_MANAGER_STEMS):
        logger.info(
            "[adult_flow] global intent: manager request (sender=%s)",
            conversation.sender_id,
        )
        _trace_adult_decision(
            intent="adult_global",
            sub_intent="manager_request",
            answer_source="deterministic_handler",
            handoff_requested=True,
            deterministic_reason="adult_global_manager_request",
        )
        if (lead.phone or "").strip():
            return (
                "კარგი, თქვენი ნომერი მენეჯერს გადავცემ — დაგიკავშირდებათ."
            )
        return (
            "კი, რა თქმა უნდა. მომწერეთ თქვენი 9-ნიშნა საკონტაქტო ნომერი "
            "და მენეჯერი დაგიკავშირდებათ."
        )

    # Bare greeting AFTER START — re-prompt for which evening interests
    # them but don't loop back into clarify-event language verbatim.
    if conversation.state != "START" and _is_bare_greeting(text):
        logger.info(
            "[adult_flow] global intent: greeting (state=%s sender=%s)",
            conversation.state, conversation.sender_id,
        )
        _trace_adult_decision(
            intent="adult_global",
            sub_intent="greeting",
            answer_source="deterministic_handler",
            deterministic_reason="adult_global_greeting",
        )
        return (
            "გამარჯობა. ზრდასრულთა კულტურული საღამოების შესახებ "
            "გაინტერესებთ ინფორმაცია?"
        )

    return None


def handle(conversation: Conversation, message: str) -> str:
    lead = _ensure_lead(conversation)
    lead.last_message_at = conversation.last_activity

    # ADULT LLM Engine gate — when the feature flag is on, route through
    # the new LLM engine first. Failure or empty response falls through
    # to the legacy state machine (the engine's own try/except returns
    # "" on any internal failure; the wrapper here adds a belt-and-
    # braces guard so an engine bug cannot crash the webhook).
    engine_flag = getattr(settings, "USE_ADULT_LLM_ENGINE", False)
    if engine_flag:
        engine_response = _run_adult_engine_safely(conversation, lead, message)
        if engine_response:
            return engine_response
        # Engine returned "" — log and fall through to legacy state machine.
        logger.info(
            "[adult_flow] engine returned empty — falling back to legacy state machine "
            "(sender=%s)",
            conversation.sender_id,
        )

    # P3-C PATCH 7 — global intent guard. Runs before the state machine
    # so identity / greeting / thanks / decline / manager don't loop
    # back into "რომელი საღამო გიზიდავთ".
    intent_reply = _maybe_handle_adult_global_intent(conversation, lead, message)
    if intent_reply is not None:
        return intent_reply

    if conversation.state == "START":
        events = _load_events()
        conversation.state = "SHOW_EVENTS"
        if not _visible_events(events):
            _trace_adult_decision(
                intent="adult_events",
                sub_intent="no_active_events",
                answer_source="admin_config",
                approved_copy_id="adult_no_active_events",
                deterministic_reason="admin_config_no_active_events",
            )
            return _no_active_events_reply()
        _trace_adult_decision(
            intent="adult_events",
            sub_intent="active_events_list",
            answer_source="admin_config",
            deterministic_reason="admin_config_active_events",
        )
        return (
            ADULT_WELCOME.format(
                company_name=settings.COMPANY_NAME,
                events_list=_format_event_list(events),
            )
            .strip()
        )

    if conversation.state == "SHOW_EVENTS":
        events = _load_events()
        if not _visible_events(events):
            _trace_adult_decision(
                intent="adult_events",
                sub_intent="no_active_events",
                answer_source="admin_config",
                approved_copy_id="adult_no_active_events",
                deterministic_reason="admin_config_no_active_events",
            )
            return _no_active_events_reply()
        event = _detect_event(message, events)
        if not event:
            _trace_adult_decision(
                intent="adult_events",
                sub_intent="active_events_list",
                answer_source="admin_config",
                deterministic_reason="admin_config_active_events_clarify",
            )
            return ADULT_CLARIFY_EVENT.format(
                events_list=_format_event_list(events),
            ).strip()

        selected_events[conversation_cache_key(conversation)] = event
        lead.event_interest = event["name"]
        response = _generate_event_response(conversation, message, event)
        conversation.state = "ANSWER_QUESTIONS"
        return _end_with_booking_question(response)

    if conversation.state == "ANSWER_QUESTIONS":
        event = _current_event(conversation)
        if event is None:
            conversation.state = "SHOW_EVENTS"
            _trace_adult_decision(
                intent="adult_events",
                sub_intent="no_active_events",
                answer_source="admin_config",
                approved_copy_id="adult_no_active_events",
                deterministic_reason="admin_config_no_active_events",
            )
            return _no_active_events_reply()
        if _wants_booking(message):
            conversation.state = "SEND_BOOKING"
            _finalize_booking(conversation)
            return ADULT_SEND_BOOKING.format(booking_link=event["booking_link"]).strip()

        response = _generate_event_response(conversation, message, event)
        return _end_with_booking_question(response)

    if conversation.state == "SEND_BOOKING":
        if _current_event(conversation) is None:
            conversation.state = "SHOW_EVENTS"
            _trace_adult_decision(
                intent="adult_events",
                sub_intent="no_active_events",
                answer_source="admin_config",
                approved_copy_id="adult_no_active_events",
                deterministic_reason="admin_config_no_active_events",
            )
            return _no_active_events_reply()
        _finalize_booking(conversation)
        return ADULT_BOOKING_FORWARDED.strip()

    event = _current_event(conversation)
    if event is None:
        _trace_adult_decision(
            intent="adult_events",
            sub_intent="no_active_events",
            answer_source="admin_config",
            approved_copy_id="adult_no_active_events",
            deterministic_reason="admin_config_no_active_events",
        )
        return _no_active_events_reply()
    return _generate_done_response(conversation, message, event)


def run(context) -> str:
    return handle(context.conversation, context.message_text)


# ADULT LLM Engine wrapper. The engine itself catches every internal
# error and returns ``""``; we keep an extra try/except here so a defect
# raised BEFORE the engine's own try block (e.g. an import-time error)
# is contained. Per the patch brief, the safe fallback below is the
# user-facing message when both the engine and the legacy state machine
# would otherwise fail.
_ADULT_ENGINE_SAFE_FALLBACK: str = (
    "მოგვწერეთ სახელი და საკონტაქტო ნომერი, და მენეჯერი დეტალებს "
    "დაგიზუსტებთ."
)


def _run_adult_engine_safely(
    conversation: Conversation, lead: Lead, message: str,
) -> str:
    """Run the ADULT LLM engine inside a try/except and return ``""`` on
    any failure so ``handle`` can fall through to the legacy state
    machine. Never raises.
    """
    try:
        from app.agent.llm.adult_llm_engine import run_adult_llm_turn

        return run_adult_llm_turn(
            user_message=message,
            conversation=conversation,
            lead=lead,
            sender_id=conversation.sender_id,
            platform=conversation.platform,
        ) or ""
    except Exception as exc:
        logger.exception(
            "[adult_flow] ADULT LLM engine raised — falling back to legacy: %s",
            exc,
        )
        return ""


def _ensure_lead(conversation: Conversation) -> Lead:
    if conversation.lead is None:
        conversation.lead = Lead(
            sender_id=conversation.sender_id,
            platform=conversation.platform,
            segment="ADULT",
        )
    conversation.lead.segment = "ADULT"
    return conversation.lead


def _load_events() -> list[dict[str, str]]:
    try:
        events = admin_config_service.get_active_adult_events()
    except Exception as exc:
        logger.warning("[adult_flow] admin adult events load failed: %s", exc)
        return []
    return [_admin_event_to_flow_event(event) for event in events]


def _admin_event_to_flow_event(event: dict) -> dict[str, str]:
    price = str(event.get("price_text") or "").strip()
    if not price and event.get("price_gel") is not None:
        price = str(event.get("price_gel") or "").strip()
    description = str(event.get("description") or "").strip()
    theme = str(event.get("theme") or event.get("format") or description or "").strip()
    return {
        "id": str(event.get("id") or "").strip(),
        "name": str(event.get("title") or "").strip(),
        "date": str(event.get("date_text") or "").strip(),
        "time": "",
        "theme": theme,
        "guest": str(event.get("guest") or "").strip(),
        "location": str(event.get("location") or "").strip(),
        "price": price,
        "booking_link": str(
            event.get("reservation_url") or event.get("payment_terms") or "",
        ).strip(),
        "description": description,
        "atmosphere": ADULT_DEFAULT_ATMOSPHERE,
    }


def _empty_event(event_id: str) -> dict[str, str]:
    return {
        "id": event_id,
        "name": "",
        "date": "",
        "time": "",
        "theme": "",
        "guest": "",
        "location": "",
        "price": "",
        "booking_link": "",
        "description": "",
        "atmosphere": ADULT_DEFAULT_ATMOSPHERE,
    }


def _event_field(label: str) -> str | None:
    fields = {
        "სახელი": "name",
        "თემა": "theme",
        "თარიღი": "date",
        "დრო": "time",
        "ლოკაცია": "location",
        "მოწვეული სტუმრები": "guest",
        "ფასი": "price",
        "ჯავშნის ლინკი": "booking_link",
        "აღწერა": "description",
    }
    return fields.get(label)


def _format_event_list(events: list[dict[str, str]]) -> str:
    visible_events = _visible_events(events)
    if not visible_events:
        return _no_active_events_reply()

    lines = []
    for index, event in enumerate(visible_events, start=1):
        lines.append(
            ADULT_EVENT_LIST_ITEM.format(
                index=index,
                name=event["name"] or ADULT_EVENT_NAME_PLACEHOLDER,
                date=event["date"] or ADULT_EVENT_PLACEHOLDER,
                theme=event["theme"] or ADULT_EVENT_PLACEHOLDER,
                guest=event["guest"] or ADULT_EVENT_PLACEHOLDER,
            ),
        )
    return "\n\n".join(lines)


def _detect_event(message: str, events: list[dict[str, str]] | None = None) -> dict[str, str] | None:
    if events is None:
        events = _load_events()
    normalized = message.strip().lower()

    visible_events = _visible_events(events)
    for index, event in enumerate(visible_events, start=1):
        if normalized == str(index) or str(index) in normalized:
            return event
        searchable = " ".join(
            [
                event["name"],
                event["theme"],
                event["guest"],
                event["date"],
            ],
        ).lower()
        if any(part and part in searchable for part in normalized.split()):
            return event

    if len(visible_events) == 1:
        return visible_events[0]
    return None


def _current_event(conversation: Conversation) -> dict[str, str] | None:
    events = _load_events()
    visible_events = _visible_events(events)
    keys = _selected_event_keys(conversation)
    cache_key = keys[0]
    selected = None
    for key in keys:
        if key in selected_events:
            selected = selected_events.get(key)
            break
    selected_id = str((selected or {}).get("id") or "").strip()
    if selected_id:
        for event in visible_events:
            if event.get("id") == selected_id:
                selected_events[cache_key] = event
                for legacy_key in keys[1:]:
                    selected_events.pop(legacy_key, None)
                return event
        _clear_selected_event(conversation)

    if visible_events:
        selected_events[cache_key] = visible_events[0]
        for legacy_key in keys[1:]:
            selected_events.pop(legacy_key, None)
        return visible_events[0]

    _clear_selected_event(conversation)
    return None


def _generate_event_response(conversation: Conversation, message: str, event: dict[str, str]) -> str:
    context = _event_context(event)
    try:
        response = openai_service.generate_response(
            history=conversation.history,
            user_message=message,
            segment="ADULT",
            context=context,
        )
        _trace_adult_decision(
            intent="adult_events",
            sub_intent="selected_event_detail",
            answer_source="llm_direct",
            used_llm=True,
        )
        return response
    except Exception:
        _trace_adult_decision(
            intent="adult_events",
            sub_intent="selected_event_detail",
            answer_source="fallback",
            used_llm=True,
            fallback_reason="adult_event_detail_generate_response_error",
        )
        return _premium_event_response(event)


def _generate_done_response(conversation: Conversation, message: str, event: dict[str, str]) -> str:
    context = "{}\n\n{}\n\n{}".format(
        settings.KNOWLEDGE_BASE,
        _format_event_list(_load_events()),
        ADULT_DONE_CONTEXT.format(event_name=event["name"]).strip(),
    )
    try:
        return openai_service.generate_response(
            history=conversation.history,
            user_message=message,
            segment="ADULT",
            context=context,
        )
    except Exception:
        return _premium_event_response(event)


def _event_context(event: dict[str, str]) -> str:
    return ADULT_EVENT_CONTEXT.format(
        name=event["name"],
        theme=event["theme"],
        guest=event["guest"],
        location=event["location"],
        date=event["date"],
        time=event["time"],
        atmosphere=event["atmosphere"],
        booking_link=event["booking_link"],
    ).strip()


def _premium_event_response(event: dict[str, str]) -> str:
    return ADULT_EVENT_DETAILS.format(
        event_name=event["name"],
        event_date=_event_date_time(event),
        event_location=event["location"],
        event_guests=event["guest"],
        event_description=_event_description(event),
    ).strip()


def _end_with_booking_question(response: str) -> str:
    question = _booking_question()
    if question in response:
        return response
    return f"{response}\n\n{question}"


def _booking_question() -> str:
    return ADULT_EVENT_DETAILS.format(
        event_name="",
        event_date="",
        event_location="",
        event_guests="",
        event_description="",
    ).strip().splitlines()[-1]


def _event_date_time(event: dict[str, str]) -> str:
    if event["date"] and event["time"]:
        return "{} - {}".format(event["date"], event["time"])
    return event["date"] or event["time"]


def _event_description(event: dict[str, str]) -> str:
    parts = [event.get("description", ""), event.get("atmosphere", "")]
    return "\n".join(part for part in parts if part).strip()


def _wants_booking(message: str) -> bool:
    normalized = message.strip().lower()
    positive_words = (
        "დიახ",
        "კი",
        "მინდა",
        "დაჯავშნა",
        "დავჯავშნე",
        "ვჯავშნი",
        "ადგილი",
        "ბმული",
        "ლინკი",
        "yes",
        "ok",
    )
    return any(word in normalized for word in positive_words)


def _generate_summary(conversation: Conversation) -> str:
    try:
        return openai_service.generate_summary(conversation.history)
    except Exception:
        lead = _ensure_lead(conversation)
        return ADULT_SUMMARY_FALLBACK.format(
            event_interest=lead.event_interest,
        ).strip()


def _finalize_booking(conversation: Conversation) -> None:
    lead = _ensure_lead(conversation)
    if lead.status == "Booked":
        conversation.state = "DONE"
        return

    lead.status = "Booked"
    lead.conversation_summary = _generate_summary(conversation)
    sheets_service.create_lead(lead)
    notification_service.send_manager_notification(lead, lead.conversation_summary)
    conversation.state = "DONE"
