"""Structured camp TOPIC facts (live need 2026-06-28).

A camp-related QUESTION about a SPECIFIC concern (safety / food / gadgets /
confidence / communication / …) was answered with the whole camp description.

Fix (deterministic, legacy/giant-prompt path — engine ON, planner + slim OFF):
  * New structured knowledge file app/agent/knowledge/camp_topic_facts.yaml with
    ~16 topics (triggers + focused answer block each).
  * New deterministic classifier app/reasoning/camp_topic_facts.py — NO LLM, NO
    one-huge-blob; picks the single best topic and returns ONLY that block.
  * New pre-engine interceptor parent_flow._maybe_handle_camp_topic_facts, wired
    LAST among the deterministic handlers (after Sunday School / adult events /
    booking day-time / registration link / manager phone / repeat price) so it
    never overrides a canonical flow and never interrupts an active booking.

The agent answers a specific question with the relevant block only; a general
camp question gets a short overview; nothing is ever dumped.
"""
from __future__ import annotations

import dataclasses
import re

import pytest

import app.config as config_module
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.reasoning import camp_topic_facts as ctf
from app.services import admin_config_service, conversation_service, messenger_service

_MANAGER_NUMBER = "558 67 47 33"
_CAMP_URL = "https://tinyurl.com/36jcae8z"
_ENGINE = "[ENGINE-MOCK]"
# Mocked engine price/date answers (canonical price/date flow stand-ins).
_PRICE_FULL = "[ENGINE-PRICE] ბანაკის ღირებულებაა 2150₾. შედის ტრანსპორტი, კვება."
_DATES_FULL = "[ENGINE-DATES] ბანაკი ტარდება 23–29 ივნისი, 5–11 ივლისი, 14–20 ივლისი."

# Distinctive sentinel per topic — a phrase that appears ONLY in that one block.
# Used by the no-full-dump guard (each specific answer must carry ZERO other
# topics' sentinels).
_SENTINELS = {
    "safety": "ვიდეომონიტორინგ",
    "parent_communication": "ფოტო-ვიდეო",
    "food": "კვება შედის",
    "gadgets": "გაჯეტებისგან განტვირთვა",
    "confidence_motivation": "მოტივაციის ამაღლებაში",
    "communication_socialization": "სოციალიზაცი",
    "bullying_empathy": "ბულინგ",
    "emotional_intelligence": "ემოციური ინტელექტ",
    "thinking_expression": "არგუმენტირებულად",
    "independence_responsibility": "დამოუკიდებელი ცხოვრებ",
    "interests_orientation": "უნარების აღმოჩენ",
    "values_identity": "ფასეულობათა სისტ",
    "sports_health": "სპორტული აქტივობები და ჯანსაღი",
    "activities_creativity": "პერფორმანსები",
    "rest_environment": "აერთიანებს განვითარებას",
    "general_overview": "დღიანი პროგრამა",
}


@pytest.fixture(autouse=True)
def _reset():
    conversation_service.conversations.clear()
    parent_flow.invalid_phone_retries.clear()
    parent_flow._sunday_school_notified_senders.clear()
    yield
    conversation_service.conversations.clear()
    parent_flow._sunday_school_notified_senders.clear()


@pytest.fixture
def engine_on(monkeypatch):
    swapped = dataclasses.replace(
        config_module.settings,
        USE_PARENT_LLM_ENGINE=True,
        USE_CONVERSATION_PLANNER=False,
        CONVERSATION_PLANNER_AUTHORITATIVE=False,
        USE_SLIM_PROMPTS=False,
    )
    monkeypatch.setattr(parent_flow, "settings", swapped)
    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})

    def _engine(c, m):
        low = (m or "").lower()
        if "როდის" in low or "თარიღ" in low:
            return _DATES_FULL
        if any(p in low for p in ("ფასი", "ღირს", "ღირებულ", "გადასახ")):
            return _PRICE_FULL
        return _ENGINE

    monkeypatch.setattr(parent_flow, "_run_llm_engine_safely", _engine)
    return swapped


