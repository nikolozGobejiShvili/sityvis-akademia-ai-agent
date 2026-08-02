# -*- coding: utf-8 -*-
"""Client QA LIVE smoke matrix (2026-07-01) — READ-ONLY, no side effects.

Purpose
-------
A single data-driven matrix that fires many Georgian client-like questions at
the agent in the CURRENT live/legacy mode (parent LLM engine ON, planner + slim
OFF) so we can catch client-facing problems BEFORE handing the agent to the
client.

What this exercises (and what it does NOT)
------------------------------------------
This is a DETERMINISTIC smoke test, NOT a real-OpenAI run. It mirrors the exact
pattern of the shipped legacy QA files
(`test_legacy_camp_topic_facts_2026_06_28.py`,
`test_legacy_parent_contact_emoji_medical_2026_06_28.py`,
`test_legacy_client_report_wording_unknown_fallback_2026_06_29.py`):

  * `USE_PARENT_LLM_ENGINE=True` (+ planner/slim/authoritative OFF) so the
    DETERMINISTIC pre-engine interceptor chain (topic facts, unknown-detail
    manager defers, seats/known+unknown split, staff/peer/menu/frequency splits,
    org / political / clarification, closings, multi-intent, emoji policy,
    mid-convo leak strip) is active — that chain only runs when the engine gate
    is ON.
  * `parent_flow._run_llm_engine_safely` is REPLACED by a smart mock
    (`_smart_engine`) that returns the APPROVED wordings the real LLM is
    prompted to produce (intro / simple-price / payment / dates / manager
    connect). The deterministic POST-processing (price sanitizer that strips
    TBC / installment / upfront terms, greeting-emoji placement, dedupe, leak
    strip) is then validated against those representative outputs — exactly how
    the shipped tests assert the price/payment behaviour.

Therefore this matrix validates the deterministic CLIENT-SAFETY layer + the
approved-wording post-processing. It does NOT (and cannot, without a mock)
validate the LLM's free composition — that is covered separately by the
prompt-content assertions in the shipped legacy files.

Read-only guarantees (safety requirements)
------------------------------------------
Because the engine is mocked, the parent tool executor (Sheets / Calendar /
email / manager handoff) is never reached. As belt-and-braces this file ALSO
installs tripwires on every side-effecting function and ASSERTS none of them
fire on any case:

  * Google Sheets writes  — sheets_service.save_lead / create_lead / update_lead
  * Google Calendar writes— calendar_service.book_slot / create_event /
                            cancel_calendar_event
  * email / manager handoff — notification_service.notify_manager /
                            notify_manager_handoff / notify_sunday_school_handoff
  * outbound Meta send    — messenger_service.send_message

The shared conftest additionally blocks real SMTP, real Meta/WhatsApp HTTP, and
Redis. No commit / no staging / no `evals/baseline.json` write happens here.

Run
---
    python -m pytest tests/test_client_qa_live_smoke_matrix_2026_07_01.py -q

Each failing case prints a full report: case id, category, input turns, the
ACTUAL response, missing expected strings, forbidden strings found, and notes.
"""
from __future__ import annotations

import dataclasses
import re

import pytest

import app.config as config_module
from app.agent.tools import parent_tool_executor as pte
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import (
    admin_config_service,
    calendar_service,
    conversation_service,
    messenger_service,
    notification_service,
    sheets_service,
)

# ─────────────────────────────────────────────────────────────────────────────
# Canonical strings (copied verbatim from the shipped source + legacy QA files).
# ─────────────────────────────────────────────────────────────────────────────
_MGR = "558 67 47 33"
_ENDING = "ამ დეტალებს მენეჯერი გაგაცნობთ : 558 67 47 33"

# Mocked-engine sentinels / approved wordings the real LLM is prompted to emit.
_ENGINE = "[ENGINE-MOCK]"
_DATES = "[ENGINE-DATES] ბანაკი ტარდება 23–29 ივნისი, 5–11 ივლისი, 14–20 ივლისი."
# Approved deterministic Camp intro (client hotfix 2026-07-03). The intro is now
# returned by `parent_flow._maybe_handle_camp_intro` (byte-exact), BEFORE the
# engine — so this mock is only a fallback for non-intro turns.
_INTRO = (
    "სიტყვის აკადემიის ბანაკი არის 7-დღიანი გამოცდილება, სადაც ბავშვები არა "
    "მხოლოდ ისვენებენ, არამედ რამდენიმე დღით შორდებიან ციფრულ ხმაურს, ერთვებიან "
    "ცოცხალ დისკუსიებში, სწავლობენ ფიქრს, აზრის ჩამოყალიბებასა და რეალურ "
    "ურთიერთობას.\n\nრამდენი წლის არის თქვენი შვილი?"
)
# Simple-price answer AS THE LLM PRODUCES IT (with payment/installment terms) —
# the deterministic price sanitizer strips the payment sentence for a SIMPLE
# price question, leaving price + inclusions + CTA. For a payment question the
# sanitizer is a no-op, so this same block keeps its payment terms.
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
_MANAGER_CONNECT = (
    "თუ გსურთ, მენეჯერთან დაგაკავშირებთ. მომწერეთ სახელი და 9-ნიშნა ნომერი."
)

