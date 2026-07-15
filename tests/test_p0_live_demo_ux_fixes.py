"""P0 LIVE DEMO UX REGRESSION — offline/mocked regression tests.

Covers the real-client Messenger transcript issues (2026-06-13):

  ISSUE 1 — clear camp intent must SKIP the generic two-option
            disambiguation menu and continue the camp flow.
  ISSUE 4 — an explicit „ღონისძიების ფასი" in a camp conversation must
            NEVER return the camp price; it asks which event / lists the
            active events.
  ISSUE 5 — an unknown date / title / guest must be searched against the
            ACTIVE event list; if found → answer from event data; if not
            found → say it is not in the active list, list the available
            active events, and offer manager verification (never invent).
  ISSUE 2/6 — the deterministic event answers use paragraph breaks; the
            camp age-question logic (ask once / never duplicate) is
            enforced by the existing post-processors.

Strategy note (per audit #7): the PARENT camp-price and price-objection
answers are SINGLE LLM BLOBS (the engine composes them). Their paragraph
formatting is therefore validated with the REAL model via
``tools/scenario_runner_full.py`` (the client-transcript scenarios), NOT
with a mocked formatting assertion. The NEW event-clarification / event-
listing answers ARE assembled from blocks in code, so their „\\n\\n"
structure IS asserted here deterministically.

All external services are mocked. No network, no OpenAI, no Meta/Calendar/
Sheets writes.
"""

from __future__ import annotations

import dataclasses

import pytest

import app.config as config_module
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import admin_config_service, conversation_service


# -- fixtures --------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_state():
    conversation_service.conversations.clear()
    parent_flow.available_slots.clear()
    parent_flow.slots_shown_for_state.clear()
    yield
    conversation_service.conversations.clear()
    parent_flow.available_slots.clear()
    parent_flow.slots_shown_for_state.clear()


@pytest.fixture
def mock_profile(monkeypatch):
    from app.services import messenger_service
    monkeypatch.setattr(
        messenger_service, "get_user_profile",
        lambda sid, plat: {
            "name": "ანა ლომიძე", "first_name": "ანა",
            "last_name": "ლომიძე", "username": "",
        },
    )


@pytest.fixture
def mock_start_intent(monkeypatch):
    from app.services import openai_service
    monkeypatch.setattr(
        openai_service, "detect_start_intent", lambda m: "GREETING",
    )


def _enable_engine(monkeypatch, content: str):
    """Flip USE_PARENT_LLM_ENGINE on and stub the OpenAI engine to return
    a fixed Georgian reply (no tool calls)."""
    swapped = dataclasses.replace(
        config_module.settings, USE_PARENT_LLM_ENGINE=True,
    )
    monkeypatch.setattr(parent_flow, "settings", swapped)
    monkeypatch.setattr(
        "app.agent.llm.parent_llm_engine.run_parent_llm_turn",
        lambda **kwargs: content,
    )


_MENU_MARKER = "გვითხარით, რა გაინტერესებთ"


# =========================================================================
# ISSUE 1 — clear camp intent skips the disambiguation menu
# =========================================================================

_CLEAR_CAMP_INTENT = [
    "გამარჯობა, სიტყვის აკადემიის ბანაკით ვარ დაინტერესებული",
    "ბანაკით ვარ დაინტერესებული",
    "საზაფხულო ბანაკი მაინტერესებს",
    "ბავშვის ბანაკზე მინდა ინფორმაცია",
]

_AMBIGUOUS_OR_BARE = [
    "გამარჯობა",          # bare greeting → menu
    "ბანაკი",              # bare topic word → menu
    "გამარჯობა, ბანაკი",  # greeting + bare topic → menu
    "ფასი?",               # bare price, no camp keyword → not camp intent
    "",
]


@pytest.mark.parametrize("msg", _CLEAR_CAMP_INTENT)
def test_issue1_detector_true_for_clear_camp_intent(msg):
    assert parent_flow._has_explicit_georgian_camp_intent(msg) is True


@pytest.mark.parametrize("msg", _AMBIGUOUS_OR_BARE)
def test_issue1_detector_false_for_ambiguous_or_bare(msg):
    assert parent_flow._has_explicit_georgian_camp_intent(msg) is False


