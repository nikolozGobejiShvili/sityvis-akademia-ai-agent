"""Legacy-mode explicit user-ACTION / topic detection (2026-06-25).

Intent/action-level (NOT exact-phrase) detection used by the legacy
(giant-prompt) path so an EXPLICIT user action — especially a camp
registration-link request — is handled before generic topic flows and is never
swallowed by a stale ADULT context (live bug: after switching to adult events,
„ბანაკის სარეგისტრაციო ლინკი მომწერე" was routed to the adult flow and asked the
child's age instead of returning the camp link).

Deterministic: no planner, no LLM, no side effects. Reuses parent_flow's
canonical camp-registration markers via a LAZY import so there is no import
cycle (parent_flow imports this module at load time; this module only touches
parent_flow inside a function call).

`detect_legacy_explicit_action(text, conversation=None) -> {"action", "topic"}`
where action ∈ {camp_registration_link, camp_manager_contact, manager_contact,
consultation_request, adult_event_named_lookup, adult_event_discovery,
adult_event_subscription, stop_or_decline, None}.
"""
from __future__ import annotations

import re

_CAMP_KEYWORDS = ("ბანაკ", "საზაფხულო", "ლაგერ")
_ADULT_KEYWORDS = ("ზრდასრულ", "კულტურულ", "ღონისძიებ", "საღამო", "კონცერ")
# Consultation booking is a SEPARATE Calendar flow — never a registration link.
_CONSULT_STEMS = ("კონსულტ", "კოსულტ", "ჯავშ")
_MANAGER_STEMS = ("მენეჯერ", "მენჯერ")          # incl. the live „მენჯერ" typo
_CONTACT_STEMS = ("ნომერ", "ტელეფონ", "კონტაქტ")
_DECLINE_STEMS = ("არ მინდა", "უარს", "გავაუქმ")
_SUBSCRIBE_STEMS = ("გამომიწერ", "გამოწერა", "შემატყობინ", "მაცნობ", "სიაში ჩამამატ")
# Self-call intent — the user will phone the manager THEMSELVES („მე თვითონ
# დავურეკავ"), so they want the manager's number. Paired with a manager/contact
# cue this is an EXPLICIT request for the manager's contact, even when a decline
# („არ მინდა") co-occurs in the same message.
_SELF_CALL_STEMS = (
    "დავურეკავ", "დავუკავშირდები", "დავკავშირდები", "თვითონ დავ", "თავად დავ",
)

# UNAMBIGUOUS link/form/registration markers for the context-aware (no camp
# keyword) case. Deliberately EXCLUDES the „ჩაწერა/ჩავწერ/ჩავეწერ" enrollment
# family, which overlaps with the consultation flow — so a bare „ჩაწერა მინდა"
# in camp context is NOT hijacked as a registration link.
_LINK_FORM_MARKERS = (
    "რეგისტრ", "სარეგისტრ", "დარეგისტ", "დავრეგისტ", "რეგისტირ",
    "ლინკ", "ბმულ", "register", "sign up", "signup", "sign-up",
)
_FORM_TOKEN_RE = re.compile(r"(?<![ა-ჰ])ფორმ(?!ატ)")


def _has(low: str, stems) -> bool:
    return any(s in low for s in stems)


def _is_manager_contact_request(low: str) -> bool:
    """True when the message EXPLICITLY asks for the manager's contact details:
    a manager word + a contact word (number/phone/contact), OR a self-call
    intent („მე თვითონ დავურეკავ") that targets the manager or a number.

    This is an explicit POSITIVE action and must outrank a generic decline that
    co-occurs in the SAME message (live bug 2026-06-25: „კონსულტაცია არ მინდა
    მენეჯერის ნომერი რომ მომწეროთ და მე თვითონ დავურეკავ" — the parent declines
    the consultation but still wants the manager's number to call directly)."""
    has_manager = _has(low, _MANAGER_STEMS)
    has_contact = _has(low, _CONTACT_STEMS)
    if has_manager and has_contact:
        return True
    if _has(low, _SELF_CALL_STEMS) and (has_manager or has_contact):
        return True
    return False