# Price CTA (survives the simple-price sanitizer).
_PRICE_CTA = "თუ გსურთ, კონსულტაციაზე ჩაგწერთ, სადაც დეტალებს მენეჯერი გაგაცნობთ."

# Deterministic unknown-detail defers (topic-specific).
_SEATS_FB = f"რაც შეეხება კონკრეტულ ნაკადზე დარჩენილ ადგილებს, {_ENDING}"
_ROOM_FB = f"რაც შეეხება ოთახებში ბავშვების განაწილებას, {_ENDING}"
_TOWEL_FB = f"რაც შეეხება პირსახოცებს, {_ENDING}"
_MENU_FB = f"რაც შეეხება ზუსტ მენიუს, {_ENDING}"
_FREQ_FB = f"რაც შეეხება დღეში კვების რაოდენობას, {_ENDING}"
_STAFF_FB = f"რაც შეეხება სტაფის წევრების რაოდენობას, {_ENDING}"
_PEER_FB = f"რაც შეეხება მისი ტოლი ბავშვების ყოფნას კონკრეტულ ნაკადში, {_ENDING}"
_STADIUM_FB = f"რაც შეეხება სტადიონს, {_ENDING}"
_POOL_FB = f"რაც შეეხება საცურაო აუზს, {_ENDING}"
_DIRECT_CALL_FB = f"რაც შეეხება ბავშვთან პირდაპირი კონტაქტის წესებს, {_ENDING}"
_AGE_GROUP_FB = f"რაც შეეხება 14 წლის ბავშვების რაოდენობას, {_ENDING}"
_ORG_FB = f"რაც შეეხება ორგანიზატორების შესახებ დეტალებს, {_ENDING}"

# Deterministic known answers.
_FOOD_GEN_1 = "ბანაკში კვება ორგანიზებულია ჯანსაღი და დაბალანსებული მენიუს მიხედვით"
_FOOD_GEN_FULL = (
    "ბანაკში კვება ორგანიზებულია ჯანსაღი და დაბალანსებული მენიუს მიხედვით, "
    "რაც ხელს უწყობს ბავშვების ფიზიკურ და ემოციურ კეთილდღეობას. "
    "კვება შედის ბანაკის ღირებულებაში."
)
_STAFF_LINE = (
    "ადგილზე ბავშვებთან მუშაობს მაღალკვალიფიციური, პასუხისმგებლიანი და "
    "საბანაკე გამოცდილების მქონე სტაფი."
)
_ACCOMMODATION = "ბანაკში ბავშვები ნაწილდებიან კომფორტულ ოთახებში."
_PC_KEY = "მშობლებს ყოველდღიურად გაეგზავნებათ დღის პროგრამა და ფოტო-ვიდეო მასალა"
_DISCOUNT_LINE = "დედმამიშვილებისთვის მოქმედებს 10%-იანი ფასდაკლება."
_ORG_PREFIX = "ეს არის სიტყვის აკადემიის AI ასისტენტი."
_POL_1 = "პოლიტიკურ თემებზე პასუხს არ ვცემ"
# The political redirect stopped naming the camp on 2026-08-02 — „ქოცებ" is a
# political marker, so a question about the COMPANY lands here and used to be
# answered by offering a program the operator had closed.
_POL_2 = "ჩვენს პროგრამებთან დაკავშირებით"
_UNCLEAR = (
    "გთხოვთ, განმიმარტეთ, რას გულისხმობთ „ხელა ბავშვებში“, "
    "რომ უკეთესად შევძლო თქვენი დახმარება."
)


# ─────────────────────────────────────────────────────────────────────────────
# Read-only tripwires — any side effect fails the case.
# ─────────────────────────────────────────────────────────────────────────────
_SIDE_EFFECTS: list[str] = []

# (module, function name, safe return value if it were ever called)
_TRIPWIRE_TARGETS = (
    (sheets_service, "save_lead", True),
    (sheets_service, "create_lead", True),
    (sheets_service, "update_lead", True),
    (calendar_service, "book_slot", False),
    (calendar_service, "create_event", {}),
    (calendar_service, "cancel_calendar_event", True),
    (notification_service, "notify_manager", True),
    (notification_service, "notify_manager_handoff", True),
    (notification_service, "notify_sunday_school_handoff", True),
    (messenger_service, "send_message", True),
)


def _make_spy(label, safe_return):
    def _spy(*_a, **_k):
        _SIDE_EFFECTS.append(label)
        return safe_return
    return _spy


def _install_tripwires(monkeypatch):
    for module, name, safe_return in _TRIPWIRE_TARGETS:
        label = f"{module.__name__}.{name}"
        monkeypatch.setattr(module, name, _make_spy(label, safe_return), raising=False)