@pytest.mark.parametrize("msg", _CLEAR_CAMP_INTENT)
def test_issue1_static_welcome_yields_for_clear_camp_intent(msg):
    conv = Conversation(sender_id="iss1-yield", platform="instagram")
    conv.segment = "PARENT"
    assert parent_flow._maybe_static_welcome(conv, msg) is None


def test_issue1_static_welcome_still_fires_for_bare_greeting():
    conv = Conversation(sender_id="iss1-greet", platform="instagram")
    conv.segment = "PARENT"
    out = parent_flow._maybe_static_welcome(conv, "გამარჯობა")
    assert out is not None and _MENU_MARKER in out


def test_issue1_static_welcome_still_fires_for_bare_topic():
    conv = Conversation(sender_id="iss1-topic", platform="instagram")
    conv.segment = "PARENT"
    out = parent_flow._maybe_static_welcome(conv, "გამარჯობა, ბანაკი")
    assert out is not None and _MENU_MARKER in out


def test_issue1_segment_classifies_parent(monkeypatch):
    # Sanity: the clear-camp message is PARENT (matches the „ბანაკ" stem),
    # so it routes to the camp flow (not the UNCLEAR menu route).
    seg = conversation_service._classify_segment(
        "გამარჯობა, სიტყვის აკადემიის ბანაკით ვარ დაინტერესებული",
    )
    assert seg == "PARENT"


def test_issue1_legacy_routing_skips_menu_and_continues_camp(
    mock_profile, mock_start_intent,
):
    """End-to-end (engine OFF / legacy): the clear-camp first message must
    NOT show the menu — it continues the camp flow with a substantive camp
    reply (the legacy analyzer answers camp info / asks the age depending
    on the matched intent; the engine path asks the age — see
    ``test_issue1_engine_path_skips_menu``)."""
    out = conversation_service.process_message(
        "iss1-legacy",
        "გამარჯობა, სიტყვის აკადემიის ბანაკით ვარ დაინტერესებული",
        "instagram",
    )
    assert _MENU_MARKER not in out
    assert "ბანაკ" in out  # a real camp reply, not the generic menu
    assert conversation_service.conversations["iss1-legacy"].segment == "PARENT"


def test_issue1_engine_path_skips_menu(monkeypatch, camp_registration_open):
    """End-to-end (engine ON): the engine is consulted for clear camp
    intent and the menu is never returned."""
    _enable_engine(
        monkeypatch,
        "გამარჯობა. ბანაკის შესახებ დაგეხმარებით. "
        "მითხარით, რამდენი წლისაა თქვენი შვილი?",
    )
    conv = Conversation(sender_id="iss1-engine", platform="instagram")
    conv.segment = "PARENT"
    out = parent_flow.handle(conv, "საზაფხულო ბანაკი მაინტერესებს")
    assert _MENU_MARKER not in out
    # Deterministic approved intro (client hotfix 2026-07-03) asks the child age
    # („რამდენი წლის არის თქვენი შვილი?"); match either age-question phrasing.
    assert "რამდენი წლის" in out


def test_issue1_plain_greeting_engine_on_still_menu(monkeypatch):
    """A bare greeting still shows the branded menu even with the engine
    on (the engine must not be consulted)."""
    _enable_engine(
        monkeypatch,
        "engine-should-not-run",  # if this leaks, the assertion below fails
    )
    conv = Conversation(sender_id="iss1-greet-engine", platform="instagram")
    conv.segment = "PARENT"
    out = parent_flow.handle(conv, "გამარჯობა")
    assert _MENU_MARKER in out
    assert "engine-should-not-run" not in out


# =========================================================================
# ISSUE 4 / 5 / 6 — event inquiry in camp context (hermetic, seeded events)
# =========================================================================

