import logging
import re
from dataclasses import dataclass
from datetime import datetime
from string import Formatter
from typing import Any

from app.config import DATA_DIR, settings
from app.flows import adult_flow, parent_flow
from app.models.conversation import Conversation
from app.services import kill_switch, redis_state_service, sentry_service
from app.services.session_key_service import (
    canonical_platform_key,
    canonical_session_key,
    conversation_cache_key,
)
from data.prompts import UNCLEAR_ROUTING

logger = logging.getLogger(__name__)


def _maybe_dynamic_welcome(fallback: str) -> str:
    """R2: when USE_DYNAMIC_WELCOME is on, replace the hardcoded UNCLEAR_ROUTING
    menu (the „გვითხარით, რა გაინტერესებთ" list a bare greeting produces) with
    the data-driven active-programs menu; otherwise return `fallback` unchanged
    (flag OFF ⇒ byte-identical). Late import avoids a circular dependency; any
    failure or empty active list falls back to the hardcoded menu."""
    if not getattr(settings, "USE_DYNAMIC_WELCOME", False):
        return fallback
    try:
        from app.flows.parent_flow import _build_active_programs_welcome
        dynamic = _build_active_programs_welcome()
        return dynamic or fallback
    except Exception:  # pragma: no cover - defensive, never break the greeting
        return fallback

class _ConversationStore(dict):
    """In-memory store keyed by canonical session key.

    Existing tests and a few legacy helpers still read by raw sender_id.
    Those lookups are allowed only when exactly one live conversation has
    that sender_id; ambiguous sender-only lookups fail closed.
    """

    def _legacy_sender_key(self, key: object) -> str | None:
        if not isinstance(key, str) or ":" in key:
            return None
        matches = [
            store_key for store_key, conv in dict.items(self)
            if getattr(conv, "sender_id", None) == key
        ]
        return matches[0] if len(matches) == 1 else None

    def __contains__(self, key: object) -> bool:
        return dict.__contains__(self, key) or self._legacy_sender_key(key) is not None

    def __setitem__(self, key: str, value: Conversation) -> None:
        if isinstance(value, Conversation):
            try:
                if not value.session_key:
                    _ensure_conversation_identity(value)
                if key in {value.sender_id, value.session_key}:
                    key = value.session_key
            except Exception:
                pass
        dict.__setitem__(self, key, value)

    def __getitem__(self, key: str) -> Conversation:
        if dict.__contains__(self, key):
            return dict.__getitem__(self, key)
        legacy_key = self._legacy_sender_key(key)
        if legacy_key is not None:
            return dict.__getitem__(self, legacy_key)
        raise KeyError(key)

    def get(self, key: str, default: Any = None) -> Conversation | Any:
        if dict.__contains__(self, key):
            return dict.get(self, key, default)
        legacy_key = self._legacy_sender_key(key)
        if legacy_key is not None:
            return dict.get(self, legacy_key, default)
        return default

    def pop(self, key: str, default: Any = None) -> Conversation | Any:
        if dict.__contains__(self, key):
            return dict.pop(self, key, default)
        legacy_key = self._legacy_sender_key(key)
        if legacy_key is not None:
            return dict.pop(self, legacy_key, default)
        return default


conversations: _ConversationStore = _ConversationStore()


# -- P3-B Redis-backed persistence helpers --------------------------------
#
# `conversations` is the in-memory working store and is keyed by the
# canonical `platform:page_id:sender_id` session key. Redis mirrors each
# Conversation under `conversation:{platform}:{page_id}:{sender_id}`.
# During migration, Redis reads fall back to the legacy
# `conversation:{platform}:{sender_id}` key and write back the canonical key.
#
# Redis disabled / unavailable -> these helpers are no-ops and the in-memory
# store remains the source of truth during a single process lifetime.


def _conversation_session_key(
    sender_id: str,
    platform: str,
    page_id: str = "",
    *,
    require_page_id: bool = False,
) -> str:
    return canonical_session_key(
        platform, page_id, sender_id, require_page_id=require_page_id,
    )


def _ensure_conversation_identity(
    conversation: Conversation,
    *,
    page_id: str | None = None,
    require_page_id: bool = False,
) -> str:
    if page_id is not None:
        conversation.page_id = str(page_id or "").strip()
    conversation.session_key = _conversation_session_key(
        conversation.sender_id,
        conversation.platform,
        conversation.page_id,
        require_page_id=require_page_id,
    )
    return conversation.session_key


def _conversation_redis_key(
    platform_or_session_key: str,
    page_id: str | None = None,
    sender_id: str | None = None,
) -> str:
    """Return the Redis key for a canonical conversation session.

    Preferred call shape is ``_conversation_redis_key(platform, page_id, sender)``.
    The two-argument legacy shape is retained for older tests/helpers and maps
    to the canonical key with an ``unknown`` page id.
    """
    if sender_id is None:
        if page_id is None:
            session_key = str(platform_or_session_key or "").strip()
            if session_key.startswith("conversation:"):
                return session_key
            return f"conversation:{session_key}"
        sender_id = page_id
        page_id = ""
    return f"conversation:{_conversation_session_key(sender_id, platform_or_session_key, page_id or '')}"


def _legacy_conversation_redis_keys(platform: str, sender_id: str) -> list[str]:
    raw_platform = str(platform or "unknown").strip() or "unknown"
    candidates = [f"conversation:{raw_platform}:{sender_id}"]
    normalized = canonical_platform_key(platform)
    normalized_key = f"conversation:{normalized}:{sender_id}"
    if normalized_key not in candidates:
        candidates.append(normalized_key)
    return candidates


def _redis_get_json_safely(key: str) -> Any | None:
    try:
        return redis_state_service.get_json(key)
    except Exception as exc:
        logger.warning("[redis] conversation %s read failed: %s", key, exc)
        return None


def _load_conversation_from_redis(
    sender_id: str,
    platform: str,
    page_id: str = "",
) -> Conversation | None:
    """Try to restore a Conversation from Redis. None on miss / disabled / error."""
    if not redis_state_service.is_enabled():
        return None

    canonical_key = _conversation_redis_key(platform, page_id, sender_id)
    read_keys = [canonical_key]
    read_keys.extend(
        key for key in _legacy_conversation_redis_keys(platform, sender_id)
        if key not in read_keys
    )

    for key in read_keys:
        payload = _redis_get_json_safely(key)
        if not payload:
            continue
        try:
            restored = Conversation.from_dict(payload)
            _ensure_conversation_identity(restored, page_id=page_id)
            if key != canonical_key:
                _save_conversation_to_redis(restored)
            return restored
        except Exception as exc:
            logger.warning(
                "[redis] conversation %s deserialise failed -- discarding: %s",
                key, exc,
            )
            return None
    return None


def _save_conversation_to_redis(conversation: Conversation) -> None:
    if not redis_state_service.is_enabled():
        return
    key = _conversation_redis_key(
        conversation.platform, conversation.page_id, conversation.sender_id,
    )
    _ensure_conversation_identity(conversation)
    try:
        payload = conversation.to_dict()
    except Exception as exc:
        logger.warning(
            "[redis] conversation %s serialise failed: %s", key, exc,
        )
        return
    # 8-day rolling TTL: the conversation expires that many seconds after the
    # user's LAST message. Passed positionally so test doubles that stub
    # set_json(key, value, ttl=None) stay compatible.
    redis_state_service.set_json(
        key, payload, redis_state_service.conversation_ttl_seconds(),
    )