def _coming_soon(monkeypatch):
    monkeypatch.setattr(
        admin_config_service, "get_sunday_school_status",
        lambda: {"status": "coming_soon",
                 "availability_text": "საკვირაო სკოლა ივლისში დაემატება.",
                 "details_text": "დეტალები ზუსტდება", "handoff_enabled": True,
                 "lead_type": "sunday_school"},
    )


def _conv(sid="c", state="ASK_CHALLENGE", child_age="12", segment="PARENT"):
    """A mid-flow conversation with a prior assistant turn (so the static welcome
    bypass does not fire)."""
    c = Conversation(sender_id=sid, platform="instagram", segment=segment)
    c.state = state
    c.history.append({"role": "assistant", "content": "რას ელოდებით ბანაკისგან?"})
    c.lead = Lead(sender_id=sid, platform="instagram", segment=segment,
                  child_age=child_age)
    return c


def _booking_conv(sid="bk", name="სალომე", phone="558914814", child_age="14"):
    """Turn-N conversation where the bot just asked the consultation date/time."""
    c = Conversation(sender_id=sid, platform="instagram", segment="PARENT")
    c.state = "OFFER_BOOKING"
    c.history.append({
        "role": "assistant",
        "content": f"მადლობა, {name}. რომელი დღე და დრო გირჩევნიათ კონსულტაციისთვის?",
    })
    c.lead = Lead(sender_id=sid, platform="instagram", segment="PARENT",
                  name=name, phone=phone, child_age=child_age)
    return c


def _no_engine(text):
    return _ENGINE not in (text or "")


def _no_other_sentinels(text, topic):
    low = text or ""
    return [t for t, s in _SENTINELS.items() if t != topic and s in low]


# =====================================================================
# 1–3. Safety / supervision
# =====================================================================
def test_1_safety_question(engine_on):
    out = parent_flow.handle(_conv("s1"), "ბანაკში უსაფრთხოება როგორ არის?")
    assert "ევროპული საბანაკე სტანდარტ" in out
    assert "სტაფი" in out                                   # experienced staff
    assert "სამედიცინო პერსონალი 24/7" in out
    assert "24-საათიანი ვიდეომონიტორინგი" in out
    assert ("ფიზიკურ" in out and "ემოციურ უსაფრთხო" in out)
    # does NOT dump gadgets / motivation / sports
    assert "გაჯეტებისგან განტვირთვა" not in out
    assert "მოტივაციის ამაღლებაში" not in out
    assert "სპორტული აქტივობები და ჯანსაღი" not in out
    assert _no_engine(out)


def test_2_doctor_question(engine_on):
    out = parent_flow.handle(_conv("s2"), "ექიმი იქნება?")
    assert "სამედიცინო პერსონალი 24/7" in out
    assert _SENTINELS["general_overview"] not in out        # no full overview
    assert "2150" not in out


def test_3_camera_question(engine_on):
    out = parent_flow.handle(_conv("s3"), "კამერები არის?")
    assert "24-საათიანი ვიდეომონიტორინგი" in out
    assert _SENTINELS["general_overview"] not in out
    assert "2150" not in out


# =====================================================================
# 4–5. Parent communication
# =====================================================================
def test_4_parent_communication(engine_on):
    out = parent_flow.handle(_conv("p4"), "ფოტოებს და ვიდეოებს გამოგვიგზავნით?")
    assert "დღის პროგრამა" in out
    assert "ფოტო-ვიდეო მასალა" in out
    assert "მშობლებთან" in out
    assert "გაჯეტებისგან განტვირთვა" not in out
    assert "მოტივაციის ამაღლებაში" not in out