# A controlled active-events pool so these tests don't depend on the live
# data/admin_config/sections.yaml. Dates are in the future relative to the
# repo's „today" so the date filter keeps them.
_SEED_EVENTS = [
    {
        "id": "guest_meet",
        "title": "შეხვედრა ნინო ქართველთან",
        "status": "active", "active": True, "min_age": 13,
        "date_text": "20 ივლისი 19:00",
        "location": "ონლაინ შეხვედრა",
        "price_text": "40", "price_gel": 40,
        "description": "სასაუბრო საღამო ნინო ქართველთან განვითარებაზე.",
        "reservation_url": "https://example.com/guest",
        "guest": "ნინო ქართველი",
        "tags": ["#ნინოქართველთან"],
    },
    {
        "id": "concert",
        "title": "ზაფხულის სცენა",
        "status": "active", "active": True, "min_age": 13,
        "date_text": "25 ივლისი 20:00",
        "location": "თბილისი",
        "price_text": "60", "price_gel": 60,
        "reservation_url": "https://example.com/scene",
        "tags": ["#ჯაზფესტი"],
    },
]


@pytest.fixture
def seed_events(monkeypatch):
    """Replace the active-events pool with a controlled list. The
    ``find_active_events_*`` helpers call ``get_active_adult_events``
    internally, so patching this one chokepoint makes the whole search
    layer deterministic."""
    monkeypatch.setattr(
        admin_config_service, "get_active_adult_events",
        lambda *a, **k: [dict(e) for e in _SEED_EVENTS],
    )


def _parent_conv(sender_id="iss45", *, event_context=False):
    conv = Conversation(sender_id=sender_id, platform="instagram")
    conv.segment = "PARENT"
    conv.state = "ASK_CHALLENGE"  # mid-flow, not START
    conv.lead = Lead(sender_id=sender_id, platform="instagram", segment="PARENT")
    if event_context:
        conv.history.append({
            "role": "assistant",
            "content": "ამ ეტაპზე ხელმისაწვდომი ღონისძიებებია: — ...",
        })
    return conv


# -- ISSUE 4 — event price must never return the camp price ---------------


def test_issue4_event_price_never_returns_camp_price(seed_events):
    conv = _parent_conv()
    out = parent_flow._maybe_handle_event_inquiry(conv, "ღონისძიების ფასი რა არის")
    assert out is not None
    assert "2150" not in out  # the CAMP price must never appear
    assert "რომელი ღონისძიებ" in out  # asks which event
    # lists the available active events
    assert "შეხვედრა ნინო ქართველთან" in out
    assert "ზაფხულის სცენა" in out


def test_issue4_event_price_via_full_handle_no_camp_price(seed_events, monkeypatch):
    """Through the real handle() (engine path): the event-price question is
    intercepted before the engine, so the LLM (which knows the camp price)
    is never consulted and 2150 cannot leak."""
    _enable_engine(monkeypatch, "ბანაკის ფასი 2150 ლარია")  # engine must NOT run
    conv = _parent_conv("iss4-handle")
    out = parent_flow.handle(conv, "ღონისძიების ფასი რა არის")
    assert "2150" not in out
    assert "ღონისძიებ" in out


# -- ISSUE 5 — date / title / guest resolution ----------------------------


def test_issue5_date_with_no_event_lists_active(seed_events):
    conv = _parent_conv()
    out = parent_flow._maybe_handle_event_inquiry(
        conv, "16-ში რომ ღონისძიებაა ამაზე ვკითხულობ",
    )
    assert out is not None
    # No premature self/child target question.
    assert "თქვენთვის თუ" not in out
    assert "შვილისთვის" not in out
    assert "16 რიცხვში" in out  # names the unfound date
    assert "შეხვედრა ნინო ქართველთან" in out  # lists active events
    assert "2150" not in out


def test_issue5_date_with_event_returns_that_event(seed_events):
    conv = _parent_conv()
    out = parent_flow._maybe_handle_event_inquiry(
        conv, "20-ში რა ღონისძიებაა?",
    )
    assert out is not None
    assert "შეხვედრა ნინო ქართველთან" in out
    assert "20 ივლისი" in out


