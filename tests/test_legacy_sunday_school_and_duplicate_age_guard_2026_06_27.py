"""Combined legacy hotfix (live bugs 2026-06-27):

Bug A — Sunday School intent must route to the Sunday-School coming_soon
        response, NOT camp; and coming_soon must NOT reveal details.
Bug B1 — an out-of-range child age („6 წლის…") must not be stored as a name
         and must get the eligibility + manager-consultation answer.
Bug B2 — repeated same-intent CAMP price questions return the approved full
         price block. Pure payment-process and exact reservation amount stay separate.

Legacy/giant-prompt path: engine ON, planner + slim OFF.
"""
from __future__ import annotations

import dataclasses

import pytest

import app.config as config_module
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import admin_config_service, conversation_service, messenger_service

_MANAGER_NUMBER = "558 67 47 33"
_CAMP_URL = "https://tinyurl.com/36jcae8z"
# A recognisable FULL price answer the mocked engine returns for the FIRST camp
# price question (includes the transport/discount/installment block + 2150).
_FULL_PRICE = (
    "[FULL] ბანაკის ღირებულებაა 2150 ლარი. ღირებულებაში შედის ტრანსპორტი, "
    "განთავსება, კვება და პროგრამა. 10%-იანი ფასდაკლება. გადახდა 6 თვემდე TBC."
)
_DATES_ANSWER = "[DATES] ბანაკი ტარდება 23–29 ივნისი, 5–11 ივლისი, 14–20 ივლისი."
_PAYMENT_ANSWER = "ბანაკის ჯავშნის საფასურის გადახდა ხდება წინასწარ, ხოლო სრული თანხის — ხელშეკრულებით გათვალისწინებულ დროში. გადახდის გადანაწილება შესაძლებელია 6 თვემდე TBC-ისა და საქართველოს ბანკის საშუალებით"


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
    # The engine answers the FIRST price question + dates/payment questions; route
    # the mocked engine reply by the inbound message so each test can assert it.
    def _engine(c, m):
        low = (m or "").lower()
        if "როდის" in low:
            return _DATES_ANSWER
        if "გადახდა" in low:
            return _PAYMENT_ANSWER
        return _FULL_PRICE
    monkeypatch.setattr(parent_flow, "_run_llm_engine_safely", _engine)
    return swapped


def _coming_soon(monkeypatch):
    monkeypatch.setattr(
        admin_config_service, "get_sunday_school_status",
        lambda: {"status": "coming_soon", "availability_text": "საკვირაო სკოლა ივლისში დაემატება.",
                 "details_text": "დეტალები ზუსტდება", "handoff_enabled": True,
                 "lead_type": "sunday_school"},
    )


def _ss_conv(sid="ss"):
    """A conversation after the menu (state START, a prior assistant turn)."""
    c = Conversation(sender_id=sid, platform="instagram", segment="PARENT")
    c.state = "START"
    c.history.append({"role": "assistant", "content": "გვითხარით, რა გაინტერესებთ: ბანაკი / ღონისძიებები"})
    c.lead = Lead(sender_id=sid, platform="instagram", segment="PARENT")
    return c


def _price_conv(sid="pr"):
    """A mid-flow conversation (eligible child) where price questions are asked."""
    c = Conversation(sender_id=sid, platform="instagram", segment="PARENT")
    c.state = "ASK_CHALLENGE"
    c.history.append({"role": "assistant", "content": "რას ელოდებით ბანაკისგან?"})
    c.lead = Lead(sender_id=sid, platform="instagram", segment="PARENT", child_age="10")
    return c


def _turn(conv, msg):
    # Mirror conversation_service: the inbound user message is appended to
    # history BEFORE the flow runs (so a repeat camp_price question is counted).
    conv.history.append({"role": "user", "content": msg})
    out = parent_flow.handle(conv, msg)
    conv.history.append({"role": "assistant", "content": out})
    return out


def _no_camp(text):
    low = (text or "")
    return ("ბანაკი 7-დღიან" not in low) and ("2150" not in low)


