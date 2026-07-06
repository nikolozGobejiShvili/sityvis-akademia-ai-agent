"""Client QA report fixes (2026-06-29): topic-specific unknown-detail fallback,
known+unknown split, approved wording, and the blue-heart 💙 emoji policy.

Deterministic, legacy/giant-prompt path — engine ON, planner + slim OFF.

Covers:
  * unknown-detail fallback with a topic prefix + the EXACT approved ending
    „ამ დეტალებს მენეჯერი გაგაცნობთ : 558 67 47 33" (never „დაგიზუსტებთ", the
    space before the colon is intentional, manager phone always) — no emoji.
  * remaining-seats / stream-availability fallback (never invents availability).
  * known+unknown split (discount / eligible age / stream date → then seats).
  * approved food/menu wording; approved intro / price / CTA wording (prompt).
  * 💙 policy: ONLY greeting-start / booking-confirmed / farewell; never red ❤️;
    never a period immediately after 💙.
"""
from __future__ import annotations

import dataclasses
import re

import pytest

import app.config as config_module
from app.agent.llm import parent_llm_engine
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.reasoning import camp_topic_facts as ctf
from app.services import conversation_service, messenger_service

_MGR = "558 67 47 33"
_ENDING = "ამ დეტალებს მენეჯერი გაგაცნობთ : 558 67 47 33"
_ENGINE = "[ENGINE-MOCK]"
_SEATS_FB = f"რაც შეეხება კონკრეტულ ნაკადზე დარჩენილ ადგილებს, {_ENDING}"


@pytest.fixture(autouse=True)
def _reset():
    conversation_service.conversations.clear()
    yield
    conversation_service.conversations.clear()


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
            return "[ENGINE-DATES] ბანაკი ტარდება 23–29 ივნისი, 5–11 ივლისი."
        if any(p in low for p in ("ფასი", "ღირს", "ღირებულ", "გადასახ")):
            return "[ENGINE-PRICE] ბანაკის ღირებულებაა 2150₾."
        return _ENGINE

    monkeypatch.setattr(parent_flow, "_run_llm_engine_safely", _engine)
    return swapped


@pytest.fixture
def emoji_on(monkeypatch):
    """The client 💙 policy is pinned OFF in conftest; opt back in here."""
    monkeypatch.setattr(parent_flow, "_CLIENT_EMOJI_ENABLED", True, raising=False)


def _conv(sid="c", state="ASK_CHALLENGE", child_age="12", segment="PARENT", history=True):
    c = Conversation(sender_id=sid, platform="instagram", segment=segment)
    c.state = state
    if history:
        c.history.append({"role": "assistant", "content": "რას ელოდებით ბანაკისგან?"})
    c.lead = Lead(sender_id=sid, platform="instagram", segment=segment, child_age=child_age)
    return c


def _no_hearts(text):
    return "💙" not in text and "❤️" not in text


# =====================================================================
# 1–5. Unknown-detail fallback with topic prefix + manager phone
# =====================================================================
def test_1_room_occupancy(engine_on):
    out = parent_flow.handle(_conv("u1"), "ოთახში რამდენი ბავშვი იქნება?")
    assert f"რაც შეეხება ოთახებში ბავშვების განაწილებას, {_ENDING}" in out
    assert "რამდენიმე ბავშვი" not in out and "კომფორტული განაწილება" not in out
    assert "2-3 ბავშვი" not in out and "2–3 ბავშვი" not in out
    assert _no_hearts(out)


def test_2_towels(engine_on):
    out = parent_flow.handle(_conv("u2"), "პირსახოცები იქნება?")
    assert f"რაც შეეხება პირსახოცებს, {_ENDING}" in out
    assert not any(w in out for w in ("დიახ, იქნება", "არა, არ იქნება", "თან წამოიღეთ"))
    assert _no_hearts(out)


def test_3_hotel_guests(engine_on):
    out = parent_flow.handle(_conv("u3"), "სასტუმროში სხვა სტუმრებიც იქნებიან?")
    assert f"რაც შეეხება სასტუმროში სხვა სტუმრების ყოფნას, {_ENDING}" in out
    assert not any(w in out for w in ("მხოლოდ ბანაკისთვის", "სრულად დაჯავშნილი", "სხვა სტუმრები არ"))
    assert _no_hearts(out)


def test_4_transport_departure(engine_on):
    out = parent_flow.handle(_conv("u4"), "ტრანსპორტი საიდან გავა?")
    # 2026-07-06 — transport is now answered by the deterministic transport
    # interceptor (before the operational defer): it states the KNOWN fact
    # (transport is included in the price) + a manager defer for the exact
    # departure point/time (never invented, never the sports answer).
    assert "ბანაკის ღირებულებაში ტრანსპორტირება შედის" in out
    assert "ტრანსპორტის გასვლის ზუსტ ადგილს და დროს" in out
    assert "558 67 47 33" in out
    assert "სპორტული აქტივობები" not in out
    assert _no_hearts(out)


def test_5_hourly_schedule(engine_on):
    out = parent_flow.handle(_conv("u5"), "დღის განრიგი საათობრივად როგორია?")
    assert f"რაც შეეხება დღის ზუსტ განრიგს, {_ENDING}" in out
    assert _no_hearts(out)


def test_5b_direct_call_rules(engine_on):
    out = parent_flow.handle(_conv("u5b"), "ბავშვს დღეში რამდენჯერ დავურეკავ?")
    assert f"რაც შეეხება ბავშვთან პირდაპირი კონტაქტის წესებს, {_ENDING}" in out
    assert not any(w in out for w in ("ნებისმიერ დროს", "შეუზღუდავად", "დღეში ორჯერ"))
    assert _no_hearts(out)