def test_issue5_unknown_title_lists_active(seed_events):
    # „გალაკტიონის საღამო" — not in the active list. Via event context
    # (the previous turn listed events) so the bare reference is caught.
    conv = _parent_conv(event_context=True)
    out = parent_flow._maybe_handle_event_inquiry(
        conv, "გალაკტიონის საღამოს ვგულისხმობ",
    )
    assert out is not None
    assert "ვერ ვპოულობ" in out  # not in the active list
    assert "შეხვედრა ნინო ქართველთან" in out  # lists active events
    assert "მენეჯერთან გადავამოწმებთ" in out  # offers manager verification
    assert "2150" not in out


def test_issue5_unknown_guest_lists_active(seed_events):
    conv = _parent_conv(event_context=True)
    out = parent_flow._maybe_handle_event_inquiry(conv, "თამარ ლომიძე იქნებოდა")
    assert out is not None
    assert "ვერ ვპოულობ" in out
    assert "შეხვედრა ნინო ქართველთან" in out


def test_issue5_known_guest_answers_from_event_data(seed_events):
    # Guest IS in the active list → answer from event data (not invented).
    conv = _parent_conv(event_context=True)
    out = parent_flow._maybe_handle_event_inquiry(conv, "ნინო ქართველი იქნებოდა")
    assert out is not None
    assert "შეხვედრა ნინო ქართველთან" in out
    assert "20 ივლისი" in out
    assert "40 ლარი" in out
    assert "https://example.com/guest" in out
    assert "ვერ ვპოულობ" not in out  # NOT a not-found message
    assert "2150" not in out


def test_issue5_alias_tag_matches(seed_events):
    # An event referenced by its hashtag alias resolves to that event.
    conv = _parent_conv(event_context=True)
    out = parent_flow._maybe_handle_event_inquiry(conv, "ჯაზფესტი მაინტერესებს")
    assert out is not None
    assert "ზაფხულის სცენა" in out  # the #ჯაზფესტი event
    assert "25 ივლისი" in out


def test_issue5_no_false_fire_without_event_signal_or_context(seed_events):
    # A camp message that names the camp must NOT be hijacked.
    conv = _parent_conv()
    assert parent_flow._maybe_handle_event_inquiry(
        conv, "ბანაკში რა ღონისძიებები იქნება?",
    ) is None
    # A bare name with no event keyword and no event context → not an
    # event inquiry (engine handles it).
    conv2 = _parent_conv("iss5-nofire")
    assert parent_flow._maybe_handle_event_inquiry(
        conv2, "ნინო ქართველი იქნებოდა",
    ) is None


# -- ISSUE 6 — deterministic paragraph formatting (code-built answers) -----


def test_issue6_event_answers_use_paragraph_breaks(seed_events):
    conv = _parent_conv(event_context=True)
    which = parent_flow._maybe_handle_event_inquiry(conv, "ღონისძიების ფასი რა არის")
    no_day = parent_flow._maybe_handle_event_inquiry(conv, "16-ში რა ღონისძიებაა")
    not_found = parent_flow._maybe_handle_event_inquiry(
        conv, "გალაკტიონის საღამო ვგულისხმობ",
    )
    info = parent_flow._maybe_handle_event_inquiry(conv, "ნინო ქართველი იქნებოდა")
    for label, out in (
        ("which", which), ("no_day", no_day),
        ("not_found", not_found), ("info", info),
    ):
        assert out is not None, label
        assert "\n\n" in out, f"{label}: expected paragraph breaks, got {out!r}"


def test_issue6_no_active_events_safe_fallback(monkeypatch):
    monkeypatch.setattr(
        admin_config_service, "get_active_adult_events", lambda *a, **k: [],
    )
    conv = _parent_conv()
    out = parent_flow._maybe_handle_event_inquiry(conv, "ღონისძიების ფასი რა არის")
    assert out is not None
    assert "მენეჯერთან" in out  # honest manager handoff, no invented event
    assert "2150" not in out


# -- ISSUE 2 (behavioural) — camp age-question logic (deterministic) -------
#
# The camp-PRICE answer itself is a single LLM blob, so its paragraph order
# is validated via scenario_runner (real model). The age-question BEHAVIOUR
# around it is enforced by deterministic post-processors and IS tested here.