# -- Segment classification (Phase 3.6A — owner-confirmed policy) -----------
#
# Bare greetings ("გამარჯობა", "Hi") now route to UNCLEAR. The user is asked
# to pick a direction (children's camp vs adult cultural evenings) before the
# agent enters either flow. UNCLEAR is RECOVERABLE: the next message is
# re-classified on the same conversation, so split-fragment intent like
#   user: "გამარჯობა"      → UNCLEAR (asks direction)
#   user: "ბანაკი მაინტერესებს" → PARENT (continues camp flow)
# is resolved without losing context.
#
# Classification is keyword-based on stems (no morphology library) so it
# survives Georgian noun declension: "ბანაკი / ბანაკში / ბანაკის" all match
# the stem "ბანაკ". Matching is plain substring `in lowered_text`. This
# accepts the occasional accidental hit (a stem that appears inside an
# unrelated word) in exchange for zero dependencies and predictable
# behaviour. If a hit is wrong, the user can clarify in the next turn —
# UNCLEAR is recoverable.

GREETING_ONLY_KEYWORDS = (
    "გამარჯობა", "სალამი", "გაუმარჯოს", "მოგესალმებით",
    "ჰაი", "ჰელო", "hi", "hello", "hey",
)

# Camp / children's-camp keyword stems. Matching is substring on a lower-
# cased message. Stems cover Georgian declension (e.g. "ბანაკ" catches
# ბანაკი, ბანაკში, ბანაკის, ბანაკიდან).
# NOTE: "პროგრამა" is intentionally NOT included — it is generic and can
# also describe an adult cultural programme; including it would cause
# tie-break misfires.
CAMP_KEYWORDS = (
    "ბანაკ",      # ბანაკი, ბანაკში, ბანაკის ...
    "ლაგერ",      # ლაგერი
    "ბავშვ",      # ბავშვი, ბავშვები, ბავშვებს
    "შვილ",       # შვილი, შვილს, შვილზე
    "საზაფხულო",
    "ეკრან",      # ეკრანი, ეკრანთან, ეკრანდამოკიდებულება
    "მოზარდ",     # მოზარდი, მოზარდები
    "სკოლ",       # სკოლა, სკოლაში
    # Minimal English camp-intent stems. We don't aim for broad English
    # conversation support — the parent LLM engine still replies in
    # Georgian — but a parent who happens to write "I want camp for my
    # child" should not be dropped into the UNCLEAR menu when the
    # intent is unambiguous.
    "camp",
    "child",
    "kid",
    "summer",
)

# Adult / cultural-evening keyword stems.
ADULT_KEYWORDS = (
    "ღონისძიებ",  # ღონისძიება, ღონისძიების
    "საღამო",
    "ბილეთ",      # ბილეთი, ბილეთები
    "კულტურ",     # კულტურა, კულტურული
    "პოეზი",      # პოეზია, პოეზიის
    "მუსიკ",      # მუსიკა, მუსიკალური
    "შეხვედრ",    # შეხვედრა, შეხვედრის
    "კლუბ",       # კლუბი, კლუბში
)

# Price-only keyword stems. A message that ONLY signals price (no camp or
# adult signal) stays UNCLEAR — adult events also have ticket prices, so
# price alone does not prove camp interest. Owner-confirmed (Phase 3.6A).
PRICE_KEYWORDS = (
    "ფასი",
    "ღირს",
    "რამდენი",
    "გადახდ",     # გადახდა, გადახდის
)


def _is_pure_greeting(text: str) -> bool:
    """Return True only when message is a bare greeting (no other content).

    "გამარჯობა" → True       — sets UNCLEAR per Phase 3.6A owner decision
    "გამარჯობა ბანაკი მაინტერესებს" → False (has more content; falls to
                                              keyword classifier → PARENT)
    """
    cleaned = (text or "").strip().lower().strip("!.,?:;")
    if not cleaned:
        return False
    return cleaned in GREETING_ONLY_KEYWORDS


_IDENTITY_QUESTION_STEMS: tuple[str, ...] = (
    "ბოტი ხარ", "ბოტი ხართ", "რობოტი ხარ", "რობოტი ხართ",
    "ai ხარ", "ai ხართ", "ხელოვნურ", "მანქან", "ნამდვი",
    "გენდერ", "ვინ ხარ", "ვინ ხართ",
)


def _maybe_identity_reply(message_text: str) -> str | None:
    """Short brand-identity reply for the UNCLEAR-segment case where
    the user asks "ბოტი ხარ?" / "AI ხარ?" / "ვინ ხართ?". The reply is
    intentionally short and brand-grounded — it does not name a model
    family (GPT / Claude / OpenAI / Anthropic) and re-offers the
    routing menu so the user can pick a direction.

    Returns ``None`` when the message is not an identity question, so
    the caller falls back to the normal UNCLEAR menu.
    """
    text = (message_text or "").lower().strip()
    if not text or len(text) > 80:
        return None
    if not any(stem in text for stem in _IDENTITY_QUESTION_STEMS):
        return None
    # Brand name in Georgian genitive: trailing "ა" → "ის"
    # (e.g. "სიტყვის აკადემია" → "სიტყვის აკადემიის"). Conservative:
    # only inflect when the brand actually ends in "ა"; otherwise
    # keep the raw form.
    company = getattr(settings, "COMPANY_NAME", "სიტყვის აკადემია") or ""
    if company.endswith("ა"):
        company_gen = company[:-1] + "ის"
    else:
        company_gen = company
    return (
        f"{company_gen} ვირტუალური ასისტენტი ვარ — ვეხმარები ბანაკისა და "
        "ღონისძიებების შესახებ ინფორმაციით. გვითხარით, რა გაინტერესებთ — "
        "ბავშვების საზაფხულო ბანაკი თუ ზრდასრულთა კულტურული საღამოები?"
    )


def _classify_segment(message_text: str) -> str:
    """Deterministic keyword classifier — Phase 3.6A.

    Returns one of: "PARENT", "ADULT", "UNCLEAR".

    Rules (owner-confirmed):
      1. Bare greeting                       → UNCLEAR
      2. Both camp and adult keywords match  → UNCLEAR (tie-break: do not guess)
      3. Only camp keywords match            → PARENT
      4. Only adult keywords match           → ADULT
      5. No camp/adult match (incl. bare price questions like "ფასი?") → UNCLEAR
    """
    if _is_pure_greeting(message_text):
        return "UNCLEAR"

    text = (message_text or "").lower()
    has_camp = any(kw in text for kw in CAMP_KEYWORDS)
    has_adult = any(kw in text for kw in ADULT_KEYWORDS)

    # Tie-break: do not guess between camp and adult. Stay UNCLEAR and re-ask.
    if has_camp and has_adult:
        return "UNCLEAR"
    if has_camp:
        return "PARENT"
    if has_adult:
        return "ADULT"

    # No camp/adult signal — includes bare price questions ("ფასი?"), vague
    # follow-ups ("მაინტერესებს"), and anything else. Stay UNCLEAR so the
    # user picks a direction explicitly. The next message will be re-
    # classified on the same conversation (recovery loop in process_message).
    return "UNCLEAR"


def _match_active_program_segment(message_text: str) -> str | None:
    """USE_DYNAMIC_PROGRAMS: route a message that NAMES an active admin program by
    that program's type (adult_events → ADULT, else PARENT). None when flag off /
    no specific match — the caller falls back to _classify_segment, so flag-off
    routing is byte-identical and the 3 generic-named programs keep classifier
    routing. Precision lives in reasoning/dynamic_program_match (Phase 2)."""
    if not getattr(settings, "USE_DYNAMIC_PROGRAMS", False):
        return None
    if not (message_text or "").strip():
        return None
    try:
        from app.services import admin_config_service
        from app.reasoning.dynamic_program_match import match_dynamic_program
        match = match_dynamic_program(message_text, admin_config_service.get_active_sections())
    except Exception:  # pragma: no cover - defensive
        return None
    if not match:
        return None
    return "ADULT" if match.get("type") == "adult_events" else "PARENT"


