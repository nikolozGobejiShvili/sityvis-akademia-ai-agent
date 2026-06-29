"""Follow-up (live smoke 2026-06-28):

P1 — parent→child CONTACT questions route to the parent-communication block
     (not the consultation phone/video flow, not communication_socialization).
P2 — deterministic one-❤️ emoji policy (greeting / booking confirmation /
     thank-you only; never on a generic CTA or contact ask).
P3 — no mid-conversation greeting/„thank you for contacting" leak.
P4/P5 — medication / medical questions get a SAFE answer (medical personnel
     24/7 + clarify schedule with manager in advance; never overpromise).

Legacy/giant-prompt path: engine ON, planner + slim OFF. The ❤️ policy is gated
by parent_flow._CLIENT_EMOJI_ENABLED (default ON for live, pinned OFF in
conftest); this file opts back in.
"""
from __future__ import annotations

import dataclasses

import pytest

import app.config as config_module
from app.agent.tools import parent_tool_executor as pte
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.reasoning import camp_topic_facts as ctf
from app.services import admin_config_service, conversation_service, messenger_service

_MANAGER_NUMBER = "558 67 47 33"
_HEART = "❤️"
_LEAK = "მადლობა, რომ დაგვიკავშირდით. "          # simulated mid-convo intro leak
_PRICE = "ბანაკის ღირებულებაა 2150₾. შედის ტრანსპორტი."
_DATES = "ბანაკი ტარდება 23–29 ივნისი, 5–11 ივლისი."
_ENGINE = "[ENGINE] ბანაკზე დაგეხმარებით."


@pytest.fixture(autouse=True)
def _reset():
    conversation_service.conversations.clear()
    parent_flow.invalid_phone_retries.clear()
    parent_flow._sunday_school_notified_senders.clear()
    pte.book_consultation_success_for_conversation.clear()
    yield
    conversation_service.conversations.clear()
    parent_flow._sunday_school_notified_senders.clear()
    pte.book_consultation_success_for_conversation.clear()


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
    # Opt back in to the client ❤️ policy (conftest pins it OFF by default).
    monkeypatch.setattr(parent_flow, "_CLIENT_EMOJI_ENABLED", True, raising=False)

    def _engine(c, m):
        low = (m or "").lower()
        # Simulate the LLM leaking a greeting/intro on engine-answered turns so
        # the mid-conversation leak guard is exercised on price/date turns.
        if "როდის" in low or "თარიღ" in low:
            return _LEAK + _DATES
        if any(p in low for p in ("ფასი", "ღირს", "ღირებულ", "გადასახ")):
            return _LEAK + _PRICE
        if "მენეჯერ" in low:
            return "თუ გსურთ, მენეჯერთან დაგაკავშირებთ. მომწერეთ სახელი და 9-ნიშნა ნომერი."
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


def _conv(sid="c", state="ASK_CHALLENGE", child_age="12"):
    """Mid-flow conversation (a prior assistant turn → not the first reply)."""
    c = Conversation(sender_id=sid, platform="instagram", segment="PARENT")
    c.state = state
    c.history.append({"role": "assistant", "content": "რას ელოდებით ბანაკისგან?"})
    c.lead = Lead(sender_id=sid, platform="instagram", segment="PARENT",
                  child_age=child_age)
    return c


def _fresh_conv(sid="f"):
    """First-contact conversation (no assistant turn yet)."""
    c = Conversation(sender_id=sid, platform="instagram", segment="PARENT")
    c.state = "START"
    c.lead = Lead(sender_id=sid, platform="instagram", segment="PARENT")
    return c


_PC = ctf.answer_for_topic("parent_communication")
_CONSULT_PHRASE = "კონსულტაცია ძირითადად ტელეფონით ან ვიდეოზარით"


# =====================================================================
# P1 — Parent→child contact routing
# =====================================================================
def test_1_how_do_i_contact_my_child(engine_on):
    out = parent_flow.handle(_conv("p1"), "მე როგორ დავუკავშირდები ბავშვს?")
    assert out == _PC
    assert "დღის პროგრამა" in out and "ფოტო-ვიდეო მასალა" in out
    assert "კონტაქტის წესები" in out and "მენეჯერი" in out
    assert _CONSULT_PHRASE not in out