# =====================================================================
# 6–9. Stream availability / remaining seats (never invent)
# =====================================================================
def test_6_seats_stream2(engine_on):
    out = parent_flow.handle(_conv("s6"), "მე-2 ნაკადზე ადგილები გაქვთ?")
    assert _SEATS_FB in out
    assert not any(w in out for w in ("კი, ადგილები არის", "ადგილი იქნება", "დაგარეგისტრირებთ",
                                      "მოვასწრებთ", "თავისუფალია"))
    assert _no_hearts(out)


def test_7_seats_date_stream(engine_on):
    out = parent_flow.handle(_conv("s7"), "5-11 ივლისის ნაკადზე არის ადგილი?")
    assert _SEATS_FB in out
    assert not any(w in out for w in ("კი, ადგილი არის", "თავისუფალია", "დაგარეგისტრირებთ"))


def test_8_seats_count(engine_on):
    out = parent_flow.handle(_conv("s8"), "რამდენი ადგილი დარჩა?")
    assert _SEATS_FB in out
    assert not re.search(r"\d+\s*ადგილ", out)                # no invented count


def test_9_seats_with_stream_date(engine_on):
    out = parent_flow.handle(_conv("s9"), "მე-2 ნაკადზე, 5-11 ივლისი, გაქვთ ადგილები?")
    assert "მე-2 ნაკადი ტარდება 5–11 ივლისს." in out         # known part (may confirm)
    assert _SEATS_FB in out                                  # unknown part deferred
    assert not any(w in out for w in ("კი, ადგილები არის", "თავისუფალია"))


# =====================================================================
# 10–12. Known + unknown split
# =====================================================================
def test_10_discount_plus_seats_exact(engine_on):
    out = parent_flow.handle(_conv("k10"), "ორი ბავშვი მინდა გამოვუშვა, ფასდაკლება და ადგილები იქნება?")
    expected = ("დედმამიშვილებისთვის მოქმედებს 10%-იანი ფასდაკლება.\n\n" + _SEATS_FB)
    assert expected in out
    assert _no_hearts(out)


def test_11_age_plus_seats(engine_on):
    out = parent_flow.handle(_conv("k11"), "მეორე ბავშვი 12 წლის არის და ადგილები გაქვთ?")
    assert "12 წლის ასაკი ბანაკისთვის შესაბამისია, რადგან პროგრამა 9–17 წლის ბავშვებისთვისაა." in out
    assert _SEATS_FB in out
    assert "რა არის მთავარი, რის მიღებაც გსურთ" not in out    # no generic discovery Q


def test_12_exact_menu_split(engine_on):
    out = parent_flow.handle(_conv("k12"), "ზუსტად რა მენიუ ექნებათ?")
    assert "ბანაკში კვება ორგანიზებულია ჯანსაღი და დაბალანსებული მენიუს მიხედვით" in out
    assert f"რაც შეეხება ზუსტ მენიუს, {_ENDING}" in out


# =====================================================================
# 13–16. Approved wording (intro / price / CTA / food)
# =====================================================================
def test_13_intro_wording_in_prompt():
    # Client follow-up hotfix (2026-06-29) — updated intro wording.
    prompt = parent_llm_engine._build_system_prompt()
    assert ("სიტყვის აკადემიის ბანაკი 7-დღიანი გამოცდილებაა, სადაც ბავშვები ისვენებენ და, "
            "ამავდროულად, სწავლობენ საკუთარი აზრებისა და ემოციების გამოხატვას") in prompt
    assert "რამდენი წლის არის თქვენი შვილი" in prompt
    # The old wording is no longer the APPROVED intro — the only remaining mention
    # is the explicit „never use this phrase" instruction (a negative rule).
    assert "დამტკიცებული ფორმულირება" in prompt
    assert prompt.count("თვითგამოხატვის პროცესში ერთვებიან") == 1  # the ban only


def test_13b_greeting_intro_gets_one_blue_heart(engine_on, emoji_on, monkeypatch):
    intro = ("გამარჯობა! სიტყვის აკადემიის ბანაკი 7-დღიანი გამოცდილებაა. "
             "რამდენი წლის არის თქვენი შვილი?")
    monkeypatch.setattr(parent_flow, "_run_llm_engine_safely", lambda c, m: intro)
    # Fresh first contact → greeting emoji; age UNKNOWN so the age question is
    # not stripped (the flow removes it only when the child age is already known).
    conv = _conv("g13", state="START", history=False, child_age="")
    out = parent_flow.handle(conv, "გამარჯობა, ბანაკზე ინფორმაცია მაინტერესებს")
    assert out.count("💙") == 1
    assert "❤️" not in out
    assert "💙." not in out
    assert "რამდენი წლის არის თქვენი შვილი" in out


def test_14_price_payment_wording_in_prompt():
    # Client follow-up hotfix (2026-06-29) — updated payment wording; simple
    # price and payment are separated (simple price must not carry payment terms).
    prompt = parent_llm_engine._build_system_prompt()
    assert ("ბანაკის ჯავშნის საფასურის გადახდა ხდება წინასწარ, ხოლო სრული თანხის — "
            "ხელშეკრულებით გათვალისწინებულ დროში.") in prompt
    # The simple-price rule forbids payment terms in a simple price answer.
    assert "მარტივ ფასის" in prompt


def test_14b_price_answer_has_no_blue_heart(engine_on, emoji_on):
    out = parent_flow.handle(_conv("p14"), "ბანაკის ფასი რა არის?")
    assert "2150" in out
    assert _no_hearts(out)


