# -*- coding: utf-8 -*-
"""Camp admin-status behaviour (2026-07-01).

The operator can turn the camp off from Admin Config (`summer_camp.status`).
Supported statuses: active / hidden / full / coming_soon / ended.

  * active       → camp works normally (regression-protected: byte-identical).
  * hidden/ended → camp is OFF; camp questions get „streams completed".
  * full         → camp not sold; „places are full".
  * coming_soon  → camp not sold yet; „details are being clarified".

Sunday School and adult events are gated by their OWN status and must keep
working under any camp status. Live/legacy mode: engine ON, planner + slim OFF.
The camp status is injected with an in-memory `load_sections` override — the real
`sections.yaml` is never edited.
"""
from __future__ import annotations

import dataclasses

import pytest

import app.config as config_module
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import admin_config_service, conversation_service, messenger_service

# ── Expected wording ─────────────────────────────────────────────────────────
_ENDED = "ბანაკის მიმდინარე ნაკადები უკვე დასრულებულია."
_FULL = "ბანაკის მიმდინარე ნაკადებზე ადგილები შევსებულია."
_COMING = "ბანაკის დეტალები ჯერ ზუსტდება."
# Approved wording (2026-07-02): camp-off offers ONLY Sunday School + manager
# connection; adult events are NOT mentioned by default.
_ALT = "ამ ეტაპზე თქვენი შვილისთვის შეგვიძლია შემოგთავაზოთ საკვირაო სკოლა. თუ გსურთ, დეტალებზე მენეჯერთან დაგაკავშირებთ."
_CHILD_OFF = "ამ ეტაპზე ბანაკის მიმდინარე ნაკადები აქტიური არ არის."
_SS_COMING = "საკვირაო სკოლის დეტალები ჯერ ზუსტდება. თუ გსურთ, მენეჯერთან დაგაკავშირებთ."
_ROOM_FB = "რაც შეეხება ოთახებში ბავშვების განაწილებას, ამ დეტალებს მენეჯერი გაგაცნობთ : 558 67 47 33"
_SEATS_FB = "რაც შეეხება კონკრეტულ ნაკადზე დარჩენილ ადგილებს, ამ დეტალებს მენეჯერი გაგაცნობთ : 558 67 47 33"
_REG_URL = "https://example.test/register"
_AGE_Q = "რამდენი წლის არის თქვენი შვილი"

# Any camp-off marker (used to assert non-camp flows are NOT intercepted).
_CAMP_OFF_MARKERS = (_ENDED, _FULL, _COMING, _CHILD_OFF)


def _mock_engine(conv, message):
    low = (message or "").lower()
    if "ფასი" in low or "ღირ" in low:
        return ("ბანაკის საფასურია 2150 ლარი. ღირებულებაში შედის ტრანსპორტი, განთავსება, კვება "
                "და სრული პროგრამა. თუ გსურთ, კონსულტაციაზე ჩაგწერთ, სადაც დეტალებს მენეჯერი გაგაცნობთ.")
    if "როდის" in low or "თარიღ" in low:
        return "[ENGINE-DATES] ბანაკი ტარდება 23–29 ივნისი."
    if "ინფორმაცი" in low or "მაინტერეს" in low:
        return ("სიტყვის აკადემიის ბანაკი 7-დღიანი გამოცდილებაა, სადაც ბავშვები ისვენებენ და, "
                "ამავდროულად, სწავლობენ საკუთარი აზრებისა და ემოციების გამოხატვას.\n\n"
                "რამდენი წლის არის თქვენი შვილი?")
    return "[ENGINE-REACHED]"


def _sections(camp_status: str, ss_status: str = "coming_soon"):
    return [
        {"id": "summer_camp", "status": camp_status,
         "name": "საზაფხულო ბანაკი", "price_text": "2150", "price_gel": 2150,
         "age_min": 9, "age_max": 17, "duration_days": 7,
         "registration_url": _REG_URL, "location": "ამბასადორი კაჭრეთი",
         "streams": [{"name": "I ნაკადი", "dates_text": "23–29 დეკემბერი", "status": "active"}]},
        {"id": "sunday_school", "status": ss_status,
         "availability_text": "საკვირაო სკოლა ივლისში დაემატება.",
         "details_text": "დეტალები ზუსტდება", "handoff_enabled": True, "lead_type": "sunday_school"},
        {"id": "adult_events", "status": "active",
         "events": [{"id": "ev1", "title": "პოეზიის საღამო", "status": "active",
                     "min_age": 13, "date_text": "2030 წლის დეკემბერი", "price_text": "50"}]},
    ]


