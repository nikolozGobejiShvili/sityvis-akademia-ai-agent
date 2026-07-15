from __future__ import annotations

import dataclasses

import pytest

import app.config as config_module
from app.agent.intent.parent_intent_detector import (
    INTENT_CONDITIONS_QUESTION,
    INTENT_DATES_QUESTION,
    INTENT_LOCATION_QUESTION,
)
from app.agent.tools.parent_tool_executor import ParentToolExecutor
from app.agent.tools.parent_tools import TOOL_GET_CAMP_INFO
from app.flows import parent_flow, parent_turn_router
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import admin_config_service


def _conversation(sender_id: str = "final-camp", *, history=None) -> Conversation:
    conv = Conversation(
        sender_id=sender_id,
        platform="instagram",
        page_id="page-final",
        segment="PARENT",
    )
    conv.lead = Lead(
        sender_id=sender_id,
        platform="instagram",
        segment="PARENT",
        child_age="12",
    )
    for turn in history or [{"role": "assistant", "content": "ბანაკზე გესაუბრებით."}]:
        conv.history.append(turn)
    return conv


@pytest.fixture
def closed_registration(monkeypatch):
    monkeypatch.setattr(
        admin_config_service,
        "get_camp_registration_status",
        lambda: "closed",
    )
    monkeypatch.setattr(
        admin_config_service,
        "is_camp_registration_open",
        lambda: False,
    )


@pytest.fixture
def parent_engine_on(monkeypatch):
    swapped = dataclasses.replace(
        config_module.settings,
        USE_PARENT_LLM_ENGINE=True,
        USE_CONVERSATION_PLANNER=False,
        CONVERSATION_PLANNER_AUTHORITATIVE=False,
        USE_REASONING_LAYER=False,
        USE_SLIM_PROMPTS=False,
    )
    monkeypatch.setattr(parent_flow, "settings", swapped)


def _reply(message: str, *, sender_id: str = "final-camp") -> tuple[str, Conversation]:
    conv = _conversation(sender_id)
    out = parent_flow.handle(conv, message)
    return out, conv


def _assert_no_sales_entry(text: str) -> None:
    low = text.lower()
    assert "http" not in low
    assert "კონსულტ" not in low
    assert "ჩაგწერ" not in low
    assert "დაჯავშ" not in low
    assert "რეგისტრაციის ბმული" not in low


@pytest.mark.parametrize(
    "message",
    [
        "ბანაკი რა ღირს?",
        "ბანაკის ფასი რა არის?",
        "ბანაკის ღირებულება მითხარით",
    ],
)
def test_final_policy_price_remains_available_without_sales_cta(
    closed_registration,
    parent_engine_on,
    message,
):
    out, conv = _reply(message, sender_id=f"price-{abs(hash(message))}")

    assert parent_flow._camp_price_value() in out
    assert "TBC" in out
    _assert_no_sales_entry(out)
    assert conv.state == "START"
    assert conv.pending_booking is None


@pytest.mark.parametrize(
    "message",
    [
        "ბანაკზე ახლა რეგისტრაცია შეიძლება?",
        "ბანაკზე ადგილები არის?",
        "ბანაკის რეგისტრაციის ლინკი გამომიგზავნეთ",
        "ბანაკზე კონსულტაცია მინდა",
        "ბავშვი მიმდინარე ნაკადს შეუერთდება?",
    ],
)
def test_final_policy_registration_availability_and_booking_are_closed(
    closed_registration,
    message,
):
    out, conv = _reply(message, sender_id=f"registration-{abs(hash(message))}")

    assert out == parent_flow._camp_registration_closed_answer()
    _assert_no_sales_entry(out)
    assert conv.state == "START"
    assert conv.pending_booking is None


@pytest.mark.parametrize(
    "message",
    [
        "ბანაკის ნაკადები როდის არის?",
        "დაიწყო უკვე ბანაკი?",
        "ბანაკი რამდენი დღეა?",
        "ბანაკი სად ტარდება?",
        "ბანაკში ტრანსპორტირება როგორ ხდება?",
        "ბანაკის პროგრამაში რა ხდება?",
    ],
)
def test_final_policy_current_camp_details_are_limited(closed_registration, message):
    out, _conv = _reply(message, sender_id=f"details-{abs(hash(message))}")

    assert out == parent_flow._camp_registration_closed_answer()
    _assert_no_sales_entry(out)
    assert "14-20" not in out
    assert "14–20" not in out
    assert "7-დღ" not in out
    assert "კაჭრეთ" not in out
    assert "ტრანსპორტირება შედის" not in out