def test_5_direct_child_contact(engine_on):
    out = parent_flow.handle(_conv("p5"), "ბავშვთან კონტაქტი მექნება?")
    assert "დღის პროგრამა" in out
    assert "მენეჯერი" in out and "კონტაქტის წესები" in out   # manager clarifies
    # never invents unlimited calls
    assert "ნებისმიერ დროს" not in out and "ნებისმიერ მომენტ" not in out


# =====================================================================
# 6. Food
# =====================================================================
def test_6_food(engine_on):
    out = parent_flow.handle(_conv("f6"), "კვება შედის?")
    assert "კვება შედის ბანაკის ღირებულებაში" in out
    assert "ალერგია" in out
    # no mixed-script characters (no Cyrillic)
    assert not re.search("[Ѐ-ӿ]", out)


# =====================================================================
# 7. Gadgets
# =====================================================================
def test_7_gadgets(engine_on):
    out = parent_flow.handle(_conv("g7"), "ბავშვი სულ ტელეფონშია, ამაზე მუშაობთ?")
    assert "გაჯეტებისგან განტვირთვა" in out
    assert "ეკრანისგან დისტანცია" not in out


# =====================================================================
# 8. Confidence / motivation
# =====================================================================
def test_8_confidence(engine_on):
    out = parent_flow.handle(_conv("cf8"), "თავდაჯერებულობა აკლია")
    assert "მოტივაციის ამაღლებაში" in out
    assert "თავდაჯერებულობის გაძლიერებაში" in out
    assert _SENTINELS["safety"] not in out                  # no safety dump


# =====================================================================
# 9. Communication / socialization
# =====================================================================
def test_9_communication(engine_on):
    out = parent_flow.handle(_conv("cm9"), "კომუნიკაცია უჭირს")
    assert "სოციალიზაცი" in out
    assert _SENTINELS["food"] not in out and _SENTINELS["safety"] not in out


# =====================================================================
# 10. Bullying
# =====================================================================
def test_10_bullying(engine_on):
    out = parent_flow.handle(_conv("b10"), "ბულინგის თემაზე მუშაობთ?")
    assert "ბულინგის პრევენცია" in out
    assert "ემპათია" in out and "ურთიერთპატივისცემა" in out
    assert _SENTINELS["general_overview"] not in out


# =====================================================================
# 11. Emotional intelligence
# =====================================================================
def test_11_emotional_intelligence(engine_on):
    out = parent_flow.handle(_conv("e11"), "ემოციებს ვერ მართავს")
    assert "ემოციური ინტელექტ" in out
    assert _SENTINELS["general_overview"] not in out


# =====================================================================
# 12. Thinking / expression
# =====================================================================
def test_12_thinking_expression(engine_on):
    out = parent_flow.handle(_conv("t12"), "თავისი აზრის გამოხატვა უჭირს")
    assert "ანალიტიკურ აზროვნება" in out
    assert "არგუმენტირებულად" in out
    assert _SENTINELS["general_overview"] not in out


# =====================================================================
# 13. Activities
# =====================================================================
def test_13_activities(engine_on):
    out = parent_flow.handle(_conv("a13"), "რა აქტივობებია?")
    assert "შემოქმედებ" in out and "გუნდურ" in out
    assert "პერფორმანსები" in out and "მუსიკალური" in out
    assert _SENTINELS["safety"] not in out


# =====================================================================
# 14. Sports
# =====================================================================
def test_14_sports(engine_on):
    out = parent_flow.handle(_conv("sp14"), "სპორტული აქტივობები იქნება?")
    assert "სპორტული აქტივობები და ჯანსაღი" in out
    assert _SENTINELS["general_overview"] not in out


# =====================================================================
# 15. General overview
# =====================================================================
def test_15_general_overview(engine_on):
    out = parent_flow.handle(_conv("o15"), "ბანაკზე დეტალური ინფორმაცია მინდა")
    assert "7-დღიანი პროგრამა" in out                       # 7 days
    assert "9-დან 17 წლამდე" in out                          # age 9–17
    assert "2150₾" in out                                    # price
    # short overview — NOT a dump of all topic blocks
    assert _SENTINELS["safety"] not in out
    assert _SENTINELS["food"] not in out
    assert _SENTINELS["bullying_empathy"] not in out
    assert _no_engine(out)