# PARENT Reschedule State + Segment Override Patch (2026-06-10).
#
# Live bug: a conversation that had been locked to ADULT (from earlier
# adult-event testing) stayed ADULT forever — `process_message` only
# re-classifies the segment when it is NOT already PARENT/ADULT (see the
# routing block). So „კონსულტაციის გადატანა მინდა" routed to the ADULT
# engine and got answered with an adult-event date. These deterministic,
# unambiguous PARENT/consultation/reschedule phrases must OVERRIDE a
# sticky ADULT segment and route to the PARENT booking/reschedule flow.
# The lead's PARENT fields (child_age / name / phone / booking) are
# preserved — only the routing segment flips.
_PARENT_CONSULTATION_OVERRIDE_PHRASES: tuple[str, ...] = (
    "კონსულტაცი",            # კონსულტაცია / კონსულტაციის / კონსულტაციაზე
    "კონსულტაციის გადატანა",
    "გადავიტანოთ",
    "გადატანა მინდა",
    "ჩავნიშნეთ",
    "ჩამწერეთ",
    "ჩავწეროთ",
    "ბანაკზე გეუბნები",
    "ბანაკის კონსულტაცი",
    "ბანაკის შესახებ",
    "სხვა დროზე გადავიტანოთ",
)


def _is_parent_consultation_intent(message_text: str) -> bool:
    """True when the message carries an unambiguous PARENT/camp
    consultation or reschedule signal that must win over a sticky ADULT
    segment. Deliberately narrow — only clear consultation/reschedule
    vocabulary, so a genuine adult-event question is never hijacked."""
    text = (message_text or "").lower()
    if not text:
        return False
    return any(p in text for p in _PARENT_CONSULTATION_OVERRIDE_PHRASES)


# General Registration-Link Intent Routing (2026-06-19).
#
# A registration/sign-up link/form request is answered with the CONFIGURED
# Admin link for the clear target:
#   * camp keyword       → segment PARENT  → engine `get_camp_info("registration")`
#                          → camp Admin `registration_url`;
#   * adult-event keyword/ context → segment ADULT → engine
#                          `provide_adult_reservation_link` → event `reservation_url`;
#   * a sticky PARENT/ADULT segment (context target) → that flow resolves it.
# The links live in Admin/config (`get_camp_facts()` / `find_adult_event`) and
# are NEVER invented; a missing URL degrades to the manager/contact fallback
# inside those tools.
#
# The ONLY gap this helper fills: a FRESH request that asks for a
# registration link/form but names NO target (no camp/adult keyword) and has
# no established segment → the classifier returns UNCLEAR. Rather than guess
# a link (or show the generic two-option menu), we ask a short,
# registration-specific clarification. Code-level string (no prompt change).
_REGISTRATION_LINK_MARKERS: tuple[str, ...] = (
    "რეგისტრაცი",   # რეგისტრაცია / რეგისტრაციის / სარეგისტრაციო
    "დარეგისტრ",    # დარეგისტრირება / დარეგისტრირდე
    "დავრეგისტრ",   # დავრეგისტრირდე
    "ჩაწერა",       # ჩაწერა — NOT bare „ჩაწერ" (the past participle
                    # „ჩაწერილი" / „already enrolled" must not match)
    "ჩავწერ",       # ჩავწერო
    "ჩავეწერ",      # ჩავეწერო
    "ბმულ",         # ბმული
    "ლინკ",         # ლინკი
    "registr",      # registration / register (English)
    "link",         # English "link" (English "form" deliberately omitted —
                    # it is a substring of "information")
    "sign up",
    "signup",
    "sign-up",
)

# „ფორმა"/„ფორმის" as a STANDALONE token — word-boundary-aware so it never
# fires inside „ინ-ფორმა-ცია" (information) or „ფორმატ-ი" (format). Same live
# substring bug as parent_flow._CAMP_FORM_TOKEN_RE (2026-06-20).
_REGISTRATION_FORM_TOKEN_RE = re.compile(r"(?<![ა-ჰ])ფორმ(?!ატ)")

_REGISTRATION_LINK_CLARIFICATION = (
    "რომელი მიმართულების რეგისტრაციის ლინკი გნებავთ — "
    "ბანაკის თუ კონკრეტული ღონისძიების?"
)


def _is_registration_link_request(message_text: str) -> bool:
    """True when the message asks for a registration / sign-up link or form.

    Used ONLY in the UNCLEAR branch (no camp/adult target, no sticky
    segment) to ask a registration-specific clarification instead of
    guessing a link. A request that already names the camp / an event, or
    arrives inside a PARENT/ADULT conversation, never reaches this — it is
    routed to the camp / adult flow which returns the configured link. The
    „ფორმა" token is word-boundary-aware so an INFORMATION request
    („ინფორმაცია მომწერე") never matches."""
    text = (message_text or "").lower()
    if not text:
        return False
    if any(m in text for m in _REGISTRATION_LINK_MARKERS):
        return True
    return bool(_REGISTRATION_FORM_TOKEN_RE.search(text))


# =========================================================================
# Conversation Planner integration (Phase 3, 2026-06-24) — the topic-routing
# authority + state-writeback + central final-validator chokepoint. All gated
# behind USE_CONVERSATION_PLANNER (compute/shadow) and additionally
# CONVERSATION_PLANNER_AUTHORITATIVE (apply). Default OFF + pinned OFF in
# tests → byte-identical behaviour for the existing suite. Fail-closed.
# =========================================================================

# Intents the PARENT flow answers deterministically (planner pre-answer / the
# existing deterministic handlers). When the planner returns one of these the
# turn is routed to parent_flow even from a sticky-ADULT segment, WITHOUT
# flipping the sticky segment (route this turn only).
_PLANNER_PARENT_INTENTS: frozenset[str] = frozenset({
    "state_recall", "manager_phone_request", "booking_recall", "decline",
    "adult_event_decline", "name_update", "sunday_school", "tone_request",
    "camp_registration",
})


def _planner_authoritative() -> bool:
    return bool(
        getattr(settings, "USE_CONVERSATION_PLANNER", False)
        and getattr(settings, "CONVERSATION_PLANNER_AUTHORITATIVE", False)
    )


def _maybe_compute_plan(conversation, message_text: str):
    """Compute the unified TurnPlan once per turn (when USE_CONVERSATION_PLANNER
    is on). Returns None when the flag is off or on any error (fail-closed)."""
    if not getattr(settings, "USE_CONVERSATION_PLANNER", False):
        return None
    try:
        from app.reasoning import conversation_planner
        plan = conversation_planner.plan_turn(message_text, conversation)
        logger.info(
            "[planner][%s] intent=%s topic=%s policy=%s clear=%s "
            "use_booking=%s wb_adult=%s reason=%s",
            "auth" if _planner_authoritative() else "shadow",
            plan.user_current_intent, plan.active_topic, plan.answer_policy,
            plan.state_to_clear, plan.should_use_confirmed_booking,
            plan.writeback_adult_age, plan.reason,
        )
        return plan
    except Exception:  # pragma: no cover — planner must never break a reply
        return None


