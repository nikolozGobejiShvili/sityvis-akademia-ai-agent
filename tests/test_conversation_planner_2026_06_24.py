"""Conversation Planner / State-Context Contract tests (Reasoning Layer
Phase 3, 2026-06-24).

These validate the PLANNER DECISION (intent / active_topic / state authority /
answer_policy / forbidden-pattern flags) — NOT phrase-specific response paths and
NOT the LLM. Deterministic / offline. The planner is metadata-only and never
mutates state, so each turn sets the lead/booking state the live capture handlers
WOULD have stored, then asserts the planner's decision for the next turn.
"""
from __future__ import annotations

import types

from app.models.lead import Lead
from app.reasoning import conversation_planner as cp
from app.reasoning.conversation_planner import plan_turn


def _conv(**lead_kw):
    lead = Lead(sender_id="t", platform="messenger", segment="PARENT")
    for k, v in lead_kw.items():
        setattr(lead, k, v)
    return types.SimpleNamespace(
        lead=lead,
        pending_booking=lead_kw.pop("pending_booking", None),
        state="",
        segment="PARENT",
    )


# ─────────────────── PART C — state/context authority rules ───────────────────

def test_current_message_wins_name_over_stale_underage():
    """C.1 — „ჩემი სახელია ნიკოლოზი" with a stale child_age=7 must be a
    name_update, NOT a continuation of the underage/camp flow."""
    conv = _conv(child_age="7")
    p = plan_turn("ჩემი სახელია ნიკოლოზი", conv)
    assert p.user_current_intent == "name_update"
    assert p.active_topic == "general_state"
    assert cp.F_NO_REASK_CHILD_AGE in p.forbidden_response_patterns
    assert cp.S_PENDING_BOOKING in p.state_to_ignore


def test_topic_switch_camp_clears_adult_context():
    """C.2 — a camp question after adult-event context switches the active topic
    to camp and clears the leftover adult-event target."""
    conv = _conv(child_age="15", adult_target_relation="შვილი", adult_target_age="15")
    p = plan_turn("ბანაკზე უსაფრთხოება მაინტერესებს", conv)
    assert p.active_topic == "camp"
    assert cp.S_ADULT_TARGET in p.state_to_clear


def test_decline_closes_adult_context():
    """C.3 — „არ მინდა მადლობა" closes the pending sales/event context."""
    conv = _conv(adult_target_relation="შვილი")
    p = plan_turn("არ მინდა მადლობა", conv)
    assert p.user_current_intent == "adult_event_decline"
    assert p.answer_policy == "close_context"
    assert cp.S_ADULT_TARGET in p.state_to_clear


def test_state_recall_high_priority_no_booking_continuation():
    """C.4 — state recall (even a typo) must not continue booking / ask date."""
    for msg in (
        "ჩემზე რა ინფორმაცია გაქვს?",
        "ჩემზე რა ინფრომაცია გაქვს?",   # typo — typo-tolerant via gateway
        "რა მქვია?",
        "ჩემი ნომერი იცი?",
    ):
        conv = _conv(name="ნუცა", phone="595999733", child_age="13")
        p = plan_turn(msg, conv)
        assert p.user_current_intent == "state_recall", msg
        assert p.answer_policy == "state_recall_summary", msg
        assert cp.F_NO_CONTINUE_BOOKING in p.forbidden_response_patterns, msg
        assert cp.F_NO_DATE_TIME_QUESTION in p.forbidden_response_patterns, msg


def test_state_recall_and_booking_recall_use_confirmed_booking():
    """C.5 — both general state recall and booking recall use the confirmed
    booking as the source."""
    conv = _conv(
        name="ნუცა", phone="595999733", child_age="13",
        calendly_booked=True, booked_datetime_iso="2026-06-25T12:00",
    )
    recall = plan_turn("ჩემზე რა ინფორმაცია გაქვს?", conv)
    booking = plan_turn("კონსულტაცია როდის მაქვს?", conv)
    assert recall.should_use_confirmed_booking is True
    assert cp.S_CONFIRMED_BOOKING in recall.state_to_use
    assert booking.user_current_intent == "booking_recall"
    assert booking.should_use_confirmed_booking is True
    assert cp.F_NO_NEW_CONSULTATION in booking.forbidden_response_patterns