def test_15_consultation_cta_wording_in_prompt():
    # Client follow-up hotfix (2026-06-29) — updated consultation CTA wording.
    prompt = parent_llm_engine._build_system_prompt()
    assert "თუ გსურთ, კონსულტაციაზე ჩაგწერთ, სადაც დეტალებს მენეჯერი გაგაცნობთ." in prompt


def test_16_food_general_wording(engine_on):
    out = parent_flow.handle(_conv("f16"), "კვება როგორია ბანაკში?")
    assert "ბანაკში კვება ორგანიზებულია ჯანსაღი და დაბალანსებული მენიუს მიხედვით" in out
    assert not re.search("[Ѐ-ӿ]", out)                       # no mixed-script / Cyrillic


# =====================================================================
# 17–24. Emoji policy (💙 only greeting / booking / farewell)
# =====================================================================
def test_17_greeting_one_blue_heart(emoji_on):
    conv = _conv("e17", state="START", history=False)
    out = parent_flow._apply_client_emoji_policy(
        conv, "გამარჯობა, ბანაკზე ინფორმაცია მაინტერესებს",
        "გამარჯობა. სიტყვის აკადემიის ბანაკი 7-დღიანი გამოცდილებაა.",
    )
    assert out.count("💙") == 1 and "❤️" not in out and "💙." not in out
    assert out.startswith("გამარჯობა 💙")


def test_18_booking_confirmation_blue_heart(emoji_on, monkeypatch):
    monkeypatch.setattr(parent_flow, "_booking_success_this_turn", lambda c: True)
    base = ("კონსულტაცია ჩანიშნულია.\n\n"
            "თქვენი მონაცემები გამოიყენება მხოლოდ კონსულტაციისთვის და არ გასაჯაროვდება.")
    out = parent_flow._apply_client_emoji_policy(_conv("e18"), "დამიდასტურე", base)
    assert out.count("💙") == 1 and "❤️" not in out
    assert "კონსულტაცია ჩანიშნულია 💙" in out and "💙." not in out
    assert "თქვენი მონაცემები გამოიყენება მხოლოდ კონსულტაციისთვის" in out   # privacy wording


def test_19_farewell_blue_heart(emoji_on):
    out = parent_flow._apply_client_emoji_policy(
        _conv("e19"), "მადლობა",
        "მადლობა თქვენ. თუ კიდევ დაგჭირდებათ ინფორმაცია, მომწერეთ.",
    )
    assert out.count("💙") == 1 and "❤️" not in out and "💙." not in out
    assert "მადლობა თქვენ 💙" in out


def test_20_generic_manager_cta_no_forced_heart(emoji_on):
    out = parent_flow._apply_client_emoji_policy(
        _conv("e20"), "მენეჯერთან დამაკავშირეთ",
        "მენეჯერის ნომერია: 558 67 47 33.",
    )
    assert _no_hearts(out)


def test_21_unknown_fallback_no_heart(engine_on, emoji_on):
    out = parent_flow.handle(_conv("e21"), "პირსახოცები იქნება?")
    assert f"რაც შეეხება პირსახოცებს, {_ENDING}" in out
    assert _no_hearts(out)


def test_22_price_no_heart(engine_on, emoji_on):
    out = parent_flow.handle(_conv("e22"), "ბანაკის ფასი რა არის?")
    assert _no_hearts(out)


def test_23_safety_no_heart(engine_on, emoji_on):
    out = parent_flow.handle(_conv("e23"), "უსაფრთხოება როგორ არის?")
    assert _no_hearts(out)


def test_24_consultation_offer_no_heart(emoji_on):
    # An OFFER (not a confirmed booking) must never get 💙.
    out = parent_flow._apply_client_emoji_policy(
        _conv("e24"), "კონსულტაციაზე ჩამწერეთ?",
        "თუ გსურთ, კონსულტაციაზე ჩაგწერთ, სადაც მენეჯერი ყველა დეტალს გაგაცნობთ.",
    )
    assert _no_hearts(out)


def test_24b_no_period_after_heart_unit():
    # The guard removes any „." immediately after the heart, keeps the break.
    assert parent_flow._strip_period_after_heart("კონსულტაცია ჩანიშნულია 💙.") == "კონსულტაცია ჩანიშნულია 💙"
    assert parent_flow._strip_period_after_heart("გამარჯობა 💙. ტექსტი") == "გამარჯობა 💙 ტექსტი"
    assert parent_flow._strip_period_after_heart("მადლობა 💙\n\nტექსტი") == "მადლობა 💙\n\nტექსტი"


# =====================================================================
# 25–29. Regressions — known flows must NOT hit the unknown fallback
# =====================================================================
def test_25_safety_still_works(engine_on):
    out = parent_flow.handle(_conv("r25"), "ბანაკში უსაფრთხოება როგორ არის?")
    assert "24-საათიანი ვიდეომონიტორინგი" in out
    assert _ENDING not in out


def test_26_parent_communication_still_works(engine_on):
    out = parent_flow.handle(_conv("r26"), "ბავშვთან კონტაქტი მექნება?")
    assert "ფოტო-ვიდეო მასალა" in out                        # known block returned
    # Client wording fix (2026-07-01): the direct-contact caveat is the approved
    # topic-specific manager defer (not the generic „ამ საკითხს" fallback).
    assert f"რაც შეეხება ბავშვთან პირდაპირი კონტაქტის წესებს, {_ENDING}" in out
    assert "რაც შეეხება ამ საკითხს" not in out
    assert "აგიხსნით" not in out