def _camp_context(conversation) -> bool:
    """True when the CURRENT topic is camp.

    PARENT is NOT evidence of camp. Every kids' program — Sunday School,
    Disneyland, whatever the operator adds next — is served by the PARENT flow,
    so `segment == "PARENT"` was true for all of them and this returned camp for
    all of them. `followup_service` found and fixed the same false rule
    („the old `segment == "PARENT"` early return classified them as camp leads");
    it survived here.

    What it cost, live 2026-09-03: deep in a Sunday-School conversation „როგორ
    დავრეგისტრირდე ?" reached `parent_flow._maybe_handle_camp_registration_link`
    through this function and came back „ბანაკის ბოლო ნაკადი უკვე დაიწყო და
    რეგისტრაცია დასრულებულია" in 55ms, never touching the engine — while the
    Sunday School registration URL sat in the turn context unused.

    Camp context is now: the conversation resolves to NO other active program,
    AND the last assistant turn actually said camp. „რეგისტრაცი" and „ჩაწერ" are
    gone from that list — every program's registration answer contains them, so
    the agent's own Sunday-School reply was being read back as camp evidence.

    An explicit camp keyword in the CURRENT text is handled by the caller
    (`_is_camp_registration_link_request`), which is unchanged: „ბანაკზე როგორ
    დავრეგისტრირდე" still takes the camp path exactly as before.

    Still deliberately does NOT use the long-lived ``lead.child_age`` (it stays
    set after a switch to adult events).
    """
    if conversation is None:
        return False
    # The canonical resolver the turn context uses. A section here means the
    # parent is demonstrably on some OTHER active program — camp is never
    # returned by it (a camp turn resolves to "nothing"), so any hit is a
    # non-camp program and settles the question.
    try:
        from app.agent.llm.parent_llm_engine import _active_program_section

        if _active_program_section(
            conversation, "", getattr(conversation, "lead", None)
        ) is not None:
            return False
    except Exception:  # pragma: no cover — defensive: fall through to the scan
        pass
    for turn in reversed(list(getattr(conversation, "history", []) or [])):
        if isinstance(turn, dict) and turn.get("role") == "assistant":
            low = str(turn.get("content") or "").lower()
            return any(s in low for s in _CAMP_KEYWORDS)
    return False


def _has_link_form_marker(low: str) -> bool:
    return _has(low, _LINK_FORM_MARKERS) or bool(_FORM_TOKEN_RE.search(low))


def _names_specific_event(text: str) -> bool:
    """Reuse the adult engine's genuine-name gate so „გია მურღულია" is a named
    lookup while „ღონისძიებები რა გაქვთ?" is generic discovery. Fail-safe to
    False (generic) on any import/parsing problem."""
    try:
        from app.agent.llm.adult_llm_engine import _has_genuine_event_name_token
        from app.services import admin_config_service
        return bool(
            _has_genuine_event_name_token(
                admin_config_service._event_query_tokens(text),
            )
        )
    except Exception:  # pragma: no cover — defensive
        return False


def detect_legacy_explicit_action(text: str, conversation=None) -> dict:
    """Return the explicit action + topic for ``text`` (intent-level). Never
    raises — returns {"action": None, "topic": None} on no/empty match."""
    none = {"action": None, "topic": None}
    low = (text or "").lower().strip()
    if not low:
        return none

    has_camp = _has(low, _CAMP_KEYWORDS)
    has_adult = _has(low, _ADULT_KEYWORDS)

    # 0. Manager-contact request — HIGHEST priority. An explicit request for the
    #    manager's number/phone (or a self-call intent that needs it) wins over a
    #    generic decline AND over the „კონსულტ" consultation stem in the SAME
    #    message. Live bug 2026-06-25: a mixed „decline the consultation + give me
    #    the manager's number, I'll call myself" message was cold-closed because
    #    the decline branch below ran first.
    if _is_manager_contact_request(low):
        if has_adult and not has_camp:
            return {"action": "manager_contact", "topic": "adult_event"}
        return {"action": "camp_manager_contact", "topic": "camp"}

    # 1. Decline / stop — high priority (never search/book on a decline), but
    #    NOT above an explicit manager-contact request handled at step 0.
    if _has(low, _DECLINE_STEMS):
        return {"action": "stop_or_decline", "topic": None}

    # 2. Consultation booking is its own flow — defer (NOT a registration link).
    if _has(low, _CONSULT_STEMS):
        return {"action": "consultation_request", "topic": "camp"}

    # 3. Camp registration link.
    #    * an explicit camp keyword ALWAYS wins (even from a stale adult
    #      context) — reuse parent_flow's canonical detector for fidelity;
    #    * else a clear link/form/registration marker in an established camp
    #      context (sticky PARENT / recent camp turn), with NO adult keyword.
    if has_camp:
        try:
            from app.flows.parent_flow import _is_camp_registration_link_request
            if _is_camp_registration_link_request(text):
                return {"action": "camp_registration_link", "topic": "camp"}
        except Exception:  # pragma: no cover — defensive
            pass
    elif (
        not has_adult
        and _has_link_form_marker(low)
        and _camp_context(conversation)
    ):
        return {"action": "camp_registration_link", "topic": "camp"}

    # (Manager-contact request is handled at step 0 — highest priority.)

    # 4. Adult-event subscription.
    if has_adult and _has(low, _SUBSCRIBE_STEMS):
        return {"action": "adult_event_subscription", "topic": "adult_event"}

    # 5. Adult events — named lookup vs generic discovery.
    if has_adult:
        if _names_specific_event(text):
            return {"action": "adult_event_named_lookup", "topic": "adult_event"}
        return {"action": "adult_event_discovery", "topic": "adult_event"}

    return none