def test_camp_safety_not_consultation_format():
    """C.6 — camp safety/contact/visit must answer camp policy, never the
    consultation phone/video format, and never invent exact numbers."""
    conv = _conv(child_age="13")
    p = plan_turn(
        "უსაფრთხოება დაცულია? რამდენი ზედამხედველი ეყოლებათ?", conv,
    )
    assert p.user_current_intent == "camp_safety"
    assert p.active_topic == "camp"
    assert cp.F_NO_CONSULTATION_FORMAT in p.forbidden_response_patterns
    assert cp.F_NO_INVENT_FACTS in p.forbidden_response_patterns
    assert p.should_handoff_to_manager is True
    assert cp.F_NO_REASK_CHILD_AGE in p.forbidden_response_patterns


def test_camp_child_contact_not_consultation_format():
    conv = _conv(child_age="13")
    p = plan_turn("შემეძლება ბანაკის განმავლობაში ბავშვს დავურეკო?", conv)
    assert p.user_current_intent == "camp_child_contact"
    assert cp.F_NO_CONSULTATION_FORMAT in p.forbidden_response_patterns


def test_generic_adult_discovery_not_named_event_lookup():
    """C.7 — generic discovery (no event name) must not be a named-event lookup."""
    conv = _conv()
    p = plan_turn("ჩემთვის მინდა ღონისძიებები რას შემომთავაზებთ?", conv)
    assert p.user_current_intent == "adult_event_for_self"
    assert p.active_topic == "adult_event"
    assert cp.F_NO_NAMED_EVENT_LOOKUP in p.forbidden_response_patterns


def test_mixed_adult_self_and_child_keeps_ages_separate():
    """C.8 — adult_age=30 captured; child reused; 30 never becomes child age;
    no redundant for-whom clarifier when child age is known."""
    conv = _conv(child_age="13")
    p = plan_turn(
        "ჩემთვის და ჩემი შვილისთვის მინდა ღონისძიება, მე ვარ 30 წლის", conv,
    )
    assert p.user_current_intent == "adult_event_for_self_and_child"
    assert p.adult_age == "30"
    assert p.wants_for_child is True
    assert p.child_age == "13"
    assert p.should_ask_clarifying_question is False     # child age known
    assert cp.F_NO_ADULT_AGE_AS_CHILD in p.forbidden_response_patterns


def test_mixed_adult_self_and_child_asks_once_when_child_unknown():
    conv = _conv()
    p = plan_turn(
        "ჩემთვის და ჩემი შვილისთვის მინდა ღონისძიება, მე ვარ 30 წლის", conv,
    )
    assert p.adult_age == "30"
    assert p.wants_for_child is True
    assert p.should_ask_clarifying_question is True       # child age unknown → ask ONCE


def test_consultation_request_no_registration_link():
    """C.9 — a consultation request must not return a registration link."""
    conv = _conv(child_age="13")
    p = plan_turn("კი მინდა კონსულტაციაზე ჩაწერა", conv)
    assert p.user_current_intent in ("consultation_booking", "consultation_time_selection")
    assert p.active_topic == "consultation"
    assert cp.F_NO_REGISTRATION_LINK in p.forbidden_response_patterns


def test_pii_mask_always_forbidden_pattern():
    """C.10 — full phone leak is forbidden on every plan."""
    conv = _conv(name="ნუცა", phone="595999733")
    for msg in ("ბანაკზე მაინტერესებს", "ჩემზე რა ინფორმაცია გაქვს?", "გამარჯობა"):
        p = plan_turn(msg, conv)
        assert cp.F_NO_FULL_PHONE in p.forbidden_response_patterns


def test_tone_request_short_ack():
    conv = _conv(child_age="13")
    p = plan_turn("ადამიანურად მელაპარაკე", conv)
    assert p.user_current_intent == "tone_request"
    assert p.should_answer_directly is True


