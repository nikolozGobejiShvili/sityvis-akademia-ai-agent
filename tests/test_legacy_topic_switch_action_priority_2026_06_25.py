"""Legacy topic-switch + explicit-action priority (live bug 2026-06-25).

After a switch to adult events, an explicit CAMP registration-link request was
swallowed by the sticky ADULT segment (routed to the adult flow, which asked the
child's age) instead of returning the camp registration link.

Fix: intent/action-level detection (app/reasoning/legacy_actions) + an
ADULT→PARENT routing flip for an explicit camp action, plus a camp-context-aware
path in parent_flow._maybe_handle_camp_registration_link. Planner/slim stay OFF;
no phrase-specific handlers.
"""
from __future__ import annotations

import dataclasses

import pytest

import app.config as config_module
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.reasoning.legacy_actions import detect_legacy_explicit_action
from app.services import admin_config_service, conversation_service, messenger_service

_CAMP_URL = "https://tinyurl.com/36jcae8z"
_AGE_Q = ("რამდენი წლის", "რა წლისაა", "რომელ კლას", "ბავშვის ასაკი")


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    conversation_service.conversations.clear()
    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    yield
    conversation_service.conversations.clear()


def _seed(sid: str, *, segment: str, child_age: str = "14", state: str = "DONE") -> Conversation:
    conv = Conversation(sender_id=sid, platform="instagram", segment=segment)
    conv.state = state
    conv.lead = Lead(
        sender_id=sid, platform="instagram", segment=segment,
        child_age=child_age, name="ნიკოლოზი", phone="595999733",
    )
    conv.history = [{"role": "assistant", "content": "ღონისძიების შესახებ დაგეხმარებით."}]
    conversation_service.conversations[sid] = conv
    return conv


def _no_age_question(text: str) -> bool:
    low = (text or "").lower()
    return not any(m in low for m in _AGE_Q)


# =====================================================================
# Step 2 — detector unit tests (intent/action-level, not exact phrase)
# =====================================================================
def test_detect_camp_registration_with_camp_keyword():
    out = detect_legacy_explicit_action("ბანაკის სარეგისტრაციო ლინკი მომწერე")
    assert out == {"action": "camp_registration_link", "topic": "camp"}


def test_detect_camp_registration_in_camp_context_no_keyword():
    # Camp context is the LAST ASSISTANT TURN naming camp, not `segment ==
    # "PARENT"`. Every kids' program is served by the PARENT flow, so the old
    # rule made Sunday School and Disneyland conversations read as camp — live
    # 2026-09-03 a Sunday-School „როგორ დავრეგისტრირდე ?" was answered „ბანაკის
    # ბოლო ნაკადი უკვე დაიწყო". The scenario this test describes is unchanged;
    # only the evidence for it is now real.
    conv = Conversation(sender_id="c", platform="instagram", segment="PARENT")
    conv.history.append({"role": "user", "content": "ბანაკი მაინტერესებს"})
    conv.history.append({"role": "assistant", "content": "ბანაკის ნაკადები: 23-29 ივნისი."})
    out = detect_legacy_explicit_action("სარეგისტრაციო ლინკი მინდა", conv)
    assert out["action"] == "camp_registration_link"


def test_detect_registration_in_other_program_context_is_not_camp():
    """The regression the change above exists for.

    A Sunday-School conversation asking a bare „როგორ დავრეგისტრირდე?" must not
    be claimed by the camp handler — the engine answers it from that program's
    own registration URL, which now travels in the turn context.
    """
    conv = Conversation(sender_id="ss", platform="instagram", segment="PARENT")
    conv.history.append({"role": "user", "content": "საკვირაო სკოლა მაინტერესებს"})
    conv.history.append(
        {"role": "assistant", "content": "საკვირაო სკოლა: 595 ლარი, რეგისტრაცია ღიაა."}
    )
    out = detect_legacy_explicit_action("როგორ დავრეგისტრირდე ?", conv)
    assert out["action"] != "camp_registration_link"


def test_detect_bare_link_in_adult_context_is_not_camp():
    conv = Conversation(sender_id="a", platform="instagram", segment="ADULT")
    out = detect_legacy_explicit_action("ლინკი მომწერე", conv)
    assert out["action"] != "camp_registration_link"


def test_detect_adult_named_lookup():
    out = detect_legacy_explicit_action("გია მურღულიას ღონისძიება არის სიაში?")
    assert out["topic"] == "adult_event"
    assert out["action"] in ("adult_event_named_lookup", "adult_event_discovery")


def test_detect_adult_discovery():
    out = detect_legacy_explicit_action("ზრდასრულთა ღონისძიებები რა გაქვთ?")
    assert out == {"action": "adult_event_discovery", "topic": "adult_event"}


def test_detect_consultation_not_registration():
    out = detect_legacy_explicit_action("კი მინდა კონსულტაცია")
    assert out["action"] == "consultation_request"


def test_detect_darexistreba_in_camp_context():
    # Same correction as above: the camp context is stated by the conversation,
    # not inferred from the PARENT segment.
    conv = Conversation(sender_id="c", platform="instagram", segment="PARENT")
    conv.history.append({"role": "user", "content": "ბანაკი მაინტერესებს"})
    conv.history.append({"role": "assistant", "content": "საზაფხულო ბანაკის შესახებ:"})
    out = detect_legacy_explicit_action("დარეგისტრირება მინდა", conv)
    assert out["action"] == "camp_registration_link"