# =====================================================================
# Bug A — Sunday School routing + coming_soon response
# =====================================================================
def test_1_ss_detailed_info_coming_soon(engine_on, monkeypatch):
    _coming_soon(monkeypatch)
    out = parent_flow.handle(_ss_conv("a1"), "საკვირაო სკოლასთან დაკავშირებით მაინტერესებს დეტალური ინფორმაცია?")
    assert "დეტალები ჯერ ზუსტდება" in out          # coming_soon response
    assert "მენეჯერ" in out                          # offers manager
    assert "ბანაკი 7-დღიან" not in out               # no camp description
    assert "2150" not in out                          # no camp price
    assert "ივლის" not in out                         # no detail leak
    assert "აქტიური ღონისძიება" not in out           # no adult event fallback


def test_2_ss_details_interest(engine_on, monkeypatch):
    _coming_soon(monkeypatch)
    out = parent_flow.handle(_ss_conv("a2"), "საკვირაო სკოლის დეტალები მაინტერესებს")
    assert "დეტალები ჯერ ზუსტდება" in out
    assert _no_camp(out)


def test_3_ss_info_request(engine_on, monkeypatch):
    _coming_soon(monkeypatch)
    out = parent_flow.handle(_ss_conv("a3"), "საკვირაო სკოლაზე მინდა ინფორმაცია")
    assert "დეტალები ჯერ ზუსტდება" in out


def test_4_ss_enroll_intent_offers_manager_no_link(engine_on, monkeypatch):
    _coming_soon(monkeypatch)
    out = parent_flow.handle(_ss_conv("a4"), "საკვირაო სკოლაში ჩაწერა მინდა")
    assert "დეტალები ჯერ ზუსტდება" in out
    assert "მენეჯერ" in out                          # offers manager connection
    assert "http" not in out and _CAMP_URL not in out  # no registration link


def test_5_camp_still_works(engine_on, monkeypatch):
    _coming_soon(monkeypatch)
    # „ბანაკზე მაინტერესებს ინფორმაცია" must NOT route to Sunday School.
    assert parent_flow._is_sunday_school_intent("ბანაკზე მაინტერესებს ინფორმაცია") is False
    out = parent_flow.handle(_ss_conv("a5"), "ბანაკზე მაინტერესებს ინფორმაცია")
    assert "დეტალები ჯერ ზუსტდება" not in out         # not the SS coming_soon answer


def test_6_adult_events_still_work(engine_on, monkeypatch):
    _coming_soon(monkeypatch)
    q = "ზრდასრულთა ღონისძიებები რა გაქვთ?"
    assert parent_flow._is_sunday_school_intent(q) is False
    out = parent_flow.handle(_ss_conv("a6"), q)
    assert "დეტალები ჯერ ზუსტდება" not in out         # not Sunday School


def test_7_coming_soon_wording_guard(engine_on, monkeypatch):
    _coming_soon(monkeypatch)
    out = parent_flow.handle(_ss_conv("a7"), "საკვირაო სკოლა მაინტერესებს")
    for banned in ("დაგიტოვებთ ინტერესს", "ინტერესი დაფიქსირდა", "lead", "ლიდი"):
        assert banned not in out


# =====================================================================
# Bug B1 — out-of-range child age must not become a name
# =====================================================================
def _contact_ctx_conv(sid="b1"):
    c = Conversation(sender_id=sid, platform="instagram", segment="PARENT")
    c.state = "OFFER_BOOKING"
    c.history.append({"role": "assistant", "content": "მომწერეთ თქვენი სახელი და 9-ნიშნა საკონტაქტო ნომერი."})
    c.lead = Lead(sender_id=sid, platform="instagram", segment="PARENT")
    return c


def test_8_out_of_range_age_with_description(engine_on):
    conv = _contact_ctx_conv("b8")
    out = parent_flow.handle(conv, "6 წლის არის მაგრამ 10 წლის ბავშვივით აზროვნებს")
    assert conv.lead.child_age == "6"                 # age recognised
    assert (conv.lead.name or "") == ""               # NOT stored as a name
    assert "სახელი მივიღე" not in out
    assert ("9–17" in out) or ("9-17" in out)         # mentions camp range
    assert "მენეჯერ" in out                           # offers manager consultation


def test_9_out_of_range_age_simple(engine_on):
    conv = _contact_ctx_conv("b9")
    out = parent_flow.handle(conv, "6 წლისაა")
    assert "სახელი მივიღე" not in out
    assert ("9–17" in out) or ("9-17" in out)