def test_sunday_school_clears_adult_and_pending():
    conv = _conv(adult_target_relation="შვილი")
    conv.pending_booking = {"requested_datetime_iso": "2026-06-25T12:00"}
    p = plan_turn("საკვირაო სკოლა მაინტერესებს", conv)
    assert p.user_current_intent == "sunday_school"
    assert cp.S_ADULT_TARGET in p.state_to_clear
    assert cp.S_PENDING_BOOKING in p.state_to_clear


def test_planner_never_raises():
    for bad in ("", None, "   ", "🙂🙂🙂", "asdkfjالعربية"):
        p = plan_turn(bad, _conv())
        assert isinstance(p, cp.TurnPlan)


# ─────────────────── PART E — master messy conversation (planner level) ───────

def test_master_messy_conversation_planner_decisions():
    """One realistic messy conversation, asserting the PLANNER decision at each
    turn. State is advanced exactly as the live capture handlers would set it."""
    conv = _conv()
    lead = conv.lead

    # 1. camp info
    p = plan_turn("გამარჯობა, ბანაკზე მაინტერესებს ინფორმაცია", conv)
    assert p.active_topic == "camp"

    # 2. child age disclosed → capture child_age=13
    p = plan_turn("13 წლის არის", conv)
    assert p.active_topic == "camp"
    lead.child_age = "13"

    # 3. price + dates
    p = plan_turn("ბანაკის ფასი რა არის და როდის ტარდება?", conv)
    assert p.active_topic == "camp"
    assert p.user_current_intent in ("camp_price", "camp_dates", "camp_info")

    # 4. camp-period child contact — NOT consultation format, no age re-ask
    p = plan_turn("შემეძლება ბანაკის განმავლობაში ბავშვს დავურეკო?", conv)
    assert p.user_current_intent == "camp_child_contact"
    assert cp.F_NO_CONSULTATION_FORMAT in p.forbidden_response_patterns
    assert cp.F_NO_REASK_CHILD_AGE in p.forbidden_response_patterns

    # 5. safety + supervisor count — answer + manager for the unknown count
    p = plan_turn(
        "უსაფრთხოება დაცულია? შემეძლება ბავშვი მოვინახულო? რამდენი ზედამხედველი ეყოლებათ?",
        conv,
    )
    assert p.user_current_intent in ("camp_safety", "camp_visit_policy")
    assert cp.F_NO_CONSULTATION_FORMAT in p.forbidden_response_patterns
    assert cp.F_NO_REASK_CHILD_AGE in p.forbidden_response_patterns

    # 6. activities / intellectual development / guests
    p = plan_turn(
        "მინდა ახალი მეგობრები გაიჩინოს, ცოტა ჩაკეტილია. ინტელექტუალური თამაშები ექნებათ? მოწვეული სტუმრები იქნებიან?",
        conv,
    )
    assert p.active_topic == "camp"
    assert cp.F_NO_INVENT_FACTS in p.forbidden_response_patterns

    # 7. consultation request
    p = plan_turn("კი მინდა კონსულტაციაზე ჩაწერა", conv)
    assert p.active_topic == "consultation"
    assert p.should_continue_booking is True
    assert cp.F_NO_REGISTRATION_LINK in p.forbidden_response_patterns

    # 8. contact provided → capture name/phone
    p = plan_turn("ნუცა 595999733", conv)
    assert p.active_topic == "consultation"
    lead.name = "ნუცა"
    lead.phone = "595999733"

    # 9-11. time selection
    p = plan_turn("25 ივნისს 12 საათზე ჩამწერეთ", conv)
    assert p.active_topic == "consultation"
    assert p.user_current_intent in ("consultation_time_selection", "consultation_booking")

    # 12. booking confirmed → canonical state
    lead.calendly_booked = True
    lead.booked_datetime_iso = "2026-06-25T12:00"
    lead.status = "Booked"

    # 13. adult event discovery for self
    p = plan_turn("მადლობა. ჩემთვის მინდა ღონისძიებები, რას შემომთავაზებთ?", conv)
    assert p.user_current_intent == "adult_event_for_self"
    assert cp.F_NO_NAMED_EVENT_LOOKUP in p.forbidden_response_patterns

    # 14. mixed self+child → adult_age=30, reuse child_age=13
    p = plan_turn("ჩემთვის და ჩემი შვილისთვის მინდა ღონისძიება, მე ვარ 30 წლის", conv)
    assert p.user_current_intent == "adult_event_for_self_and_child"
    assert p.adult_age == "30"
    assert p.child_age == "13"
    assert p.should_ask_clarifying_question is False
    lead.adult_age = "30"
    lead.adult_target_relation = "შვილი"

    # 15. decline closes adult context
    p = plan_turn("არ მინდა მადლობა", conv)
    assert p.answer_policy == "close_context"
    assert cp.S_ADULT_TARGET in p.state_to_clear
    lead.adult_target_relation = ""        # capture handler clears it

    # 16. sunday school
    p = plan_turn("საკვირაო სკოლა მაინტერესებს", conv)
    assert p.user_current_intent == "sunday_school"

    # 17. camp safety again — known child_age=13, no consultation, no adult
    p = plan_turn(
        "ბანაკზე მაინტერესებს რამდენად უსაფრთხოა? დაცულია უსაფრთხოების ზომები? რამდენი ზედამხედველი ეყოლებათ?",
        conv,
    )
    assert p.active_topic == "camp"
    assert p.user_current_intent == "camp_safety"
    assert cp.F_NO_REASK_CHILD_AGE in p.forbidden_response_patterns

    # 18. general state recall — name + masked phone + child + adult + booking
    p = plan_turn("ჩემზე რა ინფრომაცია გაქვს?", conv)
    assert p.user_current_intent == "state_recall"
    assert cp.S_CONFIRMED_BOOKING in p.state_to_use
    assert cp.S_ADULT_AGE in p.state_to_use
    assert p.should_use_confirmed_booking is True
    assert cp.F_NO_DATE_TIME_QUESTION in p.forbidden_response_patterns

    # 19. name recall
    p = plan_turn("რა მქვია?", conv)
    assert p.user_current_intent == "state_recall"

    # 20. booking recall
    p = plan_turn("კონსულტაცია როდის მაქვს?", conv)
    assert p.user_current_intent == "booking_recall"
    assert p.should_use_confirmed_booking is True

    # 21. calm correction — must use existing booking, never offer a new one
    p = plan_turn("აბა რატო მთავაზობ ახალ კონსულტაციას?", conv)
    assert p.should_use_confirmed_booking is True
    assert cp.F_NO_NEW_CONSULTATION in p.forbidden_response_patterns

    # 22. tone request — short ack, state not lost
    p = plan_turn("ადამიანურად მელაპარაკე", conv)
    assert p.user_current_intent == "tone_request"