def test_27_sunday_school_not_camp_fallback(engine_on, monkeypatch):
    monkeypatch.setattr(
        "app.services.admin_config_service.get_sunday_school_status",
        lambda: {"status": "coming_soon", "availability_text": "საკვირაო სკოლა ივლისში დაემატება.",
                 "details_text": "დეტალები ზუსტდება", "handoff_enabled": True, "lead_type": "sunday_school"},
    )
    out = parent_flow.handle(_conv("r27"), "საკვირაო სკოლაზე ინფორმაცია მინდა")
    assert "დეტალები ჯერ ზუსტდება" in out
    assert _ENDING not in out


def test_28_adult_event_not_camp_fallback(engine_on):
    out = parent_flow.handle(_conv("r28", state="START"), "ზრდასრულთა ღონისძიებები რა გაქვთ?")
    assert _ENDING not in out
    assert "დარჩენილ ადგილებს" not in out


def test_29_stream_date_question_not_seats_fallback(engine_on):
    # A pure „when is stream 2?" (no seats/availability word) → engine dates,
    # NOT the remaining-seats fallback.
    out = parent_flow.handle(_conv("r29"), "მე-2 ნაკადი როდის არის?")
    assert _SEATS_FB not in out
    assert "დარჩენილ ადგილებს" not in out


# =====================================================================
# Unit: no red heart remains in the deterministic policy
# =====================================================================
def test_heart_constant_is_blue():
    assert parent_flow._HEART == "💙"


# =====================================================================
# CLIENT FOLLOW-UP HOTFIX (2026-06-29) — global anti-invention +
# live-test failures 1–8 (first-turn defer, typo, greeting emoji,
# price/payment split, accommodation split, org, duplicate-age, farewell)
# =====================================================================
_GENERIC_FB = f"რაც შეეხება ამ საკითხს, {_ENDING}"
_ROOM_FB = f"რაც შეეხება ოთახებში ბავშვების განაწილებას, {_ENDING}"
_TOWEL_FB = f"რაც შეეხება პირსახოცებს, {_ENDING}"
_ORG_FB = f"რაც შეეხება ორგანიზატორების შესახებ დეტალებს, {_ENDING}"
_INTRO = (
    "სიტყვის აკადემიის ბანაკი 7-დღიანი გამოცდილებაა, სადაც ბავშვები ისვენებენ და, "
    "ამავდროულად, სწავლობენ საკუთარი აზრებისა და ემოციების გამოხატვას.\n\n"
    "რამდენი წლის არის თქვენი შვილი?"
)
_PRICE_WITH_PAYMENT = (
    "ბანაკის საფასურია 2150 ლარი. ღირებულებაში შედის ტრანსპორტი, განთავსება, კვება "
    "და სრული პროგრამა. ბანაკის საფასური სრულად უნდა დაიფაროს წინასწარ, თუმცა "
    "შესაძლებელია 6 თვემდე გადანაწილება TBC-ის და საქართველოს ბანკის განვადებით. "
    "თუ გსურთ, კონსულტაციაზე ჩაგწერთ, სადაც დეტალებს მენეჯერი გაგაცნობთ."
)
_PAYMENT_APPROVED = (
    "ბანაკის ჯავშნის საფასურის გადახდა ხდება წინასწარ, ხოლო სრული თანხის — "
    "ხელშეკრულებით გათვალისწინებულ დროში."
)


def _fresh(sid, child_age=""):
    return _conv(sid, state="START", child_age=child_age, history=False)


# 1. Global unknown rule — un-normalizable topic → generic fallback.
def test_hf1_generic_unknown_fallback(engine_on, emoji_on):
    out = parent_flow.handle(_conv("hf1"), "დაზღვევა გაქვთ ბანაკში?")
    assert _GENERIC_FB in out
    assert _no_hearts(out)


# 2. First-turn unknown fallback (room) — before intro / age question.
def test_hf2_first_turn_room(engine_on, emoji_on):
    out = parent_flow.handle(_fresh("hf2"), "ოთახში რამდენი ბავშვი იქნება?")
    assert _ROOM_FB in out
    assert "7-დღიანი" not in out
    assert "რამდენი წლის" not in out
    assert _no_hearts(out)


# 3. First-turn typo room question.
def test_hf3_first_turn_room_typo(engine_on):
    out = parent_flow.handle(_fresh("hf3"), "ოთხაში რამდენი ბავაში იქნება?")
    assert _ROOM_FB in out
    assert "7-დღიანი" not in out
    assert "რამდენი წლის" not in out


# 4. First-turn towel fallback.
def test_hf4_first_turn_towel(engine_on, emoji_on):
    out = parent_flow.handle(_fresh("hf4"), "პირსახოცები იქნება?")
    assert _TOWEL_FB in out
    assert "7-დღიანი" not in out
    assert "რამდენი წლის" not in out
    assert _no_hearts(out)


# 5. First-turn stream availability fallback (never invents availability).
def test_hf5_first_turn_seats(engine_on):
    out = parent_flow.handle(_fresh("hf5"), "მე-2 ნაკადზე ადგილები გაქვთ?")
    assert _SEATS_FB in out
    assert "7-დღიანი" not in out
    assert "რამდენი წლის" not in out
    assert not any(w in out for w in ("თავისუფალია", "კი, ადგილები არის", "ადგილი იქნება"))


# 6. Greeting 💙 placement (after greeting only, not after intro text).
def test_hf6_greeting_emoji_placement(engine_on, emoji_on, monkeypatch):
    monkeypatch.setattr(parent_flow, "_run_llm_engine_safely", lambda c, m: _INTRO)
    out = parent_flow.handle(_fresh("hf6"), "გამარჯობა ბანაკზე მაინტერესებს ინფორმაცია")
    assert out.startswith("გამარჯობა 💙")
    # Approved deterministic Camp intro (client hotfix 2026-07-03).
    assert "ციფრულ ხმაურს" in out
    assert "სწავლობენ საკუთარი აზრებისა და ემოციების გამოხატვას" not in out
    assert "რამდენი წლის არის თქვენი შვილი" in out
    assert "ერთვებიან 💙" not in out
    assert "გამოხატვას 💙" not in out
    assert "💙." not in out
    assert out.count("💙") == 1
    assert "❤️" not in out