def test_final_policy_current_parent_support_uses_manager_handoff_source(
    closed_registration,
    monkeypatch,
):
    sentinel = "MANAGER_CONTACT_SENTINEL"
    monkeypatch.setattr(admin_config_service, "get_manager_phone", lambda: sentinel)

    out, _conv = _reply("ბავშვს როგორ დავურეკო ბანაკში?", sender_id="parent-support")

    assert out != parent_flow._camp_registration_closed_answer()
    assert sentinel in out
    assert "მენეჯერი" in out
    _assert_no_sales_entry(out)


@pytest.mark.parametrize(
    "message",
    [
        "შემდეგი ბანაკი როდის იქნება?",
        "მომავალ ნაკადზე რეგისტრაცია როდის დაიწყება?",
        "შემდეგი ნაკადის თარიღები ცნობილია?",
        "მომავალ წელს ბანაკი იქნება?",
    ],
)
def test_final_policy_future_camp_is_pending_information(closed_registration, message):
    out, _conv = _reply(message, sender_id=f"future-{abs(hash(message))}")

    assert out == parent_flow._camp_future_information_not_announced_answer()
    _assert_no_sales_entry(out)
    assert "14-20" not in out
    assert "14–20" not in out


@pytest.mark.parametrize(
    "message",
    [
        "ახლა რა გაქვთ ბავშვისთვის?",
        "ბანაკის ალტერნატივა რა არის?",
        "საკვირაო სკოლის ფასი რა არის?",
        "საკვირაო სკოლის თარიღები მაინტერესებს",
    ],
)
def test_final_policy_sunday_school_is_direction_without_details(
    closed_registration,
    message,
):
    out, _conv = _reply(message, sender_id=f"sunday-{abs(hash(message))}")

    assert "საკვირაო სკოლ" in out
    assert parent_flow._camp_price_value() not in out
    _assert_no_sales_entry(out)
    assert "14-20" not in out
    assert "14–20" not in out


@pytest.mark.parametrize(
    "message",
    [
        "ბანაკში აუზთან დაკავშირებით დეტალი მაინტერესებს",
        "ბანაკზე რაღაც კონკრეტული კითხვა მაქვს",
        "იქ რა ხდება ზუსტად?",
    ],
)
def test_final_policy_unknown_camp_questions_do_not_leak_stale_facts(
    closed_registration,
    message,
):
    history = [{"role": "assistant", "content": "ბანაკზე გესაუბრებით."}]
    conv = _conversation(f"unknown-{abs(hash(message))}", history=history)
    out = parent_flow.handle(conv, message)

    assert out == parent_flow._camp_registration_closed_answer()
    _assert_no_sales_entry(out)
    assert "14-20" not in out
    assert "14–20" not in out
    assert "კაჭრეთ" not in out


@pytest.mark.parametrize(
    "intent,message",
    [
        (INTENT_DATES_QUESTION, "ბანაკის თარიღები მაინტერესებს"),
        (INTENT_LOCATION_QUESTION, "ბანაკი სად ტარდება?"),
        (INTENT_CONDITIONS_QUESTION, "ბანაკის პირობები მითხარით"),
    ],
)
def test_final_policy_router_detail_fallbacks_are_limited(
    closed_registration,
    intent,
    message,
):
    conv = _conversation(f"router-{intent}")
    out = parent_turn_router._response_for_intent(intent, conv, conv.lead, message)

    assert out == parent_flow._camp_registration_closed_answer()
    _assert_no_sales_entry(out)


def test_final_policy_tool_fallback_limits_non_price_facts_but_keeps_price(
    closed_registration,
):
    conv = _conversation("tool-final")
    executor = ParentToolExecutor(
        conversation=conv,
        lead=conv.lead,
        sender_id=conv.sender_id,
        platform=conv.platform,
    )

    price = executor.execute(TOOL_GET_CAMP_INFO, {"topic": "price"})
    assert price["success"] is True
    assert price["topic"] == "price"

    location = executor.execute(TOOL_GET_CAMP_INFO, {"topic": "location"})
    assert location == {
        "success": False,
        "reason": "camp_public_info_limited",
        "topic": "location",
        "message": parent_flow._camp_registration_closed_answer(),
    }

    all_info = executor.execute(TOOL_GET_CAMP_INFO, {"topic": "all"})
    assert all_info["success"] is False
    assert all_info["reason"] == "camp_public_info_limited"
    assert "registration_url" not in all_info
    assert "streams" not in all_info