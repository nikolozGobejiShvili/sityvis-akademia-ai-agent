from __future__ import annotations

import pytest

from app.agent.intent.parent_intent_detector import (
    INTENT_DATES_QUESTION,
    INTENT_LOCATION_QUESTION,
)
from app.agent.tools.parent_tool_executor import ParentToolExecutor
from app.agent.tools.parent_tools import TOOL_GET_CAMP_INFO
from app.flows import parent_flow, parent_turn_router
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import admin_config_service, conversation_service


CURRENT_CLOSED = "ბანაკის ბოლო ნაკადი უკვე დაიწყო და რეგისტრაცია დასრულებულია."
FUTURE_PENDING = "შემდეგი ბანაკის თარიღები და რეგისტრაციის ინფორმაცია ჯერ არ არის გამოცხადებული."


def _conversation(sender_id: str, *, camp_history: bool = True) -> Conversation:
    conv = Conversation(
        sender_id=sender_id,
        platform="instagram",
        page_id="page-live-correction",
        segment="PARENT",
    )
    conv.lead = Lead(
        sender_id=sender_id,
        platform="instagram",
        segment="PARENT",
        child_age="12",
    )
    if camp_history:
        conv.history.append({"role": "assistant", "content": "ბანაკზე გესაუბრებით."})
    return conv


def _reply(message: str, sender_id: str) -> tuple[str, Conversation]:
    conv = _conversation(sender_id)
    out = parent_flow.handle(conv, message)
    return out, conv


def _assert_no_sales_entry(text: str) -> None:
    low = text.lower()
    assert "http" not in low
    assert "რეგისტრაციის ბმული" not in low
    assert "კონსულტაციაზე" not in low
    assert "ჩაგწერ" not in low
    assert "დაჯავშ" not in low


def _assert_not_sunday_school(text: str) -> None:
    assert "საკვირაო" not in text
    assert "Sunday" not in text


def _assert_single_policy(text: str) -> None:
    assert text.count(CURRENT_CLOSED) <= 1
    assert text.count(FUTURE_PENDING) <= 1
    assert not (CURRENT_CLOSED in text and FUTURE_PENDING in text)
    assert not (parent_flow._camp_price_value() in text and "საკვირაო" in text)


def test_live_greeting_plus_camp_price_uses_process_message_price_owner():
    assert admin_config_service.get_camp_registration_status() == "closed"
    assert admin_config_service.is_camp_registration_open() is False
    conversation_service.conversations.clear()

    out = conversation_service.process_message(
        "live-price-greeting",
        "გამარჯობა ბანაკი რა ღირს?",
        platform="instagram",
        page_id="page-live-correction",
    )

    assert parent_flow._camp_price_value() in out
    assert "ტრანსპორტირება" in out
    assert "TBC" in out
    _assert_not_sunday_school(out)
    _assert_no_sales_entry(out)
    assert "ნომერ" not in out
    assert "მენეჯერი" not in out
    _assert_single_policy(out)


@pytest.mark.parametrize(
    "message",
    [
        "გამარჯობა ბანაკი რა ღირს?",
        "ბანაკის ფასი მაინტერესებს",
        "რა ღირს საზაფხულო ბანაკი?",
        "ბანაკში მონაწილეობა რა თანხაა?",
    ],
)
def test_live_camp_price_priority_wins_before_closed_policy(message):
    out, conv = _reply(message, f"live-price-{abs(hash(message))}")

    assert parent_flow._camp_price_value() in out
    assert "ტრანსპორტირება" in out
    assert "გადანაწილება" in out
    _assert_not_sunday_school(out)
    _assert_no_sales_entry(out)
    assert "ნომერ" not in out
    assert "მენეჯერი" not in out
    assert conv.state == "START"
    assert conv.pending_booking is None
    _assert_single_policy(out)