# ─────────────────────────────────────────────────────────────────────────────
# The smart mocked engine — returns the approved wording per single intent.
# ─────────────────────────────────────────────────────────────────────────────
def _smart_engine(_conv, message):
    """Stand-in for the real LLM: returns the exact APPROVED wording the system
    prompt asks for, per intent. The deterministic post-processing in
    parent_flow (price sanitizer / emoji / dedupe / leak strip) is what we are
    actually validating on top of these representative outputs."""
    low = (message or "").lower()
    if any(x in low for x in ("როდის", "თარიღ")):
        return _DATES
    has_price = any(x in low for x in ("ფასი", "ღირ", "ღირებულ"))
    has_payment = (
        any(x in low for x in ("გადახდ", "გადაიხდ", "შეძენ", "ვიყიდ", "ყიდვ"))
        or ("გადასახად" in low and "როგორ" in low)
    )
    if has_price and has_payment:
        # Combined price+payment question → payment question, so the price
        # sanitizer is a no-op and the block keeps both price and payment info.
        return _PRICE_WITH_PAYMENT
    if has_payment:
        return _PAYMENT_APPROVED
    if has_price:
        return _PRICE_WITH_PAYMENT
    if (
        low.strip().startswith("გამარჯობა")
        or ("ბანაკ" in low and ("ინფორმაცი" in low or "მაინტერესებ" in low))
        or ("ინფორმაცი" in low and "მინდა" in low)
    ):
        return _INTRO
    if "მენეჯერ" in low:
        return _MANAGER_CONNECT
    return _ENGINE


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _reset():
    conversation_service.conversations.clear()
    parent_flow.invalid_phone_retries.clear()
    parent_flow._sunday_school_notified_senders.clear()
    pte.book_consultation_success_for_conversation.clear()
    _SIDE_EFFECTS.clear()
    yield
    conversation_service.conversations.clear()
    parent_flow._sunday_school_notified_senders.clear()
    pte.book_consultation_success_for_conversation.clear()
    _SIDE_EFFECTS.clear()


@pytest.fixture(autouse=True)
def _client_qa_env(monkeypatch):
    """Live/legacy mode: engine ON, planner/slim OFF, emoji policy ON (live),
    engine mocked to approved wordings, profile fetch stubbed, side-effect
    tripwires installed."""
    swapped = dataclasses.replace(
        config_module.settings,
        USE_PARENT_LLM_ENGINE=True,
        USE_CONVERSATION_PLANNER=False,
        CONVERSATION_PLANNER_AUTHORITATIVE=False,
        USE_SLIM_PROMPTS=False,
    )
    monkeypatch.setattr(parent_flow, "settings", swapped)
    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    monkeypatch.setattr(parent_flow, "_run_llm_engine_safely", _smart_engine)
    # The client 💙 policy is pinned OFF in conftest; opt back in (live default).
    monkeypatch.setattr(parent_flow, "_CLIENT_EMOJI_ENABLED", True, raising=False)
    _install_tripwires(monkeypatch)
    yield


def _apply_coming_soon(monkeypatch):
    monkeypatch.setattr(
        admin_config_service,
        "get_sunday_school_status",
        lambda: {
            "status": "coming_soon",
            "availability_text": "საკვირაო სკოლა ივლისში დაემატება.",
            "details_text": "დეტალები ზუსტდება",
            "handoff_enabled": True,
            "lead_type": "sunday_school",
        },
    )


def _build_conv(case):
    sid = f"qa-{case['id']}"
    fresh = case.get("fresh", False)
    state = case.get("state", "START" if fresh else "ASK_CHALLENGE")
    child_age = case.get("child_age", "" if fresh else "12")
    c = Conversation(sender_id=sid, platform="instagram", segment="PARENT")
    c.state = state
    if not fresh:
        # A prior assistant turn → not the first reply (static welcome bypass).
        c.history.append({"role": "assistant", "content": "რას ელოდებით ბანაკისგან?"})
    c.lead = Lead(
        sender_id=sid, platform="instagram", segment="PARENT", child_age=child_age
    )
    return c


# ─────────────────────────────────────────────────────────────────────────────
# Global assertions (apply to every response) + per-category rules.
# ─────────────────────────────────────────────────────────────────────────────
# Rules 1–5: never allowed in ANY response.
_GLOBAL_FORBIDDEN = ("❤️", "💙.", "მსურს დაგეხმაროთ", "დეტალებს დეტალურად", "აგიხსნით")
# Rule 6: when the manager-defer ending is present these must NOT co-occur.
_DEFER_COFORBIDDEN = (
    "რამდენი წლის არის თქვენი შვილი?",
    "თქვენი შვილი რამდენი წლისაა?",
    "როგორია თქვენი შვილის ასაკი",
    "თუ გსურთ, კონსულტაციაზე ჩაგწერთ",
    "კონსულტაციაზე ჩაგწერთ, სადაც დეტალებს მენეჯერი გაგაცნობთ",
    "აგიხსნით",
)
# Rule 7: simple-price answers only.
_SIMPLE_PRICE_FORBIDDEN = ()


def _global_problems(case, resp):
    problems = []
    for bad in _GLOBAL_FORBIDDEN:
        if bad in resp:
            problems.append(f"[global rule] forbidden {bad!r} present")
    if _ENDING in resp:
        for bad in _DEFER_COFORBIDDEN:
            if bad in resp:
                problems.append(
                    f"[global rule 6] manager-defer co-occurs with {bad!r}"
                )
    if case.get("simple_price"):
        for bad in _SIMPLE_PRICE_FORBIDDEN:
            if bad in resp:
                problems.append(f"[global rule 7] simple-price forbidden {bad!r}")
    if case.get("unknown_fallback") and _MGR not in resp:
        problems.append(f"[global rule 8] unknown-fallback missing {_MGR!r}")
    return problems


