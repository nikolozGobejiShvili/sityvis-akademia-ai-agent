"""Live bug (2026-07-07): stream/age/price first-turn routing + false „as above".

BUG 1 — a first message that names a camp STREAM/cohort („3 ნაკადი" / „მესამე
        ნაკადი") together with an age-limit and/or price ask — even WITHOUT the
        word „ბანაკი" and with the typo „ასოკობრივი" — must be answered directly
        (stream date + age band + price), never the generic camp-vs-adult menu.
BUG 2 — deprecated „როგორც ზემოთ მოგწერეთ" wording must not appear in camp
        price behavior; price follow-ups get a direct/full price block with no
        false back-reference.

Legacy/giant-prompt path: engine ON, planner + slim OFF. The camp facts + status
are mocked so the assertions are deterministic (independent of the operator's
sections.yaml).
"""
from __future__ import annotations

import dataclasses

import pytest

import app.config as config_module
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import admin_config_service, messenger_service

_MENU = "გვითხარით, რა გაინტერესებთ"
_MENU_TEXT = (
    "გვითხარით, რა გაინტერესებთ:\n\n— ბავშვების საზაფხულო ბანაკი\n"
    "— ზრდასრულთა კულტურული საღამოები"
)

_CAMP_FACTS = {
    "year": 2026,
    "age_min": 9,
    "age_max": 17,
    "price_gel": 2150,
    "duration_days": 7,
    "streams": [
        {"name": "I ნაკადი", "dates_text": "23-29 ივნისი"},
        {"name": "II ნაკადი", "dates_text": "5-11 ივლისი"},
        {"name": "III ნაკადი", "dates_text": "14-20 ივლისი"},
    ],
}


@pytest.fixture(autouse=True)
def _camp(monkeypatch):
    """Deterministic camp facts + active status for every test."""
    monkeypatch.setattr(admin_config_service, "get_camp_facts", lambda: dict(_CAMP_FACTS))
    monkeypatch.setattr(admin_config_service, "get_camp_status", lambda: "active")
    return monkeypatch


@pytest.fixture
def engine(monkeypatch):
    """Engine ON with a distinctive sentinel so a leaked engine path is visible."""
    swapped = dataclasses.replace(
        config_module.settings, USE_PARENT_LLM_ENGINE=True,
        USE_CONVERSATION_PLANNER=False, CONVERSATION_PLANNER_AUTHORITATIVE=False,
        USE_SLIM_PROMPTS=False,
    )
    monkeypatch.setattr(parent_flow, "settings", swapped)
    monkeypatch.setattr(messenger_service, "get_user_profile", lambda s, p: {})
    monkeypatch.setattr(parent_flow, "_run_llm_engine_safely", lambda c, m: "SENTINEL_ENGINE")
    return monkeypatch


def _conv(sid="x", *, state="START", history=None, child_age="") -> Conversation:
    c = Conversation(sender_id=sid, platform="instagram", segment="PARENT")
    c.state = state
    c.lead = Lead(sender_id=sid, platform="instagram", segment="PARENT",
                  child_age=child_age)
    for t in history or []:
        c.history.append(t)
    return c


def _turn(conv, msg):
    conv.history.append({"role": "user", "content": msg})
    out = parent_flow.handle(conv, msg)
    conv.history.append({"role": "assistant", "content": out})
    return out


# ══ BUG 1 — stream number extraction (unit) ══════════════════════════════════
@pytest.mark.parametrize("msg,expected", [
    ("3 ნაკადი რა ღირს?", 3),
    ("3 ნაკადის ასაკი", 3),
    ("მე-3 ნაკადი", 3),
    ("მე-2 ნაკადზე", 2),
    ("მესამე ნაკადის ღირებულება", 3),
    ("მეორე ნაკადი", 2),
    ("პირველი ნაკადი", 1),
    ("III ნაკადი", 3),
    ("ბანაკი მაინტერესებს", None),      # no stream number
])
def test_extract_stream_number(msg, expected):
    assert parent_flow._extract_camp_stream_number(msg.lower()) == expected


def test_stream_dates_text_from_canonical_facts():
    assert parent_flow._camp_stream_dates_text(3) == "14-20 ივლისი"
    assert parent_flow._camp_stream_dates_text(1) == "23-29 ივნისი"
    assert parent_flow._camp_stream_dates_text(9) is None   # out of range


def test_typo_normalisation():
    assert "ასაკობრივი" in parent_flow._normalise_camp_typos("ასოკობრივი ზღვარი")


# ══ BUG 1 — menu-skip detector recognises streams ════════════════════════════
@pytest.mark.parametrize("msg", [
    "მაინტერესებს 3 ნაკადის ასოკობრივი ზღვარი და ფასი",
    "მესამე ნაკადის ასაკობრივი ზღვარი და ღირებულება მაინტერესებს",
    "3 ნაკადი რა ღირს?",
    "3 ნაკადის ასაკი მაინტერესებს",
])
def test_stream_message_is_explicit_camp_intent(msg):
    assert parent_flow._has_explicit_georgian_camp_intent(msg) is True


@pytest.mark.parametrize("msg", ["გამარჯობა", "ინფორმაცია მაინტერესებს", "დეტალები მაინტერესებს"])
def test_ambiguous_first_message_not_camp_intent(msg):
    assert parent_flow._has_explicit_georgian_camp_intent(msg) is False


# ══ BUG 1 — the four required first-turn scenarios (E2E) ══════════════════════
def test_case1_stream_age_price_direct(engine):
    out = parent_flow.handle(_conv("c1"), "მაინტერესებს 3 ნაკადის ასოკობრივი ზღვარი და ფასი")
    assert _MENU not in out
    assert "SENTINEL_ENGINE" not in out
    assert "2150" in out
    assert "ტრანსპორტ" in out
    assert "მე-3 ნაკადი" not in out
    assert "14-20 ივლისი" not in out
    assert "9–17" not in out