# 7. Updated intro wording in the actual reply.
def test_hf7_intro_wording_output(engine_on, monkeypatch):
    monkeypatch.setattr(parent_flow, "_run_llm_engine_safely", lambda c, m: _INTRO)
    out = parent_flow.handle(_fresh("hf7"), "ბანაკზე მაინტერესებს ინფორმაცია")
    # Approved deterministic Camp intro (client hotfix 2026-07-03) — exact text.
    assert ("სიტყვის აკადემიის ბანაკი არის 7-დღიანი გამოცდილება, სადაც ბავშვები არა "
            "მხოლოდ ისვენებენ, არამედ რამდენიმე დღით შორდებიან ციფრულ ხმაურს, ერთვებიან "
            "ცოცხალ დისკუსიებში, სწავლობენ ფიქრს, აზრის ჩამოყალიბებასა და რეალურ "
            "ურთიერთობას.") in out
    assert "სწავლობენ საკუთარი აზრებისა და ემოციების გამოხატვას" not in out
    assert "თვითგამოხატვის პროცესში ერთვებიან" not in out
    assert "თვითგამოხქტვაში" not in out


# 8. Simple price answer — no payment / installment / bank terms.
def test_hf8_simple_price_no_payment(engine_on, emoji_on, monkeypatch):
    monkeypatch.setattr(parent_flow, "_run_llm_engine_safely", lambda c, m: _PRICE_WITH_PAYMENT)
    out = parent_flow.handle(_conv("hf8"), "ბანაკის ფასი რა არის?")
    assert "2150" in out
    for w in ("ტრანსპორტი", "განთავსება", "კვება", "სრული პროგრამა"):
        assert w in out
    assert "თუ გსურთ, კონსულტაციაზე ჩაგწერთ, სადაც დეტალებს მენეჯერი გაგაცნობთ." in out
    for bad in ("TBC", "საქართველოს ბანკ", "Bank of Georgia", "განვადებ", "წინასწარ",
                "ჯავშნის საფასურ", "ხელშეკრულებ"):
        assert bad not in out
    assert _no_hearts(out)


# 9. Payment answer — approved payment wording, kept intact.
def test_hf9_payment_answer(engine_on, emoji_on, monkeypatch):
    monkeypatch.setattr(parent_flow, "_run_llm_engine_safely", lambda c, m: _PAYMENT_APPROVED)
    out = parent_flow.handle(_conv("hf9"), "როგორ ხდება გადახდა?")
    assert _PAYMENT_APPROVED in out
    assert "Bank of Georgia" not in out
    assert _no_hearts(out)


# 10. One-time payment question → payment wording (not the simple price).
def test_hf10_onetime_payment(engine_on, monkeypatch):
    monkeypatch.setattr(parent_flow, "_run_llm_engine_safely", lambda c, m: _PAYMENT_APPROVED)
    out = parent_flow.handle(_conv("hf10"), "ერთიანად ხდება გადახდა?")
    assert "ხელშეკრულებით გათვალისწინებულ დროში" in out
    assert "2150" not in out


# 11. Purchase question → payment wording.
def test_hf11_purchase(engine_on, monkeypatch):
    monkeypatch.setattr(parent_flow, "_run_llm_engine_safely", lambda c, m: _PAYMENT_APPROVED)
    out = parent_flow.handle(_conv("hf11"), "როგორ ხდება შეძენა?")
    assert "ხელშეკრულებით გათვალისწინებულ დროში" in out


# 12. General accommodation → approved general sentence (no room count).
def test_hf12_accommodation_general(engine_on):
    out = parent_flow.handle(_conv("hf12"), "განთავსება როგორია?")
    assert "ბანაკში ბავშვები ნაწილდებიან კომფორტულ ოთახებში." in out
    assert not re.search(r"\d+\s*ბავშვ", out)


# 13. Exact room count → unknown fallback (not the general sentence).
def test_hf13_exact_room_count(engine_on):
    out = parent_flow.handle(_conv("hf13"), "ოთახში რამდენი ბავშვი იქნება?")
    assert _ROOM_FB in out
    assert "ნაწილდებიან კომფორტულ ოთახებში" not in out


# 14. Organization / team question → no age funnel, org defer.
def test_hf14_org_question(engine_on, emoji_on):
    out = parent_flow.handle(_conv("hf14"), "თქვენს უკან ვინ დგას?")
    assert "ეს არის სიტყვის აკადემიის AI ასისტენტი." in out
    assert _ORG_FB in out
    assert "რამდენი წლის არის თქვენი შვილი" not in out
    assert "თქვენი შვილი რამდენი წლისაა" not in out
    assert _no_hearts(out)


# 15. Duplicate-age guard — unit.
def test_hf15_duplicate_age_guard_unit():
    both = ("სიტყვის აკადემია დამოუკიდებელი გუნდია. რამდენი წლის არის თქვენი შვილი? "
            "თქვენი შვილი რამდენი წლისაა?")
    out = parent_flow._dedupe_child_age_questions(both)
    n = out.count("რამდენი წლის არის თქვენი შვილი") + out.count("თქვენი შვილი რამდენი წლისაა")
    assert n == 1
    assert "რამდენი წლის არის თქვენი შვილი" in out       # keeps the first
    assert "თქვენი შვილი რამდენი წლისაა" not in out       # drops the second