def test_2_child_contact_in_camp(engine_on):
    out = parent_flow.handle(_conv("p2"), "ბავშვთან კონტაქტი როგორ მექნება ბანაკში?")
    assert out == _PC
    assert _CONSULT_PHRASE not in out


def test_3_daily_communication_not_socialization(engine_on):
    out = parent_flow.handle(_conv("p3"), "დღის განმავლობაში ბავშვთან კომუნიკაციას შევძლებ?")
    assert out == _PC
    assert ctf.answer_for_topic("communication_socialization") != out


def test_4_typo_konataqti(engine_on):
    out = parent_flow.handle(_conv("p4"), "ბავშვთან კონატაქტი როგორ მექნება ბანაკში?")
    assert out == _PC


def test_5_typo_bavsshv(engine_on):
    out = parent_flow.handle(_conv("p5"), "მე როგორ დავუკავშირდები ბავსშვს?")
    assert out == _PC


def test_6_communication_difficulty_still_socialization(engine_on):
    out = parent_flow.handle(_conv("p6"), "კომუნიკაცია უჭირს")
    assert out == ctf.answer_for_topic("communication_socialization")
    assert out != _PC


# =====================================================================
# P2 — Emoji policy
# =====================================================================
def test_7_first_greeting_one_heart(engine_on):
    out = parent_flow.handle(_fresh_conv("e7"), "გამარჯობა, ბანაკზე ინფორმაცია მაინტერესებს")
    assert out.count(_HEART) == 1


def test_8_generic_manager_cta_no_heart(engine_on):
    out = parent_flow.handle(_conv("e8"), "მენეჯერთან დამაკავშირეთ")
    assert _HEART not in out                          # generic manager CTA → no forced ❤️
    assert "მენეჯერთან დაგაკავშირებთ" in out          # manager connection still works


def test_9_consultation_offer_no_heart(engine_on):
    out = parent_flow.handle(_conv("e9"), "კონსულტაციაზე ჩამწერეთ?")
    assert _HEART not in out                          # no heart before booking


def test_10_booking_confirmation_one_heart(engine_on):
    sid = "e10"
    conv = _conv(sid)
    pte.book_consultation_success_for_conversation[sid] = True
    confirmation = (
        "კონსულტაცია 21 ივნისს, 14:00 ჩაგინიშნეთ. მენეჯერი დაგიკავშირდებათ. "
        + parent_flow._PRIVACY_NOTICE
    )
    out = parent_flow._apply_client_emoji_policy(conv, "კი", confirmation)
    assert out.count(_HEART) == 1
    assert "თქვენი ინფორმაცია გამოიყენება მხოლოდ კონსულტაციისთვის" in out


def test_11_thank_you_one_heart(engine_on):
    out = parent_flow.handle(_conv("e11"), "მადლობა")
    assert out.count(_HEART) == 1


def test_12_non_greeting_topic_no_heart(engine_on):
    out = parent_flow.handle(_conv("e12"), "ბანაკში უსაფრთხოება როგორ არის?")
    assert _HEART not in out
    assert "ვიდეომონიტორინგი" in out                  # safety answer intact


# =====================================================================
# P3 — Mid-conversation greeting leak
# =====================================================================
def test_13_doctor_no_greeting_leak(engine_on):
    out = parent_flow.handle(_conv("g13"), "ექიმი გეყოლებათ?")
    assert "სამედიცინო პერსონალი 24/7" in out
    assert not out.startswith("მადლობა, რომ დაგვიკავშირდით")
    assert not out.startswith("გამარჯობა")
    assert not out.startswith("მოგესალმებით")


def test_13b_leak_guard_strips_intro(engine_on):
    conv = _conv("g13b")
    leaked = "მადლობა, რომ დაგვიკავშირდით. ბანაკში არის სამედიცინო პერსონალი 24/7."
    out = parent_flow._strip_midconvo_intro_leak(conv, "ექიმი გეყოლებათ?", leaked)
    assert out == "ბანაკში არის სამედიცინო პერსონალი 24/7."