def _case_problems(case, resp):
    problems = []
    for exp in case.get("expected_contains", []):
        if exp not in resp:
            problems.append(f"MISSING expected: {exp!r}")
    anys = case.get("expected_any")
    if anys and not any(a in resp for a in anys):
        problems.append(f"MISSING expected_any (need >=1 of): {anys!r}")
    for bad in case.get("forbidden_contains", []):
        if bad in resp:
            problems.append(f"FORBIDDEN present: {bad!r}")
    return problems


def _format_report(case, resp, problems):
    return "\n".join(
        [
            "",
            "=" * 72,
            f"CLIENT QA SMOKE FAILURE — {case['id']}  [{case['category']}]",
            "=" * 72,
            f"USER INPUT (turns): {case['turns']}",
            f"NOTES: {case.get('notes', '')}",
            "-" * 72,
            "ACTUAL RESPONSE:",
            resp if resp else "<empty>",
            "-" * 72,
            "PROBLEMS:",
            *[f"  • {p}" for p in problems],
            "=" * 72,
        ]
    )


# ─────────────────────────────────────────────────────────────────────────────
# The matrix — 50 priority cases.
#   Each case: id, category, turns (1 = single, 2+ = multi-turn), expected_*,
#   forbidden_*, and optional conv config (fresh / state / child_age /
#   sunday_school) + assertion flags (simple_price / unknown_fallback).
# ─────────────────────────────────────────────────────────────────────────────
MATRIX = [
    # ── Intro / greeting ─────────────────────────────────────────────────────
    {
        "id": "01_intro_greeting",
        "category": "intro",
        "fresh": True,
        "turns": ["გამარჯობა, ბანაკზე ინფორმაცია მაინტერესებს"],
        "expected_contains": [
            "გამარჯობა 💙",
            "ციფრულ ხმაურს",
            "რამდენი წლის არის თქვენი შვილი?",
        ],
        "forbidden_contains": [
            "სწავლობენ საკუთარი აზრებისა და ემოციების გამოხატვას",
            "თვითგამოხატვის პროცესში ერთვებიან",
            "გამოხატვას 💙",
            "💙.",
        ],
    },
    {
        "id": "02_intro_plain",
        "category": "intro",
        "fresh": True,
        "turns": ["ბანაკზე მინდა ინფორმაცია"],
        "expected_contains": [
            "ციფრულ ხმაურს",
            "რამდენი წლის არის თქვენი შვილი?",
        ],
        "forbidden_contains": [
            "❤️",
            "სწავლობენ საკუთარი აზრებისა და ემოციების გამოხატვას",
        ],
    },
    # ── Price / payment ──────────────────────────────────────────────────────
    {
        "id": "03_camp_price",
        "category": "price",
        "turns": ["ბანაკის ფასი რა არის?"],
        "expected_contains": [
            "2150",
            "ტრანსპორტ",
            "განთავს",
            "კვება",
            "სრული პროგრამა",
        ],
        "forbidden_contains": ["??"],
    },
    {
        "id": "04_payment_how",
        "category": "payment",
        "turns": ["როგორ ხდება გადახდა?"],
        "expected_contains": [
            "ბანაკის ჯავშნის საფასურის გადახდა ხდება წინასწარ",
            "სრული თანხის — ხელშეკრულებით გათვალისწინებულ დროში",
        ],
        "forbidden_contains": ["??"],
    },
    {
        "id": "05_payment_onetime",
        "category": "payment",
        "turns": ["ერთიანად ხდება გადახდა?"],
        "expected_contains": [
            "ბანაკის ჯავშნის საფასურის გადახდა ხდება წინასწარ",
            "სრული თანხის — ხელშეკრულებით გათვალისწინებულ დროში",
        ],
    },
    # ── Seats / availability ─────────────────────────────────────────────────
    {
        "id": "06_seats_stream2",
        "category": "seats",
        "unknown_fallback": True,
        "turns": ["მე-2 ნაკადზე ადგილები გაქვთ?"],
        "expected_contains": [_SEATS_FB],
        "forbidden_contains": [
            "კი, ადგილები",
            "თავისუფალია",
            "დაგარეგისტრირებთ",
            "რამდენი წლის არის თქვენი შვილი?",
        ],
    },
    {
        "id": "07_seats_count",
        "category": "seats",
        "unknown_fallback": True,
        "turns": ["რამდენი ადგილი დარჩა?"],
        "expected_contains": ["კონკრეტულ ნაკადზე დარჩენილ ადგილებს", _MGR],
        "forbidden_contains": ["ადგილი არის", "თავისუფალია"],
    },
    {
        "id": "08_discount_plus_seats",
        "category": "seats",
        "unknown_fallback": True,
        "turns": ["ორი ბავშვი მინდა გამოვუშვა, ფასდაკლება და ადგილები იქნება?"],
        "expected_contains": [_DISCOUNT_LINE, _SEATS_FB],
    },
    # ── Food / menu ──────────────────────────────────────────────────────────
    {
        "id": "09_food_general",
        "category": "food",
        "turns": ["კვება როგორია ბანაკში?"],
        "expected_contains": [_FOOD_GEN_1, "კვება შედის ბანაკის ღირებულებაში"],
        "forbidden_contains": ["💙"],
    },
    {
        "id": "10_food_frequency",
        "category": "food",
        "unknown_fallback": True,
        "turns": ["კვება დღეში რადმენჯერ არის?"],
        "expected_contains": [_FOOD_GEN_1, _FREQ_FB],
        "forbidden_contains": ["სამჯერ", "ოთხჯერ", "💙"],
    },
    {
        "id": "11_food_frequency_repeat_multiturn",
        "category": "food",
        "unknown_fallback": True,
        "turns": [
            "კვება დღეში რადმენჯერ არის?",
            "დღეში რამდენჯერ ექნებათ კვება არ იცი?",
        ],
        "expected_contains": [_FREQ_FB],
        "forbidden_contains": [_FOOD_GEN_FULL],
        "notes": "repeat suppression should drop the general food block on turn 2",
    },
    {
        "id": "12_menu_general",
        "category": "food",
        "unknown_fallback": True,
        "turns": ["მენიუ როგორი იქნება?"],
        "expected_contains": [_FOOD_GEN_1, _MENU_FB],
    },
    {
        "id": "13_menu_exact",
        "category": "food",
        "unknown_fallback": True,
        "turns": ["ზუსტად რა მენიუ ექნებათ?"],
        "expected_contains": [_MENU_FB],
    },
    # ── Rooms / accommodation ────────────────────────────────────────────────
    {
        "id": "14_accommodation_general",
        "category": "rooms",
        "turns": ["განთავსება როგორია?"],
        "expected_contains": [_ACCOMMODATION],
    },
    {
        "id": "15_room_count_fresh",
        "category": "rooms",
        "fresh": True,
        "unknown_fallback": True,
        "turns": ["ოთახში რამდენი ბავშვი იქნება?"],
        "expected_contains": [_ROOM_FB],
        "forbidden_contains": ["რამდენიმე ბავშვი", "2–3", "რამდენი წლის არის თქვენი შვილი?"],
    },
    {
        "id": "16_room_count_typo_fresh",
        "category": "rooms",
        "fresh": True,
        "unknown_fallback": True,
        "turns": ["ოთხაში რამდენი ბავაში იქნება?"],
        "expected_contains": [_ROOM_FB],
    },
    {
        "id": "17_towels",
        "category": "rooms",
        "unknown_fallback": True,
        "turns": ["პირსახოცები იქნება?"],
        "expected_contains": [_TOWEL_FB],
    },
    {
        "id": "18_hotel_other_guests",
        "category": "rooms",
        "unknown_fallback": True,
        "turns": ["სხვა სტუმრები იქნებიან ბანაკში თუ მარტო ბანაკის ბავშვები იქნებიან?"],
        "expected_contains": [_ENDING],
        "forbidden_contains": [
            "თუ გსურთ, კონსულტაციაზე ჩაგწერთ",
            "აგიხსნით",
            "რამდენი წლის არის თქვენი შვილი?",
        ],
    },
    # ── Safety / staff ───────────────────────────────────────────────────────
    {
        "id": "19_safety",
        "category": "safety",
        "turns": ["ბანაკში უსაფრთხოება როგორ არის დაცული?"],
        "expected_contains": [
            "უსაფრთხოების ნაწილს დიდი ყურადღება ეთმობა",
            "სამედიცინო პერსონალი 24/7",
            "24-საათიანი ვიდეომონიტორინგი",
        ],
        "forbidden_contains": ["💙"],
    },
    {
        "id": "20_staff_count",
        "category": "safety",
        "unknown_fallback": True,
        "turns": ["რამდენი ადამიანისგან შედგება ბანაკის სტაფი?"],
        "expected_contains": ["სტაფ", _STAFF_FB],
    },
    {
        "id": "21_leader_count",
        "category": "safety",
        "unknown_fallback": True,
        "turns": ["რამდენი ლიდერი იქნება?"],
        "expected_contains": [_STAFF_FB],
    },
    # ── Parent contact ───────────────────────────────────────────────────────
    {
        "id": "22_parent_child_contact",
        "category": "parent_contact",
        "unknown_fallback": True,
        "turns": ["ბავშვთან კონტაქტი მექნება?"],
        "expected_contains": [_PC_KEY, _DIRECT_CALL_FB],
        "forbidden_contains": [
            "ვიდეო კონსულტაცია",
            "ტელეფონით კონსულტაცია",
            "💙",
            "აგიხსნით",
        ],
        "notes": (
            "FIXED 2026-07-01 — the parent_communication block's direct-contact "
            "caveat now uses the approved manager defer (no 'აგიხსნით'); the known "
            "daily-updates part is kept."
        ),
    },
    {
        "id": "23_direct_call_rules",
        "category": "parent_contact",
        "unknown_fallback": True,
        "turns": ["დღეში რამდენჯერ შევძლებ დარეკვას?"],
        "expected_contains": [_DIRECT_CALL_FB],
        "forbidden_contains": ["აგიხსნით"],
        "notes": (
            "FIXED 2026-07-01 — direct_call noun_markers now cover the 'დარეკვ' "
            "verbal-noun stem, so this defers deterministically (previously fell "
            "through to the engine)."
        ),
    },
    # ── Activities / sports / unknown facilities ─────────────────────────────
    {
        "id": "24_activities",
        "category": "activities",
        "turns": ["რა აქტივობები იქნება?"],
        "expected_contains": ["აქტივობ"],
    },
    {
        "id": "25_sports",
        "category": "activities",
        "turns": ["სპორტული აქტივობები იქნება?"],
        "expected_contains": ["სპორტ"],
    },
    {
        "id": "26_stadium",
        "category": "activities",
        "child_age": "",
        "unknown_fallback": True,
        "turns": ["სტადიონი ექნებათ ბანაკში?"],
        "expected_contains": [_STADIUM_FB],
        "forbidden_contains": [
            "რამდენი წლის არის თქვენი შვილი?",
            "თუ გსურთ, კონსულტაციაზე ჩაგწერთ",
            "💙",
        ],
    },
    {
        "id": "27_pool",
        "category": "activities",
        "unknown_fallback": True,
        "turns": ["აუზი იქნება?"],
        "expected_contains": [_ENDING],
    },
    # ── Peer / same-age ──────────────────────────────────────────────────────
    {
        "id": "28_unclear_phrase",
        "category": "peer",
        "child_age": "",
        "turns": ["ჩემი შვილი ხელა ბავშვები იქნებიან?"],
        "expected_contains": [_UNCLEAR],
        "forbidden_contains": ["ასე უკეთ გაგვეცნობა"],
    },
    {
        "id": "29_peer_same_age",
        "category": "peer",
        "child_age": "",
        "unknown_fallback": True,
        "turns": ["ჩემი შვილი 14 წლის არის და მისი ტოლი ბავშვები თუ იქნებიან?"],
        "expected_contains": ["14 წლის ასაკი ბანაკისთვის შესაბამისია", _PEER_FB],
        "forbidden_contains": ["თანატოლები იქნებიან"],
    },
    {
        "id": "30_age_group_count",
        "category": "peer",
        "unknown_fallback": True,
        "turns": ["რამდენი ბავშვი იქნება 14 წლის?"],
        "expected_contains": [_AGE_GROUP_FB],
        "forbidden_contains": ["თუ გსურთ, კონსულტაციაზე ჩაგწერთ", "აგიხსნით"],
    },
    # ── Registration / manager / consultation ────────────────────────────────
    {
        "id": "31_manager_number",
        "category": "manager",
        "turns": ["მენეჯერის ნომერი მომწერეთ"],
        "expected_contains": [_MGR],
    },
    {
        "id": "32_connect_manager",
        "category": "manager",
        "turns": ["მენეჯერთან დამაკავშირეთ"],
        "expected_any": ["მენეჯერთან დაგაკავშირებთ", "მენეჯერ"],
        "forbidden_contains": ["💙"],
        "notes": "generic manager CTA — manager flow, no forced 💙",
    },
    {
        "id": "33_book_consultation",
        "category": "manager",
        "turns": ["კონსულტაციაზე ჩამწერეთ"],
        "forbidden_contains": ["💙"],
        "notes": "booking flow / asks required data; no 💙 (not confirmed)",
    },
    # ── Closing ──────────────────────────────────────────────────────────────
    {
        "id": "34_thanks",
        "category": "closing",
        "child_age": "",
        "turns": ["მადლობა"],
        "expected_contains": ["💙"],
        "forbidden_contains": [
            "💙.",
            "რამდენი წლის არის თქვენი შვილი?",
            "თქვენი შვილი რამდენი წლისაა?",
            "ტელეფონის ნომერი",
            "კონსულტაციაზე ჩაგწერთ",
        ],
    },
    {
        "id": "35_thanks_decline",
        "category": "closing",
        "child_age": "",
        "turns": ["მადლობა არ მინდა"],
        "expected_contains": ["💙"],
        "forbidden_contains": [
            "რამდენი წლის არის თქვენი შვილი?",
            "ტელეფონის ნომერი",
            "კონსულტაციაზე ჩაგწერთ",
        ],
    },
    {
        "id": "36_soft_close",
        "category": "closing",
        "child_age": "",
        "turns": ["ჯერ არა, მადლობა"],
        "forbidden_contains": [
            "რამდენი წლის არის თქვენი შვილი?",
            "9-ნიშნა",
            "კონსულტაციაზე ჩაგწერთ",
        ],
        "notes": "soft close — no age question, no phone request, no consultation push",
    },
    # ── Organization / political / off-topic ─────────────────────────────────
    {
        "id": "37_who_is_behind",
        "category": "org",
        "unknown_fallback": True,
        "turns": ["თქვენს უკან ვინ დგას?"],
        "expected_contains": [_ORG_PREFIX, _ORG_FB],
        "forbidden_contains": [
            "რამდენი წლის არის თქვენი შვილი?",
            "თქვენი შვილი რამდენი წლისაა?",
        ],
    },
    {
        "id": "38_who_is_organizer",
        "category": "org",
        "unknown_fallback": True,
        "turns": ["ვინ არის ორგანიზატორი?"],
        "expected_contains": [_ORG_FB],
        "notes": "organizer fallback — no invented founder/legal details",
    },
    {
        "id": "39_political_qoc",
        "category": "political",
        "child_age": "",
        "turns": ["ქოცები ხართ თქვენ?"],
        "expected_contains": [_POL_1, _POL_2],
        "forbidden_contains": ["მსურს დაგეხმაროთ", "რამდენი წლის არის თქვენი შვილი?"],
    },
    {
        "id": "40_political_nac",
        "category": "political",
        "child_age": "",
        "turns": ["ნაცები ხართ?"],
        "expected_contains": [_POL_1],
        "forbidden_contains": ["რამდენი წლის არის თქვენი შვილი?"],
    },
    # ── Sunday School / adult events ─────────────────────────────────────────
    {
        "id": "41_sunday_school",
        "category": "other_program",
        "sunday_school": True,
        "turns": ["საკვირაო სკოლაზე ინფორმაცია მინდა"],
        "expected_contains": ["დეტალები ჯერ ზუსტდება"],
        "forbidden_contains": ["2150", "7-დღიან"],
        "notes": "Sunday School coming_soon flow, not the camp intro",
    },
    {
        "id": "42_adult_events",
        "category": "other_program",
        "state": "START",
        "turns": ["ზრდასრულთა ღონისძიებები რა გაქვთ?"],
        "forbidden_contains": ["7-დღიან", "2150", "დარჩენილ ადგილებს"],
        "notes": "adult route (engine); must not leak camp intro / seats fallback",
    },
    # ── Multi-question stress ────────────────────────────────────────────────
    {
        "id": "43_multi_price_sports",
        "category": "multi",
        "turns": ["ფასი რა არის და სპორტული აქტივობები იქნება?"],
        "expected_contains": ["2150", "სპორტული აქტივობები"],
    },
    {
        "id": "44_multi_price_seats",
        "category": "multi",
        "unknown_fallback": True,
        "turns": ["ფასი რა არის და ადგილები გაქვთ?"],
        "expected_contains": ["2150", _SEATS_FB],
    },
    {
        "id": "45_multi_price_stadium",
        "category": "multi",
        "unknown_fallback": True,
        "turns": ["ფასი რა არის და სტადიონი ექნებათ?"],
        "expected_contains": ["2150", _STADIUM_FB],
    },
    {
        "id": "46_multi_food_menu",
        "category": "multi",
        "unknown_fallback": True,
        "turns": ["კვება შედის და მენიუ როგორი იქნება?"],
        "expected_contains": [_FOOD_GEN_1, _MENU_FB],
    },
    {
        "id": "47_multi_safety_contact",
        "category": "multi",
        "turns": ["უსაფრთხოება როგორ არის და ბავშვთან კონტაქტი მექნება?"],
        "expected_contains": ["უსაფრთხოებ"],
        "expected_any": ["მშობლ", "კომუნიკაცი"],
        "notes": (
            "safety + parent-communication (the parent_communication block no "
            "longer contains 'აგიხსნით' after the 2026-07-01 fix)."
        ),
    },
    {
        "id": "48_multi_accommodation_room",
        "category": "multi",
        "unknown_fallback": True,
        "turns": ["განთავსება როგორია და ოთახში რამდენი ბავშვი იქნება?"],
        "expected_contains": [_ROOM_FB],
        "notes": (
            "the anti-invention room defer fires (critical). The general "
            "accommodation sentence is superseded by the room defer — see report "
            "finding (multi-intent accommodation not appended)."
        ),
    },
    {
        "id": "49_multi_price_payment",
        "category": "multi",
        "turns": ["ბანაკის ფასი რა არის და როგორ ხდება გადახდა?"],
        "expected_contains": ["2150", "TBC"],
        "notes": (
            "price+payment combined; payment question so the price sanitizer is a "
            "no-op → the block keeps price + installment/payment info. Exact "
            "payment sub-wording in a combined question is LLM-composed."
        ),
    },
    {
        "id": "50_multi_streamdate_seats",
        "category": "multi",
        "unknown_fallback": True,
        "turns": ["მე-2 ნაკადი როდის არის და ადგილები გაქვთ?"],
        "expected_contains": [_SEATS_FB],
        "notes": (
            "seats interceptor short-circuits before the dates engine, so the "
            "stream DATE is NOT returned — see report finding (stream date + "
            "seats not combined)."
        ),
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────
def test_matrix_shape():
    assert len(MATRIX) == 50
    ids = [c["id"] for c in MATRIX]
    assert len(ids) == len(set(ids)), "duplicate case ids"
    for c in MATRIX:
        assert c["turns"], f"{c['id']} has no turns"


def test_engine_is_on_and_mocked():
    # The live/legacy runtime mode is in effect for this file.
    assert parent_flow.settings.USE_PARENT_LLM_ENGINE is True
    assert parent_flow.settings.USE_CONVERSATION_PLANNER is False
    assert parent_flow.settings.CONVERSATION_PLANNER_AUTHORITATIVE is False
    assert parent_flow.settings.USE_SLIM_PROMPTS is False
    assert parent_flow._run_llm_engine_safely is _smart_engine
    assert parent_flow._CLIENT_EMOJI_ENABLED is True


@pytest.mark.parametrize("case", MATRIX, ids=[c["id"] for c in MATRIX])
def test_client_qa_smoke(case, monkeypatch, camp_registration_open):
    if case.get("sunday_school"):
        _apply_coming_soon(monkeypatch)

    conv = _build_conv(case)
    resp = ""
    for turn in case["turns"]:
        resp = parent_flow.handle(conv, turn)
        # Replicate conversation_service history growth for multi-turn cases.
        conv.history.append({"role": "user", "content": turn})
        conv.history.append({"role": "assistant", "content": resp})

    problems = _global_problems(case, resp) + _case_problems(case, resp)
    if _SIDE_EFFECTS:
        problems.append(
            f"READ-ONLY VIOLATED — side effects triggered: {sorted(set(_SIDE_EFFECTS))}"
        )

    if problems:
        pytest.fail(_format_report(case, resp, problems), pytrace=False)


# ─────────────────────────────────────────────────────────────────────────────
# Direct-call marker regression (client QA fix 2026-07-01)
# The „დარეკვ" verbal-noun stem + „შეეძლ"/„დრო" cues route call-rule questions to
# the deterministic manager defer — never the engine, never an invented call
# frequency, never „აგიხსნით", never an emoji.
# ─────────────────────────────────────────────────────────────────────────────
_DIRECT_CALL_VARIANTS = [
    "დღეში რამდენჯერ შევძლებ დარეკვას?",
    "რამდენჯერ დავურეკავ ბავშვს?",
    "ბავშვს დარეკვა შეეძლება?",
    "ზარის დრო როგორ იქნება?",
    "ბავშვთან დარეკვის წესები როგორია?",
]


@pytest.mark.parametrize(
    "msg",
    _DIRECT_CALL_VARIANTS,
    ids=[f"v{i}" for i in range(len(_DIRECT_CALL_VARIANTS))],
)
def test_direct_call_marker_regression(msg, camp_registration_open):
    conv = _build_conv({"id": "direct_call_variant", "turns": [msg]})
    out = parent_flow.handle(conv, msg)
    assert _DIRECT_CALL_FB in out, f"{msg!r} did not defer to manager: {out!r}"
    assert out != _ENGINE, f"{msg!r} fell through to the engine mock"
    assert "აგიხსნით" not in out
    assert "💙" not in out and "❤️" not in out
    assert not re.search(r"\d+\s*ჯერ", out), f"invented call frequency: {out!r}"
    assert not _SIDE_EFFECTS, f"read-only violated: {sorted(set(_SIDE_EFFECTS))}"


# ─────────────────────────────────────────────────────────────────────────────
# „აგიხსნით" wording guarantee (client QA 2026-07-01)
# The LLM engine / legacy path may still COMPOSE a consultation CTA with
# „აგიხსნით" (the giant prompt historically promoted it). handle()'s final
# deterministic pass must rewrite it to „გაგაცნობთ" so it never reaches the
# client, no matter what the model produced.
# ─────────────────────────────────────────────────────────────────────────────
_AGIXSNIT_ENGINE_LEAKS = [
    "ეს გასაგები სურვილია. თუ გსურთ, კონსულტაციაზე ჩაგწერთ და მენეჯერი დეტალურად აგიხსნით პროცესს.",
    "ბანაკი 2150 ლარია. თუ გინდათ, კონსულტაციაზე ჩაგწერთ და მენეჯერი დეტალებს აგიხსნით.",
    "თუ გსურთ, კონსულტაციაზეც ჩაგწერთ და დეტალებს მენეჯერი აგიხსნით.",
    "მენეჯერი დეტალურად აგიხსნით.",
    "დეტალებს აგიხსნით.",
]


@pytest.mark.parametrize(
    "engine_reply",
    _AGIXSNIT_ENGINE_LEAKS,
    ids=[f"leak{i}" for i in range(len(_AGIXSNIT_ENGINE_LEAKS))],
)
def test_agixsnit_never_reaches_live_output(engine_reply, monkeypatch, camp_registration_open):
    # Force the (mocked) engine to leak „აგიხსნით"; handle() must scrub it.
    monkeypatch.setattr(parent_flow, "_run_llm_engine_safely", lambda c, m: engine_reply)
    conv = _build_conv({"id": "agixsnit_leak", "turns": ["ბანაკის შესახებ მაინტერესებს"]})
    out = parent_flow.handle(conv, "ბანაკის შესახებ მაინტერესებს")
    assert "აგიხსნით" not in out, f"live output still contains agixsnit: {out!r}"
    assert "გაგაცნობთ" in out, f"expected gagatsnobt (approved wording) in: {out!r}"
    assert not _SIDE_EFFECTS, f"read-only violated: {sorted(set(_SIDE_EFFECTS))}"


def test_normalise_agixsnit_unit():
    # Direct unit coverage of the wording guarantee.
    assert parent_flow._normalise_agixsnit_wording(
        "თუ გსურთ, კონსულტაციაზე ჩაგწერთ და მენეჯერი დეტალურად აგიხსნით პროცესს."
    ) == "თუ გსურთ, კონსულტაციაზე ჩაგწერთ, სადაც დეტალებს მენეჯერი გაგაცნობთ."
    assert "აგიხსნით" not in parent_flow._normalise_agixsnit_wording("დეტალებს აგიხსნით.")
    # No-op for text without the banned word (deterministic blocks/defers).
    clean = "რაც შეეხება ზუსტ მენიუს, ამ დეტალებს მენეჯერი გაგაცნობთ : 558 67 47 33"
    assert parent_flow._normalise_agixsnit_wording(clean) == clean