# 15b. Duplicate-age guard — end to end (engine leaked two).
def test_hf15b_duplicate_age_guard_end_to_end(engine_on, monkeypatch):
    dbl = ("სიამოვნებით დაგეხმარებით. რამდენი წლის არის თქვენი შვილი? "
           "თქვენი შვილი რამდენი წლისაა?")
    monkeypatch.setattr(parent_flow, "_run_llm_engine_safely", lambda c, m: dbl)
    out = parent_flow.handle(_conv("hf15b", child_age=""), "ბანაკზე მაინტერესებს")
    n = out.count("რამდენი წლის არის თქვენი შვილი") + out.count("თქვენი შვილი რამდენი წლისაა")
    assert n == 1


# 16. Thanks closing — no funnel continuation.
def test_hf16_thanks_closing(engine_on, emoji_on):
    out = parent_flow.handle(_conv("hf16", child_age=""), "მადლობა")
    assert "💙" in out
    assert "❤️" not in out
    assert "💙." not in out
    assert "რამდენი წლის არის თქვენი შვილი" not in out
    assert "თქვენი შვილი რამდენი წლისაა" not in out
    assert "9-ნიშნა" not in out and "ნომერი მომწერეთ" not in out
    assert "კონსულტაციაზე ჩაგწერთ" not in out


# 17. Decline + thanks — warm close, no age/phone/consultation.
def test_hf17_decline_thanks(engine_on, emoji_on):
    out = parent_flow.handle(_conv("hf17", child_age=""), "მადლობა არ მინდა")
    assert "💙" in out
    assert "💙." not in out
    assert "რამდენი წლის" not in out
    assert "9-ნიშნა" not in out
    assert "კონსულტაციაზე ჩაგწერთ" not in out


# 18. Soft close.
def test_hf18_soft_close(engine_on):
    out = parent_flow.handle(_conv("hf18", child_age=""), "ჯერ არა, მადლობა")
    assert "რამდენი წლის" not in out
    assert "9-ნიშნა" not in out
    assert "კონსულტაციაზე ჩაგწერთ" not in out


# 19. Later close.
def test_hf19_later_close(engine_on):
    out = parent_flow.handle(_conv("hf19", child_age=""), "მადლობა, მერე მოგწერთ")
    assert "რამდენი წლის" not in out
    assert "9-ნიშნა" not in out
    assert "კონსულტაციაზე ჩაგწერთ" not in out


# ── Regression — known flows keep working, no unknown fallback ──────────────
def test_hf_reg_food_general_no_heart(engine_on, emoji_on):
    out = parent_flow.handle(_conv("hfr1"), "კვება როგორია ბანაკში?")
    assert "ბანაკში კვება ორგანიზებულია ჯანსაღი და დაბალანსებული მენიუს მიხედვით" in out
    assert _ENDING not in out
    assert _no_hearts(out)


def test_hf_reg_exact_menu_split(engine_on):
    out = parent_flow.handle(_conv("hfr2"), "ზუსტად რა მენიუ ექნებათ?")
    assert "ბანაკში კვება ორგანიზებულია ჯანსაღი და დაბალანსებული მენიუს მიხედვით" in out
    assert f"რაც შეეხება ზუსტ მენიუს, {_ENDING}" in out


def test_hf_reg_safety_no_fallback(engine_on):
    out = parent_flow.handle(_conv("hfr3"), "ბანაკში უსაფრთხოება როგორ არის?")
    assert "24-საათიანი ვიდეომონიტორინგი" in out
    assert _ENDING not in out


def test_hf_reg_stream_date_known_not_seats(engine_on):
    out = parent_flow.handle(_conv("hfr4"), "მე-2 ნაკადი როდის არის?")
    assert _SEATS_FB not in out
    assert "დარჩენილ ადგილებს" not in out


# ── Adversarial-review hardening (client follow-up hotfix 2026-06-29) ────────
def test_hf_rev_bare_greeting_menu_preserved(engine_on, emoji_on):
    # Bare „გამარჯობა" first turn → welcome menu with 💙 on its OWN opening line
    # and the two-option menu preserved (not collapsed onto one line).
    out = parent_flow.handle(_fresh("rev1"), "გამარჯობა")
    assert out.startswith("გამარჯობა 💙")
    assert out.count("💙") == 1 and "💙." not in out
    assert "— ბავშვების საზაფხულო ბანაკი" in out and "— ზრდასრულთა კულტურული საღამოები" in out
    # menu items stay on their own lines (paragraph break not collapsed)
    assert "\n" in out.split("💙", 1)[1]


def test_hf_rev_gamarjobat_not_split():
    # The longer greeting „გამარჯობათ" must not be split by the shorter form.
    out = parent_flow._add_heart_after_greeting("გამარჯობათ, ბანაკი მშვენიერია.")
    assert out.startswith("გამარჯობა 💙")
    assert out.count("💙") == 1
    assert "💙 თ" not in out                       # not split before „თ"


def test_hf_rev_greeting_plus_unknown_no_heart(engine_on, emoji_on):
    # A first-turn greet + unknown-detail → the manager defer only, NO 💙.
    out = parent_flow.handle(_fresh("rev3"), "გამარჯობა, ოთახში რამდენი ბავშვია?")
    assert _ROOM_FB in out
    assert _no_hearts(out)
    assert "გამარჯობა" not in out                  # no invented greeting on the defer


def test_hf_rev_price_upfront_leak_stripped(engine_on, monkeypatch):
    # A paraphrased upfront-payment leak („წინასწარ") is stripped from a simple
    # price answer even without the TBC / განვადება anchors.
    leak = ("ბანაკის საფასურია 2150 ლარი. ღირებულებაში შედის ტრანსპორტი, კვება. "
            "თანხის ნაწილი წინასწარ გადაიხდება. თუ გსურთ, კონსულტაციაზე ჩაგწერთ.")
    monkeypatch.setattr(parent_flow, "_run_llm_engine_safely", lambda c, m: leak)
    out = parent_flow.handle(_conv("rev4"), "ბანაკის ფასი რა არის?")
    assert "2150" in out
    assert "წინასწარ" not in out