@pytest.fixture(autouse=True)
def _reset():
    conversation_service.conversations.clear()
    parent_flow.invalid_phone_retries.clear()
    parent_flow._sunday_school_notified_senders.clear()
    yield
    conversation_service.conversations.clear()
    parent_flow._sunday_school_notified_senders.clear()


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    swapped = dataclasses.replace(
        config_module.settings, USE_PARENT_LLM_ENGINE=True,
        USE_CONVERSATION_PLANNER=False, CONVERSATION_PLANNER_AUTHORITATIVE=False,
        USE_SLIM_PROMPTS=False)
    monkeypatch.setattr(parent_flow, "settings", swapped)
    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    monkeypatch.setattr(parent_flow, "_CLIENT_EMOJI_ENABLED", True, raising=False)
    monkeypatch.setattr(parent_flow, "_run_llm_engine_safely", _mock_engine)
    yield


def _set_status(monkeypatch, camp_status, ss_status="coming_soon"):
    monkeypatch.setattr(
        admin_config_service, "load_sections",
        lambda: _sections(camp_status, ss_status))


def _conv(sid, child_age="12"):
    c = Conversation(sender_id=sid, platform="instagram", segment="PARENT")
    c.state = "ASK_CHALLENGE"
    c.history.append({"role": "assistant", "content": "რას ელოდებით ბანაკისგან?"})
    c.lead = Lead(sender_id=sid, platform="instagram", segment="PARENT", child_age=child_age)
    return c


def _ask(monkeypatch, camp_status, msg, child_age="12", ss_status="coming_soon"):
    _set_status(monkeypatch, camp_status, ss_status)
    return parent_flow.handle(_conv(f"{camp_status}-{abs(hash(msg)) % 99999}", child_age), msg)


def _no_camp_off(out):
    return all(m not in out for m in _CAMP_OFF_MARKERS)


# ── get_camp_status helper unit coverage (default-active safety) ─────────────
def test_get_camp_status_defaults(monkeypatch):
    for bad in [None, "", "  ", "bogus", "ACTIVE_X", 123]:
        monkeypatch.setattr(admin_config_service, "load_sections",
                            lambda b=bad: [{"id": "summer_camp", "status": b}])
        assert admin_config_service.get_camp_status() == "active", f"bad={bad!r}"
    monkeypatch.setattr(admin_config_service, "load_sections", lambda: [])
    assert admin_config_service.get_camp_status() == "active"      # missing section
    for st in ["active", "hidden", "full", "coming_soon", "ended", "ENDED", " Hidden "]:
        monkeypatch.setattr(admin_config_service, "load_sections",
                            lambda s=st: [{"id": "summer_camp", "status": s}])
        assert admin_config_service.get_camp_status() == st.strip().lower()
    assert "ended" in admin_config_service.VALID_STATUSES


# =====================================================================
# ACTIVE — regression: everything works exactly as before
# =====================================================================
def test_01_active_intro(monkeypatch):
    out = _ask(monkeypatch, "active", "ბანაკზე ინფორმაცია მინდა", child_age="")
    # Approved deterministic Camp intro (client hotfix 2026-07-03) replaces the
    # old LLM-paraphrased intro.
    assert "ციფრულ ხმაურს" in out
    assert "სწავლობენ საკუთარი აზრებისა და ემოციების გამოხატვას" not in out
    assert _AGE_Q in out
    assert _no_camp_off(out)


def test_02_active_price(monkeypatch):
    out = _ask(monkeypatch, "active", "ბანაკის ფასი რა არის?")
    assert "2150" in out
    assert _no_camp_off(out)


def test_03_active_room(monkeypatch):
    out = _ask(monkeypatch, "active", "ოთახში რამდენი ბავშვი იქნება?")
    assert _ROOM_FB in out
    assert _no_camp_off(out)


def test_04_active_registration(monkeypatch):
    out = _ask(monkeypatch, "active", "რეგისტრაცია მინდა ბანაკზე")
    assert _REG_URL in out and "რეგისტრაცია" in out
    assert _no_camp_off(out)


def test_05_active_sunday_school(monkeypatch):
    out = _ask(monkeypatch, "active", "საკვირაო სკოლაზე ინფორმაცია მინდა")
    assert _SS_COMING in out
    assert _no_camp_off(out)