@pytest.mark.parametrize(
    "message",
    [
        "ბანაკის ნაკადები როდის არის?",
        "ბანაკი უკვე დაიწყო?",
        "ახლა კიდევ გაქვთ ბანაკი?",
        "შეიძლება ახლა ჩაწერა?",
        "რეგისტრაციის ლინკი გამომიგზავნეთ",
    ],
)
def test_live_current_camp_and_registration_use_current_closed_policy(message):
    out, conv = _reply(message, f"live-current-{abs(hash(message))}")

    assert out == CURRENT_CLOSED
    _assert_not_sunday_school(out)
    _assert_no_sales_entry(out)
    assert "ადგილები შევსებულია" not in out
    assert "14-20" not in out
    assert "14–20" not in out
    assert conv.state == "START"
    assert conv.pending_booking is None
    _assert_single_policy(out)


@pytest.mark.parametrize(
    "message",
    [
        "ტრანსპორტი როგორ ხდება?",
        "ბანაკი სად ტარდება?",
        "რამდენდღიანია ბანაკი?",
        "მიმდინარე ბანაკის განრიგი როგორია?",
    ],
)
def test_live_current_operational_details_are_limited_not_cross_sold(message):
    out, conv = _reply(message, f"live-operational-{abs(hash(message))}")

    assert out == CURRENT_CLOSED
    _assert_not_sunday_school(out)
    _assert_no_sales_entry(out)
    assert "ტრანსპორტირება შედის" not in out
    assert "კაჭრეთ" not in out
    assert "7-დღ" not in out
    assert conv.pending_booking is None
    _assert_single_policy(out)


@pytest.mark.parametrize(
    "message",
    [
        "შემდეგი ბანაკი როდის იქნება?",
        "მომავალი ბანაკის თარიღები ცნობილია?",
        "შემდეგი ნაკადი როდის დაიწყება?",
        "მომავალ ბანაკზე რეგისტრაცია როდის გაიხსნება?",
    ],
)
def test_live_future_camp_uses_future_pending_policy(message):
    out, conv = _reply(message, f"live-future-{abs(hash(message))}")

    assert out == FUTURE_PENDING
    _assert_not_sunday_school(out)
    _assert_no_sales_entry(out)
    assert "ბანაკის დეტალები ჯერ ზუსტდება" not in out
    assert "14-20" not in out
    assert "14–20" not in out
    assert conv.state == "START"
    assert conv.pending_booking is None
    _assert_single_policy(out)


@pytest.mark.parametrize(
    "message",
    [
        "ახლა ბავშვისთვის რა გაქვთ?",
        "ბანაკის ნაცვლად რას მთავაზობთ?",
        "ახლა რომელ პროგრამაზე შეიძლება ბავშვის ჩართვა?",
        "სხვა საბავშვო პროგრამა გაქვთ?",
    ],
)
def test_live_current_offering_discovery_uses_sunday_school_pending_owner(message):
    out, conv = _reply(message, f"live-offering-{abs(hash(message))}")

    assert "საკვირაო სკოლ" in out
    assert parent_flow._camp_price_value() not in out
    assert CURRENT_CLOSED not in out
    assert FUTURE_PENDING not in out
    _assert_no_sales_entry(out)
    assert "14-20" not in out
    assert "14–20" not in out
    assert "კაჭრეთ" not in out
    assert conv.pending_booking is None


def test_live_router_fallback_uses_same_closed_policy_for_current_details():
    conv = _conversation("live-router")

    dates = parent_turn_router._response_for_intent(
        INTENT_DATES_QUESTION,
        conv,
        conv.lead,
        "ბანაკის ნაკადები როდის არის?",
    )
    location = parent_turn_router._response_for_intent(
        INTENT_LOCATION_QUESTION,
        conv,
        conv.lead,
        "ბანაკი სად ტარდება?",
    )

    assert dates == CURRENT_CLOSED
    assert location == CURRENT_CLOSED


def test_live_parent_tool_keeps_price_but_limits_current_facts():
    conv = _conversation("live-tool")
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
        "message": CURRENT_CLOSED,
    }