def test_hf_rev_payment_via_gadasakhad_not_gutted(engine_on, monkeypatch):
    # „გადასახადი როგორ ხდება?" is a PAYMENT question → the approved payment
    # wording survives (the price sanitizer must not gut it).
    monkeypatch.setattr(parent_flow, "_run_llm_engine_safely", lambda c, m: _PAYMENT_APPROVED)
    out = parent_flow.handle(_conv("rev5"), "გადასახადი როგორ ხდება?")
    assert _PAYMENT_APPROVED in out


def test_hf_rev_yes_thanks_not_closed(engine_on):
    # „კი, მადლობა" (a slot-offer confirmation) must NOT be cold-closed.
    assert parent_flow._is_thanks_or_farewell_close("კი, მადლობა") is False
    assert parent_flow._is_thanks_or_farewell_close("მადლობა, ჩამწერეთ") is False
    # …but „კიდევ" must not trip the „კი" affirmation, and a plain thanks closes.
    assert parent_flow._is_thanks_or_farewell_close("კიდევ მადლობა") is True
    assert parent_flow._is_thanks_or_farewell_close("მადლობა") is True


def test_hf_rev_dedupe_asaki_ramdenia_form():
    # AGE_QUESTION_RE misses „ასაკი რამდენია?"; the dedup + ensure-guard must not.
    dbl = "გასაგებია. თქვენი შვილის ასაკი რამდენია? თქვენი შვილი რამდენი წლისაა?"
    out = parent_flow._dedupe_child_age_questions(dbl)
    assert "თქვენი შვილი რამდენი წლისაა" not in out
    assert "ასაკი რამდენია" in out
    conv = _conv("rev7", child_age="")
    out2 = parent_flow._ensure_camp_age_question(
        conv, "ბანაკი მაინტერესებს", "გასაგებია. თქვენი შვილის ასაკი რამდენია?",
    )
    assert out2.count("რამდენ") == 1                # no second age question appended


# =====================================================================
# CLIENT FOLLOW-UP HOTFIX (2026-06-30) — exact-detail food/staff/peer,
# multi-question, political / clarification / final-response guards
# =====================================================================
_FOOD_GEN = ("ბანაკში კვება ორგანიზებულია ჯანსაღი და დაბალანსებული მენიუს მიხედვით, "
             "რაც ხელს უწყობს ბავშვების ფიზიკურ და ემოციურ კეთილდღეობას. "
             "კვება შედის ბანაკის ღირებულებაში.")
_FREQ_FB = f"რაც შეეხება დღეში კვების რაოდენობას, {_ENDING}"
_MENU_FB2 = f"რაც შეეხება ზუსტ მენიუს, {_ENDING}"
_STAFF_LINE = ("ადგილზე ბავშვებთან მუშაობს მაღალკვალიფიციური, პასუხისმგებლიანი და "
               "საბანაკე გამოცდილების მქონე სტაფი.")
_STAFF_FB = f"რაც შეეხება სტაფის წევრების რაოდენობას, {_ENDING}"
_PEER_FB = f"რაც შეეხება მისი ტოლი ბავშვების ყოფნას კონკრეტულ ნაკადში, {_ENDING}"
_STADIUM_FB = f"რაც შეეხება სტადიონს, {_ENDING}"


def _conv_hist(sid, prior, child_age="12"):
    c = _conv(sid, child_age=child_age)
    c.history.append({"role": "assistant", "content": prior})
    return c


def test_ed1_food_frequency(engine_on):
    out = parent_flow.handle(_conv("ed1"), "კვება დღეში რადმენჯერ არის?")
    assert _FOOD_GEN in out
    assert _FREQ_FB in out
    assert not re.search(r"დღეში\s*\d+", out)          # no invented frequency


def test_ed2_food_frequency_repeat(engine_on):
    out = parent_flow.handle(_conv_hist("ed2", _FOOD_GEN), "დღეში რამდენჯერ ექნებათ კვება არ იცი?")
    assert _FREQ_FB in out
    assert _FOOD_GEN not in out                          # no repeated general block


def test_ed3_menu_detail(engine_on):
    out = parent_flow.handle(_conv("ed3"), "მენიუ როგორი იქნება?")
    assert _FOOD_GEN in out
    assert _MENU_FB2 in out


def test_ed3b_menu_detail_variants(engine_on):
    for m in ("ზუსტად რა მენიუ ექნებათ?", "მენიუში რა იქნება?", "რა საჭმელები ექნებათ?", "დღის მენიუ როგორია?"):
        out = parent_flow.handle(_conv("ed3b"), m)
        assert _MENU_FB2 in out, m


def test_ed4_stadium_no_age_question(engine_on):
    out = parent_flow.handle(_conv("ed4", child_age=""), "სტადიონი ექნებათ ბანაკში?")
    assert _STADIUM_FB in out
    assert "როგორია თქვენი შვილის ასაკი" not in out
    assert "რამდენი წლის არის თქვენი შვილი" not in out
    assert "თქვენი შვილი რამდენი წლისაა" not in out


def test_ed5_multi_price_sports(engine_on):
    out = parent_flow.handle(_conv("ed5"), "ფასი რა არის ბანაკის? და სპორტული აქტივობები იქნება?")
    assert "2150" in out
    assert "სპორტული აქტივობები" in out                  # sports NOT dropped


