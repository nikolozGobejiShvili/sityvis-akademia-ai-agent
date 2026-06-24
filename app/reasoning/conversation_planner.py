"""Conversation Planner / State-Context Contract — Reasoning Layer Phase 3
(2026-06-24).

ONE unified, DETERMINISTIC planning layer that decides what the CURRENT turn is
about and produces ONE structured decision (`TurnPlan`) for the response layer.
It is a CLASSIFICATION / PLANNING contract — NOT a pile of per-phrase handlers.

Design constraints (operator):
  * NO path explosion — one classifier maps stem-groups → an intent ENUM →
    one answer_policy + state-authority decision. Adding an intent is a new enum
    value, never a new runtime handler/path.
  * Current explicit user intent OVERRIDES stale/pending state unless the user
    is clearly continuing the same flow.
  * adult_age and child_age stay strictly separate.
  * Confirmed booking is authoritative for BOTH state recall and booking recall.
  * Topic switch / decline CLEARS incompatible pending context.

It builds ON TOP of the existing Turn Intent Gateway
(`reasoning_layer.analyze_turn_intent`) + the lead/booking/pending state, so it
re-detects almost nothing. It is METADATA-ONLY: it NEVER answers the user,
NEVER calls the LLM, NEVER touches Calendar/Sheets/WhatsApp/email, NEVER mutates
state. Fail-closed: any error → a low-confidence `unclear` plan so the caller
keeps the existing deterministic behaviour.

STAGE 1 (this module): the contract + classifier + offline tests, behind the
default-OFF flag `USE_CONVERSATION_PLANNER` and wired only in SHADOW (log-only)
mode. Making the plan AUTHORITATIVE over the handlers / LLM context is Stage 2
(separate, approval-gated, live-verified).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

# ── State keys (stable identifiers used in state_to_use/ignore/clear) ──────────
S_NAME = "name"
S_PHONE = "phone_masked"
S_CHILD_AGE = "child_age"
S_ADULT_AGE = "adult_age"
S_CONFIRMED_BOOKING = "confirmed_booking"
S_PENDING_BOOKING = "pending_booking"
S_ADULT_TARGET = "adult_event_target"      # adult_target_relation/_age
S_CHALLENGE = "challenge_interest"

# ── Forbidden-response policy flags (consumed by a Stage-2 validator) ──────────
F_NO_REASK_CHILD_AGE = "do_not_ask_child_age_again"
F_NO_CAMP_ELIGIBILITY_FOR_ADULT = "do_not_answer_adult_event_as_camp_eligibility"
F_NO_CONSULTATION_FORMAT = "do_not_use_consultation_format_for_camp_safety"
F_NO_CONTINUE_BOOKING = "do_not_continue_booking_on_state_recall"
F_NO_DATE_TIME_QUESTION = "do_not_ask_date_time"
F_NO_NEW_CONSULTATION = "do_not_offer_new_consultation_when_booked"
F_NO_SLOT_UNAVAILABLE_OWN = "do_not_say_slot_unavailable_for_own_booking"
F_NO_ADULT_AGE_AS_CHILD = "do_not_treat_adult_age_as_child_age"
F_NO_REGISTRATION_LINK = "do_not_return_registration_link_for_consultation"
F_NO_FULL_PHONE = "do_not_leak_full_phone"
F_NO_REPEAT_WRONG_FALLBACK = "do_not_repeat_wrong_fallback_after_correction"
F_NO_NAMED_EVENT_LOOKUP = "do_not_treat_generic_discovery_as_named_event_lookup"
F_NO_INVENT_FACTS = "do_not_invent_unspecified_facts"
F_MUST_RETURN_MANAGER_PHONE = "must_return_manager_phone"
F_MUST_RETURN_REGISTRATION_LINK = "must_return_registration_link"
F_NO_ROBOTIC_DECLINE_PHRASE = "do_not_use_robotic_decline_phrase"
F_NO_REASK_KNOWN_CONTACT = "do_not_reask_known_name_or_phone"

# ── Camp sub-intent stem groups (classification, NOT handlers) ────────────────
_CAMP_CONTACT = ("დავურეკ", "დაურეკ", "დარეკ", "დაკავშირდე", "დაკავშირება ბავშვ")
_CAMP_VISIT = ("მოვინახულ", "მონახულ", "ვიზიტ", "ნახვა მინდა", "ადგილზე მისვლ", "მივიდე ბანაკ")
_CAMP_SAFETY = ("უსაფრთხ", "დაცულ", "ზედამხედვ", "ექიმ", "სამედიცინ", "მეთვალყურ")
_CAMP_GUESTS = ("მოწვე", "სტუმ")
_CAMP_ACTIVITIES = ("აქტივ", "თამაშ", "ინტელექტ", "გასართ", "ჩაკეტ", "მეგობრ", "განვითარ", "პროგრამა")
_CAMP_DATES = ("როდის", "თარიღ", "ნაკად", "რიცხვ", "როდიდან", "რა დროს")
_CAMP_PRICE = ("ფასი", "ღირ", "გადახდ", "განვადებ")

# ── Adult-age self-statement markers (Class 5 — adult age self-correction) ────
# A genuine self-age CORRECTION reads as „ჩემი ასაკი 29 …" (an explicit „my
# age" statement) and/or attributes the other number to the child („ეგ ჩემი
# შვილის ასაკია"). These are intentionally NARROW so a normal adult-self
# DISCOVERY turn („მე ვარ 30 წლის, რა შემომთავაზებთ?") is NOT swallowed — that
# is plain adult-event discovery (handled by the adult_event branch, which
# writes the adult age back on its own).
_ADULT_SELF_AGE_MARKERS = ("ჩემი ასაკი", "ჩემი ასაკია")
_CHILD_AGE_ATTRIBUTION_MARKERS = ("შვილის ასაკი", "ბავშვის ასაკი")

# ── Registration intent markers (used only as a planner-side fallback) ────────
_REGISTRATION_STEMS = ("რეგისტრ", "სარეგისტრაც", "დარეგისტრ", "დავრეგისტრ")

# ── Name/phone-update statement markers (NOT questions) ───────────────────────
_NAME_UPDATE = ("მქვია", "სახელია", "მერქმევა", "დამიძახე")
_TIME_SELECTION = (
    "საათზე", "საათი", "12:00", "11:00", "13:00", "სთ-ზე",
    "ჩამწერ", "ჩამნიშნ", "ჩამიწერ",   # „ჩამწერეთ" — the მ-infix form misses „ჩაწერ"
)


@dataclass
class TurnPlan:
    """One structured planning decision for the current turn. Internal metadata
    only — never user-facing text."""
    user_current_intent: str = "unclear"
    active_topic: str = "none"               # camp|consultation|adult_event|sunday_school|general_state|none
    state_to_use: list[str] = field(default_factory=list)
    state_to_ignore: list[str] = field(default_factory=list)
    state_to_clear: list[str] = field(default_factory=list)
    answer_policy: str = "safe_fallback"
    forbidden_response_patterns: list[str] = field(default_factory=list)
    should_ask_clarifying_question: bool = False
    should_offer_consultation: bool = False
    should_continue_booking: bool = False
    should_answer_directly: bool = False
    should_use_confirmed_booking: bool = False
    should_handoff_to_manager: bool = False
    should_call_tools: bool = False
    should_not_call_tools: bool = False
    # adult/child separation (kept explicit so the response layer never mixes)
    adult_age: str | None = None
    child_age: str | None = None
    wants_for_child: bool = False
    # State WRITEBACKS (Class 5, 2026-06-24). The planner is metadata-only and
    # NEVER mutates state itself; when one of these is set, the AUTHORITATIVE
    # apply step (`conversation_service` / `parent_flow`) performs the write.
    # `writeback_adult_age` captures a self-age correction
    # („ჩემი ასაკი 29 წელია…") onto `lead.adult_age` WITHOUT touching
    # `lead.child_age`. Empty = no writeback.
    writeback_adult_age: str | None = None
    writeback_child_age: str | None = None
    confidence: float = 0.0
    reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def plan_turn(message: str, conversation=None) -> TurnPlan:
    """Produce ONE planning decision for the current turn. Never raises."""
    try:
        return _plan(message, conversation)
    except Exception:  # pragma: no cover — planner must never break a reply
        return TurnPlan(reason="planner-error-failclosed", confidence=0.0)


def _lead_of(conversation):
    return getattr(conversation, "lead", None)


def _booked(lead) -> bool:
    if lead is None:
        return False
    if bool(getattr(lead, "calendly_booked", False)):
        return True
    return bool((getattr(lead, "booked_datetime_iso", "") or "").strip())


def _plan(message: str, conversation) -> TurnPlan:
    text = (message or "").strip()
    if not text:
        return TurnPlan(reason="empty-message", confidence=0.0)
    low = text.lower()

    from app.reasoning.reasoning_layer import analyze_turn_intent
    gw = analyze_turn_intent(message, conversation)

    lead = _lead_of(conversation)
    child_age = (getattr(lead, "child_age", "") or "").strip() if lead else ""
    adult_age = (getattr(lead, "adult_age", "") or "").strip() if lead else ""
    name = (getattr(lead, "name", "") or "").strip() if lead else ""
    phone = (getattr(lead, "phone", "") or "").strip() if lead else ""
    target_rel = (getattr(lead, "adult_target_relation", "") or "").strip() if lead else ""
    target_age = (getattr(lead, "adult_target_age", "") or "").strip() if lead else ""
    pending = getattr(conversation, "pending_booking", None) if conversation else None
    is_booked = _booked(lead)

    # State-recall is typo-tolerant via the gateway (`is_state_recall`) — which we
    # now CONSUME here (it was a dead signal) — OR the explicit recall stems used
    # by the deterministic memory handler.
    is_recall = bool(getattr(gw, "is_state_recall", False)) or _matches_recall(low)
    is_name_q = _matches_name_recall(low)
    is_phone_q = _matches_phone_recall(low)

    plan = TurnPlan(confidence=getattr(gw, "confidence", 0.0))
    plan.child_age = child_age or None
    plan.adult_age = adult_age or None

    # Universal: full phone is always masked in the user-facing reply.
    plan.forbidden_response_patterns.append(F_NO_FULL_PHONE)

    seg = (getattr(conversation, "segment", "") or "").upper()
    adult_ctx = seg == "ADULT" or _recent_adult_context(conversation)

    # ── 0. Manager-phone request (HIGHEST priority) ───────────────────────────
    # An explicit „მენეჯერის ნომერი" / „მე თვითონ დავურეკავ" request must be
    # answered with the manager number on THIS turn — even mid Sunday-School
    # collection or mid-booking. Class 1: it OVERRIDES pending Sunday-School /
    # adult-event context so a pending collection can never swallow it.
    if getattr(gw, "is_manager_phone_request", False):
        plan.user_current_intent = "manager_phone_request"
        plan.active_topic = "manager_contact"
        plan.answer_policy = "give_manager_phone"
        plan.should_answer_directly = True
        plan.should_handoff_to_manager = True
        plan.should_not_call_tools = True
        plan.state_to_ignore = [S_PENDING_BOOKING, S_ADULT_TARGET]
        plan.forbidden_response_patterns.append(F_MUST_RETURN_MANAGER_PHONE)
        plan.reason = "explicit manager-phone request (overrides pending state)"
        return plan

    # ── 0b. Adult-age self-correction (Class 5) ───────────────────────────────
    # „ჩემი ასაკი 29 წელია, ეგ ჩემი შვილის ასაკია" → write adult_age=29, keep
    # child_age. The planner is metadata-only; the writeback is applied by the
    # authoritative caller. active_topic stays adult_event when that was the
    # current topic; otherwise it is a neutral state update.
    if _is_adult_age_self_statement(low, gw):
        gw_age = getattr(gw, "age", None)
        plan.user_current_intent = "adult_age_correction"
        plan.adult_age = str(gw_age) if gw_age is not None else (adult_age or None)
        plan.writeback_adult_age = plan.adult_age
        plan.child_age = child_age or None          # preserved, never touched
        if adult_ctx:
            plan.active_topic = "adult_event"
            plan.answer_policy = "event_discovery"
            plan.should_call_tools = True
            plan.state_to_use = [S_ADULT_AGE]
            plan.forbidden_response_patterns += [
                F_NO_CAMP_ELIGIBILITY_FOR_ADULT, F_NO_ADULT_AGE_AS_CHILD,
                F_NO_NAMED_EVENT_LOOKUP,
            ]
        else:
            plan.active_topic = "general_state"
            plan.answer_policy = "answer_directly"
            plan.should_answer_directly = True
            plan.forbidden_response_patterns.append(F_NO_ADULT_AGE_AS_CHILD)
        plan.state_to_ignore = [S_PENDING_BOOKING]
        plan.reason = "adult age self-correction (adult_age writeback, child_age preserved)"
        return plan

    # ── 1. Tone request (only when there is no real business question) ────────
    if getattr(gw, "is_human_tone_request", False) and not getattr(gw, "has_question", False) \
            and getattr(gw, "topic", "other") == "other":
        plan.user_current_intent = "tone_request"
        plan.active_topic = "none"
        plan.answer_policy = "answer_directly"
        plan.should_answer_directly = True
        plan.reason = "human tone request (no business question)"
        return plan

    # ── 1b. Name update (explicit STATEMENT) — checked BEFORE recall so
    # „ჩემი სახელია ნიკოლოზი" (a name the user PROVIDES) is not mis-read as a
    # recall question by the `ჩემი\s*სახელ` regex, and never resurrects a stale
    # underage/camp narrative. Recall QUESTIONS („რა მქვია?") have
    # has_question=True and fall through to the recall branch below.
    if any(m in low for m in _NAME_UPDATE) and not getattr(gw, "has_question", False):
        plan.user_current_intent = "name_update"
        plan.active_topic = "general_state"
        plan.answer_policy = "answer_directly"
        plan.should_answer_directly = True
        plan.state_to_ignore = [S_PENDING_BOOKING, S_ADULT_TARGET]
        if child_age:
            plan.forbidden_response_patterns.append(F_NO_REASK_CHILD_AGE)
        plan.reason = "name update (current message overrides stale state)"
        return plan

    # ── 2. State / identity recall (HIGH priority; current message wins) ──────
    if is_recall or is_name_q or is_phone_q:
        plan.user_current_intent = "state_recall"
        plan.active_topic = "general_state"
        plan.answer_policy = "state_recall_summary"
        plan.should_answer_directly = True
        plan.should_not_call_tools = True
        plan.state_to_use = [S_NAME, S_PHONE, S_CHILD_AGE]
        if adult_age:
            plan.state_to_use.append(S_ADULT_AGE)
        if is_booked:
            plan.state_to_use.append(S_CONFIRMED_BOOKING)
            plan.should_use_confirmed_booking = True
        plan.state_to_ignore = [S_PENDING_BOOKING, S_ADULT_TARGET]
        plan.forbidden_response_patterns += [
            F_NO_CONTINUE_BOOKING, F_NO_DATE_TIME_QUESTION,
        ]
        if is_booked:
            plan.forbidden_response_patterns.append(F_NO_NEW_CONSULTATION)
        plan.reason = "state/identity recall"
        return plan

    # ── 3. Decline → close the current sales/event context ────────────────────
    if getattr(gw, "is_decline", False):
        plan.user_current_intent = (
            "adult_event_decline" if (target_rel or target_age) else "decline"
        )
        plan.active_topic = "none"
        plan.answer_policy = "close_context"
        plan.state_to_clear = [S_ADULT_TARGET, S_PENDING_BOOKING]
        plan.should_not_call_tools = True
        # The polite close must never be the robotic „სიამოვნებით." opener.
        plan.forbidden_response_patterns.append(F_NO_ROBOTIC_DECLINE_PHRASE)
        plan.reason = "decline closes pending sales/event context"
        return plan

    # ── 4. Bare registration in an active camp context (Class 5) ──────────────
    # „რეგისტრაცია მინდა" with NO camp keyword falls through the existing
    # camp-keyword-gated `_maybe_handle_camp_registration_link`. When the active
    # context is camp (PARENT segment / known child / recent camp), classify it
    # as camp registration → return the link, never append an age question.
    if (
        getattr(gw, "topic", "other") == "registration"
        or any(s in low for s in _REGISTRATION_STEMS)
    ) and not getattr(gw, "is_consultation_request", False):
        camp_ctx = (
            seg == "PARENT" or bool(child_age) or _has_camp_signal(low)
            or _recent_camp_context(conversation)
        )
        if camp_ctx and not adult_ctx:
            plan.user_current_intent = "camp_registration"
            plan.active_topic = "camp"
            plan.answer_policy = "camp_registration_link"
            plan.should_answer_directly = True
            plan.state_to_use = [S_CHILD_AGE] if child_age else []
            plan.state_to_ignore = [S_ADULT_TARGET, S_PENDING_BOOKING, S_ADULT_AGE]
            plan.forbidden_response_patterns += [
                F_MUST_RETURN_REGISTRATION_LINK, F_NO_DATE_TIME_QUESTION,
            ]
            if child_age:
                plan.forbidden_response_patterns.append(F_NO_REASK_CHILD_AGE)
            plan.reason = "bare registration in active camp context"
            return plan

    # ── 5. Sunday School (clears adult-event + pending booking) ───────────────
    if getattr(gw, "topic", "other") == "sunday_school":
        plan.user_current_intent = "sunday_school"
        plan.active_topic = "sunday_school"
        plan.answer_policy = "answer_directly"
        plan.should_answer_directly = True
        plan.state_to_clear = [S_ADULT_TARGET, S_PENDING_BOOKING]
        plan.state_to_use = []
        if name:
            plan.state_to_use.append(S_NAME)
        if phone:
            plan.state_to_use.append(S_PHONE)
        # Class 1: when the contact is already known, the handoff must NOT
        # re-ask name/phone — it uses the stored contact.
        if name and phone:
            plan.forbidden_response_patterns.append(F_NO_REASK_KNOWN_CONTACT)
        plan.reason = "sunday school status"
        return plan

    # ── 6. Booking recall vs continue booking vs time selection ───────────────
    # Enter on the gateway's booking topic / consultation signal OR an explicit
    # time-selection marker („12 საათზე", „ჩამწერეთ") — the latter covers the
    # მ-infix imperative „ჩამწერეთ" that the gateway's „ჩაწერ" stem misses.
    has_time_selection = any(m in low for m in _TIME_SELECTION)
    if (
        getattr(gw, "topic", "other") == "booking"
        or getattr(gw, "is_consultation_request", False)
        or has_time_selection
    ):
        if is_booked and _matches_recall_when(low):
            plan.user_current_intent = "booking_recall"
            plan.active_topic = "consultation"
            plan.answer_policy = "confirm_existing_booking"
            plan.should_use_confirmed_booking = True
            plan.should_answer_directly = True
            plan.state_to_use = [S_CONFIRMED_BOOKING]
            plan.state_to_ignore = [S_PENDING_BOOKING]
            plan.forbidden_response_patterns += [
                F_NO_NEW_CONSULTATION, F_NO_SLOT_UNAVAILABLE_OWN,
            ]
            plan.reason = "recall of an existing confirmed booking"
            return plan
        # a registration request must NOT yield a registration link mid-consultation
        plan.forbidden_response_patterns.append(F_NO_REGISTRATION_LINK)
        if any(m in low for m in _TIME_SELECTION):
            plan.user_current_intent = "consultation_time_selection"
            plan.answer_policy = "continue_booking"
        else:
            plan.user_current_intent = "consultation_booking"
            plan.answer_policy = "continue_booking"
        plan.active_topic = "consultation"
        plan.should_continue_booking = True
        plan.should_call_tools = True
        plan.state_to_use = [S_NAME, S_CHILD_AGE]
        plan.reason = "consultation booking flow"
        return plan

    # ── 6b. Bare contact phone provided → consultation contact provision ──────
    if getattr(gw, "phone", None):
        plan.user_current_intent = "phone_update"
        plan.active_topic = "consultation"
        plan.answer_policy = "continue_booking"
        plan.should_continue_booking = True
        plan.should_call_tools = True
        plan.state_to_use = [S_NAME, S_PHONE, S_CHILD_AGE]
        plan.reason = "contact phone provided"
        return plan

    # ── 7. Adult event (discovery / for self / child / both) ──────────────────
    # Enter on an explicit adult-event topic OR an adult-self signal (an adult
    # stating their own age + asking what's offered, even with no event word).
    if getattr(gw, "topic", "other") == "adult_event" or getattr(gw, "is_adult_self", False):
        has_self = bool(getattr(gw, "is_self_reference", False)) or bool(getattr(gw, "is_adult_self", False))
        has_child = bool(getattr(gw, "is_child_reference", False))
        gw_age = getattr(gw, "age", None)
        # adult_age = an explicit self age (>=18); NEVER the child's. Persist it
        # (writeback) when the lead has no adult_age yet, so a later state recall
        # / event turn keeps it.
        if gw_age is not None and gw_age >= 18 and has_self:
            plan.adult_age = str(gw_age)
            if not adult_age:
                plan.writeback_adult_age = str(gw_age)
        if has_self and has_child:
            plan.user_current_intent = "adult_event_for_self_and_child"
            plan.wants_for_child = True
            plan.child_age = child_age or None
            if not child_age:
                plan.should_ask_clarifying_question = True   # ask child age ONCE
        elif has_child and not has_self:
            plan.user_current_intent = "adult_event_for_child"
            plan.wants_for_child = True
        elif has_self:
            plan.user_current_intent = "adult_event_for_self"
        else:
            plan.user_current_intent = "adult_event_discovery"
        plan.active_topic = "adult_event"
        plan.answer_policy = "event_discovery"
        plan.should_call_tools = True
        plan.state_to_use = [S_ADULT_AGE] if plan.adult_age else []
        if plan.wants_for_child and child_age:
            plan.state_to_use.append(S_CHILD_AGE)
        plan.state_to_ignore = [S_PENDING_BOOKING]
        plan.forbidden_response_patterns += [
            F_NO_CAMP_ELIGIBILITY_FOR_ADULT, F_NO_ADULT_AGE_AS_CHILD,
        ]
        # Every „events for me / for my child / what do you offer" turn is
        # DISCOVERY, not a named-event lookup — so the gateway's deliberately
        # loose genuine-name gate must never turn it into „ამ სახელით ვერ
        # ვპოულობ". (A turn that truly names a specific event is handled by the
        # existing named-event resolvers, not this planner intent.)
        plan.forbidden_response_patterns.append(F_NO_NAMED_EVENT_LOOKUP)
        plan.reason = "adult event interest"
        return plan

    # ── 8. Camp sub-intents (the messy real-life class) ───────────────────────
    # A camp turn is: an explicit camp/price topic, a camp keyword, OR a
    # camp-flavoured concern (safety / contact / visit / guests / activities)
    # raised by a known camp parent (child_age set or a child reference) — so
    # „უსაფრთხოება დაცულია? რამდენი ზედამხედველი?" continues the camp topic
    # without an explicit „ბანაკი" each time.
    camp_concern = _has_camp_concern(low)
    gw_age = getattr(gw, "age", None)
    # A child-range age statement („13 წლის არის") with no adult-self signal is a
    # camp/parent turn (the child's age), even before child_age is persisted.
    child_age_statement = (
        bool(getattr(gw, "is_age_statement", False))
        and gw_age is not None and gw_age <= 17
        and not getattr(gw, "is_adult_self", False)
    )
    is_camp = (
        getattr(gw, "topic", "other") == "camp"
        or _has_camp_signal(low)
        or (camp_concern and (bool(child_age) or bool(getattr(gw, "is_child_reference", False))))
        or child_age_statement
    )
    if is_camp or getattr(gw, "topic", "other") == "price":
        plan.active_topic = "camp"
        # current camp turn CLEARS leftover adult-event / pending consultation
        # context (topic switch authority) unless the user asks consultation.
        if target_rel or target_age:
            plan.state_to_clear.append(S_ADULT_TARGET)
        if pending and not getattr(gw, "is_consultation_request", False):
            plan.state_to_clear.append(S_PENDING_BOOKING)
        plan.state_to_use = [S_CHILD_AGE] if child_age else []
        plan.state_to_ignore = [S_ADULT_TARGET, S_PENDING_BOOKING, S_ADULT_AGE]
        plan.should_answer_directly = True
        if child_age:
            plan.forbidden_response_patterns.append(F_NO_REASK_CHILD_AGE)

        sub = _camp_subintent(low, gw)
        plan.user_current_intent = sub
        if sub in ("camp_child_contact", "camp_visit_policy", "camp_safety"):
            plan.answer_policy = "answer_directly"
            # these are NOT consultation-format questions
            plan.forbidden_response_patterns.append(F_NO_CONSULTATION_FORMAT)
            if sub in ("camp_safety",):
                # exact supervisor count is not in source-of-truth → offer manager
                plan.should_handoff_to_manager = True
                plan.forbidden_response_patterns.append(F_NO_INVENT_FACTS)
        elif sub == "camp_guests":
            plan.answer_policy = "say_not_available_and_offer_manager"
            plan.should_handoff_to_manager = True
            plan.forbidden_response_patterns.append(F_NO_INVENT_FACTS)
        elif sub == "camp_activities":
            plan.answer_policy = "answer_directly_and_offer_consultation"
            plan.should_offer_consultation = True
            plan.forbidden_response_patterns.append(F_NO_INVENT_FACTS)
        elif sub in ("camp_price", "camp_dates", "camp_age_eligibility", "camp_info"):
            plan.answer_policy = "answer_directly"
        plan.reason = f"camp turn: {sub}"
        return plan

    # ── 9. Off-topic / insult → calm boundary, no event search ────────────────
    if getattr(gw, "is_off_topic", False) or getattr(gw, "is_insult", False):
        plan.user_current_intent = "unclear"
        plan.active_topic = "none"
        plan.answer_policy = "safe_fallback"
        plan.state_to_clear = [S_ADULT_TARGET]
        plan.forbidden_response_patterns.append(F_NO_NAMED_EVENT_LOOKUP)
        plan.reason = "off-topic / insult — calm boundary"
        return plan

    # ── 10. Fallback ──────────────────────────────────────────────────────────
    plan.user_current_intent = "unclear"
    plan.active_topic = "none"
    plan.answer_policy = "ask_one_clarifying_question"
    plan.should_ask_clarifying_question = True
    plan.reason = "ambiguous / low signal"
    return plan


# ── Recall detection (typo-tolerant via gateway; stems reuse the live handler) ─

def _recall_stems():
    """Lazy-import the deterministic memory handler's stem sets so the planner
    never drifts from the live recall triggers (and to avoid an import cycle)."""
    from app.flows import parent_flow as _pf
    return (
        _pf._MEMORY_INFO_TRIGGER_STEMS,
        _pf._NAME_RECALL_TRIGGER_STEMS,
        _pf._PHONE_RECALL_TRIGGER_STEMS,
    )


def _matches_recall(low: str) -> bool:
    general, _name, _phone = _recall_stems()
    return any(s in low for s in general)


def _matches_name_recall(low: str) -> bool:
    _general, name, _phone = _recall_stems()
    return any(s in low for s in name)


def _matches_phone_recall(low: str) -> bool:
    _general, _name, phone = _recall_stems()
    return any(s in low for s in phone)


def _matches_recall_when(low: str) -> bool:
    """A 'when is my consultation / remind me' recall phrasing."""
    has_when = ("როდის" in low) or ("შემახსენ" in low) or ("გახსოვ" in low) \
        or ("რატო" in low) or ("რატომ" in low)
    return has_when and ("კონსულტ" in low or "ჯავშ" in low or "ჩაწერ" in low or "დრო" in low)


# ── Camp signal + sub-intent classification ───────────────────────────────────

def _has_camp_signal(low: str) -> bool:
    return any(s in low for s in ("ბანაკ", "საზაფხულო", "ნაკად", "ლაგერ"))


def _is_adult_age_self_statement(low: str, gw) -> bool:
    """True when the user states THEIR OWN age (>=18) — an adult-age
    self-correction („ჩემი ასაკი 29 წელია, ეგ ჩემი შვილის ასაკია").

    Requires an adult self-age marker AND a self-age ≥ 18 from the gateway. A
    child age statement („7 წლის არის") never matches (no self marker; age<18)."""
    gw_age = getattr(gw, "age", None)
    if gw_age is None or gw_age < 18:
        return False
    has_self_marker = any(m in low for m in _ADULT_SELF_AGE_MARKERS)
    # „… ჩემი შვილის ასაკია" reinforces (the OTHER number was the child's).
    attributes_child = any(m in low for m in _CHILD_AGE_ATTRIBUTION_MARKERS)
    return has_self_marker or attributes_child


def _last_assistant_content(conversation) -> str:
    for turn in reversed(list(getattr(conversation, "history", []) or [])):
        if isinstance(turn, dict) and turn.get("role") == "assistant":
            return str(turn.get("content") or "")
    return ""


def _recent_adult_context(conversation) -> bool:
    """True when the conversation is CURRENTLY in an adult-event context — the
    lead carries an adult-event relative target OR the last assistant turn was
    about adult events. Used so an adult-age self-correction keeps
    active_topic=adult_event when the current message has no event word.

    NOTE: a persisted ``lead.adult_age`` is deliberately NOT treated as
    „current adult context" — it stays set even after the user switches back to
    camp, so relying on it would wrongly keep every later turn adult (it once
    blocked a bare „რეგისტრაცია მინდა" from resolving to camp registration). The
    active topic is driven by the sticky segment (handled at the call site) and
    the recent assistant turn, not by the long-lived age field."""
    lead = _lead_of(conversation)
    if lead is not None:
        if (getattr(lead, "adult_target_relation", "") or "").strip() \
                or (getattr(lead, "adult_target_age", "") or "").strip():
            return True
    last = _last_assistant_content(conversation).lower()
    return any(s in last for s in ("ღონისძიებ", "ზრდასრულ", "საღამო", "კონცერტ"))


def _recent_camp_context(conversation) -> bool:
    """True when the recent assistant turn was about the camp / camp
    registration — so a bare „რეგისტრაცია მინდა" resolves to camp registration."""
    last = _last_assistant_content(conversation).lower()
    return any(s in last for s in ("ბანაკ", "საზაფხულო", "რეგისტრაცი", "ჩაწერ"))


def _has_camp_concern(low: str) -> bool:
    """Camp-flavoured concern stems (safety / contact / visit / guests /
    activities). Used only WITH a child-context guard so a bare safety word does
    not over-fire into camp."""
    groups = (
        _CAMP_CONTACT + _CAMP_VISIT + _CAMP_SAFETY + _CAMP_GUESTS + _CAMP_ACTIVITIES
    )
    return any(s in low for s in groups)


def _camp_subintent(low: str, gw) -> str:
    """Map a camp-topic turn to one camp sub-intent (classification, not paths).
    Order = specificity: contact/visit/safety/guests/activities first, then the
    generic info/price/dates/eligibility."""
    if any(s in low for s in _CAMP_CONTACT):
        return "camp_child_contact"
    if any(s in low for s in _CAMP_VISIT):
        return "camp_visit_policy"
    if any(s in low for s in _CAMP_SAFETY):
        return "camp_safety"
    if any(s in low for s in _CAMP_GUESTS):
        return "camp_guests"
    if any(s in low for s in _CAMP_ACTIVITIES):
        return "camp_activities"
    if getattr(gw, "topic", "") == "price" or any(s in low for s in _CAMP_PRICE):
        return "camp_price"
    if any(s in low for s in _CAMP_DATES):
        return "camp_dates"
    if getattr(gw, "is_age_statement", False) or "ასაკ" in low:
        return "camp_age_eligibility"
    return "camp_info"