# =====================================================================
# 16. Sunday School exclusion
# =====================================================================
def test_16_sunday_school_excluded(engine_on, monkeypatch):
    _coming_soon(monkeypatch)
    msg = "საკვირაო სკოლაზე ინფორმაცია მინდა"
    assert ctf.detect_camp_topic(msg) is None                # not a camp topic
    out = parent_flow.handle(_conv("ss16"), msg)
    assert "დეტალები ჯერ ზუსტდება" in out                   # Sunday School flow
    assert _SENTINELS["general_overview"] not in out
    assert "2150" not in out


# =====================================================================
# 17. Adult event exclusion
# =====================================================================
def test_17_adult_event_excluded(engine_on):
    msg = "ზრდასრულთა ღონისძიებები რა გაქვთ?"
    assert ctf.detect_camp_topic(msg) is None
    out = parent_flow.handle(_conv("ad17", state="START"), msg)
    # no camp topic block is used; the turn falls through to the engine (adult route)
    for s in _SENTINELS.values():
        assert s not in out


# =====================================================================
# 18. Price exclusion (canonical price flow with 2150₾)
# =====================================================================
def test_18_price_excluded(engine_on):
    msg = "ბანაკის ფასი რა არის?"
    assert ctf.detect_camp_topic(msg) is None
    out = parent_flow.handle(_conv("pr18"), msg)
    assert "2150" in out                                     # canonical price
    for s in _SENTINELS.values():
        assert s not in out                                  # not topic facts


# =====================================================================
# 19. Registration link exclusion
# =====================================================================
def test_19_registration_excluded(engine_on):
    msg = "ბანაკის რეგისტრაციის ლინკი მომწერე"
    assert ctf.detect_camp_topic(msg) is None
    out = parent_flow.handle(_conv("rg19"), msg)
    assert out == parent_flow._render_camp_registration_answer()


# =====================================================================
# 20. Date exclusion
# =====================================================================
def test_20_dates_excluded(engine_on):
    msg = "როდის არის ბანაკი?"
    assert ctf.detect_camp_topic(msg) is None
    out = parent_flow.handle(_conv("dt20"), msg)
    assert out == _DATES_FULL
    for s in _SENTINELS.values():
        assert s not in out


# =====================================================================
# 21. Booking context guard
# =====================================================================
def test_21a_explicit_topic_in_booking_answers_topic(engine_on):
    conv = _booking_conv("bk21a")
    out = parent_flow.handle(conv, "უსაფრთხოება მაინტერესებს")
    assert "24-საათიანი ვიდეომონიტორინგი" in out             # safety topic answered
    assert _SENTINELS["safety"] in out


def test_21b_daypart_reply_stays_in_booking(engine_on):
    conv = _booking_conv("bk21b")
    out = parent_flow.handle(conv, "ორშაბათს საღამოს")
    assert ("რომელი საათი" in out) or ("რომელ საათზე" in out)  # stays in booking
    for s in _SENTINELS.values():
        assert s not in out                                  # no camp topic facts


# =====================================================================
# 22. No full dump — every specific topic answer carries ZERO other sentinels
# =====================================================================
def test_22_no_full_dump_per_topic():
    for topic in ctf.TOPIC_PRIORITY:
        if topic == "general_overview":
            continue  # overview legitimately spans several themes
        ans = ctf.answer_for_topic(topic)
        leaks = _no_other_sentinels(ans, topic)
        assert not leaks, f"{topic} answer leaked other categories: {leaks}"