def test_ed6_multi_food_menu(engine_on):
    out = parent_flow.handle(_conv("ed6"), "კვება შედის და მენიუ როგორი იქნება?")
    assert "ბანაკში კვება ორგანიზებულია" in out
    assert _MENU_FB2 in out


def test_ed7_multi_safety_contact(engine_on):
    out = parent_flow.handle(_conv("ed7"), "უსაფრთხოება როგორ არის და ბავშვთან კონტაქტი მექნება?")
    assert "უსაფრთხოებ" in out
    assert ("მშობლ" in out) or ("კომუნიკაცი" in out)     # parent-communication present


def test_ed8_multi_price_stadium(engine_on):
    out = parent_flow.handle(_conv("ed8"), "ფასი რა არის და სტადიონი ექნებათ?")
    assert "2150" in out
    assert _STADIUM_FB in out


def test_ed8b_multi_price_seats(engine_on):
    out = parent_flow.handle(_conv("ed8b"), "ფასი რა არის და ადგილები გაქვთ?")
    assert "2150" in out
    assert _SEATS_FB in out


def test_ed9_political_qoc(engine_on):
    out = parent_flow.handle(_conv("ed9", child_age=""), "ქოცები ხართ თქვენ?")
    assert "პოლიტიკურ თემებზე პასუხს არ ვცემ" in out
    assert "ბანაკთან დაკავშირებულ კითხვებზე დაგეხმარებით" in out
    assert "მსურს დაგეხმაროთ" not in out
    assert "რამდენი წლის" not in out and "ასაკი" not in out
    assert _no_hearts(out)


def test_ed10_political_nac(engine_on):
    out = parent_flow.handle(_conv("ed10", child_age=""), "ნაცები ხართ?")
    assert "პოლიტიკურ თემებზე პასუხს არ ვცემ" in out
    assert "მსურს დაგეხმაროთ" not in out
    assert "რამდენი წლის" not in out


def test_ed10b_political_no_false_positive():
    import app.reasoning.camp_topic_facts as _ctf
    assert _ctf.political_reply("თქვენი ნაცნობი ვარ") is None    # „ნაცნობი" ≠ political


def test_ed11_hotel_guests_no_cta(engine_on):
    out = parent_flow.handle(_conv("ed11"), "სხვა სტუმრები იქნებიან ბანაკში თუ მარტო ბანაკის ბავშვები იქნებიან?")
    assert _ENDING in out
    assert "კონსულტაციაზე ჩაგწერთ" not in out
    assert "აგიხსნით" not in out


def test_ed12_staff_count(engine_on):
    out = parent_flow.handle(_conv("ed12"), "რამდენი ადამიანისგან შედგება ბანაკის სტაფი?")
    assert _STAFF_LINE in out
    assert _STAFF_FB in out
    assert not re.search(r"\d+\s*(ადამიან|ლიდერ|სტაფ)", out)   # no invented count


def test_ed13_staff_count_followup(engine_on):
    out = parent_flow.handle(_conv("ed13"), "რამდენი ადამიანი იქნება სტაფში არ იცი?")
    assert _STAFF_FB in out


def test_ed14_unclear_phrase(engine_on):
    out = parent_flow.handle(_conv("ed14", child_age=""), "ჩემი შვილი ხელა ბავშვები იქნებიან?")
    assert ("გთხოვთ, განმიმარტეთ, რას გულისხმობთ „ხელა ბავშვებში“, რომ უკეთესად "
            "შევძლო თქვენი დახმარება.") in out
    assert "ასე უკეთ გაგვეცნობა თქვენი სურვილები" not in out


def test_ed15_peer_same_age(engine_on):
    out = parent_flow.handle(_conv("ed15", child_age=""), "ჩემი შვილი 14 წლის არის და მისი ტოლი ბავშვები თუ იქნებიან?")
    assert "14 წლის ასაკი ბანაკისთვის შესაბამისია" in out
    assert _PEER_FB in out
    assert "თანატოლები იქნებიან" not in out


def test_ed16_age_group_count(engine_on):
    out = parent_flow.handle(_conv("ed16"), "რამდენი ბავშვი იქნება 14 წლის?")
    assert f"რაც შეეხება 14 წლის ბავშვების რაოდენობას, {_ENDING}" in out
    assert "კონსულტაციაზე ჩაგწერთ" not in out
    assert "აგიხსნით" not in out


def test_ed17_final_guard_unit():
    leaked = ("რაც შეეხება სტადიონს, ამ დეტალებს მენეჯერი გაგაცნობთ : 558 67 47 33. "
              "როგორია თქვენი შვილის ასაკი, რომ უკეთ დაგეხმაროთ?")
    out = parent_flow._strip_extras_after_unknown_fallback(leaked)
    assert _ENDING in out
    assert "როგორია თქვენი შვილის ასაკი" not in out
    assert "რამდენი წლის არის თქვენი შვილი" not in out

    leaked2 = ("რაც შეეხება სხვა სტუმრებს ბანაკში, ამ დეტალებს მენეჯერი გაგაცნობთ : 558 67 47 33. "
               "თუ გსურთ, კონსულტაციაზე ჩაგწერთ, სადაც დეტალებს მენეჯერი აგიხსნით.")
    out2 = parent_flow._strip_extras_after_unknown_fallback(leaked2)
    assert _ENDING in out2
    assert "კონსულტაციაზე ჩაგწერთ" not in out2
    assert "აგიხსნით" not in out2


def test_ed17b_final_guard_preserves_known_unknown_split():
    split = ("დედმამიშვილებისთვის მოქმედებს 10%-იანი ფასდაკლება.\n\n" + _SEATS_FB)
    assert parent_flow._strip_extras_after_unknown_fallback(split) == split