def test_case2_ordinal_stream_age_price_direct(engine):
    out = parent_flow.handle(_conv("c2"), "მესამე ნაკადის ასაკობრივი ზღვარი და ღირებულება მაინტერესებს")
    assert _MENU not in out
    assert "2150" in out and "ტრანსპორტ" in out
    assert "მე-3 ნაკადი" not in out and "14-20 ივლისი" not in out
    assert "9–17" not in out


def test_case3_stream_price_direct(engine):
    out = parent_flow.handle(_conv("c3"), "3 ნაკადი რა ღირს?")
    assert _MENU not in out
    assert "SENTINEL_ENGINE" not in out
    assert "2150" in out and "ტრანსპორტ" in out
    assert "მე-3 ნაკადი" not in out and "14-20 ივლისი" not in out
    assert "რეგისტრაციის ბმული" not in out


def test_case4_stream_age_only_direct(engine):
    out = parent_flow.handle(_conv("c4"), "3 ნაკადის ასაკი მაინტერესებს")
    assert _MENU not in out
    assert out == parent_flow._camp_registration_closed_answer()
    assert "მე-3 ნაკადი" not in out and "14-20 ივლისი" not in out
    assert "9–17" not in out
    assert "2150" not in out            # price was NOT asked -> not volunteered


# ══ BUG 1 — case 5: a bare greeting still shows the menu ══════════════════════
def test_case5_bare_greeting_still_menu(engine):
    out = parent_flow.handle(_conv("c5"), "გამარჯობა")
    assert _MENU in out
    assert "SENTINEL_ENGINE" not in out


# ══ BUG 1 — the handler defers on seats / bare-dates stream questions ═════════
def test_stream_seats_question_defers_to_operational():
    # A seats question (even with a stream number) is NOT the stream direct answer.
    assert parent_flow._maybe_handle_camp_stream_query(_conv(), "მე-2 ნაკადზე ადგილები გაქვთ?") is None


def test_bare_stream_dates_question_defers():
    # No age/price ask → defer (engine/dates handler answers).
    assert parent_flow._maybe_handle_camp_stream_query(_conv(), "მე-2 ნაკადი როდის არის?") is None


def test_adult_segment_defers():
    c = Conversation(sender_id="a", platform="instagram", segment="ADULT")
    c.lead = Lead(sender_id="a", platform="instagram", segment="ADULT")
    assert parent_flow._maybe_handle_camp_stream_query(c, "3 ნაკადის ფასი?") is None


# ══ BUG 2 — false „as above" ═════════════════════════════════════════════════
def test_direct_price_handler_has_no_false_as_above():
    out = parent_flow._camp_price_direct_answer()
    for bad in ("როგორც ზემოთ მოგწერეთ", "როგორც უკვე გითხარით", "ზემოთ მოგწერეთ"):
        assert bad not in out
    assert "2150" in out and "ტრანსპორტირება" in out


def test_assistant_gave_camp_price_detection():
    gave = _conv(history=[
        {"role": "user", "content": "რა ღირს?"},
        {"role": "assistant", "content": "ბანაკის ღირებულებაა 2150 ლარი."},
    ])
    not_gave = _conv(history=[
        {"role": "user", "content": "ფასი მაინტერესებს"},
        {"role": "assistant", "content": _MENU_TEXT},
    ])
    assert parent_flow._assistant_gave_camp_price(gave) is True
    assert parent_flow._assistant_gave_camp_price(not_gave) is False


def test_case6_price_followup_no_prior_price_direct(engine):
    conv = _conv("f6", state="ASK_CHALLENGE", child_age="10", history=[
        {"role": "user", "content": "ფასი მაინტერესებს"},
        {"role": "assistant", "content": _MENU_TEXT},
    ])
    out = _turn(conv, "ღირებულებაც რო მომწეროთ")
    assert "2150" in out
    assert "როგორც ზემოთ მოგწერეთ" not in out
    assert "ზემოთ მოგწერეთ" not in out
    assert "ტრანსპორტირება" in out


def test_case7_price_followup_variant_no_false_ref(engine):
    conv = _conv("f7", state="ASK_CHALLENGE", child_age="10", history=[
        {"role": "user", "content": "ბანაკის ფასი?"},
        {"role": "assistant", "content": _MENU_TEXT},
    ])
    out = _turn(conv, "ფასიც მომწერეთ")
    assert "2150" in out
    assert "როგორც ზემოთ მოგწერეთ" not in out
    assert "ზემოთ მოგწერეთ" not in out


def test_repeat_price_full_block_when_price_actually_given(engine):
    # Regression: a TRUE repeat (assistant DID give the price) now repeats the
    # full approved block, never a deprecated „as above" shortcut.
    conv = _conv("f_short", state="ASK_CHALLENGE", child_age="10", history=[
        {"role": "user", "content": "რა ღირს?"},
        {"role": "assistant", "content": "ბანაკის ღირებულებაა 2150 ლარი. ღირებულებაში შედის ტრანსპორტი."},
    ])
    out = _turn(conv, "ფასი კიდევ ერთხელ მითხარით")
    for expected in ("2150", "ტრანსპორტ", "გადანაწილება", "TBC", "საქართველოს ბანკ", "10%"):
        assert expected in out, expected
    for bad in ("როგორც ზემოთ", "როგორც უკვე გითხარით", "ზემოთ მოგწერეთ"):
        assert bad not in out