def test_issue2_price_no_age_returns_deterministic_full_block(monkeypatch):
    """Camp price is owned by the deterministic full-block handler and
    does not append a qualification question on first price."""
    _enable_engine(monkeypatch, "ENGINE_REPLY 2150 TBC")
    conv = Conversation(sender_id="iss2-noage", platform="instagram")
    conv.segment = "PARENT"
    conv.state = "ASK_CHALLENGE"
    conv.lead = Lead(sender_id="iss2-noage", platform="instagram", segment="PARENT")
    out = parent_flow.handle(conv, "ბანაკის ფასი რა არის?")
    assert "2150" in out
    assert "TBC" in out
    assert "რამდენი წლისაა" not in out

def test_issue2_price_known_age_no_duplicate_age_question(monkeypatch):
    """Camp answer when the child age is already known → no duplicate age
    question even if the engine adds one."""
    _enable_engine(
        monkeypatch,
        "ბანაკის სრული ღირებულებაა 2150 ლარი. "
        "თქვენი შვილი რამდენი წლისაა?",
    )
    conv = Conversation(sender_id="iss2-age", platform="instagram")
    conv.segment = "PARENT"
    conv.state = "ASK_CHALLENGE"
    conv.lead = Lead(
        sender_id="iss2-age", platform="instagram", segment="PARENT",
        child_age="14",
    )
    out = parent_flow.handle(conv, "ფასი რა არის?")
    assert "რამდენი წლისაა" not in out  # known age → not re-asked


# -- ISSUE 3 / 6 — multi-point paragraph reformatter (deterministic) -------
#
# The camp-price / price-objection answer is a single LLM blob. Live QA
# showed the real model returning it as ONE dense paragraph. The production
# post-processor ``_format_multipoint_paragraphs`` runs on the REAL output
# and inserts paragraph breaks. These tests feed the EXACT dense shape the
# real model produced (captured from a scenario_runner run) and assert the
# reformatter adds the breaks — this tests the real post-processor on a
# realistic input, NOT a mocked LLM.

# Verbatim shape of a real gpt-4.1-mini price-objection reply (one block).
_REAL_DENSE_OBJECTION = (
    "გასაგებია, ფასი ნამდვილად მნიშვნელოვანი ფაქტორია. "
    "ფასი მოიცავს ტრანსპორტს, განთავსებას, კვებას და პროგრამას, რაც "
    "უზრუნველყოფს სრულყოფილ ზაფხულს თქვენი შვილისთვის. "
    "გადახდის გადანაწილება შესაძლებელია 6 თვემდე TBC-ისა და "
    "საქართველოს ბანკის საშუალებით. "
    "თუ გსურთ, კონსულტაციაზე ჩაგწერთ და მენეჯერი დეტალებს აგიხსნით."
)


def test_issue6_reformatter_splits_dense_objection_into_paragraphs():
    out = parent_flow._format_multipoint_paragraphs(_REAL_DENSE_OBJECTION)
    assert "\n\n" in out, "dense multi-point answer must gain paragraph breaks"
    assert out.count("\n\n") >= 3  # empathy / included / payment / CTA
    # No fact is lost — only whitespace changed.
    for token in ("ტრანსპორტ", "გადანაწილება", "TBC", "კონსულტაცია"):
        assert token in out


def test_issue6_reformatter_noop_on_single_point_short_reply():
    # A short single-point factual reply must NOT be reformatted.
    short = "ბანაკი ტარდება ამბასადორ კაჭრეთში."
    assert parent_flow._format_multipoint_paragraphs(short) == short
    # An already-paragraphed reply is left untouched.
    already = "გასაგებია.\n\nფასი 2150 ლარია და მოიცავს ტრანსპორტს, კვებას."
    assert parent_flow._format_multipoint_paragraphs(already) == already


def test_issue6_reformatter_noop_on_booking_confirmation():
    # Booking confirmations are single-point — never reformatted.
    conf = "16 ივნისი, 14:00 საათზე კონსულტაცია ჩაგინიშნეთ. მენეჯერი დაგიკავშირდებათ."
    assert parent_flow._format_multipoint_paragraphs(conf) == conf