def test_14_price_no_greeting_leak(engine_on):
    out = parent_flow.handle(_conv("g14"), "ბანაკის ფასი რა არის?")
    assert "მადლობა, რომ დაგვიკავშირდით" not in out
    assert "2150" in out


def test_15_safety_no_greeting_leak(engine_on):
    out = parent_flow.handle(_conv("g15"), "უსაფრთხოება როგორ არის?")
    assert "მადლობა, რომ დაგვიკავშირდით" not in out
    assert "ვიდეომონიტორინგი" in out


def test_15b_leak_guard_not_on_first_reply(engine_on):
    # On the FIRST reply a leading greeting is legitimate (owned by the welcome).
    conv = _fresh_conv("g15b")
    text = "გამარჯობა. ბანაკზე დაგეხმარებით."
    out = parent_flow._strip_midconvo_intro_leak(conv, "ბანაკი", text)
    assert out == text


def test_15c_user_thanks_response_not_stripped(engine_on):
    # When the user actually thanked, a warm „მადლობა თქვენ" reply is preserved.
    conv = _conv("g15c")
    text = "მადლობა თქვენ. თუ კიდევ დაგჭირდებათ ინფორმაცია, მომწერეთ."
    out = parent_flow._strip_midconvo_intro_leak(conv, "მადლობა", text)
    assert out == text


# =====================================================================
# P4/P5 — Medication safety
# =====================================================================
def test_16_medication_supervision_no_overpromise(engine_on):
    msg = ("ჩემს შვილს ყოველდღე სჭირდება კონკრეტული მედიკამენტის მიღება და ხომ "
           "გააკონტროლებთ რომ თავის დროზე დალიოს?")
    out = parent_flow.handle(_conv("m16"), msg)
    assert "სამედიცინო პერსონალი 24/7" in out
    assert "მენეჯერთან უნდა დაზუსტდეს" in out
    assert "პასუხისმგებელ გუნდს" in out
    assert "მენეჯერთან დაგაკავშირებთ" in out
    for bad in ("აუცილებლად გააკონტროლებენ", "ექიმი მისცემს წამალს",
                "გარანტირებულად დალევს", "აუცილებლად დალევს", "ჩვენ გავაკონტროლებთ"):
        assert bad not in out
    assert _HEART not in out                          # manager offer alone → no heart


def test_17_doctor_gives_medicine_no_guarantee(engine_on):
    out = parent_flow.handle(_conv("m17"), "წამალს ექიმი მისცემს?")
    assert "მენეჯერთან უნდა დაზუსტდეს" in out
    assert "აუცილებლად" not in out
    assert _HEART not in out


def test_18_medication_schedule(engine_on):
    out = parent_flow.handle(_conv("m18"), "წამლის გრაფიკი აქვს ბავშვს")
    assert "სამედიცინო პერსონალი 24/7" in out
    assert "მენეჯერთან უნდა დაზუსტდეს" in out
    for bad in ("აუცილებლად", "გარანტირებ"):
        assert bad not in out


# =====================================================================
# Regression
# =====================================================================
def test_19_parent_communication_still_works(engine_on):
    out = parent_flow.handle(_conv("r19"), "ბავშვთან კონტაქტი მექნება?")
    assert out == _PC


def test_20_gadgets_still_works(engine_on):
    out = parent_flow.handle(_conv("r20"), "ბავშვი სულ ტელეფონშია")
    assert "გაჯეტებისგან განტვირთვა" in out
    assert _HEART not in out


def test_21_sunday_school_excluded(engine_on, monkeypatch):
    _coming_soon(monkeypatch)
    out = parent_flow.handle(_conv("r21"), "საკვირაო სკოლაზე ინფორმაცია მინდა")
    assert "დეტალები ჯერ ზუსტდება" in out
    assert out != _PC


def test_22_canonical_price(engine_on):
    out = parent_flow.handle(_conv("r22"), "ბანაკის ფასი რა არის?")
    assert "2150" in out


def test_23_canonical_dates(engine_on):
    out = parent_flow.handle(_conv("r23"), "როდის არის ბანაკი?")
    assert "23–29 ივნისი" in out
    assert "მადლობა, რომ დაგვიკავშირდით" not in out