# ─────────────────── PART F — smaller live transcript ─────────────────────────

def test_part_f_transcript_planner_decisions():
    conv = _conv()
    lead = conv.lead

    p = plan_turn("მე ვარ 30 წლის რა შეიძლება შემომთავაზოთ?", conv)
    assert p.active_topic == "adult_event"
    assert p.user_current_intent in ("adult_event_for_self", "adult_event_discovery")
    assert p.adult_age == "30"

    p = plan_turn("ჩემთვის და ჩემი შვილისთვის მინდა", conv)
    assert p.wants_for_child is True
    assert p.should_ask_clarifying_question is True        # child age unknown → ask once
    lead.adult_age = "30"

    p = plan_turn("15 წლის არის", conv)
    # child age disclosure → capture; adult_age stays separate
    lead.child_age = "15"
    assert lead.adult_age == "30" and lead.child_age == "15"

    p = plan_turn("არ მინდა მადლობა", conv)
    assert p.answer_policy == "close_context"

    p = plan_turn(
        "ბანაკზე მაინტერესებს რამდენად უსაფრთხოა? დაცულია უსაფრთხოების ზომები? რამდენი ზედამხედველი ეყოლებათ?",
        conv,
    )
    assert p.active_topic == "camp"
    assert p.user_current_intent == "camp_safety"
    assert cp.F_NO_REASK_CHILD_AGE in p.forbidden_response_patterns
    assert cp.F_NO_CONSULTATION_FORMAT in p.forbidden_response_patterns
