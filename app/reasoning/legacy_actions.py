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


def _camp_context(conversation) -> bool:
    """True when the CURRENT topic is camp — a sticky PARENT segment OR a recent
    camp/registration assistant turn. Deliberately does NOT use the long-lived
    ``lead.child_age`` (it stays set after a switch to adult events and would
    wrongly force camp context for a bare adult-context link request)."""
    if conversation is None:
        return False
    if (getattr(conversation, "segment", "") or "").upper() == "PARENT":
        return True
    for turn in reversed(list(getattr(conversation, "history", []) or [])):
        if isinstance(turn, dict) and turn.get("role") == "assistant":
            low = str(turn.get("content") or "").lower()
            return any(s in low for s in ("ბანაკ", "საზაფხულო", "რეგისტრაცი", "ჩაწერ"))
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

    # 0. Decline / stop — highest priority (never search/book on a decline).
    if _has(low, _DECLINE_STEMS):
        return {"action": "stop_or_decline", "topic": None}

    # 1. Consultation booking is its own flow — defer (NOT a registration link).
    if _has(low, _CONSULT_STEMS):
        return {"action": "consultation_request", "topic": "camp"}

    # 2. Camp registration link.
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

    # 3. Manager contact (number/phone) request.
    if _has(low, _MANAGER_STEMS) and _has(low, _CONTACT_STEMS):
        if has_adult and not has_camp:
            return {"action": "manager_contact", "topic": "adult_event"}
        return {"action": "camp_manager_contact", "topic": "camp"}

    # 4. Adult-event subscription.
    if has_adult and _has(low, _SUBSCRIBE_STEMS):
        return {"action": "adult_event_subscription", "topic": "adult_event"}

    # 5. Adult events — named lookup vs generic discovery.
    if has_adult:
        if _names_specific_event(text):
            return {"action": "adult_event_named_lookup", "topic": "adult_event"}
        return {"action": "adult_event_discovery", "topic": "adult_event"}

    return none