def test_22b_handler_returns_single_block(engine_on):
    # Each specific question's reply equals exactly the one expected block.
    cases = [
        ("კამერები არის?", "safety"),
        ("კვება შედის?", "food"),
        ("ბავშვი სულ ტელეფონშია", "gadgets"),
        ("ბულინგის თემაზე მუშაობთ?", "bullying_empathy"),
    ]
    for msg, topic in cases:
        out = parent_flow.handle(_conv("blk"), msg)
        assert out == ctf.answer_for_topic(topic)


# =====================================================================
# Convention / safety guards
# =====================================================================
def test_no_cyrillic_or_latin_in_any_block():
    for topic in ctf.TOPIC_PRIORITY:
        ans = ctf.answer_for_topic(topic)
        assert not re.search("[Ѐ-ӿ]", ans), f"Cyrillic in {topic}"
        assert not re.search("[A-Za-z]", ans), f"Latin letters in {topic}"


def test_no_crm_wording_in_any_block():
    banned = ("დაგიტოვებთ ინტერესს", "ინტერესი დაფიქსირდა", "lead", "ლიდი")
    for topic in ctf.TOPIC_PRIORITY:
        low = ctf.answer_for_topic(topic).lower()
        for b in banned:
            assert b.lower() not in low, f"CRM word {b!r} in {topic}"


def test_gadgets_uses_new_wording_not_old():
    ans = ctf.answer_for_topic("gadgets")
    assert "გაჯეტებისგან განტვირთვა" in ans
    assert "ეკრანისგან დისტანცია" not in ans


def test_overview_price_is_canonical_not_hardcoded(monkeypatch):
    # The overview price comes from get_camp_facts(), not a literal in the YAML.
    monkeypatch.setattr(
        admin_config_service, "get_camp_facts",
        lambda: {"price_gel": 1999, "duration_days": 7, "age_min": 9, "age_max": 17},
    )
    out = ctf.answer_for_topic("general_overview")
    assert "1999₾" in out and "2150" not in out


def test_adult_segment_never_gets_camp_topic(engine_on):
    conv = _conv("adseg", segment="ADULT")
    # Even a clear safety question is not answered with a camp topic in ADULT.
    out = parent_flow._maybe_handle_camp_topic_facts(conv, "უსაფრთხოება როგორ არის?")
    assert out is None


def test_detect_is_self_contained_unit():
    assert ctf.detect_camp_topic("") is None
    assert ctf.detect_camp_topic("გამარჯობა") is None        # no topic
    assert ctf.detect_camp_topic("კამერები არის?") == "safety"
    # Doctor/medical now routes to the dedicated safe medical block (2026-06-28),
    # not the general safety topic.
    assert ctf.resolve_camp_answer("ექიმი იქნება?") == ctf.medical_answer()


# =====================================================================
# Follow-up (2026-06-28): unknown-detail honest defer + paragraphing +
# camp-context activities.
# =====================================================================
_UNKNOWN_DEFER = "ამ საკითხზე ზუსტი ინფორმაცია არ მაქვს"
_BAD_ROOM_CLAIMS = ("რამდენიმე ბავშვი", "2–3 ბავშვი", "2-3 ბავშვი", "კომფორტული განაწილება")
_DISCOVERY_Q = "რა არის მთავარი, რის მიღებაც გსურთ"


def test_f1_unknown_room_occupancy_defers(engine_on):
    out = parent_flow.handle(_conv("u1"), "ოთახში რამდენი ბავშვი იქნება?")
    assert _UNKNOWN_DEFER in out
    assert "მენეჯერი დაგიზუსტებთ დეტალებს" in out
    assert "მენეჯერთან დაგაკავშირებთ" in out
    for bad in _BAD_ROOM_CLAIMS:
        assert bad not in out                                # never invented
    assert _DISCOVERY_Q not in out                           # no discovery question
    assert not re.search(r"\d", out)                         # no invented 2/3/4
    assert _no_engine(out)


def test_f2_unknown_room_distribution_defers(engine_on):
    out = parent_flow.handle(_conv("u2"), "ოთახებში როგორ ანაწილებთ ბავშვებს?")
    assert _UNKNOWN_DEFER in out
    assert "მენეჯერი" in out
    for bad in _BAD_ROOM_CLAIMS:
        assert bad not in out