def _planner_apply_writebacks(conversation, plan) -> None:
    """Apply the planner's deterministic state writebacks (Class 5). Currently:
    the adult-age self-correction writes ``lead.adult_age`` while preserving
    ``lead.child_age``. Pure, in-memory; never touches Calendar/Sheets. Visible
    in the trace as ``writebacks``."""
    try:
        wb_adult = (getattr(plan, "writeback_adult_age", None) or "").strip()
        if not wb_adult:
            return
        lead = getattr(conversation, "lead", None)
        if lead is None:
            return
        before = (getattr(lead, "adult_age", "") or "").strip()
        if before == wb_adult:
            return
        lead.adult_age = wb_adult
        # child_age is intentionally NOT touched — the two ages stay separate.
        logger.info(
            "[planner][writeback] adult_age=%s (child_age preserved=%s)",
            wb_adult, (getattr(lead, "child_age", "") or "").strip() or "—",
        )
        try:
            from app.reasoning import conversation_trace as _trace
            _trace.set(writebacks={"adult_age": wb_adult})
        except Exception:  # pragma: no cover — trace must never break a reply
            pass
    except Exception:  # pragma: no cover — writeback must never break a reply
        logger.exception("[planner][writeback] raised — ignored")


def _planner_route_decision(plan, current_segment: str):
    """Return ``(route_segment, persist)`` — which flow handles THIS turn, and
    whether to flip the sticky ``conversation.segment``.

    A clear domain (adult_event / camp / consultation) is a sticky topic switch
    (persist=True). A neutral intent the parent flow answers deterministically
    routes to PARENT for THIS turn without flipping the sticky segment. An
    ambiguous turn keeps the current segment unchanged."""
    topic = getattr(plan, "active_topic", "none")
    intent = getattr(plan, "user_current_intent", "unclear")
    if topic == "adult_event":
        return "ADULT", True
    if topic in ("camp", "consultation"):
        return "PARENT", True
    if intent in _PLANNER_PARENT_INTENTS or topic in (
        "general_state", "sunday_school", "manager_contact",
    ):
        return "PARENT", False
    return current_segment, False


def _planner_final_validate(conversation, plan, response: str) -> str:
    """Central final validator (Class 6) — the LAST safety layer. Enforces the
    planner's forbidden-response patterns on the FINAL answer regardless of
    route. Prefers upstream routing/context fixes; this only repairs a leaked
    violation. Fail-closed (returns the original response on any error)."""
    try:
        from app.flows import parent_flow
        return parent_flow.planner_final_validate(conversation, plan, response)
    except Exception:  # pragma: no cover — validator must never break a reply
        return response


def _handle_subscription_request(conversation) -> str:
    """#6 — subscription consent step: confirm with the KNOWN name + MASKED phone
    (no adult-age ask, no full-phone leak), and mark confirm-pending so the next
    affirmation saves. Never raises."""
    from app.reasoning import response_policy as _rp
    from app.reasoning import selected_state as _ss
    lead = getattr(conversation, "lead", None)
    name = (getattr(lead, "name", "") or "").strip() if lead else ""
    phone = (getattr(lead, "phone", "") or "").strip() if lead else ""
    masked = _ss._mask(phone) if phone else ""
    try:
        conversation.adult_subscription_status = "confirm_pending"
    except Exception:  # pragma: no cover — defensive
        pass
    try:
        from app.reasoning import conversation_trace as _t
        _t.set(route="subscription_request", answered_by="response_policy.subscription_confirm")
    except Exception:
        pass
    return _rp.subscription_confirm(name, masked)


def _handle_subscription_save(conversation) -> str:
    """#6 — the user confirmed → save via the existing subscription service
    (events Sheets tab). Honest on failure; never fakes a save; resets the
    pending marker."""
    from app.reasoning import response_policy as _rp
    lead = getattr(conversation, "lead", None)
    name = (getattr(lead, "name", "") or "").strip() if lead else ""
    phone = (getattr(lead, "phone", "") or "").strip() if lead else ""
    saved = False
    try:
        from app.services import adult_subscription_service
        result = adult_subscription_service.subscribe(
            platform=getattr(conversation, "platform", "") or "messenger",
            sender_id=getattr(conversation, "sender_id", "") or "",
            name=name or None,
            phone=phone or None,
        )
        saved = bool(result.get("success"))
    except Exception:  # pragma: no cover — subscription save must never crash a reply
        logger.exception("[subscription] save raised")
        saved = False
    try:
        conversation.adult_subscription_status = "subscribed" if saved else "asked"
    except Exception:
        pass
    try:
        from app.reasoning import conversation_trace as _t
        _t.set(route="subscription_save",
               answered_by="adult_subscription_service.subscribe",
               note=("saved" if saved else "save_failed"))
    except Exception:
        pass
    return _rp.subscription_saved() if saved else _rp.subscription_failed()


def _apply_response_policy(conversation, plan, message_text: str, response: str) -> str:
    """Consultant-quality response composition (Stage 3). Reasoning-driven by the
    planner intent + selected_state; refines the FINAL answer:

      * eligible child age → replace a generic/awkward qualification with the
        brand pain-point discovery (sales_agent_prompt STEP 4);
      * consultation CTA → the MANAGER explains the details, not the AI;
      * concise/human → drop a redundant second „მადლობა".

    Pure render; never raises (returns the original response on any error)."""
    try:
        if not response:
            return response
        from app.reasoning import response_policy as _rp
        intent = getattr(plan, "user_current_intent", "")
        lead = getattr(conversation, "lead", None)

        # #3 — eligible child age → pain-point discovery (replace the LLM's
        # awkward qualification). Only when the captured child age is in-band.
        if intent == "camp_age_eligibility" and lead is not None:
            child_age = (getattr(lead, "child_age", "") or "").strip()
            if child_age.isdigit():
                try:
                    from app.services import admin_config_service
                    age_min, age_max = admin_config_service.get_camp_age_bounds()
                except Exception:
                    age_min, age_max = 9, 17
                if age_min <= int(child_age) <= age_max:
                    response = _rp.eligible_age_reply(child_age)

        # #4 — consultation CTA: the manager explains the details, not the AI.
        response = _rp.fix_consultation_cta(response)
        # #11 — drop a redundant second „მადლობა".
        response = _rp.collapse_repeated_thanks(response)
        return response or ""
    except Exception:  # pragma: no cover — composer must never break a reply
        return response