def test_10_eligible_age_still_works(engine_on):
    conv = _contact_ctx_conv("b10")
    out = parent_flow.handle(conv, "10 წლისაა")
    assert conv.lead.child_age == "10"
    # No out-of-range block — eligible age flows to the engine / normal handling.
    assert ("9–17" not in out) and ("9-17" not in out)
    assert "ბანაკი განკუთვნილია" not in out


# =====================================================================
# Bug B2 — duplicate camp price → short repeat
# =====================================================================
def test_11_repeat_price_full_block(engine_on):
    conv = _price_conv("b11")
    out1 = _turn(conv, "ღირებულება რომ მომწეროთ")
    assert "2150" in out1 and "ტრანსპორტი" in out1     # full first answer
    out2 = _turn(conv, "რა ღირს?")
    # Full-price-block change (2026-07-08): a REPEAT price question returns the
    # FULL block again (price + installments + discount) — NOT a „როგორც ზემოთ
    # მოგწერეთ" short back-reference.
    assert "2150" in out2 and "ტრანსპორტი" in out2
    assert "გადანაწილება" in out2 and "TBC" in out2 and "10%" in out2
    assert "როგორც ზემოთ" not in out2


def test_12_same_intent_variants_full_block_on_repeat(engine_on):
    conv = _price_conv("b12")
    out1 = _turn(conv, "ფასი რა არის?")
    assert "ტრანსპორტი" in out1                         # full first
    out2 = _turn(conv, "ღირებულება რამდენია?")
    # Repeat → full block (installments + discount), not a short duplicate.
    assert "ტრანსპორტი" in out2 and "2150" in out2
    assert "გადანაწილება" in out2 and "10%" in out2
    assert "როგორც ზემოთ" not in out2


def test_13_dates_after_price_now_limited_by_final_camp_policy(engine_on):
    conv = _price_conv("b13")
    _turn(conv, "რა ღირს?")
    out = _turn(conv, "როდის არის ბანაკი?")
    assert out == parent_flow._camp_registration_closed_answer()
    assert _DATES_ANSWER not in out
    assert "როგორც ზემოთ" not in out


def test_14_payment_after_price_process_not_suppressed(engine_on):
    conv = _price_conv("b14")
    _turn(conv, "რა ღირს?")
    out = _turn(conv, "გადახდა როგორ ხდება?")
    assert out == _PAYMENT_ANSWER
    assert "2150" not in out
    assert "როგორც ზემოთ" not in out

def test_15_sunday_school_price_not_camp_price():
    assert parent_flow._is_camp_price_intent("საკვირაო სკოლის ფასი რა არის?") is False


def test_16_adult_event_price_not_camp_price():
    assert parent_flow._is_camp_price_intent("ღონისძიების ფასი რა არის?") is False
    assert parent_flow._is_camp_price_intent("ზრდასრულთა საღამოს ბილეთის ფასი?") is False


# =====================================================================
# Cross-fix regressions — manager phone, camp registration, daypart
# =====================================================================
def test_manager_phone_priority_preserved(engine_on):
    conv = _price_conv("rg1")
    out = parent_flow.handle(conv, "კონსულტაცია არ მინდა, მენეჯერის ნომერი მომწერეთ")
    assert _MANAGER_NUMBER in out


def test_camp_registration_preserved(engine_on):
    conv = _price_conv("rg2")
    out = parent_flow.handle(conv, "ბანაკის რეგისტრაციის ლინკი მომწერე")
    assert out == parent_flow._render_camp_registration_answer()


def test_price_intent_unit_matrix():
    yes = ["ღირებულება რომ მომწეროთ", "რა ღირს?", "ფასი რა არის?", "ბანაკის ფასი?",
           "რამდენია გადასახადი?"]
    no = ["გადახდა როგორ ხდება?", "როდის არის ბანაკი?", "საკვირაო სკოლის ფასი?",
          "ღონისძიების ფასი?"]
    for m in yes:
        assert parent_flow._is_camp_price_intent(m) is True, m
    for m in no:
        assert parent_flow._is_camp_price_intent(m) is False, m