def test_06_active_adult(monkeypatch):
    out = _ask(monkeypatch, "active", "ზრდასრულთა ღონისძიებები რა გაქვთ?")
    assert _no_camp_off(out)
    assert "2150" not in out


# =====================================================================
# HIDDEN — camp OFF
# =====================================================================
def test_07_hidden_intro(monkeypatch):
    out = _ask(monkeypatch, "hidden", "ბანაკზე ინფორმაცია მინდა", child_age="")
    assert _ENDED in out and _ALT in out
    assert _AGE_Q not in out
    assert "სწავლობენ საკუთარი აზრებისა" not in out


def test_08_hidden_price(monkeypatch):
    out = _ask(monkeypatch, "hidden", "ბანაკის ფასი რა არის?")
    assert _ENDED in out
    assert "2150" not in out


def test_09_hidden_registration(monkeypatch):
    out = _ask(monkeypatch, "hidden", "რეგისტრაცია მინდა ბანაკზე")
    assert _ENDED in out
    assert _REG_URL not in out
    assert "9-ნიშნა" not in out and "ნომერი მომწერეთ" not in out


def test_10_hidden_room(monkeypatch):
    out = _ask(monkeypatch, "hidden", "ოთახში რამდენი ბავშვი იქნება?")
    assert _ENDED in out
    assert _ROOM_FB not in out


def test_11_hidden_seats(monkeypatch):
    out = _ask(monkeypatch, "hidden", "მე-2 ნაკადზე ადგილები გაქვთ?")
    assert _ENDED in out
    assert _SEATS_FB not in out


# =====================================================================
# ENDED — camp OFF (completed)
# =====================================================================
def test_12_ended_intro(monkeypatch):
    out = _ask(monkeypatch, "ended", "ბანაკზე ინფორმაცია მინდა", child_age="")
    assert _ENDED in out
    assert _AGE_Q not in out


def test_13_ended_price(monkeypatch):
    out = _ask(monkeypatch, "ended", "ბანაკის ფასი რა არის?")
    assert _ENDED in out
    assert "2150" not in out


def test_14_ended_registration(monkeypatch):
    out = _ask(monkeypatch, "ended", "რეგისტრაცია მინდა ბანაკზე")
    assert _ENDED in out
    assert _REG_URL not in out


def test_15_ended_direct_question(monkeypatch):
    out = _ask(monkeypatch, "ended", "ბანაკი დასრულდა?")
    assert out.startswith("დიახ")
    assert _ENDED in out


# =====================================================================
# FULL — places full
# =====================================================================
def test_16_full_intro(monkeypatch):
    out = _ask(monkeypatch, "full", "ბანაკზე ინფორმაცია მინდა", child_age="")
    assert _FULL in out
    assert _AGE_Q not in out


def test_17_full_price(monkeypatch):
    out = _ask(monkeypatch, "full", "ბანაკის ფასი რა არის?")
    assert _FULL in out
    assert "2150" not in out


def test_18_full_seats(monkeypatch):
    out = _ask(monkeypatch, "full", "მე-2 ნაკადზე ადგილები გაქვთ?")
    assert _FULL in out
    assert _SEATS_FB not in out


def test_19_full_registration(monkeypatch):
    out = _ask(monkeypatch, "full", "რეგისტრაცია მინდა ბანაკზე")
    assert _FULL in out
    assert _REG_URL not in out


# =====================================================================
# COMING_SOON — not sold yet
# =====================================================================
def test_20_coming_intro(monkeypatch):
    out = _ask(monkeypatch, "coming_soon", "ბანაკზე ინფორმაცია მინდა", child_age="")
    assert _COMING in out
    assert _AGE_Q not in out


def test_21_coming_price(monkeypatch):
    out = _ask(monkeypatch, "coming_soon", "ბანაკის ფასი რა არის?")
    assert _COMING in out
    assert "2150" not in out


def test_22_coming_registration(monkeypatch):
    out = _ask(monkeypatch, "coming_soon", "რეგისტრაცია მინდა ბანაკზე")
    assert _COMING in out
    assert _REG_URL not in out


def test_23_coming_safety(monkeypatch):
    out = _ask(monkeypatch, "coming_soon", "ბანაკში უსაფრთხოება როგორ არის?")
    assert _COMING in out
    assert "ვიდეომონიტორინგი" not in out