class SafeFormatter(Formatter):
    def get_value(self, key: Any, args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
        if isinstance(key, str):
            return kwargs.get(key, "{" + key + "}")
        return Formatter.get_value(self, key, args, kwargs)


@dataclass
class ContentRepository:
    def __post_init__(self) -> None:
        self.knowledge = self._load(DATA_DIR / "knowledge_base.txt")
        self.events_data = self._load(DATA_DIR / "events.txt")
        self.formatter = SafeFormatter()

    def _load(self, path) -> str:
        return path.read_text(encoding="utf-8")

    def knowledge_text(self, section: str, key: str, **values: Any) -> str:
        return self._section_text(self.knowledge, section, **values)

    def event_text(self, section: str, key: str, **values: Any) -> str:
        return self._section_text(self.events_data, section, **values)

    def _section_text(self, text: str, section: str, **values: Any) -> str:
        section_map = {
            "company": "COMPANY INFO",
            "messages": "SALES SCRIPTS",
            "routing": "SALES SCRIPTS",
            "events": "EVENT",
            "calendar": "EVENT",
        }
        marker = section_map.get(section, section).upper()
        extracted = _extract_template_section(text, marker) or text
        return self.formatter.format(extracted, **values).strip()


@dataclass
class FlowContext:
    conversation: Conversation
    message_text: str
    content: ContentRepository

    @property
    def variables(self) -> dict[str, Any]:
        return {
            "company_name": settings.COMPANY_NAME,
            "company_tone": _segment_tone(self.conversation.segment),
            "company_language": settings.COMPANY_LANGUAGE,
            "message": self.message_text,
            "sender_id": self.conversation.sender_id,
            "camp_price": settings.CAMP_PRICE,
        }

    def knowledge(self, section: str, key: str) -> str:
        return self.content.knowledge_text(section, key, **self.variables)

    def events(self, section: str, key: str) -> str:
        return self.content.event_text(section, key, **self.variables)

    def join_text(self, parts: list[str]) -> str:
        return "\n\n".join(part for part in parts if part)


content_repository = ContentRepository()


def _mask_user_phone_in_response(conversation, response: str) -> str:
    """Central privacy guard — replace the user's OWN stored phone with a masked
    form (`595999733` → `595***733`) anywhere it appears in an outgoing reply,
    tolerating spacing / dashes / a `+995` prefix. Reads `conversation.lead.phone`
    and masks ONLY that exact number, so the manager phone (a different number)
    and any other digits are never touched. Idempotent (an already-masked
    `595***733` has no full digit run, so nothing matches). Never raises."""
    try:
        if not response:
            return response
        lead = getattr(conversation, "lead", None)
        phone = (getattr(lead, "phone", "") or "").strip() if lead else ""
        digits = re.sub(r"\D", "", phone)
        local = digits[-9:] if len(digits) >= 9 else digits
        if len(local) != 9:
            return response
        masked = f"{local[:3]}***{local[6:]}"
        pattern = re.compile(r"(?:\+?995[\s\-]?)?" + r"[\s\-]?".join(local))
        return pattern.sub(masked, response)
    except Exception:  # pragma: no cover — privacy guard must never break a reply
        return response


def process_message(sender_id: str, message_text: str, platform: str, page_id: str = "") -> str:
    """Public entry — wraps the real implementation with an exception
    capture so production errors reach Sentry with a privacy-safe
    context. The wrapper re-raises so the webhook layer's existing
    exception handling (`logger.exception` + skip send) is preserved
    exactly — we do NOT swallow exceptions that previously surfaced.
    """
    masked = sentry_service.mask_sender(sender_id)
    logger.info(
        "[conversation] start platform=%s sender=%s", platform, masked,
    )
    try:
        response = _process_message_impl(sender_id, message_text, platform, page_id)
        logger.info(
            "[conversation] completed platform=%s sender=%s reply_len=%d",
            platform, masked, len(response or ""),
        )
        return response
    except Exception as exc:
        logger.exception(
            "[conversation] error platform=%s sender=%s error=%s",
            platform, masked, type(exc).__name__,
        )
        # Sentry capture with PRIVACY-SAFE context only — no message
        # body, no full sender id. Per the Basic Error Monitoring
        # Patch brief.
        sentry_service.capture_exception(
            exc,
            context={
                "area": "conversation_service",
                "platform": platform,
                "sender": masked,
            },
        )
        raise


def _process_message_impl(sender_id: str, message_text: str, platform: str, page_id: str = "") -> str:
    # Emergency Kill Switch (operator-controlled via AGENT_ENABLED env).
    # Returns the safe offline message BEFORE creating a Conversation,
    # classifying the segment, calling the LLM engine, looking up
    # slots, booking, saving leads, notifying the manager, or capturing
    # follow-up markers. The check lives at the very top so a single
    # `.env` flip + restart truly disables every downstream side effect.
    if not kill_switch.is_agent_enabled():
        kill_switch.log_disabled_skip(
            context="dm", sender_id=sender_id, extra=f"platform={platform}",
        )
        return kill_switch.AGENT_DISABLED_MESSAGE

    conversation = _get_or_create_conversation(sender_id, platform, page_id)
    conversation.last_activity = datetime.utcnow()
    conversation.history.append({"role": "user", "content": message_text})

    # Per-turn diagnostic trace (CONVERSATION_TRACE_DEBUG) — observability only.
    from app.reasoning import conversation_trace as _trace
    _trace.begin(
        sender_id,
        message_text,
        platform,
        page_id=conversation.page_id,
        session_key=conversation.session_key,
    )
    _trace.set(
        flow_before=conversation.segment or "(empty)",
        use_planner=getattr(settings, "USE_CONVERSATION_PLANNER", False),
        planner_authoritative=getattr(
            settings, "CONVERSATION_PLANNER_AUTHORITATIVE", False,
        ),
    )

    _trace.set_route_decision(
        route_owner="conversation_service",
        domain="unknown",
        intent="incoming_turn",
        segment_before=conversation.segment or "",
        state_before=conversation.state or "",
        answer_source="unknown",
        deterministic_reason="conversation_service_entry",
    )
    # P3-C PATCH 3 — capture pre-response follow-up markers based on
    # what the user *just* said. These are data-only flags for a future
    # scheduler; no message is sent from here.
    _record_pre_response_followup_markers(conversation, message_text)

    # Re-classify the segment whenever it isn't already locked to PARENT or
    # ADULT. This makes UNCLEAR a RECOVERABLE state: a bare greeting routes
    # to UNCLEAR on turn 1, then a follow-up like "ბანაკი მაინტერესებს" on
    # turn 2 upgrades the segment to PARENT and enters the camp flow,
    # without losing conversation history.
    #
    # Booked-state guard: a conversation with ``state == "DONE"`` and a
    # booked lead is already past the routing decision — any further
    # message (e.g. "რა ხდება შემდეგ?") must stay in the PARENT flow
    # and not be re-routed through the UNCLEAR menu just because it
    # lacks a camp keyword. Mirror the same logic when the lead has
    # already disclosed name+phone, since that conclusively places the
    # parent in the active PARENT flow.
    lead = conversation.lead
    if conversation.segment not in {"PARENT", "ADULT"}:
        booked = bool(lead and lead.calendly_booked)
        in_flow_state = conversation.state not in {"", "START"}
        if booked or (in_flow_state and lead is not None):
            conversation.segment = "PARENT"
        else:
            conversation.segment = (
                _match_active_program_segment(message_text)
                or _classify_segment(message_text)
            )

    # PARENT Reschedule State + Segment Override Patch (2026-06-10).
    # A sticky ADULT segment (from earlier adult-event testing) must NOT
    # swallow an explicit camp-consultation / reschedule message. Flip to
    # PARENT deterministically — the lead's PARENT fields are preserved,
    # so the booking/reschedule flow continues with the known child age /
    # name / phone instead of re-running adult-event handling.
    if (
        conversation.segment == "ADULT"
        and _is_parent_consultation_intent(message_text)
    ):
        logger.info(
            "[routing] consultation/reschedule intent overrides ADULT → "
            "PARENT (sender=%s)",
            sentry_service.mask_sender(sender_id),
        )
        conversation.segment = "PARENT"

    # Explicit CAMP ACTION overrides a sticky ADULT segment (live bug
    # 2026-06-25). After a switch to adult events, „ბანაკის სარეგისტრაციო ლინკი
    # მომწერე" routed to the adult flow and asked the child's age instead of
    # returning the camp link, because the sticky ADULT segment is only flipped
    # for consultation/reschedule above. An EXPLICIT camp registration request
    # (camp keyword + link/form/registration) must route back to the PARENT
    # flow, where `_maybe_handle_camp_registration_link` returns the configured
    # link. Camp-keyword/camp-context gated (see legacy_actions), so a bare
    # „ლინკი მომწერე" in an adult context still stays ADULT.
    if conversation.segment == "ADULT":
        from app.reasoning.legacy_actions import detect_legacy_explicit_action
        _legacy_act = detect_legacy_explicit_action(message_text, conversation)
        if _legacy_act.get("action") == "camp_registration_link":
            logger.info(
                "[routing] explicit camp registration overrides ADULT → PARENT "
                "(sender=%s)", sentry_service.mask_sender(sender_id),
            )
            conversation.segment = "PARENT"

    # Conversation Planner (Phase 3) — compute the unified TurnPlan ONCE per turn
    # and stash it on the conversation so the downstream handlers (parent_flow)
    # reuse the SAME decision instead of recomputing (no drift). Class 1: this
    # runs BEFORE every flow handler, so the planner output is available to the
    # Sunday-School / pending / static handlers. Classes 2 + 5 (topic-routing
    # authority + state writebacks) apply ONLY in AUTHORITATIVE mode.
    plan = _maybe_compute_plan(conversation, message_text)
    conversation._turn_plan = plan          # transient (not persisted)
    route_segment = conversation.segment
    if plan is not None:
        _trace.set(
            planner_intent=getattr(plan, "user_current_intent", "unclear"),
            planner_active_topic=getattr(plan, "active_topic", "none"),
            planner_forbidden=list(
                getattr(plan, "forbidden_response_patterns", []) or []
            ),
        )
        # Class 3 — record the topic-scoped selected_state in the trace (visible
        # regardless of slim/giant prompt mode). Never raises.
        try:
            from app.reasoning import selected_state as _ss
            _trace.set(
                selected_state=_ss.format_selected_state(
                    _ss.build_selected_state(plan, conversation.lead, conversation),
                ),
            )
        except Exception:  # pragma: no cover — trace must never break a reply
            pass
        if _planner_authoritative():
            # Class 5 — apply state writebacks (adult_age self-correction) BEFORE
            # routing so the chosen flow sees the corrected state.
            _planner_apply_writebacks(conversation, plan)
            # Class 2 — topic-routing authority: the planner's active_topic /
            # intent decides which flow handles THIS turn. A clear domain switch
            # (adult_event / camp) is sticky; a neutral intent the parent flow
            # answers deterministically (state recall / manager phone / decline /
            # registration) routes to PARENT for THIS turn WITHOUT flipping the
            # sticky segment.
            route_segment, persist = _planner_route_decision(
                plan, conversation.segment,
            )
            if route_segment != conversation.segment:
                logger.info(
                    "[planner][route] active_topic=%s intent=%s segment=%s→%s "
                    "persist=%s (sender=%s)",
                    plan.active_topic, plan.user_current_intent,
                    conversation.segment, route_segment, persist,
                    sentry_service.mask_sender(sender_id),
                )
                if persist and route_segment in {"PARENT", "ADULT"}:
                    conversation.segment = route_segment

    _planner_intent = (
        getattr(plan, "user_current_intent", "") if plan is not None else ""
    )
    _deterministic = bool(plan is not None and _planner_authoritative())

    # Greeting after a closed/declined context → neutral re-orientation menu
    # (no stale camp/age continuation). Short-circuits BEFORE any flow handler.
    if _deterministic and _planner_intent == "greeting_after_decline":
        from app.reasoning import response_policy as _rp
        conversation.segment = "UNCLEAR"        # re-classify fresh next turn
        response = _rp.neutral_menu(settings.COMPANY_NAME)
        _trace.set(route="greeting_after_decline", segment="UNCLEAR",
                   answered_by="response_policy.neutral_menu")
    elif _deterministic and _planner_intent == "subscription_request":
        # #6 — subscription consent → confirm with KNOWN name + MASKED phone
        # (never ask the adult age, never expose the full phone). Sets the
        # confirm-pending marker so the next „კი" saves.
        response = _handle_subscription_request(conversation)
    elif _deterministic and _planner_intent == "subscription_save":
        # #6 — the user confirmed → save via the existing subscription service.
        response = _handle_subscription_save(conversation)
    elif route_segment == "UNCLEAR":
        _trace.set_route_decision(
            route_owner="conversation_service",
            domain="unknown",
            intent="unclear_routing",
            answer_source="unclear_menu",
            deterministic_reason="top_level_segment_route",
        )
        # Identity-question short-circuit: when the user asks "ბოტი
        # ხარ?" / "AI ხარ?" while still in the unclear-segment menu,
        # answer briefly with the brand identity instead of just
        # re-sending the routing menu. Stays on-policy (no engine
        # mention, no model name).
        identity_reply = _maybe_identity_reply(message_text)
        if identity_reply is not None:
            response = identity_reply
        elif _is_registration_link_request(message_text):
            # Registration/link request with NO clear target (UNCLEAR
            # segment). When camp registration is closed, fail closed to the
            # canonical camp lifecycle answer instead of asking for a linkable
            # program and risking a stale registration CTA.
            if not parent_flow._is_camp_registration_open():
                _trace.set_route_decision(
                    route_owner="conversation_service",
                    domain="camp",
                    intent="camp_registration",
                    sub_intent="registration_link",
                    answer_source="deterministic_handler",
                    approved_copy_id="camp_registration_closed",
                    deterministic_reason="unclear_closed_registration_request",
                )
                response = parent_flow._camp_registration_closed_short_answer()
            else:
                response = _REGISTRATION_LINK_CLARIFICATION
        else:
            response = _maybe_dynamic_welcome(
            UNCLEAR_ROUTING.format(company_name=settings.COMPANY_NAME).strip())
    elif route_segment == "PARENT":
        _trace.set(route="parent_flow", segment="PARENT")
        _trace.set_route_decision(
            route_owner="parent_flow",
            domain="camp",
            segment_after="PARENT",
            answer_source="unknown",
            deterministic_reason="top_level_segment_route",
        )
        response = parent_flow.handle(conversation, message_text)
    elif route_segment == "ADULT":
        # The Conversation Planner is authoritative inside parent_flow.handle;
        # on the ADULT route the planner's topic decision already steered us
        # here, the writeback ran above, and the central final validator below
        # enforces the forbidden-pattern policy on the adult engine's answer.
        _trace.set(
            route="adult_flow", segment="ADULT",
            planner_applies_on_route=bool(plan is not None and _planner_authoritative()),
        )
        _trace.set_route_decision(
            route_owner="adult_flow",
            domain="adult_events",
            segment_after="ADULT",
            answer_source="unknown",
            deterministic_reason="top_level_segment_route",
        )
        response = adult_flow.handle(conversation, message_text)
    else:
        _trace.set(route="unclear_routing", segment=route_segment)
        _trace.set_route_decision(
            route_owner="conversation_service",
            domain="unknown",
            intent="unclear_routing",
            segment_after=route_segment,
            answer_source="unclear_menu",
            deterministic_reason="top_level_segment_route",
        )
        response = _maybe_dynamic_welcome(
            UNCLEAR_ROUTING.format(company_name=settings.COMPANY_NAME).strip())

    # Response composer policy (Stage 3) — consultant-quality refinement of the
    # FINAL answer based on the planner intent + selected_state (eligible-age
    # pain-point discovery, consultation-CTA wording, concise/no-double-thanks).
    # Reasoning-driven, gated on AUTHORITATIVE mode; fail-closed.
    if plan is not None and _planner_authoritative():
        response = _apply_response_policy(conversation, plan, message_text, response)

    # Class 6 — central final validator (last safety layer). Enforces the
    # planner's forbidden-response patterns on the FINAL answer regardless of
    # route (parent / adult). Prefers upstream routing/context fixes; this only
    # catches a leaked violation before the reply is sent. Gated on
    # AUTHORITATIVE mode + a plan; fail-closed (never raises).
    if plan is not None and _planner_authoritative():
        _before = response
        response = _planner_final_validate(conversation, plan, response)
        _trace.set(
            final_validator_ran=True,
            final_validator_changed=(response != _before),
        )

    # Central PII chokepoint (Response Planner Hardening, 2026-06-23) — the
    # user's OWN stored phone must NEVER be echoed back in clear over an
    # unauthenticated channel. Masks `lead.phone` (any spacing / +995 prefix)
    # → „595***733" on EVERY outgoing reply (parent / adult / unclear), so even
    # a typo'd state-recall question that slips past the masked deterministic
    # handler and reaches the LLM cannot leak the full number. The manager phone
    # (a different, intentionally-disclosed number) is untouched.
    response = _mask_user_phone_in_response(conversation, response)

    conversation.history.append({"role": "assistant", "content": response})
    # P3-C PATCH 3 — capture post-response follow-up markers. Knowing
    # when the bot last spoke lets the scheduler decide whether the
    # 24h / 3d / 7d window has elapsed.
    conversation.last_bot_message_at = datetime.utcnow().isoformat()
    _record_post_response_followup_markers(conversation)

    # P3-B — write-through to Redis so a server restart can restore
    # state. TTL refreshes on every save (rolling 8-day conversation window).
    _save_conversation_to_redis(conversation)

    # Durable lead memory (USE_LEAD_MEMORY, Phase 4 Task 3) — best-effort
    # persist of identity facts keyed by the SAME session key
    # `lead_memory_service.maybe_seed_new_lead` reads from, so a returning
    # lead's facts survive past the conversation's own Redis TTL.
    if getattr(settings, "USE_LEAD_MEMORY", False) and conversation.lead is not None:
        try:
            from app.services import lead_memory_service
            lead_memory_service.save(
                conversation_cache_key(conversation),
                conversation.lead,
            )
        except Exception:  # pragma: no cover - best-effort
            pass

    # Bounded learning log (USE_LEARNING, Phase 5 Task 3) — flag-gated,
    # best-effort outcome logging at the same post-response chokepoint as
    # the Phase-4 lead-memory save hook immediately above. Wrapped in a
    # bare except so a classification/logging failure can NEVER change the
    # `response` already computed above (turn integrity comes first).
    if getattr(settings, "USE_LEARNING", False):
        try:
            from app.reasoning.outcome_classifier import classify_outcome
            from app.services import learning_log_service
            from app.agent.tools import parent_tool_executor
            key = conversation_cache_key(conversation)
            manager_notified = bool(
                parent_tool_executor.manager_notified_for_conversation.get(key)
            )
            outcome = classify_outcome(
                conversation, conversation.lead, response,
                manager_notified=manager_notified,
            )
            learning_log_service.log_turn({
                "ts": datetime.utcnow().isoformat(),
                "session_key": key,
                "segment": getattr(conversation, "segment", "") or "",
                "program_id": "",
                "outcome": outcome,
                "question": (message_text or "")[:200],
                "answer_preview": (response or "")[:200],
            })
        except Exception:  # pragma: no cover - best-effort; logging must never break a turn
            pass

    _trace.set_route_decision(
        segment_after=conversation.segment or route_segment or "",
        state_after=conversation.state or "",
    )

    _lead = conversation.lead
    _trace.set(
        final_answer=(response or "")[:200],
        lead_after={
            "name_exists": bool((getattr(_lead, "name", "") or "").strip()) if _lead else False,
            "phone": _trace.mask_phone(getattr(_lead, "phone", "") if _lead else ""),
            "child_age": getattr(_lead, "child_age", "") if _lead else "",
            "adult_age": getattr(_lead, "adult_age", "") if _lead else "",
            "adult_target_age": getattr(_lead, "adult_target_age", "") if _lead else "",
            "adult_target_relation": getattr(_lead, "adult_target_relation", "") if _lead else "",
            "booked_datetime_iso": getattr(_lead, "booked_datetime_iso", "") if _lead else "",
            "state": conversation.state,
            "pending_booking_exists": bool(conversation.pending_booking),
        },
    )
    _trace.emit()
    return response


# -- P3-C PATCH 3 — follow-up marker capture ------------------------------


_USER_DECLINE_PHRASES: tuple[str, ...] = (
    "არ მინდა", "არა მადლობა", "უარს ვამბობ", "გავაუქმოთ", "არ მსურს",
)
_USER_WILL_THINK_PHRASES: tuple[str, ...] = (
    "დავფიქრდები", "მერე", "მოგვიანებით", "შემდეგ", "გადავწყვეტ",
)
_USER_NO_MORE_PHRASES: tuple[str, ...] = (
    "აღარ მომწეროთ", "ნუ მომწერთ", "მეტი არ მინდა",
)
_PRICE_INTEREST_KEYWORDS: tuple[str, ...] = (
    "ფასი", "ღირს", "ღირებულება", "რამდენი", "გადახდა",
)
_AGE_PROVIDED_KEYWORDS: tuple[str, ...] = (
    "წლის", "წლისაა", "წლისა",
)


def _record_pre_response_followup_markers(
    conversation, message_text: str,
) -> None:
    """Detect lightweight signals on the inbound user message and stash
    them on the Conversation for a future scheduler. Never raises.

    Follow-up Test Mode Patch (2026-06-06): a single masked-sender log
    line surfaces blocked-reason transitions so an operator running a
    live follow-up test can see at a glance why a conversation became
    ineligible. Other marker writes (stopped_after / interest) stay
    quiet to keep the per-turn log volume low.
    """
    try:
        from app.services import sentry_service
    except Exception:  # pragma: no cover — defensive import
        sentry_service = None  # type: ignore[assignment]

    def _log_blocked(reason: str) -> None:
        if sentry_service is None:
            return
        try:
            logger.info(
                "[FOLLOWUP] marker_skipped sender=%s reason=%s",
                sentry_service.mask_sender(
                    getattr(conversation, "sender_id", "") or "",
                ),
                reason,
            )
        except Exception:
            pass

    try:
        text = (message_text or "").lower().strip()
        if not text:
            return

        # Explicit decline — strongest signal.
        if any(p in text for p in _USER_NO_MORE_PHRASES):
            conversation.followup_blocked_reason = "asked_no_more_messages"
            _log_blocked("asked_no_more_messages")
            return
        if any(p in text for p in _USER_DECLINE_PHRASES):
            conversation.followup_blocked_reason = "declined"
            conversation.stopped_after = "decline"
            _log_blocked("declined")
            return

        # "Will think about it" — supportive close, follow-up later.
        if any(p in text for p in _USER_WILL_THINK_PHRASES):
            conversation.stopped_after = "will_think"
            return

        # Price interest — meaningful interest signal.
        if any(kw in text for kw in _PRICE_INTEREST_KEYWORDS):
            conversation.last_meaningful_interest = "price"
            conversation.stopped_after = "price"
            return

        # Age provided — record so the scheduler picks the age scenario.
        if any(kw in text for kw in _AGE_PROVIDED_KEYWORDS):
            conversation.stopped_after = "age"
            return
    except Exception:
        # Marker capture must never break the message pipeline.
        return


def _record_post_response_followup_markers(conversation) -> None:
    """After the bot responds, mark booking / manager-handoff completion
    so the scheduler skips this lead in the future."""
    try:
        from app.services import sentry_service
    except Exception:  # pragma: no cover — defensive
        sentry_service = None  # type: ignore[assignment]

    def _log_blocked(reason: str) -> None:
        if sentry_service is None:
            return
        try:
            logger.info(
                "[FOLLOWUP] marker_skipped sender=%s reason=%s",
                sentry_service.mask_sender(
                    getattr(conversation, "sender_id", "") or "",
                ),
                reason,
            )
        except Exception:
            pass

    try:
        lead = conversation.lead
        if lead is None:
            return
        prior_reason = getattr(conversation, "followup_blocked_reason", "") or ""
        if getattr(lead, "calendly_booked", False):
            conversation.followup_blocked_reason = "booked"
            if prior_reason != "booked":
                _log_blocked("booked")
            return
        # Manager-handoff completion is tracked via the executor's
        # module-level dict. Read it lazily to avoid a circular import.
        try:
            from app.agent.tools.parent_tool_executor import (
                manager_notified_for_conversation,
            )
            cache_key = conversation_cache_key(conversation)
            if (
                manager_notified_for_conversation.get(cache_key)
                or manager_notified_for_conversation.get(conversation.sender_id)
            ):
                # Only block follow-ups if the user has not been declined;
                # decline takes priority.
                if conversation.followup_blocked_reason not in {
                    "declined", "asked_no_more_messages",
                }:
                    conversation.followup_blocked_reason = "manager_handoff_completed"
                    if prior_reason != "manager_handoff_completed":
                        _log_blocked("manager_handoff_completed")
        except Exception:
            pass
    except Exception:
        return


def get_all_conversations_snapshot() -> list[Conversation]:
    """Return a copy of every active in-memory Conversation.

    Used by the follow-up scheduler to scan eligible parents without
    holding a reference to the mutable module-level ``conversations``
    dict. The returned list is a fresh container — appending / popping
    from it does not affect the live store — but the Conversation
    objects themselves are still the live ones (the scheduler
    legitimately needs to read/update their followup_stage and
    write-through to Redis after a send).

    Limitation: this is the in-memory snapshot only. A one-off CLI
    invocation (`python -c "from app.services import followup_service;
    followup_service.check_and_send_followups()"`) starts with an
    empty in-memory dict and would silently skip every conversation
    the live server is holding. Use ``hydrate_from_redis()`` BEFORE
    calling the scheduler from a one-off process — both the live
    server and the legacy in-memory tests work unchanged.
    """
    return list(conversations.values())


def hydrate_from_redis() -> int:
    """Follow-up Live-Test Hydrate Patch (2026-06-06).

    Load every Redis-persisted Conversation into the in-memory
    ``conversations`` dict. Idempotent -- a session that already lives
    in memory is left untouched (the live process is the source of
    truth for fresh state).

    Returns the number of conversations loaded. Safe no-op when Redis
    is disabled / unreachable. Never raises.

    Use from a one-off CLI process before invoking
    ``followup_service.check_and_send_followups()`` so the scheduler
    sees the same conversations the live server is holding.
    """
    if not redis_state_service.is_enabled():
        logger.info("[FOLLOWUP] hydrate skipped -- redis disabled/unavailable")
        return 0
    try:
        keys = redis_state_service.scan_keys("conversation:*")
    except Exception as exc:
        logger.warning("[FOLLOWUP] hydrate scan failed: %s", exc)
        return 0

    loaded = 0
    skipped_existing = 0
    skipped_invalid = 0
    for key in keys:
        try:
            payload = redis_state_service.get_json(key)
        except Exception as exc:
            logger.warning(
                "[FOLLOWUP] hydrate read key=%s failed: %s", key, exc,
            )
            skipped_invalid += 1
            continue
        if not payload:
            skipped_invalid += 1
            continue
        try:
            conv = Conversation.from_dict(payload)
            session_key = _ensure_conversation_identity(conv)
        except Exception as exc:
            logger.warning(
                "[FOLLOWUP] hydrate deserialise key=%s failed: %s",
                key, exc,
            )
            skipped_invalid += 1
            continue
        if session_key in conversations:
            skipped_existing += 1
            continue
        conversations[session_key] = conv
        loaded += 1

    logger.info(
        "[FOLLOWUP] hydrate complete keys=%d loaded=%d skipped_existing=%d "
        "skipped_invalid=%d",
        len(keys), loaded, skipped_existing, skipped_invalid,
    )
    return loaded


def _get_or_create_conversation(
    sender_id: str,
    platform: str,
    page_id: str = "",
) -> Conversation:
    session_key = _conversation_session_key(sender_id, platform, page_id)
    if session_key in conversations:
        return conversations[session_key]

    # In-memory miss -- try Redis restore before creating a fresh one.
    # This is the P3-B restart-safety path: server restart wipes the
    # in-memory dict but Redis still holds the last-known Conversation.
    restored = _load_conversation_from_redis(sender_id, platform, page_id)
    if restored is not None:
        logger.info(
            "[redis] conversation restored sender=%s platform=%s page_id=%s "
            "state=%s segment=%s pending_booking=%s",
            sender_id, platform, page_id, restored.state, restored.segment,
            bool(restored.pending_booking),
        )
        conversations[restored.session_key] = restored
        return restored

    conversation = Conversation(sender_id=sender_id, platform=platform, page_id=page_id)
    _ensure_conversation_identity(conversation)
    conversations[conversation.session_key] = conversation
    return conversation

def reset_conversation_for_sender(sender_id: str) -> bool:
    """P3-C PATCH 7 — clear ALL per-sender state for QA / tests.

    Returns True when something was actually cleared.

    Wipes the conversation entry plus every per-sender entry in the
    in-memory module-level dicts (slot caches, retry counters,
    manager-notified flag, tool-success flag, adult selected event,
    message-buffer queues). Intended for manual QA where multiple
    scenarios are tested back-to-back from the same sender_id without a
    process restart; production traffic never calls this.

    Not a magic teardown — it does NOT delete Calendar events or Sheets
    rows. Use a fresh sender_id between QA scenarios when you want a
    truly clean lead in the CRM.
    """
    cleared = False

    def _cache_key_matches_sender(key: object) -> bool:
        key_text = str(key or "")
        return key_text == sender_id or key_text.endswith(f":{sender_id}")

    conversation_keys = [
        key for key, conv in list(conversations.items())
        if key == sender_id or getattr(conv, "sender_id", None) == sender_id
    ]
    for key in conversation_keys:
        conversations.pop(key, None)
        cleared = True

    try:
        from app.flows import parent_flow, parent_turn_router
        for d in (
            parent_flow.available_slots,
            parent_flow.ask_name_retries,
            parent_flow.invalid_phone_retries,
            parent_flow.slots_shown_for_state,
            parent_turn_router.manager_offer_shown,
        ):
            keys = [key for key in list(d.keys()) if _cache_key_matches_sender(key)]
            for key in keys:
                d.pop(key, None)
                cleared = True
    except Exception:
        pass

    try:
        from app.flows import adult_flow
        keys = [
            key for key in list(adult_flow.selected_events.keys())
            if _cache_key_matches_sender(key)
        ]
        for key in keys:
            adult_flow.selected_events.pop(key, None)
            cleared = True
    except Exception:
        pass

    try:
        from app.agent.tools import parent_tool_executor
        for d in (
            parent_tool_executor.manager_notified_for_conversation,
            parent_tool_executor._last_slots_by_sender,
            parent_tool_executor.book_consultation_success_for_conversation,
        ):
            keys = [key for key in list(d.keys()) if _cache_key_matches_sender(key)]
            for key in keys:
                d.pop(key, None)
                cleared = True
    except Exception:
        pass

    try:
        from app.services import message_buffer
        for attr in (
            "_pending_messages",
            "_pending_tasks",
            "_buffer_started_at",
            "_locks",
        ):
            d = getattr(message_buffer, attr, None)
            if isinstance(d, dict):
                keys = [
                    key for key in list(d.keys())
                    if _cache_key_matches_sender(key)
                ]
                for key in keys:
                    d.pop(key, None)
                    cleared = True
    except Exception:
        pass

    return cleared


def _flow_context(conversation: Conversation, message_text: str) -> FlowContext:
    return FlowContext(
        conversation=conversation,
        message_text=message_text,
        content=content_repository,
    )


def _segment_tone(segment: str) -> str:
    if segment == "PARENT":
        return settings.COMPANY_TONE_PARENTS
    if segment == "ADULT":
        return settings.COMPANY_TONE_ADULTS
    return ""


def _extract_template_section(text: str, marker: str) -> str:
    lines = text.splitlines()
    collected = []
    in_section = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("===") and stripped.endswith("==="):
            title = stripped.strip("= ").upper()
            if in_section:
                break
            in_section = marker in title
            continue
        if in_section:
            collected.append(line)

    return "\n".join(collected).strip()