# =====================================================================
# Required tests 1–3 — camp registration link priority
# =====================================================================
def test_1_adult_context_then_camp_registration_link(camp_registration_open):
    _seed("t1", segment="ADULT", child_age="14")
    out = conversation_service.process_message(
        "t1", "ბანაკის სარეგისტრაციო ლინკი მომწერე", "instagram",
    )
    assert _CAMP_URL in out
    assert _no_age_question(out)
    assert conversation_service.conversations["t1"].segment == "PARENT"
    assert "2150" not in out          # not a camp-info answer


def test_2_camp_context_then_explicit_registration_link(camp_registration_open):
    _seed("t2", segment="PARENT", child_age="14")
    # The camp context this test is named for now has to be present: the PARENT
    # segment alone is every kids' program, not the camp.
    conversation_service.conversations["t2"].history.extend([
        {"role": "user", "content": "ბანაკი მაინტერესებს"},
        {"role": "assistant", "content": "ბანაკის ნაკადები: 23-29 ივნისი."},
    ])
    out = conversation_service.process_message(
        "t2", "სარეგისტრაციო ლინკი მინდა", "instagram",
    )
    assert _CAMP_URL in out
    assert _no_age_question(out)


def test_3_unknown_child_age_camp_registration_link(camp_registration_open):
    _seed("t3", segment="PARENT", child_age="", state="START")
    out = conversation_service.process_message(
        "t3", "ბანაკის რეგისტრაციის ლინკი მომწერე", "instagram",
    )
    assert _CAMP_URL in out
    assert _no_age_question(out)


# =====================================================================
# Required tests 4–6 — adult events: no child-age, no camp answer
# =====================================================================
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
    return swapped


def test_4_adult_discovery_after_camp_no_age(engine_on, monkeypatch):
    _seed("t4", segment="PARENT", child_age="14")
    monkeypatch.setattr(
        parent_flow, "_run_llm_engine_safely",
        lambda c, m: "ზრდასრულთა აქტიური ღონისძიებები: დეტალებს გაგიზიარებთ.",
    )
    out = conversation_service.process_message(
        "t4", "ზრდასრულთა ღონისძიებები რა გაქვთ?", "instagram",
    )
    assert _no_age_question(out)
    assert "2150" not in out          # no camp price
    assert "ზრდასრულ" in out


def test_5_adult_named_lookup_missing_event_no_age(monkeypatch):
    # No active events configured → „not in active list", never an age question
    # and never an invented event detail.
    monkeypatch.setattr(admin_config_service, "get_active_adult_events", lambda: [])
    conv = Conversation(sender_id="t5", platform="instagram", segment="PARENT")
    conv.lead = Lead(sender_id="t5", platform="instagram", segment="PARENT", child_age="14")
    out = parent_flow._maybe_handle_event_inquiry(
        conv, "გია მურღულიას ღონისძიება არის სიაში?",
    )
    assert out is not None
    assert _no_age_question(out)
    assert "2150" not in out


def test_6_adult_named_lookup_typo_spacing_no_age(monkeypatch):
    monkeypatch.setattr(admin_config_service, "get_active_adult_events", lambda: [])
    conv = Conversation(sender_id="t6", platform="instagram", segment="PARENT")
    conv.lead = Lead(sender_id="t6", platform="instagram", segment="PARENT", child_age="14")
    out = parent_flow._maybe_handle_event_inquiry(
        conv, "გიამურღულიას ღონისძიება არის სიაში?",
    )
    # Either resolved by fuzzy matching or the safe „no active events" reply —
    # in both cases never an age question and never a camp answer.
    if out is not None:
        assert _no_age_question(out)
        assert "2150" not in out


# =====================================================================
# Required tests 7–8 — existing flows not broken
# =====================================================================
def test_7_consultation_not_hijacked_by_registration():
    conv = Conversation(sender_id="t7", platform="instagram", segment="PARENT")
    conv.lead = Lead(sender_id="t7", platform="instagram", segment="PARENT", child_age="14")
    # A consultation request must NOT be treated as a registration link.
    assert parent_flow._maybe_handle_camp_registration_link(conv, "კი მინდა კონსულტაცია") is None
    # A booking confirmation with a slot + contact is not a registration link.
    assert parent_flow._maybe_handle_camp_registration_link(
        conv, "26 ივნისი 11 საათზე ჩავნიშნოთ, ნიკოლოზი 595999733",
    ) is None


def test_8_contact_extraction_still_works():
    name, phone = parent_flow._parse_name_phone("10 წლის არის ჩემი შვილი ნიკოლოზი 595999733")
    assert name == "ნიკოლოზი"
    assert phone == "595999733"
    # And such a message is never hijacked as a camp registration link.
    conv = Conversation(sender_id="t8", platform="instagram", segment="PARENT")
    conv.lead = Lead(sender_id="t8", platform="instagram", segment="PARENT")
    assert parent_flow._maybe_handle_camp_registration_link(
        conv, "10 წლის არის ჩემი შვილი ნიკოლოზი 595999733",
    ) is None


# =====================================================================
# Regression guard — bare link in adult context must STAY adult
# =====================================================================
def test_bare_link_in_adult_context_does_not_flip_to_camp():
    _seed("ta", segment="ADULT", child_age="14")
    # No camp keyword, adult context → must NOT return the camp link / flip.
    out = detect_legacy_explicit_action(
        "ლინკი მომწერე", conversation_service.conversations["ta"],
    )
    assert out["action"] != "camp_registration_link"
