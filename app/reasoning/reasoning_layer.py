"""Deterministic structured intent analyzer — Reasoning Layer, Phase 1
(2026-06-23).

Phase 1 is DETERMINISTIC-ONLY (no LLM, per the task brief): it classifies a
PARENT turn into structured intent metadata so ambiguous routing (e.g. a decline
that ALSO switches topic) can be handled better — WITHOUT a free-form answer
generator. The reference scaffold `docs/reference/reasoning_layer.py` is an
LLM-based 4-step pass (analyze→ground→answer→reflect); it is REFERENCE ONLY and
is NOT imported here.

Contract:
  * `analyze_parent_turn(message, conversation=None) -> ReasoningAnalysis`.
  * Output is METADATA only — never user-facing text.
  * Never raises (fail-closed: any error → low-confidence default).
  * No side effects: only reads the message + calls pure `parent_flow` helpers
    (lazy-imported to avoid a circular import).
  * The caller (parent_flow.handle, behind `USE_REASONING_LAYER`) decides what to
    do with the metadata; the analyzer NEVER overrides a high-confidence
    deterministic handler and low confidence must fail closed.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

# Question morphology (Georgian) — used in addition to a literal „?".
_QUESTION_STEMS: tuple[str, ...] = (
    "რა ", "რას ", "როდის", "სად", "რამდენ", "როგორ", "რომელ", "ვინ",
)
# Decline markers (kept narrow; the authoritative decline handler lives in
# parent_flow — this is only for classification metadata).
_DECLINE_MARKERS: tuple[str, ...] = (
    "არ მინდა", "აღარ მინდა", "არ მსურს", "უარს ვამბობ", "არ ვაპირებ",
    "არა გმადლობთ", "არა მადლობა",
)
_PRICE_STEMS: tuple[str, ...] = ("ფასი", "ფასს", "ღირ", "გადახდ", "განვადებ")
_REGISTRATION_STEMS: tuple[str, ...] = ("რეგისტრ", "სარეგისტრაც")
_BOOKING_STEMS: tuple[str, ...] = ("კონსულტაც", "ჩაწერ", "ჯავშ")
_CAMP_STEMS: tuple[str, ...] = ("ბანაკ", "საზაფხულო", "ნაკად", "ლაგერ")
_ADULT_EVENT_STEMS: tuple[str, ...] = (
    "ღონისძიებ", "საღამო", "კონცერტ", "კულტურულ", "სპექტაკლ", "ზრდასრულ",
)
_CHILD_REF: tuple[str, ...] = ("შვილ", "ბავშვ")
_SELF_REF: tuple[str, ...] = ("ჩემთვის", "მე მინდა", "ჩემთან")
_CONTACT_WORDS: tuple[str, ...] = ("ნომერ", "ტელეფონ", "კონტაქტ")


@dataclass
class ReasoningAnalysis:
    """Structured, internal-only turn metadata. Never user-facing text."""
    segment: str = "unknown"          # parent | adult | unknown
    topic: str = "other"              # camp|sunday_school|adult_event|manager_contact|price|registration|booking|other
    intent: str = "other"             # ask_info|ask_price|ask_registration|ask_manager_phone|request_handoff|self_call_manager|affirm|decline|provide_contact|topic_switch|other
    has_question: bool = False
    is_topic_switch: bool = False
    is_affirmation: bool = False
    is_decline: bool = False
    requested_action: str = "none"    # answer|give_manager_phone|collect_contact|start_booking|continue_existing_flow|none
    confidence: float = 0.0
    reason: str = ""                  # short INTERNAL reason (never shown to user)

    def to_dict(self) -> dict:
        return asdict(self)


def analyze_parent_turn(message: str, conversation=None) -> ReasoningAnalysis:
    """Classify a PARENT turn into structured intent metadata (deterministic).

    Never raises — on any error returns a low-confidence default so the caller
    fails closed to the existing deterministic flow.
    """
    try:
        return _analyze(message, conversation)
    except Exception:
        return ReasoningAnalysis(reason="analyzer-error-failclosed", confidence=0.0)


def _analyze(message: str, conversation) -> ReasoningAnalysis:
    text = (message or "").strip()
    if not text:
        return ReasoningAnalysis(reason="empty-message", confidence=0.0)
    low = text.lower()

    # Lazy import — reuse the canonical, battle-tested deterministic primitives
    # (manager / self-call / affirmation / topic-switch / phone) so this analyzer
    # never drifts from the live handlers, and avoid a circular import at load.
    from app.flows import parent_flow as _pf

    has_question = ("?" in text) or any(s in low for s in _QUESTION_STEMS)
    is_affirmation = _pf._is_affirmation_only(text)
    is_topic_switch = _pf._is_topic_switch(text)
    is_decline = any(m in low for m in _DECLINE_MARKERS)
    has_phone = bool(_pf._distinct_valid_phones(text))

    ask_manager_phone = _pf._is_explicit_manager_number_request(text)
    self_call = _pf._is_self_call_manager_request(text) or (
        _pf._has_self_call_intent(text) and _pf._mentions_manager(low)
    )

    # ---- topic (priority high → low) ----
    sunday = ("საკვირაო" in low) and ("სკოლ" in low)
    manager_topic = _pf._mentions_manager(low) and any(
        m in low for m in _CONTACT_WORDS
    )
    is_price = any(s in low for s in _PRICE_STEMS)
    is_registration = any(s in low for s in _REGISTRATION_STEMS)
    is_adult_event = any(s in low for s in _ADULT_EVENT_STEMS)
    is_camp = any(s in low for s in _CAMP_STEMS)
    is_booking = any(s in low for s in _BOOKING_STEMS)

    if sunday:
        topic = "sunday_school"
    elif ask_manager_phone or self_call or manager_topic:
        topic = "manager_contact"
    elif is_registration:
        topic = "registration"
    elif is_price:
        topic = "price"
    elif is_adult_event and not is_camp:
        topic = "adult_event"
    elif is_camp:
        topic = "camp"
    elif is_booking:
        topic = "booking"
    else:
        topic = "other"

    # ---- segment ----
    has_child = any(c in low for c in _CHILD_REF)
    has_self = any(s in low for s in _SELF_REF)
    if is_camp or has_child or sunday:
        segment = "parent"
    elif is_adult_event and (has_self or not has_child):
        segment = "adult"
    else:
        segment = "unknown"

    # ---- intent + requested_action + confidence (priority high → low) ----
    if ask_manager_phone or self_call:
        intent = "self_call_manager" if self_call else "ask_manager_phone"
        action, conf = "give_manager_phone", 0.9
        reason = "manager-number / self-call request"
    elif is_decline and is_topic_switch:
        intent, action, conf = "topic_switch", "answer", 0.75
        reason = "decline + topic switch — answer the new topic"
    elif is_decline:
        intent, action, conf = "decline", "none", 0.85
        reason = "decline"
    elif has_phone:
        intent, action, conf = "provide_contact", "collect_contact", 0.8
        reason = "contact (phone) provided"
    elif is_affirmation:
        intent, action, conf = "affirm", "continue_existing_flow", 0.7
        reason = "bare affirmation for the latest CTA"
    elif sunday:
        intent, action, conf = "ask_info", "answer", 0.85
        reason = "sunday school"
    elif topic == "manager_contact":
        intent, action, conf = "ask_manager_phone", "give_manager_phone", 0.7
        reason = "manager contact mention"
    elif topic == "price":
        intent, action, conf = "ask_price", "answer", 0.85 if has_question else 0.7
        reason = "price"
    elif topic == "registration":
        intent, action, conf = "ask_registration", "answer", 0.8
        reason = "registration"
    elif topic == "adult_event":
        intent, action, conf = "ask_info", "answer", 0.7
        reason = "adult event interest"
    elif topic == "camp" and has_question:
        intent, action, conf = "ask_info", "answer", 0.7
        reason = "camp info question"
    elif topic == "booking":
        intent, action, conf = "ask_info", "start_booking", 0.6
        reason = "booking intent"
    elif is_topic_switch:
        intent, action, conf = "topic_switch", "answer", 0.6
        reason = "topic switch"
    elif has_question:
        intent, action, conf = "ask_info", "answer", 0.55
        reason = "generic question"
    else:
        intent, action, conf = "other", "none", 0.3
        reason = "ambiguous / low signal"

    return ReasoningAnalysis(
        segment=segment,
        topic=topic,
        intent=intent,
        has_question=has_question,
        is_topic_switch=is_topic_switch,
        is_affirmation=is_affirmation,
        is_decline=is_decline,
        requested_action=action,
        confidence=conf,
        reason=reason,
    )


# =========================================================================
# Reasoning Layer — Phase 2: central Turn Intent Gateway (2026-06-23).
#
# A DETERMINISTIC, metadata-only classifier that runs BEFORE the sticky domain
# handlers so they cannot consume the wrong message. It NEVER generates a
# user-facing answer, NEVER invents facts, NEVER triggers external side effects
# (email/WhatsApp/Calendar/Sheets); the caller (parent_flow) applies the routing
# metadata. Fail-closed: any error → low-confidence default so existing
# deterministic behaviour continues unchanged.
#
# Root cause it fixes (live test): the PARENT event interceptor
# (`_maybe_handle_event_inquiry`) parsed an AGE („29 წლის") as a calendar day
# („29 რიცხვში") and treated a DECLINE („მადლობა არ მინდა") as an event-name
# search, looping on the sticky „events listed" context. The gateway centrally
# disambiguates age-vs-date and decline-vs-event so no domain handler misreads.
# =========================================================================

# AGE = a number directly bound to a „წლ…/წელ…" marker. „29 წლის" → age 29.
_AGE_RE = re.compile(r"(?<!\d)(\d{1,3})\s*(?:წლ|წელ)")
# Bare 1–2 digit number (a candidate calendar day in an event-date question).
_DAY_NUMBER_RE = re.compile(r"(?<!\d)(\d{1,2})(?!\d)")
# Georgian month stems — a number adjacent to one is a DATE, not an age.
_MONTH_STEMS: tuple[str, ...] = (
    "იანვ", "თებერ", "თებირ", "მარ", "აპრ", "მაის", "ივნ", "ივლ",
    "აგვ", "სექ", "ოქტ", "ნოემ", "დეკ",
)
# Consultation / booking intent — typo-tolerant („კოსულტ" without the „ნ" was
# seen live). „ჩაწერ"/„ჯავშ" are booking stems too.
_CONSULTATION_STEMS: tuple[str, ...] = ("კონსულტ", "კოსულტ", "ჯავშ", "ჩაწერ")
# Child-specific concern the parent shares (so the answer is empathetic, NOT a
# registration link). Closed set; non-diagnostic.
_CHILD_CONCERN_STEMS: tuple[str, ...] = (
    "არაკომუნიკაბელ", "კომუნიკაცი", "მეგობრების შეძენ", "მეგობრებს ვერ",
    "მეტყველებ", "თვისებურ", "მორცხვ", "ჩაკეტილ", "ყურადღებ", "უჭირ",
    "შეესაბამებ", "შეეფერებ",
)
# Human-tone request — the user asks to be spoken to naturally / not like a bot.
_HUMAN_TONE_STEMS: tuple[str, ...] = (
    "ადამიანურ", "დაზეპირებ", "ბოტივით", "ბოტი ხარ", "ჩვეულებრივად",
    "მარტივად მელაპარაკ", "ნორმალურად მელაპარაკ",
)
# General-knowledge / off-topic interrogatives + entity stems (mirror the adult
# off-topic guard so a PARENT „მუფასა ვინაა?" is not read as an event search).
_OFFTOPIC_WHO_WHAT: tuple[str, ...] = (
    "ვინაა", "ვინ არის", "ვინ იყო", "რა არის", "რა იყო",
)
_OFFTOPIC_ENTITY_STEMS: tuple[str, ...] = (
    "კლიმატ", "გლობალუ", "მათემატიკ", "ფიზიკ", "ქიმი", "ბიოლოგ", "ფილოსოფ",
    "ფსიქოლოგ", "პოლიტიკ", "არჩევნებ", "მუფასა", "სიმბ", "ჰარი პოტერ",
    "გენდალფ", "ბეტმენ",
)
# Insults — a calm boundary, never an event search / escalation.
_INSULT_STEMS: tuple[str, ...] = (
    "დებილ", "იდიოტ", "ბრიყვ", "სულელ", "ჩერჩეტ", "გარეწარ", "მაიმუნ",
    "ნაბიჭვ", "ბოზ",
)
# State-recall — typo-tolerant („ემზე"≈„ჩემზე", „ინფრომაცია"≈„ინფორმაცია").
_STATE_RECALL_RE = re.compile(
    r"(ჩემზე|ემზე).{0,6}(ინ[ფრ]+ომაცი|ინფორმაცი|იცი|გახსოვ)"
    r"|რა.{0,4}(ინ[ფრ]+ომაცი|ინფორმაცი).{0,8}(გაქვ|იცი|გახსოვ)"
    r"|ჩემი\s*(ნომერ|ტელეფონ|სახელ)"
    r"|რა\s*იცი\s*ჩემ|რა\s*გახსოვ"
)


# Decline / stop — negation anchored at a token boundary so „ვარ მინდა"
# (the „არ" inside „ვარ") never false-matches.
_DECLINE_RE = re.compile(
    r"(?:^|[\s,.!?:;„])(?:არ|აღარ|არც)\s?მინდ"
    r"|(?:^|[\s,.!?:;„])(?:არ|აღარ)\s?მსურ"
    r"|აღარ\s?მაინტერეს"
    r"|(?:^|[\s,.!?:;„])არა[\s,]*(?:გმადლ|მადლ)"
    r"|უარს\s?ვამბ"
    r"|(?:^|[\s,.!?:;„])(?:არ|აღარ)\s?მჭირდ"
    r"|(?:^|[\s,.!?:;„])ჯერ\s+არ\s+მინდ"
    r"|შევჩერდეთ|გავაუქმოთ"
)


@dataclass
class TurnIntent:
    """Central, internal-only turn metadata for the Phase-2 gateway. NEVER
    user-facing text. The caller applies `block_event_inquiry` / `clear_*`
    to gate the sticky domain handlers."""
    segment: str = "unknown"            # parent | adult | unknown
    topic: str = "other"
    intent: str = "other"
    age: int | None = None
    date_text: str | None = None
    phone: str | None = None
    event_query: str | None = None
    has_question: bool = False
    is_decline: bool = False
    is_affirmation: bool = False
    is_topic_switch: bool = False
    is_age_statement: bool = False
    is_self_reference: bool = False
    is_child_reference: bool = False
    is_genuine_event_reference: bool = False
    is_manager_phone_request: bool = False
    # Response-Planner Hardening signals (2026-06-23) — centralised so handlers
    # consult the gateway instead of re-detecting per phrase.
    is_consultation_request: bool = False
    is_child_concern: bool = False
    is_human_tone_request: bool = False
    is_off_topic: bool = False
    is_insult: bool = False
    is_state_recall: bool = False
    is_adult_self: bool = False
    requested_action: str = "none"
    # Sticky-context decisions (the caller acts on these; the gateway never
    # mutates state itself).
    block_event_inquiry: bool = False
    clear_event_context: bool = False
    confidence: float = 0.0
    reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def analyze_turn_intent(message: str, conversation=None) -> TurnIntent:
    """Central deterministic turn-intent gateway (Phase 2).

    Never raises — on any error returns a low-confidence default so the caller
    fails closed to the existing deterministic flow.
    """
    try:
        return _analyze_turn(message, conversation)
    except Exception:
        return TurnIntent(reason="gateway-error-failclosed", confidence=0.0)


def _extract_age(low: str) -> int | None:
    m = _AGE_RE.search(low)
    if not m:
        return None
    try:
        n = int(m.group(1))
    except (TypeError, ValueError):
        return None
    return n if 0 <= n <= 120 else None


def _extract_date_day(low: str, age: int | None) -> str | None:
    """Return a calendar-day reference (as the matched substring) ONLY when a
    bare 1–31 number is a DATE — adjacent to a month stem, or „N რიცხვ/N-ში" —
    and is NOT the age number. Returns None for a pure age statement."""
    for m in _DAY_NUMBER_RE.finditer(low):
        try:
            n = int(m.group(1))
        except (TypeError, ValueError):
            continue
        if not (1 <= n <= 31):
            continue
        tail = low[m.end():m.end() + 10].lstrip()
        # The age number itself is never a date.
        if tail.startswith("წლ") or tail.startswith("წელ"):
            continue
        if n == age and (f"{n} წ" in low or f"{n}წ" in low):
            continue
        # Date markers: a following month stem, or „რიცხვ" / „-ში".
        if any(tail.startswith(ms) for ms in _MONTH_STEMS):
            return m.group(0)
        if tail.startswith("რიცხვ") or low[m.end():m.end() + 4].startswith("-ში"):
            return m.group(0)
    return None


def _analyze_turn(message: str, conversation) -> TurnIntent:
    text = (message or "").strip()
    if not text:
        return TurnIntent(reason="empty-message", confidence=0.0)
    low = text.lower()

    from app.flows import parent_flow as _pf

    has_question = ("?" in text) or any(s in low for s in _QUESTION_STEMS)
    is_affirmation = _pf._is_affirmation_only(text)
    is_topic_switch = _pf._is_topic_switch(text)
    is_decline = bool(_DECLINE_RE.search(low))
    phones = _pf._distinct_valid_phones(text)
    phone = phones[0] if len(phones) == 1 else None

    ask_manager_phone = _pf._is_explicit_manager_number_request(text)
    self_call = _pf._is_self_call_manager_request(text) or (
        _pf._has_self_call_intent(text) and _pf._mentions_manager(low)
    )

    age = _extract_age(low)
    is_age_statement = age is not None
    date_text = _extract_date_day(low, age)

    # Genuine event-name reference (reuse the adult engine's strict gate so a
    # generic „ღონისძიება" is NOT treated as a named event).
    is_genuine_event_reference = False
    event_query = None
    try:
        from app.services import admin_config_service as _acs
        tokens = _acs._event_query_tokens(message)
        if tokens:
            event_query = " ".join(tokens)
            from app.agent.llm.adult_llm_engine import _has_genuine_event_name_token
            is_genuine_event_reference = _has_genuine_event_name_token(tokens)
    except Exception:
        is_genuine_event_reference = False

    # Response-Planner signals.
    is_consultation_request = any(s in low for s in _CONSULTATION_STEMS)
    is_child_concern = ("ბავშვ" in low or "შვილ" in low) and any(
        s in low for s in _CHILD_CONCERN_STEMS
    )
    is_human_tone_request = any(s in low for s in _HUMAN_TONE_STEMS)
    is_insult = any(s in low for s in _INSULT_STEMS)
    is_state_recall = bool(_STATE_RECALL_RE.search(low))
    # Off-topic general-knowledge: a „ვინ/რა არის" interrogative OR a known
    # off-topic entity stem, with NO in-scope business signal.
    _has_business_signal = (
        any(s in low for s in _CAMP_STEMS)
        or any(s in low for s in _ADULT_EVENT_STEMS)
        or any(s in low for s in _PRICE_STEMS)
        or any(s in low for s in _REGISTRATION_STEMS)
        or any(s in low for s in _BOOKING_STEMS)
        or any(s in low for s in _CONTACT_WORDS)
        or ("საკვირაო" in low)
    )
    is_off_topic = (not _has_business_signal) and (
        any(s in low for s in _OFFTOPIC_ENTITY_STEMS)
        or any(p in low for p in _OFFTOPIC_WHO_WHAT)
    )

    sunday = ("საკვირაო" in low) and ("სკოლ" in low)
    is_price = any(s in low for s in _PRICE_STEMS)
    is_registration = any(s in low for s in _REGISTRATION_STEMS)
    is_adult_event = any(s in low for s in _ADULT_EVENT_STEMS)
    is_camp = any(s in low for s in _CAMP_STEMS)
    is_booking = any(s in low for s in _BOOKING_STEMS)
    has_child = any(c in low for c in _CHILD_REF)
    has_self = any(s in low for s in _SELF_REF)

    if sunday:
        topic = "sunday_school"
    elif ask_manager_phone or self_call:
        topic = "manager_contact"
    elif is_registration:
        topic = "registration"
    elif is_adult_event and is_price:
        topic = "adult_event"          # „ღონისძიების ფასი" stays event, not price
    elif is_price:
        topic = "price"
    elif is_adult_event and not is_camp:
        topic = "adult_event"
    elif is_camp:
        topic = "camp"
    elif is_booking:
        topic = "booking"
    else:
        topic = "other"

    # Segment: an age ≥ 18 + self/adult-event signal leans adult.
    if is_camp or has_child or sunday:
        segment = "parent"
    elif is_adult_event and (has_self or not has_child):
        segment = "adult"
    elif age is not None and age >= 18 and (is_adult_event or has_self):
        segment = "adult"
    else:
        segment = "unknown"

    # --- central routing decisions ---
    # The event interceptor must NOT fire when the turn is a decline, a manager-
    # phone request, a Sunday-School / registration ask, or an AGE statement that
    # is NOT a calendar date. An age + event interest („29 წლის და ღონისძიებები")
    # is an ADULT-segment entry the engine handles — never a named-event lookup,
    # so it is blocked regardless of the (deliberately loose) genuine-name gate.
    # A real date („29 აგვისტოს") or a genuine event name keeps it firing.
    # adult-self = the user is asking for THEMSELVES (self-reference or an
    # adult age) and NOT for a child → the for-whom clarifier is redundant.
    is_adult_self = bool(
        (has_self or (age is not None and age >= 18))
        and not has_child
        and (is_adult_event or has_self or (age is not None and age >= 18))
    )

    block_event_inquiry = bool(
        is_decline
        or ask_manager_phone
        or self_call
        or is_off_topic
        or is_insult
        or topic in ("sunday_school", "registration")
        or (is_age_statement and date_text is None)
    )
    # Sticky adult-event context clears on decline or a clear switch to a
    # different domain (camp / sunday-school / manager / registration). Uses the
    # raw domain flags (not the loose genuine-name gate) so „ბანაკის ფასი" after
    # an event list reliably clears the event context.
    clear_event_context = bool(
        is_decline or is_camp or sunday or is_registration
        or ask_manager_phone or self_call or is_off_topic or is_insult
    )

    if ask_manager_phone or self_call:
        intent, action, conf = (
            "self_call_manager" if self_call else "ask_manager_phone",
            "give_manager_phone", 0.9,
        )
        reason = "manager-number / self-call request"
    elif is_decline and is_topic_switch:
        intent, action, conf = "topic_switch", "answer", 0.8
        reason = "decline + topic switch — answer the new topic"
    elif is_decline:
        intent, action, conf = "decline", "none", 0.9
        reason = "decline / stop"
    elif phone is not None:
        intent, action, conf = "provide_contact", "collect_contact", 0.8
        reason = "single valid phone provided"
    elif is_age_statement and not date_text:
        intent, action, conf = "provide_age", "answer", 0.8
        reason = "age statement (not a date)"
    elif date_text is not None:
        intent, action, conf = "provide_date", "answer", 0.75
        reason = "calendar date reference"
    elif is_affirmation:
        intent, action, conf = "affirm", "continue_existing_flow", 0.7
        reason = "bare affirmation for the latest CTA"
    elif sunday:
        intent, action, conf = "ask_info", "answer", 0.85
        reason = "sunday school"
    elif topic == "adult_event":
        intent, action, conf = "ask_info", "show_events", 0.7
        reason = "adult event interest"
    elif topic == "price":
        intent, action, conf = "ask_price", "answer", 0.85 if has_question else 0.7
        reason = "price"
    elif topic == "registration":
        intent, action, conf = "ask_registration", "answer", 0.8
        reason = "registration"
    elif topic == "camp" and has_question:
        intent, action, conf = "ask_info", "answer", 0.7
        reason = "camp info"
    elif topic == "booking":
        intent, action, conf = "ask_info", "start_booking", 0.6
        reason = "booking intent"
    elif is_topic_switch:
        intent, action, conf = "topic_switch", "answer", 0.6
        reason = "topic switch"
    elif has_question:
        intent, action, conf = "ask_info", "answer", 0.55
        reason = "generic question"
    else:
        intent, action, conf = "other", "none", 0.3
        reason = "ambiguous / low signal"

    return TurnIntent(
        segment=segment,
        topic=topic,
        intent=intent,
        age=age,
        date_text=date_text,
        phone=phone,
        event_query=event_query,
        has_question=has_question,
        is_decline=is_decline,
        is_affirmation=is_affirmation,
        is_topic_switch=is_topic_switch,
        is_age_statement=is_age_statement,
        is_self_reference=has_self,
        is_child_reference=has_child,
        is_genuine_event_reference=is_genuine_event_reference,
        is_manager_phone_request=bool(ask_manager_phone or self_call),
        is_consultation_request=is_consultation_request,
        is_child_concern=is_child_concern,
        is_human_tone_request=is_human_tone_request,
        is_off_topic=is_off_topic,
        is_insult=is_insult,
        is_state_recall=is_state_recall,
        is_adult_self=is_adult_self,
        requested_action=action,
        block_event_inquiry=block_event_inquiry,
        clear_event_context=clear_event_context,
        confidence=conf,
        reason=reason,
    )