def test_f3_exact_menu_food_plus_manager_clarification(engine_on):
    out = parent_flow.handle(_conv("u3"), "ზუსტად რა მენიუ ექნებათ?")
    assert "კვება შედის ბანაკის ღირებულებაში" in out         # food included
    assert "ზუსტი მენიუ მენეჯერთან დაზუსტდება" in out        # exact menu deferred
    assert _UNKNOWN_DEFER not in out                         # not the generic fallback


def test_f3b_general_menu_question_no_exact_clarification(engine_on):
    out = parent_flow.handle(_conv("u3b"), "მენიუ როგორი იქნება?")
    assert "კვება შედის ბანაკის ღირებულებაში" in out
    assert "ზუსტი მენიუ მენეჯერთან დაზუსტდება" not in out    # not an exact-menu ask


def test_f4_activities_with_camp_context(engine_on):
    out = parent_flow.handle(_conv("u4"), "რას აკეთებენ ბავშვები ბანაკში?")
    assert "შემოქმედებით" in out and "გუნდურ" in out
    assert "პერფორმანსები" in out
    # transport / accommodation / food are NOT activities (the old engine bug)
    assert "ტრანსპორტ" not in out and "განთავსებ" not in out
    assert _no_engine(out)


def test_f5_generic_activities_no_camp_context_defers_to_engine(engine_on):
    # No camp keyword → NOT forced into the deterministic activities block
    # (protects the CTA-preservation flow). resolve returns None → engine.
    assert ctf.resolve_camp_answer("რას აკეთებენ ბავშვები?") is None
    assert ctf.resolve_camp_answer("კიდევ რას აკეთებენ ბავშვები?") is None


def test_f5b_child_behaviour_room_statement_not_unknown_fallback(engine_on):
    # „ერთ ოთახში გამოიკეტება" is a parent DESCRIBING the child, not a question
    # about the camp's rooms — must NOT trigger the unknown-detail defer.
    assert ctf.resolve_camp_answer("ერთ ოთახში გამოიკეტება") is None


def test_f6_paragraph_breaks_in_multi_idea_answers():
    for topic in ("safety", "parent_communication", "food", "gadgets",
                  "activities_creativity", "general_overview"):
        ans = ctf.answer_for_topic(topic)
        assert "\n\n" in ans, f"{topic} answer is a single wall-of-text"
        # No accidental 3+ consecutive newlines.
        assert "\n\n\n" not in ans, f"{topic} has excess blank lines"


def test_f7_known_topic_wins_over_unknown_fallback(engine_on):
    out = parent_flow.handle(_conv("k1"), "ბანაკში უსაფრთხოება როგორ არის?")
    assert "24-საათიანი ვიდეომონიტორინგი" in out
    assert _UNKNOWN_DEFER not in out

    out2 = parent_flow.handle(_conv("k2"), "ბავშვთან კონტაქტი მექნება?")
    assert "ფოტო-ვიდეო მასალა" in out2
    assert _UNKNOWN_DEFER not in out2


def test_f8_canonical_flows_not_unknown_fallback(engine_on, monkeypatch):
    out_price = parent_flow.handle(_conv("c1"), "ბანაკის ფასი რა არის?")
    assert "2150" in out_price and _UNKNOWN_DEFER not in out_price

    out_dates = parent_flow.handle(_conv("c2"), "როდის არის ბანაკი?")
    assert out_dates == _DATES_FULL and _UNKNOWN_DEFER not in out_dates

    _coming_soon(monkeypatch)
    out_ss = parent_flow.handle(_conv("c3"), "საკვირაო სკოლაზე ინფორმაცია მინდა")
    assert "დეტალები ჯერ ზუსტდება" in out_ss and _UNKNOWN_DEFER not in out_ss