# =====================================================================
# Non-camp flows under NON-ACTIVE camp status
# =====================================================================
@pytest.mark.parametrize("camp_status", ["hidden", "ended", "full", "coming_soon"])
def test_24_sunday_school_still_works(monkeypatch, camp_status):
    out = _ask(monkeypatch, camp_status, "საკვირაო სკოლაზე ინფორმაცია მინდა")
    assert _SS_COMING in out
    assert _no_camp_off(out)                       # not hijacked by the camp gate


@pytest.mark.parametrize("camp_status", ["hidden", "ended", "full", "coming_soon"])
def test_25_adult_still_works(monkeypatch, camp_status):
    out = _ask(monkeypatch, camp_status, "ზრდასრულთა ღონისძიებები რა გაქვთ?")
    assert _no_camp_off(out)                        # adult never blocked by camp-off
    assert "2150" not in out


def test_26_combined_camp_and_sunday_school(monkeypatch):
    out = _ask(monkeypatch, "ended", "ბანაკი და საკვირაო სკოლა მაინტერესებს")
    assert _ENDED in out                            # camp status line
    assert _SS_COMING in out                        # + Sunday School answer
    assert _AGE_Q not in out
    assert "2150" not in out


def test_27_combined_camp_and_adult(monkeypatch):
    out = _ask(monkeypatch, "ended", "ბანაკი და ზრდასრულთა ღონისძიება მაინტერესებს")
    assert _ENDED in out                            # camp status line
    assert "ზრდასრულთა ღონისძიებ" in out            # + adult pointer/route
    assert _AGE_Q not in out
    assert "2150" not in out


def test_28_child_offering_points_to_sunday_school(monkeypatch):
    out = _ask(monkeypatch, "ended", "ბავშვისთვის რა გაქვთ?")
    assert _CHILD_OFF in out
    assert _SS_COMING in out                        # SS coming_soon → its answer
    assert _AGE_Q not in out
    assert "2150" not in out
    assert _REG_URL not in out
    assert "ზრდასრულ" not in out                    # no adult events by default


# =====================================================================
# Approved wording (2026-07-02): exact camp-off text + no adult by default
# =====================================================================
_EXPECTED_BY_STATUS = {
    "hidden": parent_flow._CAMP_MSG_ENDED,
    "ended": parent_flow._CAMP_MSG_ENDED,
    "full": parent_flow._CAMP_MSG_FULL,
    "coming_soon": parent_flow._CAMP_MSG_COMING_SOON,
}


@pytest.mark.parametrize("camp_status", list(_EXPECTED_BY_STATUS))
def test_29_camp_off_exact_wording_no_adult(monkeypatch, camp_status):
    out = _ask(monkeypatch, camp_status, "ბანაკზე ინფორმაცია მინდა", child_age="")
    assert out == _EXPECTED_BY_STATUS[camp_status]
    assert "თქვენი შვილისთვის შეგვიძლია შემოგთავაზოთ საკვირაო სკოლა" in out
    assert "თუ გსურთ, დეტალებზე მენეჯერთან დაგაკავშირებთ" in out
    assert "ზრდასრულ" not in out                    # no adult events by default
    assert "რომელი მიმართულება გაინტერესებთ" not in out   # old routing trailer gone


def test_30_direct_completed_question_wording(monkeypatch):
    out = _ask(monkeypatch, "ended", "ბანაკი დასრულდა?")
    assert out == (
        "დიახ, ბანაკის მიმდინარე ნაკადები უკვე დასრულებულია.\n\n"
        "ამ ეტაპზე თქვენი შვილისთვის შეგვიძლია შემოგთავაზოთ საკვირაო სკოლა. "
        "თუ გსურთ, დეტალებზე მენეჯერთან დაგაკავშირებთ."
    )
    assert "ზრდასრულ" not in out


def test_31_adult_mentioned_only_on_explicit_request(monkeypatch):
    # Camp-only under camp-off → no adult mention…
    plain = _ask(monkeypatch, "ended", "ბანაკის ფასი რა არის?")
    assert "ზრდასრულ" not in plain
    # …but an explicit camp + adult question DOES route/mention adult.
    mixed = _ask(monkeypatch, "ended", "ბანაკი და ზრდასრულთა ღონისძიება მაინტერესებს")
    assert _ENDED in mixed
    assert "ზრდასრულთა ღონისძიებ" in mixed
