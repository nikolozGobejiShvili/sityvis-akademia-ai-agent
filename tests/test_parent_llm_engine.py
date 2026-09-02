"""P3-C SAFE — regression tests for the PARENT LLM engine.

Covers:

  * Feature-flag gating (off → legacy flow; on → engine first; engine
    fail/empty → legacy flow).
  * Tool executor invariants:
      - book_consultation requires name + phone + datetime + child_age,
      - age outside [9, 17] is rejected as not_eligible,
      - invalid phone is rejected,
      - calendar failure does not produce a fake confirmation,
      - successful booking sets lead.calendly_booked + state DONE.
  * request_manager_callback never notifies without a valid phone.
  * save_lead_info never writes Sheets / never notifies.
  * Conversation history is forwarded to the LLM.
  * Tool loop is capped at MAX_TOOL_ITERATIONS.
  * Existing P0/P1/P2 tests are NOT affected (covered by running the
    pytest suite alongside this file — no need to assert here).

External services are fully mocked. Tests must pass with no network.
"""

from __future__ import annotations

import dataclasses
import json
from types import SimpleNamespace
from typing import Any

import pytest

import app.config as config_module
from app.agent.tools import parent_tool_executor
from app.agent.tools.parent_tool_executor import (
    ParentToolExecutor,
    manager_notified_for_conversation,
)
from app.agent.tools.parent_tools import (
    TOOL_BOOK_CONSULTATION,
    TOOL_GET_AVAILABLE_SLOTS,
    TOOL_GET_CAMP_INFO,
    TOOL_REQUEST_MANAGER_CALLBACK,
    TOOL_SAVE_LEAD_INFO,
)
from app.flows import parent_flow, parent_turn_router
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import conversation_service
from app.services.session_key_service import conversation_cache_key


# -- fixtures --------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_module_state():
    conversation_service.conversations.clear()
    parent_turn_router.manager_offer_shown.clear()
    parent_flow.available_slots.clear()
    parent_flow.ask_name_retries.clear()
    parent_flow.invalid_phone_retries.clear()
    parent_flow.slots_shown_for_state.clear()
    parent_tool_executor.reset_state()
    yield
    conversation_service.conversations.clear()
    parent_turn_router.manager_offer_shown.clear()
    parent_flow.available_slots.clear()
    parent_flow.ask_name_retries.clear()
    parent_flow.invalid_phone_retries.clear()
    parent_flow.slots_shown_for_state.clear()
    parent_tool_executor.reset_state()


def _swap_engine_flag(monkeypatch, value: bool) -> None:
    """Swap parent_flow's reference to `settings` for a copy with the
    USE_PARENT_LLM_ENGINE flag flipped. The Settings dataclass is frozen
    (intentionally — production config is immutable), so we can't mutate
    the field in place; ``dataclasses.replace`` produces a new instance
    with one field overridden and we patch that into the module."""
    swapped = dataclasses.replace(
        config_module.settings, USE_PARENT_LLM_ENGINE=value,
    )
    monkeypatch.setattr(parent_flow, "settings", swapped)


@pytest.fixture
def enable_engine(monkeypatch):
    _swap_engine_flag(monkeypatch, True)


@pytest.fixture
def disable_engine(monkeypatch):
    _swap_engine_flag(monkeypatch, False)


@pytest.fixture
def camp_registration_open(monkeypatch):
    monkeypatch.setattr(
        "app.services.admin_config_service.get_camp_registration_status",
        lambda: "open",
    )


@pytest.fixture
def fresh_conversation():
    conv = Conversation(sender_id="sender_p3c", platform="instagram")
    # Pre-seed an assistant turn so the parent-greeting static welcome
    # bypass (only fires on the bot's very first reply at state=START)
    # doesn't short-circuit engine/legacy routing in the bulk of these
    # tests. The PATCH 8 / parent-greeting tests build their own
    # Conversation without this seed when they need a truly fresh one.
    conv.history.append({"role": "assistant", "content": "_test_prior_welcome"})
    return conv


# -- helpers ---------------------------------------------------------------


def _mock_book_slot_ok(**kwargs):
    """Mock for `calendar_service.book_slot` that mirrors the real
    contract: returns True AND stamps a fake event_id onto the lead.

    Live QA Bug Fix Patch (2026-06-04) — the executor's success check
    now requires `lead.calendar_event_id` to be non-empty, so the
    historic naive `lambda **kwargs: True` no longer represents a
    real success. Every test that needs a successful Calendar write
    routes through this helper instead.
    """
    lead = kwargs.get("lead")
    if lead is not None:
        try:
            lead.calendar_event_id = "evt_mock_test_id"
        except Exception:
            pass
    return True


def _mock_book_slot_capture(captured: list):
    """Factory: like ``_mock_book_slot_ok`` but also appends the call
    kwargs to ``captured`` so the test can assert what was sent."""

    def fn(**kwargs):
        captured.append(kwargs)
        lead = kwargs.get("lead")
        if lead is not None:
            try:
                lead.calendar_event_id = "evt_mock_test_id"
            except Exception:
                pass
        return True

    return fn


def _mk_response(*, content: str = "", tool_calls: list[dict[str, Any]] | None = None) -> Any:
    """Build a minimal duck-typed object that matches what the engine
    reads from an OpenAI ``chat.completions.create`` response."""

    tc_objs: list[Any] = []
    for tc in tool_calls or []:
        tc_objs.append(SimpleNamespace(
            id=tc["id"],
            function=SimpleNamespace(
                name=tc["name"],
                arguments=tc.get("arguments", "{}"),
            ),
        ))
    msg = SimpleNamespace(
        content=content or None,
        tool_calls=tc_objs or None,
    )
    choice = SimpleNamespace(message=msg)
    return SimpleNamespace(choices=[choice])


# =========================================================================
# 1 — Feature flag off → legacy flow runs
# =========================================================================


def test_flag_off_routes_to_legacy_flow(disable_engine, monkeypatch, fresh_conversation, camp_registration_open):
    monkeypatch.setattr(parent_flow, "_handle_impl", lambda c, m: "LEGACY_OK")
    called = {"engine": 0}

    def _engine(**kwargs):
        called["engine"] += 1
        return "ENGINE_OK"

    monkeypatch.setattr(
        "app.agent.llm.parent_llm_engine.run_parent_llm_turn", _engine,
    )

    # PATCH 8 — bare "გამარჯობა" now returns the static UNCLEAR_ROUTING
    # menu before either engine or legacy runs. Use an intent-bearing
    # message so the flag-routing assertion still measures the right
    # thing.
    out = parent_flow.handle(fresh_conversation, "ბანაკი მაინტერესებს")

    assert out == "LEGACY_OK"
    assert called["engine"] == 0


# =========================================================================
# 2 — Feature flag on → engine response is returned
# =========================================================================


def test_flag_on_uses_engine_response(enable_engine, monkeypatch, fresh_conversation, camp_registration_open):
    def _engine(**kwargs):
        return "ENGINE_REPLY"

    monkeypatch.setattr(
        "app.agent.llm.parent_llm_engine.run_parent_llm_turn", _engine,
    )
    # Defensively block the legacy fallback from being exercised.
    monkeypatch.setattr(parent_flow, "_handle_impl", lambda c, m: pytest.fail("legacy should not run"))

    out = parent_flow.handle(fresh_conversation, "ბანაკი მაინტერესებს")
    assert out == "ENGINE_REPLY"


# =========================================================================
# 3 — Engine exception → legacy fallback
# =========================================================================


def test_engine_exception_falls_back(enable_engine, monkeypatch, fresh_conversation, camp_registration_open):
    def _boom(**kwargs):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(
        "app.agent.llm.parent_llm_engine.run_parent_llm_turn", _boom,
    )
    monkeypatch.setattr(parent_flow, "_handle_impl", lambda c, m: "LEGACY_FALLBACK")

    out = parent_flow.handle(fresh_conversation, "ბანაკი მაინტერესებს")
    assert out == "LEGACY_FALLBACK"


# =========================================================================
# 4 — Empty engine response → legacy fallback
# =========================================================================


def test_engine_empty_response_falls_back(enable_engine, monkeypatch, fresh_conversation, camp_registration_open):
    monkeypatch.setattr(
        "app.agent.llm.parent_llm_engine.run_parent_llm_turn",
        lambda **kwargs: "",
    )
    monkeypatch.setattr(parent_flow, "_handle_impl", lambda c, m: "LEGACY_FALLBACK")

    out = parent_flow.handle(fresh_conversation, "ბანაკი მაინტერესებს")
    assert out == "LEGACY_FALLBACK"


# =========================================================================
# 5 — Intent-bearing first message: LLM returns natural welcome, no tools
# =========================================================================


def test_greeting_returns_natural_welcome(enable_engine, monkeypatch, fresh_conversation, camp_registration_open):
    from app.services import openai_service

    welcome = "გასაგებია. ბანაკის შესახებ რას გაინტერესებთ?"
    monkeypatch.setattr(
        openai_service, "chat_with_tools",
        lambda **kwargs: _mk_response(content=welcome),
    )
    # No profile fetch.
    from app.services import messenger_service
    monkeypatch.setattr(
        messenger_service, "get_user_profile", lambda sid, plat: {},
    )

    # PATCH 8 — bare "გამარჯობა" gets static menu. Use an intent-
    # bearing message so the engine actually answers and we can assert
    # the LLM-generated reply passes through.
    out = parent_flow.handle(fresh_conversation, "ბანაკი მაინტერესებს")
    assert out == welcome
    assert fresh_conversation.lead is not None
    assert fresh_conversation.lead.calendly_booked is False


# =========================================================================
# 6 — Price question: LLM calls get_camp_info("price") → returns price
# =========================================================================


def test_price_question_invokes_camp_info(enable_engine, monkeypatch, fresh_conversation, camp_registration_open):
    from app.services import messenger_service, openai_service

    monkeypatch.setattr(
        messenger_service, "get_user_profile", lambda sid, plat: {},
    )

    call_count = {"n": 0}

    def _chat(**kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _mk_response(tool_calls=[{
                "id": "call_1",
                "name": TOOL_GET_CAMP_INFO,
                "arguments": json.dumps({"topic": "price"}),
            }])
        return _mk_response(content="ბანაკის ფასი 2150 ლარია — სრული პაკეტი.")

    monkeypatch.setattr(openai_service, "chat_with_tools", _chat)

    out = parent_flow.handle(fresh_conversation, "ფასი?")
    assert "2150" in out
    assert fresh_conversation.lead.calendly_booked is False


# =========================================================================
# 7 — Age out of range: book_consultation with child_age=7 → not_eligible
# =========================================================================


def test_age_out_of_range_blocks_booking(enable_engine, monkeypatch, fresh_conversation):
    from app.services import calendar_service, messenger_service, openai_service

    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    # Even if Calendar would have been called, do not let it succeed.
    monkeypatch.setattr(calendar_service, "book_slot", lambda **kwargs: pytest.fail("book_slot must not be called"))
    monkeypatch.setattr(
        calendar_service, "check_slot_available", lambda dt: pytest.fail("check_slot_available must not be called"),
    )

    call_count = {"n": 0}

    def _chat(**kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _mk_response(tool_calls=[{
                "id": "b1",
                "name": TOOL_BOOK_CONSULTATION,
                "arguments": json.dumps({
                    "name": "ნიკოლოზი",
                    "phone": "599123456",
                    "datetime_iso": "2030-06-03T12:00:00+04:00",
                    "child_age": "7",
                    "user_confirmed_datetime": True,
                }),
            }])
        return _mk_response(content="ბანაკი 9-17 წლის მოზარდებისთვისაა.")

    monkeypatch.setattr(openai_service, "chat_with_tools", _chat)

    out = parent_flow.handle(fresh_conversation, "ჩემი შვილი 7 წლისაა, ჩაწერეთ")
    assert "9" in out and "17" in out
    assert fresh_conversation.lead.calendly_booked is False


# =========================================================================
# 8 — Missing child_age blocks booking (executor-level)
# =========================================================================


def test_book_without_child_age_returns_missing_child_age(fresh_conversation, camp_registration_open):
    lead = Lead(sender_id="sender_p3c", platform="instagram", segment="PARENT")
    fresh_conversation.lead = lead
    executor = ParentToolExecutor(
        conversation=fresh_conversation,
        lead=lead,
        sender_id="sender_p3c",
        platform="instagram",
    )

    result = executor.execute(TOOL_BOOK_CONSULTATION, {
        "name": "ნიკოლოზი",
        "phone": "599123456",
        "datetime_iso": "2030-06-03T12:00:00+04:00",
        "user_confirmed_datetime": True,
    })
    assert result["success"] is False
    assert result["reason"] == "missing_child_age"
    assert lead.calendly_booked is False


# =========================================================================
# 9 — Invalid phone blocks booking (executor-level)
# =========================================================================


def test_book_with_invalid_phone_returns_invalid_phone(fresh_conversation, camp_registration_open):
    lead = Lead(sender_id="sender_p3c", platform="instagram", segment="PARENT")
    fresh_conversation.lead = lead
    executor = ParentToolExecutor(
        conversation=fresh_conversation,
        lead=lead,
        sender_id="sender_p3c",
        platform="instagram",
    )

    result = executor.execute(TOOL_BOOK_CONSULTATION, {
        "name": "ნიკოლოზი",
        "phone": "123",
        "datetime_iso": "2030-06-03T12:00:00+04:00",
        "child_age": "14",
        "user_confirmed_datetime": True,
    })
    assert result["success"] is False
    assert result["reason"] == "invalid_phone"
    assert lead.calendly_booked is False


# =========================================================================
# 10 — Calendar failure blocks fake confirmation
# =========================================================================


def test_calendar_failure_blocks_fake_confirmation(
    enable_engine, monkeypatch, fresh_conversation,
):
    from app.services import calendar_service, messenger_service, openai_service

    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    monkeypatch.setattr(calendar_service, "check_slot_available", lambda dt: False)
    monkeypatch.setattr(calendar_service, "book_slot", lambda **kwargs: False)

    call_count = {"n": 0}

    def _chat(**kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _mk_response(tool_calls=[{
                "id": "b1",
                "name": TOOL_BOOK_CONSULTATION,
                "arguments": json.dumps({
                    "name": "ნიკოლოზი",
                    "phone": "599123456",
                    "datetime_iso": "2030-06-03T12:00:00+04:00",
                    "child_age": "14",
                    "user_confirmed_datetime": True,
                }),
            }])
        # LLM tries to fake-confirm despite the tool failure.
        return _mk_response(content="დაგაჯავშნეთ წარმატებით, მადლობა.")

    monkeypatch.setattr(openai_service, "chat_with_tools", _chat)

    out = parent_flow.handle(fresh_conversation, "ჩამწერე")
    # Guard strips the fake confirmation and substitutes the safe fallback.
    assert "დაგაჯავშნე" not in out
    assert fresh_conversation.lead.calendly_booked is False


# =========================================================================
# 11 — Booking success: lead.calendly_booked + state DONE
# =========================================================================


def test_booking_success_updates_lead_and_state(
    enable_engine, monkeypatch, fresh_conversation, camp_registration_open,):
    from app.services import (
        calendar_service,
        messenger_service,
        notification_service,
        openai_service,
        sheets_service,
    )

    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    monkeypatch.setattr(calendar_service, "check_slot_available", lambda dt: True)
    monkeypatch.setattr(calendar_service, "book_slot", _mock_book_slot_ok)

    sheets_calls: list[Any] = []
    notify_calls: list[Any] = []
    monkeypatch.setattr(
        sheets_service, "create_lead",
        lambda lead: sheets_calls.append(lead) or True,
    )
    monkeypatch.setattr(
        notification_service, "send_manager_notification",
        lambda lead, summary: notify_calls.append((lead, summary)) or True,
    )
    monkeypatch.setattr(openai_service, "generate_summary", lambda h: "summary")

    call_count = {"n": 0}

    def _chat(**kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _mk_response(tool_calls=[{
                "id": "b1",
                "name": TOOL_BOOK_CONSULTATION,
                "arguments": json.dumps({
                    "name": "ნიკოლოზი",
                    "phone": "599999733",
                    "datetime_iso": "2030-06-03T12:00:00+04:00",
                    "child_age": "14",
                    "user_confirmed_datetime": True,
                }),
            }])
        return _mk_response(content="დაჯავშნილია 1 ივნისი 12:00.")

    monkeypatch.setattr(openai_service, "chat_with_tools", _chat)

    out = parent_flow.handle(fresh_conversation, "ჩამწერე 1 ივნისს 12:00")
    assert fresh_conversation.lead.calendly_booked is True
    assert fresh_conversation.state == "DONE"
    assert sheets_calls, "Sheets row should have been attempted"
    assert notify_calls, "Manager notification should have fired"
    # Guard passes through the legitimate confirmation.
    assert out.strip() != ""


# =========================================================================
# 12 — Manager request without phone → no notification, asks for phone
# =========================================================================


def test_manager_request_without_phone_does_not_notify(
    enable_engine, monkeypatch, fresh_conversation,
):
    from app.services import (
        messenger_service,
        notification_service,
        openai_service,
        sheets_service,
    )

    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    notified: list[Any] = []
    monkeypatch.setattr(
        notification_service, "send_manager_notification",
        lambda lead, summary: notified.append(True) or True,
    )
    sheets_calls: list[Any] = []
    monkeypatch.setattr(
        sheets_service, "create_lead",
        lambda lead: sheets_calls.append(True) or True,
    )

    call_count = {"n": 0}

    def _chat(**kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _mk_response(tool_calls=[{
                "id": "m1",
                "name": TOOL_REQUEST_MANAGER_CALLBACK,
                "arguments": json.dumps({"notes": "user wants human"}),
            }])
        return _mk_response(content="გთხოვთ მომწეროთ თქვენი ნომერი.")

    monkeypatch.setattr(openai_service, "chat_with_tools", _chat)

    out = parent_flow.handle(fresh_conversation, "მინდა მენეჯერი")
    assert notified == []
    assert "ნომერ" in out


# =========================================================================
# 13 — Manager request with phone → Sheets save + notification
# =========================================================================


def test_manager_request_with_phone_notifies(
    enable_engine, monkeypatch, fresh_conversation,
):
    from app.services import (
        messenger_service,
        notification_service,
        openai_service,
        sheets_service,
    )

    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    notified: list[Any] = []
    sheets_calls: list[Any] = []
    monkeypatch.setattr(
        notification_service, "send_manager_notification",
        lambda lead, summary: notified.append(lead) or True,
    )
    monkeypatch.setattr(
        sheets_service, "create_lead",
        lambda lead: sheets_calls.append(lead) or True,
    )
    monkeypatch.setattr(openai_service, "generate_summary", lambda h: "summary")

    call_count = {"n": 0}

    def _chat(**kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _mk_response(tool_calls=[{
                "id": "m1",
                "name": TOOL_REQUEST_MANAGER_CALLBACK,
                "arguments": json.dumps({
                    "name": "ნიკოლოზი",
                    "phone": "599999733",
                }),
            }])
        return _mk_response(content="მენეჯერი დაგიკავშირდებათ უმოკლეს დროში.")

    monkeypatch.setattr(openai_service, "chat_with_tools", _chat)

    out = parent_flow.handle(fresh_conversation, "მენეჯერი დარეკოს")
    assert len(notified) == 1
    assert len(sheets_calls) == 1
    assert "მენეჯერი" in out


# =========================================================================
# 14 — save_lead_info DOES NOT touch Sheets / notification
# =========================================================================


def test_save_lead_info_does_not_persist(monkeypatch, fresh_conversation):
    from app.services import notification_service, sheets_service

    sheets_calls: list[Any] = []
    notified: list[Any] = []
    monkeypatch.setattr(
        sheets_service, "create_lead",
        lambda lead: sheets_calls.append(lead) or True,
    )
    monkeypatch.setattr(
        notification_service, "send_manager_notification",
        lambda lead, summary: notified.append(True) or True,
    )

    lead = Lead(sender_id="sender_p3c", platform="instagram", segment="PARENT")
    fresh_conversation.lead = lead
    executor = ParentToolExecutor(
        conversation=fresh_conversation,
        lead=lead,
        sender_id="sender_p3c",
        platform="instagram",
    )

    result = executor.execute(TOOL_SAVE_LEAD_INFO, {
        "name": "ნიკოლოზი",
        "phone": "599999733",
        "child_age": "14",
        "challenge": "ეკრანი",
    })

    assert result["success"] is True
    assert set(result["saved_fields"]) >= {"name", "phone", "child_age", "challenge"}
    assert lead.name == "ნიკოლოზი"
    assert lead.phone == "599999733"
    assert lead.child_age == "14"
    assert sheets_calls == []
    assert notified == []


# =========================================================================
# 15 — "მადლობა არ მინდა" closes politely, no booking / no notification
# =========================================================================


def test_decline_does_not_book_or_notify(
    enable_engine, monkeypatch, fresh_conversation,
):
    from app.services import (
        calendar_service,
        messenger_service,
        notification_service,
        openai_service,
        sheets_service,
    )

    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    monkeypatch.setattr(
        calendar_service, "book_slot",
        lambda **kwargs: pytest.fail("book_slot must not run"),
    )
    monkeypatch.setattr(
        sheets_service, "create_lead",
        lambda lead: pytest.fail("create_lead must not run"),
    )
    monkeypatch.setattr(
        notification_service, "send_manager_notification",
        lambda lead, summary: pytest.fail("notification must not run"),
    )

    monkeypatch.setattr(
        openai_service, "chat_with_tools",
        lambda **kwargs: _mk_response(content="გასაგებია, კარგი დღე გისურვებთ."),
    )

    out = parent_flow.handle(fresh_conversation, "მადლობა არ მინდა")
    assert out
    assert fresh_conversation.lead.calendly_booked is False


# =========================================================================
# 16 — Conversation history is forwarded to chat_with_tools
# =========================================================================



def test_history_is_forwarded(enable_engine, monkeypatch, fresh_conversation):
    from app.services import messenger_service, openai_service

    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    fresh_conversation.history = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hello, what can I clarify?"},
    ]

    seen: list[list[dict]] = []

    def _chat(**kwargs):
        seen.append(kwargs.get("messages") or [])
        return _mk_response(content="I can answer that.")

    monkeypatch.setattr(openai_service, "chat_with_tools", _chat)

    parent_flow.handle(fresh_conversation, "more details please")

    assert seen, "chat_with_tools should have been called at least once"
    messages = seen[0]
    user_contents = [m.get("content") for m in messages if m.get("role") == "user"]
    assistant_contents = [m.get("content") for m in messages if m.get("role") == "assistant"]
    assert "hello" in user_contents
    assert any("hello" in (c or "") for c in assistant_contents)
    # Current user message also present on an LLM-owned path.
    assert "more details please" in user_contents


# =========================================================================
# 17 ? Tool loop max iterations
# =========================================================================


def test_tool_loop_caps_iterations(enable_engine, monkeypatch, fresh_conversation):
    from app.services import messenger_service, openai_service

    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})

    call_count = {"n": 0}

    def _chat(**kwargs):
        call_count["n"] += 1
        return _mk_response(tool_calls=[{
            "id": f"call_{call_count['n']}",
            "name": TOOL_GET_CAMP_INFO,
            "arguments": json.dumps({"topic": "all"}),
        }])

    monkeypatch.setattr(openai_service, "chat_with_tools", _chat)
    monkeypatch.setattr(parent_flow, "_handle_impl", lambda c, m: "FALLBACK_OK")

    out = parent_flow.handle(fresh_conversation, "more details please")
    # After the cap, engine returns "" -> legacy fallback runs.
    assert out == "FALLBACK_OK"
    # Engine should have called the LLM exactly MAX_TOOL_ITERATIONS times.
    from app.agent.llm.parent_llm_engine import MAX_TOOL_ITERATIONS
    assert call_count["n"] == MAX_TOOL_ITERATIONS

def test_executor_unknown_tool(fresh_conversation):
    lead = Lead(sender_id="sender_p3c", platform="instagram", segment="PARENT")
    fresh_conversation.lead = lead
    executor = ParentToolExecutor(
        conversation=fresh_conversation,
        lead=lead,
        sender_id="sender_p3c",
        platform="instagram",
    )
    result = executor.execute("not_a_real_tool", {})
    assert result["success"] is False
    assert result["reason"] == "unknown_tool"


# =========================================================================
# 19 — get_camp_info("price") returns the YAML price
# =========================================================================


def test_get_camp_info_price(fresh_conversation):
    lead = Lead(sender_id="sender_p3c", platform="instagram", segment="PARENT")
    fresh_conversation.lead = lead
    executor = ParentToolExecutor(
        conversation=fresh_conversation,
        lead=lead,
        sender_id="sender_p3c",
        platform="instagram",
    )
    # This runs against the shipped admin config, where the camp's registration
    # is CLOSED — so what it actually pinned was the „price is exempt from the
    # closed-camp limit" rule, not the price payload. That exemption is gone
    # (2026-08-04): a live parent asking Disneyland's price was handed the
    # closed camp's 2150. The open-camp payload shape is pinned by the tests
    # that explicitly open registration.
    result = executor.execute(TOOL_GET_CAMP_INFO, {"topic": "price"})
    assert result["success"] is False
    assert result["reason"] == "camp_public_info_limited"
    assert "2150" not in str(result)


# =========================================================================
# 20 — Manager notification doesn't double-fire on the same conversation
# =========================================================================


def test_manager_notification_not_double_fired(monkeypatch, fresh_conversation):
    from app.services import notification_service, openai_service, sheets_service

    notified: list[Any] = []
    monkeypatch.setattr(
        notification_service, "send_manager_notification",
        lambda lead, summary: notified.append(True) or True,
    )
    monkeypatch.setattr(sheets_service, "create_lead", lambda lead: True)
    monkeypatch.setattr(openai_service, "generate_summary", lambda h: "x")

    lead = Lead(
        sender_id="sender_p3c", platform="instagram", segment="PARENT",
        name="ნიკოლოზი", phone="599999733",
    )
    fresh_conversation.lead = lead
    executor = ParentToolExecutor(
        conversation=fresh_conversation,
        lead=lead,
        sender_id="sender_p3c",
        platform="instagram",
    )

    first = executor.execute(TOOL_REQUEST_MANAGER_CALLBACK, {})
    second = executor.execute(TOOL_REQUEST_MANAGER_CALLBACK, {})
    assert first["success"] is True
    assert first["manager_notified"] is True
    assert second["success"] is True
    assert second["manager_notified"] is False
    assert len(notified) == 1


# =========================================================================
# 21 — get_available_slots returns formatted slots
# =========================================================================


def test_get_available_slots(monkeypatch, fresh_conversation, camp_registration_open):
    from app.flows import parent_flow as pf

    monkeypatch.setattr(
        pf, "_load_available_slots",
        lambda sid: [
            {"date": "25 მაისი", "time": "12:00", "datetime_iso": "2030-05-25T12:00:00+04:00"},
            {"date": "26 მაისი", "time": "14:00", "datetime_iso": "2030-05-26T14:00:00+04:00"},
        ],
    )

    lead = Lead(sender_id="sender_p3c", platform="instagram", segment="PARENT")
    fresh_conversation.lead = lead
    executor = ParentToolExecutor(
        conversation=fresh_conversation,
        lead=lead,
        sender_id="sender_p3c",
        platform="instagram",
    )

    result = executor.execute(TOOL_GET_AVAILABLE_SLOTS, {})
    assert result["success"] is True
    assert len(result["slots"]) == 2
    assert result["slots"][0]["slot_id"] == 1
    assert "12:00" in result["slots"][0]["display"]


# =========================================================================
# P3-C PATCH 1 — additional coverage
# =========================================================================


from app.agent.tools.parent_tools import (  # noqa: E402
    TOOL_MANAGE_CONSULTATION_BOOKING,
    TOOL_SWITCH_TO_ADULT_FLOW,
)


def _make_executor(conv: Conversation, lead: Lead | None = None) -> ParentToolExecutor:
    if lead is None:
        lead = Lead(
            sender_id=conv.sender_id, platform=conv.platform, segment="PARENT",
        )
    conv.lead = lead
    return ParentToolExecutor(
        conversation=conv, lead=lead,
        sender_id=conv.sender_id, platform=conv.platform,
    )


# -- PATCH 1.A — user_confirmed_datetime gate -----------------------------


def test_book_without_user_confirmed_returns_datetime_not_confirmed(
    monkeypatch, fresh_conversation, camp_registration_open,):
    """All required fields present, but the LLM did not set
    user_confirmed_datetime — booking is refused."""
    from app.services import calendar_service

    monkeypatch.setattr(
        calendar_service, "book_slot",
        lambda **kwargs: pytest.fail("book_slot must not be called"),
    )
    monkeypatch.setattr(
        calendar_service, "check_slot_available",
        lambda dt: pytest.fail("check_slot_available must not be called"),
    )

    executor = _make_executor(fresh_conversation)
    result = executor.execute(TOOL_BOOK_CONSULTATION, {
        "name": "ნიკოლოზი",
        "phone": "599999733",
        "datetime_iso": "2030-06-03T12:00:00+04:00",
        "child_age": "14",
        # user_confirmed_datetime is intentionally missing.
    })
    assert result["success"] is False
    assert result["reason"] == "datetime_not_confirmed"
    assert fresh_conversation.lead.calendly_booked is False


def test_book_with_user_confirmed_false_returns_datetime_not_confirmed(
    monkeypatch, fresh_conversation, camp_registration_open,):
    from app.services import calendar_service

    monkeypatch.setattr(
        calendar_service, "book_slot",
        lambda **kwargs: pytest.fail("book_slot must not be called"),
    )

    executor = _make_executor(fresh_conversation)
    result = executor.execute(TOOL_BOOK_CONSULTATION, {
        "name": "ნიკოლოზი",
        "phone": "599999733",
        "datetime_iso": "2030-06-03T12:00:00+04:00",
        "child_age": "14",
        "user_confirmed_datetime": False,
    })
    assert result["success"] is False
    assert result["reason"] == "datetime_not_confirmed"


def test_book_with_user_confirmed_true_can_succeed(monkeypatch, fresh_conversation, camp_registration_open):
    from app.services import (
        calendar_service,
        notification_service,
        openai_service,
        sheets_service,
    )

    monkeypatch.setattr(calendar_service, "check_slot_available", lambda dt: True)
    monkeypatch.setattr(calendar_service, "book_slot", _mock_book_slot_ok)
    monkeypatch.setattr(sheets_service, "create_lead", lambda lead: True)
    monkeypatch.setattr(
        notification_service, "send_manager_notification",
        lambda lead, summary: True,
    )
    monkeypatch.setattr(openai_service, "generate_summary", lambda h: "summary")

    executor = _make_executor(fresh_conversation)
    result = executor.execute(TOOL_BOOK_CONSULTATION, {
        "name": "ნიკოლოზი",
        "phone": "599999733",
        "datetime_iso": "2030-06-03T12:00:00+04:00",
        "child_age": "14",
        "user_confirmed_datetime": True,
    })
    assert result["success"] is True
    assert fresh_conversation.lead.calendly_booked is True


def test_engine_does_not_auto_book_after_phone_only(
    enable_engine, monkeypatch, fresh_conversation,
):
    """End-to-end: parent gives name/phone/age but no datetime. Engine
    must NOT book — should ask preferred time instead."""
    from app.services import (
        calendar_service,
        messenger_service,
        notification_service,
        openai_service,
        sheets_service,
    )

    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    monkeypatch.setattr(
        calendar_service, "book_slot",
        lambda **kwargs: pytest.fail("must not auto-book"),
    )
    monkeypatch.setattr(
        sheets_service, "create_lead",
        lambda lead: pytest.fail("must not write Sheets"),
    )
    monkeypatch.setattr(
        notification_service, "send_manager_notification",
        lambda lead, summary: pytest.fail("must not notify"),
    )

    call_count = {"n": 0}

    def _chat(**kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # LLM saves the lead fields but doesn't yet have a datetime
            # confirmed — the well-behaved path.
            return _mk_response(tool_calls=[{
                "id": "s1",
                "name": TOOL_SAVE_LEAD_INFO,
                "arguments": json.dumps({
                    "name": "ნიკოლოზი",
                    "phone": "599999733",
                    "child_age": "14",
                }),
            }])
        return _mk_response(
            content="რომელი დღე და საათი მოგწონთ კონსულტაციისთვის?",
        )

    monkeypatch.setattr(openai_service, "chat_with_tools", _chat)

    out = parent_flow.handle(
        fresh_conversation, "ნიკოლოზი 599999733, 14 წლის არის",
    )
    assert fresh_conversation.lead.calendly_booked is False
    assert "დრო" in out or "საათი" in out


# -- PATCH 1.B — registration vs consultation -----------------------------


def test_get_camp_info_registration_when_url_present(fresh_conversation, camp_registration_open):
    executor = _make_executor(fresh_conversation)
    result = executor.execute(TOOL_GET_CAMP_INFO, {"topic": "registration"})
    # Default YAML has a URL.
    assert result["success"] is True
    assert "registration_url" in result
    assert result["registration_url"].startswith("http")


def test_get_camp_info_registration_returns_missing_when_url_absent(
    monkeypatch, fresh_conversation, camp_registration_open,):
    """If knowledge YAML loses the registration_url, executor must NOT
    invent one — it returns registration_url_missing with phone.

    Config Unification Patch made ``admin_config_service.get_camp_facts``
    the primary source of truth, with ``camp_2026.yaml`` as fallback.
    The shipped ``data/admin_config/sections.yaml`` carries a real
    registration URL for the summer-camp section, so to genuinely
    exercise the "no URL anywhere" path this test stubs both layers:
    admin_config to return ``None`` (forces fallback), and
    ``load_knowledge`` to strip the URL.
    """
    from app.agent.services import knowledge_loader as kl
    from app.services import admin_config_service

    real_load = kl.load_knowledge

    def _patched(name):
        data = real_load(name)
        if name == "camp_2026":
            data = {"camp": {**data["camp"], "registration_url": ""}}
        return data

    monkeypatch.setattr(kl, "load_knowledge", _patched)
    # Tool executor imports load_knowledge through its module — patch there too.
    monkeypatch.setattr(
        "app.agent.tools.parent_tool_executor.load_knowledge", _patched,
    )
    # Force admin-config layer to defer to the fallback so the patched
    # load_knowledge call above is the only registration_url source.
    monkeypatch.setattr(
        admin_config_service, "get_camp_facts", lambda: None,
    )

    executor = _make_executor(fresh_conversation)
    result = executor.execute(TOOL_GET_CAMP_INFO, {"topic": "registration"})
    assert result["success"] is False
    assert result["reason"] == "registration_url_missing"
    assert result.get("phone")


# -- PATCH 1.C — manage_consultation_booking ------------------------------


def test_manage_cancel_without_active_booking(fresh_conversation):
    executor = _make_executor(fresh_conversation)
    result = executor.execute(TOOL_MANAGE_CONSULTATION_BOOKING, {"action": "cancel"})
    assert result["success"] is False
    assert result["reason"] == "no_active_booking"
    assert result.get("manager_handoff_required") is True


def test_manage_cancel_missing_event_id_handoff(monkeypatch, fresh_conversation):
    """Lead has booked_datetime_iso (older booking, no event_id stored).
    Cancel must NOT claim success — manager handoff fires."""
    from app.services import (
        calendar_service,
        notification_service,
        sheets_service,
    )

    lead = Lead(
        sender_id="sender_p3c", platform="instagram", segment="PARENT",
        name="ნიკოლოზი", phone="599999733",
        calendly_booked=True, booked_datetime_iso="2030-06-03T12:00:00+04:00",
        # calendar_event_id intentionally empty
    )
    notify_calls: list[Any] = []
    monkeypatch.setattr(
        calendar_service, "cancel_calendar_event",
        lambda eid: pytest.fail("cancel_calendar_event must not run without event_id"),
    )
    monkeypatch.setattr(
        notification_service, "send_manager_notification",
        lambda lead, summary: notify_calls.append(True) or True,
    )
    monkeypatch.setattr(sheets_service, "create_lead", lambda lead: True)

    executor = _make_executor(fresh_conversation, lead=lead)
    result = executor.execute(TOOL_MANAGE_CONSULTATION_BOOKING, {
        "action": "cancel",
    })
    assert result["success"] is False
    assert result["reason"] == "missing_event_id"
    assert result["manager_handoff_required"] is True
    # Manager was notified (phone is on the lead).
    assert notify_calls
    # Lead is NOT marked unbooked — backend can't confirm Calendar state.
    assert lead.calendly_booked is True


def test_manage_cancel_success_with_event_id(monkeypatch, fresh_conversation):
    from app.services import calendar_service, notification_service, sheets_service

    lead = Lead(
        sender_id="sender_p3c", platform="instagram", segment="PARENT",
        name="ნიკოლოზი", phone="599999733",
        calendly_booked=True,
        booked_datetime_iso="2030-06-03T12:00:00+04:00",
        calendar_event_id="evt_123",
        status="Booked",
    )
    cancel_calls: list[Any] = []
    monkeypatch.setattr(
        calendar_service, "cancel_calendar_event",
        lambda eid: cancel_calls.append(eid) or True,
    )
    monkeypatch.setattr(
        notification_service, "send_manager_notification",
        lambda lead, summary: True,
    )
    monkeypatch.setattr(sheets_service, "create_lead", lambda lead: True)

    executor = _make_executor(fresh_conversation, lead=lead)
    result = executor.execute(TOOL_MANAGE_CONSULTATION_BOOKING, {"action": "cancel"})
    assert result["success"] is True
    assert result["action"] == "cancel"
    assert cancel_calls == ["evt_123"]
    assert lead.calendly_booked is False
    assert lead.booked_datetime_iso == ""
    assert lead.calendar_event_id == ""
    assert lead.status == "Cancelled"


def test_manage_reschedule_without_event_id_handoff(monkeypatch, fresh_conversation, camp_registration_open):
    """Old event_id missing — reschedule must NOT silently double-book."""
    from app.services import calendar_service, notification_service, sheets_service

    lead = Lead(
        sender_id="sender_p3c", platform="instagram", segment="PARENT",
        name="ნიკოლოზი", phone="599999733",
        calendly_booked=True,
        booked_datetime_iso="2030-06-03T12:00:00+04:00",
    )
    monkeypatch.setattr(calendar_service, "check_slot_available", lambda dt: True)
    monkeypatch.setattr(
        calendar_service, "book_slot",
        lambda **kwargs: pytest.fail("must not double-book"),
    )
    monkeypatch.setattr(
        notification_service, "send_manager_notification",
        lambda lead, summary: True,
    )
    monkeypatch.setattr(sheets_service, "create_lead", lambda lead: True)

    executor = _make_executor(fresh_conversation, lead=lead)
    result = executor.execute(TOOL_MANAGE_CONSULTATION_BOOKING, {
        "action": "reschedule",
        "new_datetime_iso": "2030-06-04T11:00:00+04:00",
    })
    assert result["success"] is False
    assert result["reason"] == "missing_event_id"
    assert result["manager_handoff_required"] is True


def test_manage_reschedule_success(monkeypatch, fresh_conversation, camp_registration_open):
    from app.services import (
        calendar_service,
        notification_service,
        openai_service,
        sheets_service,
    )

    lead = Lead(
        sender_id="sender_p3c", platform="instagram", segment="PARENT",
        name="ნიკოლოზი", phone="599999733",
        calendly_booked=True,
        booked_datetime_iso="2030-06-03T12:00:00+04:00",
        calendar_event_id="evt_old",
    )
    cancel_calls: list[Any] = []
    book_calls: list[Any] = []

    monkeypatch.setattr(
        calendar_service, "cancel_calendar_event",
        lambda eid: cancel_calls.append(eid) or True,
    )
    monkeypatch.setattr(calendar_service, "check_slot_available", lambda dt: True)

    def _book_slot(**kwargs):
        book_calls.append(kwargs)
        # _book_selected_slot expects the calendar_event_id to land on
        # the lead — the real Calendar layer does this; here we mimic.
        kwargs["lead"].calendar_event_id = "evt_new"
        return True

    monkeypatch.setattr(calendar_service, "book_slot", _book_slot)
    monkeypatch.setattr(sheets_service, "create_lead", lambda lead: True)
    monkeypatch.setattr(
        notification_service, "send_manager_notification",
        lambda lead, summary: True,
    )
    monkeypatch.setattr(openai_service, "generate_summary", lambda h: "summary")

    executor = _make_executor(fresh_conversation, lead=lead)
    result = executor.execute(TOOL_MANAGE_CONSULTATION_BOOKING, {
        "action": "reschedule",
        "new_datetime_iso": "2030-06-04T11:00:00+04:00",
    })
    assert result["success"] is True
    assert result["action"] == "reschedule"
    assert cancel_calls == ["evt_old"]
    assert book_calls, "expected new booking attempt"
    assert lead.calendly_booked is True
    assert lead.calendar_event_id == "evt_new"


def test_engine_does_not_say_cancelled_on_handoff(
    enable_engine, monkeypatch, fresh_conversation,
):
    """End-to-end: LLM calls manage_consultation_booking, executor
    returns manager_handoff_required, LLM must not claim cancellation
    succeeded. We give the LLM a clean response and assert it doesn't
    contain ``გავაუქმე`` etc."""
    from app.services import (
        calendar_service,
        messenger_service,
        notification_service,
        openai_service,
        sheets_service,
    )

    fresh_conversation.lead = Lead(
        sender_id="sender_p3c", platform="instagram", segment="PARENT",
        name="ნიკოლოზი", phone="599999733",
        calendly_booked=True,
        booked_datetime_iso="2030-06-03T12:00:00+04:00",
    )
    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    monkeypatch.setattr(
        notification_service, "send_manager_notification",
        lambda lead, summary: True,
    )
    monkeypatch.setattr(sheets_service, "create_lead", lambda lead: True)
    monkeypatch.setattr(
        calendar_service, "cancel_calendar_event",
        lambda eid: pytest.fail("must not run without event_id"),
    )

    call_count = {"n": 0}

    def _chat(**kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _mk_response(tool_calls=[{
                "id": "c1",
                "name": TOOL_MANAGE_CONSULTATION_BOOKING,
                "arguments": json.dumps({"action": "cancel"}),
            }])
        return _mk_response(
            content="თქვენი მოთხოვნა გადავცეთ მენეჯერს, რომელიც დადასტურდება და დაგიკავშირდებათ.",
        )

    monkeypatch.setattr(openai_service, "chat_with_tools", _chat)

    out = parent_flow.handle(fresh_conversation, "გააუქმეთ ჯავშანი")
    assert "გავაუქმე" not in out
    assert "მენეჯერ" in out
    # Lead's booked status is preserved because backend couldn't verify.
    assert fresh_conversation.lead.calendly_booked is True


# -- PATCH 1.D — switch_to_adult_flow -------------------------------------


def test_switch_to_adult_flow_changes_segment(fresh_conversation):
    fresh_conversation.segment = "PARENT"
    executor = _make_executor(fresh_conversation)
    result = executor.execute(TOOL_SWITCH_TO_ADULT_FLOW, {
        "reason": "user said they are an adult",
    })
    assert result["success"] is True
    assert result["segment"] == "ADULT"
    assert fresh_conversation.segment == "ADULT"
    assert fresh_conversation.state == "START"


def test_engine_does_not_answer_camp_age_after_adult_switch(
    enable_engine, monkeypatch, fresh_conversation,
):
    from app.services import messenger_service, openai_service

    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})

    call_count = {"n": 0}

    def _chat(**kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _mk_response(tool_calls=[{
                "id": "a1",
                "name": TOOL_SWITCH_TO_ADULT_FLOW,
                "arguments": json.dumps({"reason": "adult event interest"}),
            }])
        return _mk_response(
            content=(
                "გასაგებია, ზრდასრულთა ღონისძიებებზე გადაგამისამართებთ — "
                "ერთ წუთში გავხსნი თქვენთვის სწორ მიმართულებას."
            ),
        )

    monkeypatch.setattr(openai_service, "chat_with_tools", _chat)

    out = parent_flow.handle(
        fresh_conversation, "მე ზრდასრული ვარ და ღონისძიებები მაინტერესებს",
    )
    assert "9-17" not in out
    assert "9–17" not in out
    assert "ბანაკ" not in out
    assert fresh_conversation.segment == "ADULT"


# -- PATCH 1.E — forbidden-phrase rewrite ---------------------------------


def test_sanitiser_rewrites_repeat_phone_phrase():
    from app.agent.llm.parent_llm_engine import sanitise_response_wording

    rewritten = sanitise_response_wording(
        "გაიმეორეთ, გთხოვთ, თქვენი ტელეფონის ნომერი",
    )
    assert "გაიმეორეთ" not in rewritten
    assert "მომწერეთ" in rewritten


def test_sanitiser_rewrites_robotic_closings():
    from app.agent.llm.parent_llm_engine import sanitise_response_wording

    cases = [
        ("ყოველთვის მზად ვარ, როცა დაგჭირდებათ.", "ყოველთვის მზად ვარ"),
        ("გთხოვთ დამიმტკიცეთ.", "დამიმტკიცეთ"),
        ("შეკვეთოთ დამატებითი კითხვები.", "შეკვეთოთ"),
        ("კიდევ რაიმეში დაგჭირდეთ დახმარება?", "კიდევ რაიმეში დაგჭირდეთ დახმარება"),
    ]
    for original, forbidden in cases:
        rewritten = sanitise_response_wording(original)
        assert forbidden not in rewritten, f"failed to rewrite: {original}"


def test_engine_response_does_not_contain_forbidden_phrases(
    enable_engine, monkeypatch, fresh_conversation,
):
    """End-to-end: even if the LLM emits a forbidden phrase, the engine
    rewrites it on the way out."""
    from app.services import messenger_service, openai_service

    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    monkeypatch.setattr(
        openai_service, "chat_with_tools",
        lambda **kwargs: _mk_response(
            content="გაიმეორეთ, გთხოვთ, თქვენი ტელეფონის ნომერი",
        ),
    )

    out = parent_flow.handle(fresh_conversation, "ნომერი არასწორი იყო")
    for forbidden in (
        "გაიმეორეთ",
        "შეკვეთოთ",
        "ყოველთვის მზად ვარ",
        "დამიმტკიცეთ",
        "კიდევ რაიმეში დაგჭირდეთ დახმარება",
    ):
        assert forbidden not in out, f"forbidden phrase leaked: {forbidden!r}"


# =========================================================================
# P3-C PATCH 2 — Georgian wording polish + CRM summary
# =========================================================================


def test_patch2_sanitiser_rewrites_payment_grammar():
    from app.agent.llm.parent_llm_engine import sanitise_response_wording

    rewritten = sanitise_response_wording(
        "გადანაწილება განვადებაში 6 თვემდე — TBC-ში."
    )
    assert "განვადებაში" not in rewritten
    assert "გადახდის გადანაწილება" in rewritten or "განვადებით" in rewritten


def test_patch2_sanitiser_rewrites_manager_callback_wording():
    from app.agent.llm.parent_llm_engine import sanitise_response_wording

    cases = (
        (
            "მენეჯერი დაგიკავშირდებათ რაც მალე იქნება შესაძლებელი.",
            "რაც მალე იქნება შესაძლებელი",
        ),
        (
            "მენეჯერი დაგიკავშირდებათ უმოკლეს დროში.",
            "უმოკლეს დროში",
        ),
        (
            "მენეჯერი დაგიკავშირდებათ შესაძლებლისთანავე.",
            "შესაძლებლისთანავე",
        ),
        ("მენეჯერის კავშირი ვერ შევძელი.", "მენეჯერის კავშირი"),
        ("მენეჯერს გადასცე ჩემი ნომერი.", "მენეჯერს გადასცე"),
        ("გთხოვთ მომწერეთ ნომერი.", "გთხოვთ მომწერეთ"),
    )
    for original, forbidden in cases:
        rewritten = sanitise_response_wording(original)
        assert forbidden not in rewritten, f"failed to rewrite: {original!r}"


def test_patch2_sanitiser_rewrites_location_and_age_typography():
    from app.agent.llm.parent_llm_engine import sanitise_response_wording

    rewritten = sanitise_response_wording(
        "ადგილი — ამბასადორი კაჭრეთი, ბანაკი 9-დან 17 წლამდე ბავშვებისთვის."
    )
    assert "ადგილი —" not in rewritten or "ლოკაცია — ამბასადორ კაჭრეთი" in rewritten
    assert "9-დან 17 წლამდე" not in rewritten
    assert "9–17 წლის" in rewritten


def test_patch2_engine_strips_payment_grammar_end_to_end(
    enable_engine, monkeypatch, fresh_conversation,
):
    from app.services import messenger_service, openai_service

    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    monkeypatch.setattr(
        openai_service, "chat_with_tools",
        lambda **kwargs: _mk_response(
            content=(
                "ბანაკის ფასი 2150 ლარია, გადანაწილება განვადებაში 6 თვემდე — "
                "TBC ან საქართველოს ბანკი."
            ),
        ),
    )

    out = parent_flow.handle(fresh_conversation, "ფასი?")
    assert "განვადებაში" not in out
    assert "2150" in out


def test_patch2_engine_strips_manager_callback_padding_end_to_end(
    enable_engine, monkeypatch, fresh_conversation,
):
    from app.services import messenger_service, openai_service

    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    monkeypatch.setattr(
        openai_service, "chat_with_tools",
        lambda **kwargs: _mk_response(
            content="მივიღე, მენეჯერი დაგიკავშირდებათ რაც მალე იქნება შესაძლებელი.",
        ),
    )

    out = parent_flow.handle(fresh_conversation, "595999733")
    assert "რაც მალე იქნება შესაძლებელი" not in out
    assert "მენეჯერი დაგიკავშირდებათ" in out


# -- PATCH 2.A — Georgian CRM summary ------------------------------------


def test_patch2_summary_md_has_georgian_only_instruction():
    """The on-disk summary prompt must explicitly require Georgian-only."""
    from app.agent.llm.prompt_loader import load_prompt, reset_cache

    reset_cache()
    text = load_prompt("summary")
    assert "ქართულად" in text
    assert (
        "არ გამოიყენო ინგლისური" in text
        or "ინგლისური" in text
    ), "summary.md should explicitly forbid English"


def test_patch2_generate_summary_sends_georgian_system_message(monkeypatch):
    """generate_summary must include a system message that forbids English."""
    from app.services import openai_service

    captured: dict[str, Any] = {}

    def _fake_chat(**kwargs):
        captured["messages"] = kwargs.get("messages") or []
        return "მოკლე ქართული რეზიუმე საუბრის შესახებ."

    monkeypatch.setattr(openai_service, "_chat_completion", _fake_chat)

    out = openai_service.generate_summary([
        {"role": "user", "content": "გამარჯობა"},
    ])
    assert out == "მოკლე ქართული რეზიუმე საუბრის შესახებ."
    assert captured.get("messages"), "should have called the chat layer"
    system_messages = [m for m in captured["messages"] if m.get("role") == "system"]
    assert system_messages, "generate_summary must pass a system message"
    sys_text = system_messages[0]["content"].lower()
    # Must mention Georgian (Georgian or transliterated).
    assert "ქართულ" in system_messages[0]["content"] or "georgian" in sys_text
    # Must forbid English.
    assert "english" in sys_text or "ინგლის" in system_messages[0]["content"]


def test_patch2_english_summary_replaced_with_georgian_fallback(monkeypatch):
    """If the LLM returns an English manager-summary phrase, the
    surfaced result must be the Georgian fallback — not the raw English."""
    from app.services import openai_service

    monkeypatch.setattr(
        openai_service, "_chat_completion",
        lambda **kwargs: (
            "Parent interested in camp for 8-year-old child, outside age range, "
            "requested manager callback."
        ),
    )

    out = openai_service.generate_summary([
        {"role": "user", "content": "x"},
    ])
    assert "Parent interested" not in out
    assert "outside age range" not in out
    assert "requested manager callback" not in out
    # Fallback is Georgian text.
    assert "მენეჯერ" in out or "მომხმარებელი" in out


def test_patch2_english_summary_fallback_byte_for_byte():
    from app.services import openai_service

    fallback = openai_service._georgian_summary_fallback()
    # The fallback must be Georgian.
    georgian_chars = sum(1 for ch in fallback if 0x10A0 <= ord(ch) <= 0x10FF)
    assert georgian_chars > 10
    # It must NOT contain English manager-summary patterns.
    lower = fallback.lower()
    for marker in (
        "parent interested",
        "outside age range",
        "requested manager callback",
        "wants consultation",
        "manager callback",
        "not eligible",
    ):
        assert marker not in lower


def test_patch2_clean_georgian_summary_passes_through(monkeypatch):
    """A clean Georgian summary from the model must NOT be replaced."""
    from app.services import openai_service

    clean = (
        "მშობელი დაინტერესებულია ბანაკით 14 წლის ბავშვისთვის. "
        "ითხოვა კონსულტაცია მენეჯერთან."
    )
    monkeypatch.setattr(
        openai_service, "_chat_completion", lambda **kwargs: clean,
    )
    out = openai_service.generate_summary([{"role": "user", "content": "x"}])
    assert out == clean


def test_patch2_english_detection_internal_error_does_not_crash(monkeypatch):
    """Detector exceptions must NOT block CRM writes — generate_summary
    must still return a usable string."""
    from app.services import openai_service

    monkeypatch.setattr(
        openai_service, "_chat_completion",
        lambda **kwargs: "Parent interested in camp",
    )

    def _bad_detector(text):
        raise RuntimeError("boom")

    monkeypatch.setattr(openai_service, "_looks_like_english_summary", _bad_detector)

    # Must not raise; the original LLM text is acceptable as last-ditch.
    out = openai_service.generate_summary([{"role": "user", "content": "x"}])
    assert isinstance(out, str)
    assert out  # non-empty


def test_patch2_executor_manager_handoff_sends_georgian_summary(
    monkeypatch, fresh_conversation,
):
    """When the executor hands off via request_manager_callback, the
    summary written to Sheets must be Georgian."""
    from app.services import notification_service, openai_service, sheets_service

    notifications: list[Any] = []
    sheets_rows: list[Any] = []

    def _create(lead):
        sheets_rows.append(lead.conversation_summary)
        return True

    def _notify(lead, summary):
        notifications.append(summary)
        return True

    monkeypatch.setattr(sheets_service, "create_lead", _create)
    monkeypatch.setattr(notification_service, "send_manager_notification", _notify)
    # The chat layer returns English — generate_summary must replace it.
    monkeypatch.setattr(
        openai_service, "_chat_completion",
        lambda **kwargs: "Parent interested in camp, wants consultation.",
    )

    lead = Lead(
        sender_id="sender_p3c", platform="instagram", segment="PARENT",
        name="ნიკოლოზი", phone="599999733",
    )
    fresh_conversation.lead = lead
    executor = ParentToolExecutor(
        conversation=fresh_conversation, lead=lead,
        sender_id="sender_p3c", platform="instagram",
    )
    result = executor.execute(TOOL_REQUEST_MANAGER_CALLBACK, {})
    assert result["success"] is True
    assert sheets_rows, "Sheets row must be written"
    assert notifications, "Manager must be notified"
    written = sheets_rows[0]
    notified = notifications[0]
    for english in (
        "Parent interested",
        "wants consultation",
        "outside age range",
        "requested manager callback",
    ):
        assert english not in written
        assert english not in notified


def test_patch2_executor_handoff_continues_when_summary_layer_raises(
    monkeypatch, fresh_conversation,
):
    """If generate_summary raises an unexpected exception, the manager
    handoff must STILL write Sheets and fire notification — using
    whatever Georgian fallback the executor has."""
    from app.services import notification_service, openai_service, sheets_service

    sheets_rows: list[Any] = []
    notifications: list[Any] = []
    monkeypatch.setattr(
        sheets_service, "create_lead",
        lambda lead: sheets_rows.append(lead.conversation_summary) or True,
    )
    monkeypatch.setattr(
        notification_service, "send_manager_notification",
        lambda lead, summary: notifications.append(summary) or True,
    )

    def _explode(history):
        raise RuntimeError("openai down")

    monkeypatch.setattr(openai_service, "generate_summary", _explode)

    lead = Lead(
        sender_id="sender_p3c", platform="instagram", segment="PARENT",
        name="ნიკოლოზი", phone="599999733",
    )
    fresh_conversation.lead = lead
    executor = ParentToolExecutor(
        conversation=fresh_conversation, lead=lead,
        sender_id="sender_p3c", platform="instagram",
    )
    result = executor.execute(TOOL_REQUEST_MANAGER_CALLBACK, {})
    assert result["success"] is True
    assert sheets_rows, "CRM write must not be blocked by summary failure"
    assert notifications, "Notification must not be blocked by summary failure"
    # Fallback must be Georgian.
    georgian_chars = sum(
        1 for ch in sheets_rows[0] if 0x10A0 <= ord(ch) <= 0x10FF
    )
    assert georgian_chars > 5


# =========================================================================
# P3-C PATCH 3 — audience-aware sales + follow-up readiness
# =========================================================================


def test_patch3_audience_segments_yaml_loads_with_required_keys():
    from app.agent.services.knowledge_loader import load_knowledge, reset_cache

    reset_cache()
    data = load_knowledge("audience_segments")
    assert "segments" in data and isinstance(data["segments"], dict)
    assert "micro_segments" in data and isinstance(data["micro_segments"], dict)
    # Each named segment must carry the rule-shaping fields the prompt
    # adapter relies on.
    for key in (
        "parent_development_concern",
        "teen_self_expression",
        "adult_cultural_evenings",
        "emigrant_parent",
    ):
        seg = data["segments"][key]
        assert seg.get("label")
        # Each label must be Georgian (contains Georgian-script chars).
        assert any(0x10A0 <= ord(ch) <= 0x10FF for ch in seg["label"])
        assert seg.get("message_angles")
    for key in ("premium_parent", "values_oriented_parent", "busy_parent"):
        micro = data["micro_segments"][key]
        assert micro.get("key_triggers")
        assert micro.get("message_angle")


def test_patch3_followup_strategy_yaml_loads_with_required_keys():
    from app.agent.services.knowledge_loader import load_knowledge, reset_cache

    reset_cache()
    data = load_knowledge("followup_strategy")
    assert "global_rules" in data
    assert "stages" in data
    assert data["global_rules"]["send_only_if_user_stopped"] is True
    for stage_key in ("first_24h", "second_3d", "third_7d"):
        stage = data["stages"][stage_key]
        assert stage.get("delay_hours")
        assert stage.get("goal")
        assert stage.get("message_template")
        # Template must be Georgian content.
        assert any(0x10A0 <= ord(ch) <= 0x10FF for ch in stage["message_template"])
    do_not = set(data["global_rules"]["do_not_follow_up_if"])
    assert {"booked", "declined", "manager_handoff_completed"} <= do_not


def test_patch3_engine_messages_contain_sales_context(
    enable_engine, monkeypatch, fresh_conversation, camp_registration_open,
):
    from app.services import messenger_service, openai_service

    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    seen: list[list[dict]] = []

    def _chat(**kwargs):
        seen.append(kwargs.get("messages") or [])
        return _mk_response(content="გასაგებია.")

    monkeypatch.setattr(openai_service, "chat_with_tools", _chat)
    parent_flow.handle(fresh_conversation, "ბანაკი მაინტერესებს")
    assert seen
    system_blocks = [m["content"] for m in seen[0] if m.get("role") == "system"]
    joined = "\n".join(system_blocks)
    # The compact sales context must be there.
    assert "Sales context" in joined
    # And it must talk about asking child age when unknown.
    assert "ბავშვის ასაკი" in joined


def test_patch3_engine_does_not_inject_raw_source_documents(
    enable_engine, monkeypatch, fresh_conversation,
):
    """The raw PDF / DOCX content must NEVER be passed to the model."""
    from app.services import messenger_service, openai_service

    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    seen: list[list[dict]] = []

    def _chat(**kwargs):
        seen.append(kwargs.get("messages") or [])
        return _mk_response(content="გასაგებია.")

    monkeypatch.setattr(openai_service, "chat_with_tools", _chat)
    parent_flow.handle(fresh_conversation, "more details please")
    assert seen
    full_prompt = " ".join(
        m.get("content") or "" for m in seen[0]
        if m.get("role") in {"system", "user"}
    )
    # Distinctive verbatim PDF phrases that must NEVER appear.
    forbidden = (
        "სამიზნე აუდიტორიის დეტალური ანალიზი",
        "ფარული სურვილი",  # PDF section header
        "ჰუკ-სათაურები",   # PDF heading
    )
    for phrase in forbidden:
        assert phrase not in full_prompt, (
            f"raw PDF content leaked into prompt: {phrase!r}"
        )
    # Distinctive verbatim DOCX phrases that must NEVER appear.
    docx_forbidden = (
        "ჩასაშენებელი follow up ლოგიკა",
        "FOLLOW-UP 1 - 24 საათში",
    )
    for phrase in docx_forbidden:
        assert phrase not in full_prompt, (
            f"raw DOCX content leaked into prompt: {phrase!r}"
        )
    # Cap on total prompt size — we should never approach the model's
    # context limit just on system blocks. 36 KB is generous (model
    # supports 128K tokens; this guard exists to catch accidental
    # large source-document injection, not to micro-manage every
    # sanitiser / policy rule addition). Raised 28 KB → 30 KB by the
    # Expired Booking Memory Fix patch; raised 30 KB → 32 KB by the
    # ADULT Live QA Polish Patch (2026-06-02) when the child-data
    # privacy-note rule + "რატო გჭირდება ასაკი?" handler paragraphs
    # were added; raised 32 KB → 34 KB by the Calendar Multi-Busy
    # Check + Reschedule Wording Patch (2026-06-04). Raised 34 KB →
    # 36 KB by the Booking Date Parse + Lead Field Separation Patch
    # (2026-06-04) which added the Georgian relative-date rule + the
    # PARENT-vs-ADULT field separation rule (~1.4 KB of curated
    # policy text). Raised 36 KB → 38 KB by the Live QA Bug Fix
    # Patch (2026-06-04) which added the verification-phrase rule +
    # the booking-success backend-enforcement rule + the
    # `calendar_booking_failed` / `verification_requested` reason
    # branches (~1.3 KB of curated policy text). Raised 38 KB → 40
    # KB by the Live QA Patch (2026-06-05) slot mismatch.
    # Raised 40 KB → 44 KB by the FULL Live QA Patch (2026-06-05
    # Session 2): ADULT→PARENT carryover rule + reschedule rule +
    # sibling-discount rule + new reason branches (slot_mismatch /
    # old_cancel_failed / old_booking_preserved) — ~2.7 KB of
    # curated policy text.
    # Raised 44 KB → 46 KB by Client Smoke Regression Patch
    # (2026-06-09): Booking Intent Flow CRITICAL block + Contact Info
    # CRITICAL block (phone+name order rule, name-reuse rule) — ~1.6 KB
    # of curated policy text fixing the booking flow ordering bug.
    # Raised 46 KB → 48 KB by Live Polish Patch (2026-06-09): კიმინდა
    # normalization, privacy wording rule, context-aware thank-you rule
    # — ~0.7 KB of curated wording policy.
    # Raised 48 KB -> 56 KB after route-decision/source-of-truth rules expanded
    # the curated system prompt. This still catches accidental raw source-document
    # injection while accepting the current canonical prompt size.
    # Raised 56 KB -> 57 KB (2026-09-02) by the „საკუთარი სიტყვის წესი" block —
    # ~0.5 KB of curated policy added after the agent gave the manager's number
    # and then, one turn later, told the parent that sharing it was outside its
    # competence. The guard's purpose is unchanged: a raw source document is
    # tens of KB, so it is still caught with room to spare.
    #
    # ⚠️ The curated prompt is now ~56 KB and this ceiling has been raised seven
    # times. Before adding the next rule, prefer replacing an existing one —
    # `docs/` already flags the un-probed "lost in the middle" risk for a prompt
    # this long, and a rule the model never reads is worse than no rule.
    assert len(full_prompt) < 57_000, (
        f"engine prompt too large: {len(full_prompt)} chars"
    )



def test_patch3_sales_context_uses_prior_price_interest_on_llm_path(
    enable_engine, monkeypatch, fresh_conversation, camp_registration_open,
):
    """A prior price question still shapes sales context on an LLM-owned turn."""
    from app.services import messenger_service, openai_service

    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    fresh_conversation.history.append({"role": "user", "content": "ფასი?"})
    fresh_conversation.history.append({
        "role": "assistant",
        "content": parent_flow._camp_price_direct_answer(),
    })
    seen: list[list[dict]] = []
    monkeypatch.setattr(
        openai_service, "chat_with_tools",
        lambda **kwargs: (seen.append(kwargs.get("messages") or []),
                          _mk_response(content="Got it."))[1],
    )
    parent_flow.handle(fresh_conversation, "more details please")
    assert seen
    joined = "\n".join(
        m["content"] for m in seen[0] if m.get("role") == "system"
    )
    assert "ფასი" in joined or "ღირებულება" in joined

def test_patch3_sales_context_for_ineligible_age(
    enable_engine, monkeypatch, fresh_conversation,
):
    from app.services import messenger_service, openai_service

    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    # Pre-populate the lead with an ineligible age so the engine sees it
    # without needing tool calls.
    fresh_conversation.lead = Lead(
        sender_id=fresh_conversation.sender_id, platform="instagram",
        segment="PARENT", child_age="7",
    )
    seen: list[list[dict]] = []
    monkeypatch.setattr(
        openai_service, "chat_with_tools",
        lambda **kwargs: (seen.append(kwargs.get("messages") or []),
                          _mk_response(content="ეს ბანაკი 9–17 წლისთვისაა."))[1],
    )
    parent_flow.handle(fresh_conversation, "კი მინდა დეტალები")
    joined = "\n".join(
        m["content"] for m in seen[0] if m.get("role") == "system"
    )
    # Sales context must remind the model not to offer booking.
    assert "დიაპაზონს არ ერგება" in joined or "მენეჯერთან" in joined


# -- PATCH 3.B — Conversation follow-up fields ----------------------------


def test_patch3_conversation_followup_fields_serialize_round_trip():
    import json as _json
    conv = Conversation(sender_id="abc", platform="instagram")
    conv.last_bot_message_at = "2030-06-03T12:00:00+04:00"
    conv.followup_stage = "first_24h"
    conv.followup_blocked_reason = "declined"
    conv.last_meaningful_interest = "price"
    conv.stopped_after = "will_think"

    data = conv.to_dict()
    # All five new fields must be present.
    for key in (
        "last_bot_message_at", "followup_stage",
        "followup_blocked_reason", "last_meaningful_interest",
        "stopped_after",
    ):
        assert key in data
    # JSON dump must succeed (no datetime/object leakage).
    serialised = _json.dumps(data, ensure_ascii=False)
    assert "2030-06-03T12:00:00+04:00" in serialised
    restored = Conversation.from_dict(_json.loads(serialised))
    assert restored.last_bot_message_at == "2030-06-03T12:00:00+04:00"
    assert restored.followup_stage == "first_24h"
    assert restored.followup_blocked_reason == "declined"
    assert restored.last_meaningful_interest == "price"
    assert restored.stopped_after == "will_think"


def test_patch3_conversation_followup_fields_default_to_empty_strings():
    conv = Conversation(sender_id="abc", platform="instagram")
    assert conv.last_bot_message_at == ""
    assert conv.followup_stage == ""
    assert conv.followup_blocked_reason == ""
    assert conv.last_meaningful_interest == ""
    assert conv.stopped_after == ""


def test_patch3_no_duplicate_user_message_timestamp_field():
    """`last_user_message_at` would duplicate the existing `last_activity`
    field. Audit must not introduce a parallel timestamp."""
    conv = Conversation(sender_id="abc", platform="instagram")
    assert not hasattr(conv, "last_user_message_at"), (
        "spec required reusing existing last_activity, not adding "
        "last_user_message_at"
    )


# -- PATCH 3.C — conversation_service marker capture ----------------------


def test_patch3_decline_sets_blocked_reason(monkeypatch):
    """When the user declines, the conversation_service records
    `followup_blocked_reason='declined'` *before* the response is
    generated, so the scheduler skips this lead."""
    from app.services import conversation_service, messenger_service, openai_service

    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    monkeypatch.setattr(
        openai_service, "detect_start_intent", lambda m: "GREETING",
    )

    # Make sure both engine paths return SOMETHING so the response
    # pipeline reaches the post-response markers — but engine flag is
    # already pinned off by the autouse fixture (conftest).
    conversation_service.process_message("sim-decline", "გამარჯობა", "instagram")
    conversation_service.process_message("sim-decline", "არა მადლობა", "instagram")
    conv = conversation_service.conversations["sim-decline"]
    assert conv.followup_blocked_reason == "declined"
    assert conv.stopped_after == "decline"


def test_patch3_will_think_sets_stopped_after(monkeypatch):
    from app.services import conversation_service, messenger_service, openai_service

    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    monkeypatch.setattr(openai_service, "detect_start_intent", lambda m: "GREETING")

    conversation_service.process_message("sim-think", "გამარჯობა", "instagram")
    conversation_service.process_message(
        "sim-think", "კარგი, დავფიქრდები", "instagram",
    )
    conv = conversation_service.conversations["sim-think"]
    assert conv.stopped_after == "will_think"
    # Not blocked — scheduler may follow up later.
    assert conv.followup_blocked_reason == ""


def test_patch3_price_question_sets_meaningful_interest(monkeypatch):
    from app.services import conversation_service, messenger_service, openai_service

    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    monkeypatch.setattr(openai_service, "detect_start_intent", lambda m: "PRICE")

    conversation_service.process_message("sim-price", "ფასი რა არის?", "instagram")
    conv = conversation_service.conversations["sim-price"]
    assert conv.last_meaningful_interest == "price"
    assert conv.stopped_after == "price"


def test_patch3_no_more_messages_blocks_followup(monkeypatch):
    from app.services import conversation_service, messenger_service, openai_service

    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    monkeypatch.setattr(openai_service, "detect_start_intent", lambda m: "GREETING")

    conversation_service.process_message("sim-stop", "გამარჯობა", "instagram")
    conversation_service.process_message(
        "sim-stop", "აღარ მომწეროთ, გთხოვთ", "instagram",
    )
    conv = conversation_service.conversations["sim-stop"]
    assert conv.followup_blocked_reason == "asked_no_more_messages"


def test_patch3_last_bot_message_at_set_after_response(monkeypatch):
    from app.services import conversation_service, messenger_service, openai_service

    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    monkeypatch.setattr(openai_service, "detect_start_intent", lambda m: "GREETING")

    conversation_service.process_message("sim-bot-ts", "გამარჯობა", "instagram")
    conv = conversation_service.conversations["sim-bot-ts"]
    assert conv.last_bot_message_at  # non-empty
    # ISO format check — fromisoformat must accept it.
    from datetime import datetime as _dt
    parsed = _dt.fromisoformat(conv.last_bot_message_at)
    assert isinstance(parsed, _dt)


def test_patch3_booked_lead_blocks_followup(monkeypatch):
    """A booked lead must result in followup_blocked_reason='booked' so
    the scheduler skips it forever."""
    from app.services import conversation_service

    conv = Conversation(sender_id="sim-booked", platform="instagram")
    conv.lead = Lead(
        sender_id="sim-booked", platform="instagram", segment="PARENT",
        calendly_booked=True,
    )
    conversation_service._record_post_response_followup_markers(conv)
    assert conv.followup_blocked_reason == "booked"


def test_patch4_sanitiser_rewrites_chamouqalibet():
    from app.agent.llm.parent_llm_engine import sanitise_response_wording

    cases = (
        "ჩამოუყალიბეთ თქვენი შვილის ასაკი.",
        "ჩამოუყალიბეთ რა გაინტერესებთ.",
    )
    for original in cases:
        rewritten = sanitise_response_wording(original)
        assert "ჩამოუყალიბეთ" not in rewritten


def test_patch4_sanitiser_rewrites_what_do_you_consider_most_important():
    from app.agent.llm.parent_llm_engine import sanitise_response_wording

    rewritten = sanitise_response_wording(
        "რას მიიჩნევთ ყველაზე მნიშვნელოვანია ბავშვისთვის?"
    )
    assert "რას მიიჩნევთ ყველაზე მნიშვნელოვანია" not in rewritten
    assert "რას ელოდებით" in rewritten or "რისი მიღება" in rewritten


def test_patch4_sanitiser_rewrites_grammatical_error_in_what_to_receive():
    from app.agent.llm.parent_llm_engine import sanitise_response_wording

    rewritten = sanitise_response_wording(
        "რისი მიღებაც გინდათ თქვენი შვილმა ბანაკიდან?"
    )
    assert "რისი მიღებაც გინდათ თქვენი შვილმა" not in rewritten
    assert "რისი მიღება გსურთ თქვენი შვილისთვის" in rewritten


def test_patch4_sanitiser_rewrites_azri_aqvs():
    from app.agent.llm.parent_llm_engine import sanitise_response_wording

    rewritten = sanitise_response_wording("მესმის, ამას აზრი აქვს.")
    assert "აზრი აქვს" not in rewritten


def test_patch4_sanitiser_rewrites_manager_explains_live():
    from app.agent.llm.parent_llm_engine import sanitise_response_wording

    rewritten = sanitise_response_wording(
        "მენეჯერი დეტალებს ცოცხლად აგიხსნით."
    )
    assert "დეტალებს ცოცხლად" not in rewritten
    assert "დეტალურად აგიხსნით" in rewritten or "დეტალურად" in rewritten


def test_patch4_engine_response_strips_combined_forbidden_phrases(
    enable_engine, monkeypatch, fresh_conversation,
):
    """End-to-end: a single response loaded with PATCH 4 violations must
    come out clean."""
    from app.services import messenger_service, openai_service

    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    monkeypatch.setattr(
        openai_service, "chat_with_tools",
        lambda **kwargs: _mk_response(content=(
            "ჩამოუყალიბეთ შვილის ასაკი. ამას აზრი აქვს, რადგან მენეჯერი "
            "დეტალებს ცოცხლად აგიხსნით."
        )),
    )

    # PATCH 8 — bare "გამარჯობა" gets static menu now. Use an intent-
    # bearing trigger so the engine actually runs and the sanitiser
    # has something to scrub.
    out = parent_flow.handle(fresh_conversation, "ბანაკი მაინტერესებს")
    for phrase in (
        "ჩამოუყალიბეთ",
        "აზრი აქვს",
        "დეტალებს ცოცხლად",
    ):
        assert phrase not in out, f"forbidden phrase leaked: {phrase!r}"


# -- PATCH 4.B — calendar_service.get_free_slots back-compat + range ------


def test_patch4_get_free_slots_legacy_positional_signature(monkeypatch):
    """Legacy callers passing a single positional `target_date` must
    keep working byte-for-byte."""
    from datetime import date as _date
    from app.services import calendar_service

    captured: list[Any] = []

    def _fake_day(target_date, duration_minutes):
        captured.append((target_date, duration_minutes))
        return [{"date": str(target_date), "time": "10:00",
                 "datetime_iso": f"{target_date}T10:00:00+04:00"}]

    monkeypatch.setattr(calendar_service, "_get_free_slots_for_day", _fake_day)
    out = calendar_service.get_free_slots(_date(2030, 6, 3))
    assert len(out) == 1
    # Booking Availability Patch (2026-06-03): default slot duration
    # is now 60 minutes (was 30).
    assert captured == [(_date(2030, 6, 3), 60)]


def test_patch4_get_free_slots_range_form(monkeypatch):
    """New `start_date` / `days` keywords iterate weekdays starting at
    `start_date` and concatenate the per-day slot lists."""
    from datetime import date as _date
    from app.services import calendar_service

    seen: list[_date] = []

    def _fake_day(target_date, duration_minutes):
        seen.append(target_date)
        return [{"date": str(target_date), "time": "10:00",
                 "datetime_iso": f"{target_date}T10:00:00+04:00"}]

    monkeypatch.setattr(calendar_service, "_get_free_slots_for_day", _fake_day)
    out = calendar_service.get_free_slots(
        start_date=_date(2030, 6, 3), days=3,
    )
    assert len(out) == 3
    assert seen == [_date(2030, 6, 3), _date(2030, 6, 4), _date(2030, 6, 5)]


def test_patch4_get_free_slots_default_uses_today(monkeypatch):
    """No args at all → searches starting at today for `days` days."""
    from app.services import calendar_service

    seen = []
    monkeypatch.setattr(
        calendar_service, "_get_free_slots_for_day",
        lambda d, dur: seen.append(d) or [],
    )
    calendar_service.get_free_slots(days=1)
    assert len(seen) == 1


def test_patch4_executor_get_available_slots_with_date_iso(
    monkeypatch, fresh_conversation, camp_registration_open,):
    """When the LLM passes `date_iso`, the executor must use the
    range form of `get_free_slots` for that specific date — NOT the
    legacy `parent_flow._load_available_slots` cache."""
    from app.flows import parent_flow as pf
    from app.services import calendar_service

    monkeypatch.setattr(
        pf, "_load_available_slots",
        lambda sid: pytest.fail("legacy slot cache must not run when date_iso is given"),
    )

    captured: list[Any] = []

    def _fake_get(*args, **kwargs):
        captured.append(kwargs)
        return [{"date": "26 მაისი", "time": "12:00",
                 "datetime_iso": "2030-05-27T12:00:00+04:00"}]

    monkeypatch.setattr(calendar_service, "get_free_slots", _fake_get)

    lead = Lead(sender_id=fresh_conversation.sender_id, platform="instagram",
                segment="PARENT")
    executor = _make_executor(fresh_conversation, lead=lead)
    result = executor.execute(TOOL_GET_AVAILABLE_SLOTS, {
        "date_iso": "2030-05-27",
    })
    assert result["success"] is True
    assert captured, "get_free_slots must have been called"
    kwargs = captured[0]
    assert kwargs.get("days") == 1
    from datetime import date as _date
    assert kwargs.get("start_date") == _date(2030, 5, 27)
    assert result["slots"][0]["display"].startswith("26 მაისი") or "12:00" in result["slots"][0]["display"]


def test_patch4_executor_get_available_slots_invalid_date_iso(fresh_conversation, camp_registration_open):
    executor = _make_executor(fresh_conversation)
    result = executor.execute(TOOL_GET_AVAILABLE_SLOTS, {"date_iso": "not-a-date"})
    assert result["success"] is False
    assert result["reason"] == "invalid_date_iso"


def test_patch4_executor_get_available_slots_no_args_uses_legacy_cache(
    monkeypatch, fresh_conversation, camp_registration_open,):
    """Without arguments the executor still routes through
    `parent_flow._load_available_slots` — the legacy behaviour the
    pre-PATCH-4 tests rely on."""
    from app.flows import parent_flow as pf

    called: list[Any] = []
    monkeypatch.setattr(
        pf, "_load_available_slots",
        lambda sid: called.append(sid) or [
            {"date": "26 მაისი", "time": "12:00",
             "datetime_iso": "2030-05-26T12:00:00+04:00"},
        ],
    )
    executor = _make_executor(fresh_conversation)
    result = executor.execute(TOOL_GET_AVAILABLE_SLOTS, {})
    assert result["success"] is True
    assert called


# -- PATCH 4.C — challenge preservation -----------------------------------


def test_patch4_save_lead_info_preserves_existing_challenge_substring():
    """A shorter rephrase of an existing challenge must NOT overwrite
    the richer original."""
    conv = Conversation(sender_id="x", platform="instagram")
    lead = Lead(
        sender_id="x", platform="instagram", segment="PARENT",
        challenge="ეკრანისგან დისტანცია",
    )
    conv.lead = lead
    executor = ParentToolExecutor(
        conversation=conv, lead=lead, sender_id="x", platform="instagram",
    )
    result = executor.execute(TOOL_SAVE_LEAD_INFO, {"challenge": "ეკრანი"})
    assert result["success"] is True
    # "ეკრანი" is contained in "ეკრანისგან დისტანცია" → no change.
    assert lead.challenge == "ეკრანისგან დისტანცია"


def test_patch4_save_lead_info_promotes_richer_challenge():
    conv = Conversation(sender_id="x", platform="instagram")
    lead = Lead(
        sender_id="x", platform="instagram", segment="PARENT",
        challenge="ეკრანი",
    )
    conv.lead = lead
    executor = ParentToolExecutor(
        conversation=conv, lead=lead, sender_id="x", platform="instagram",
    )
    executor.execute(TOOL_SAVE_LEAD_INFO, {
        "challenge": "ეკრანი და კომუნიკაცია",
    })
    assert lead.challenge == "ეკრანი და კომუნიკაცია"


def test_patch4_save_lead_info_appends_unrelated_challenge():
    conv = Conversation(sender_id="x", platform="instagram")
    lead = Lead(
        sender_id="x", platform="instagram", segment="PARENT",
        challenge="ეკრანისგან დისტანცია",
    )
    conv.lead = lead
    executor = ParentToolExecutor(
        conversation=conv, lead=lead, sender_id="x", platform="instagram",
    )
    executor.execute(TOOL_SAVE_LEAD_INFO, {"challenge": "თავდაჯერებულობა"})
    assert "ეკრანისგან დისტანცია" in lead.challenge
    assert "თავდაჯერებულობა" in lead.challenge
    assert ";" in lead.challenge


def test_patch4_known_lead_fields_reused_in_booking(monkeypatch, fresh_conversation, camp_registration_open):
    """When age + phone are already on the lead, book_consultation can
    succeed with only the missing pieces (name + datetime) given."""
    from app.services import (
        calendar_service,
        notification_service,
        openai_service,
        sheets_service,
    )

    fresh_conversation.lead = Lead(
        sender_id=fresh_conversation.sender_id, platform="instagram",
        segment="PARENT",
        name="ნიკოლოზი",
        phone="599999733",
        child_age="14",
        challenge="ეკრანისგან დისტანცია",
    )
    monkeypatch.setattr(calendar_service, "check_slot_available", lambda dt: True)
    monkeypatch.setattr(calendar_service, "book_slot", _mock_book_slot_ok)
    monkeypatch.setattr(sheets_service, "create_lead", lambda lead: True)
    monkeypatch.setattr(
        notification_service, "send_manager_notification",
        lambda lead, summary: True,
    )
    monkeypatch.setattr(openai_service, "generate_summary", lambda h: "ქართული.")

    executor = ParentToolExecutor(
        conversation=fresh_conversation, lead=fresh_conversation.lead,
        sender_id=fresh_conversation.sender_id, platform="instagram",
    )
    result = executor.execute(TOOL_BOOK_CONSULTATION, {
        "name": "ნიკოლოზი",
        "phone": "599999733",
        "datetime_iso": "2030-06-03T12:00:00+04:00",
        "child_age": "14",
        "user_confirmed_datetime": True,
    })
    assert result["success"] is True
    # Challenge is preserved through booking; the lead now has its old
    # challenge intact.
    assert fresh_conversation.lead.challenge == "ეკრანისგან დისტანცია"


def test_patch4_booking_appends_notes_to_existing_challenge(
    monkeypatch, fresh_conversation, camp_registration_open,):
    from app.services import (
        calendar_service,
        notification_service,
        openai_service,
        sheets_service,
    )

    fresh_conversation.lead = Lead(
        sender_id=fresh_conversation.sender_id, platform="instagram",
        segment="PARENT",
        child_age="14",
        challenge="ეკრანისგან დისტანცია",
    )
    monkeypatch.setattr(calendar_service, "check_slot_available", lambda dt: True)
    monkeypatch.setattr(calendar_service, "book_slot", _mock_book_slot_ok)
    monkeypatch.setattr(sheets_service, "create_lead", lambda lead: True)
    monkeypatch.setattr(
        notification_service, "send_manager_notification",
        lambda lead, summary: True,
    )
    monkeypatch.setattr(openai_service, "generate_summary", lambda h: "ქართული.")

    executor = ParentToolExecutor(
        conversation=fresh_conversation, lead=fresh_conversation.lead,
        sender_id=fresh_conversation.sender_id, platform="instagram",
    )
    result = executor.execute(TOOL_BOOK_CONSULTATION, {
        "name": "ნიკოლოზი",
        "phone": "599999733",
        "datetime_iso": "2030-06-03T12:00:00+04:00",
        "child_age": "14",
        "user_confirmed_datetime": True,
        "notes": "მშობელი დარაჯვს თვითდაჯერებულობასაც",
    })
    assert result["success"] is True
    assert "ეკრანისგან დისტანცია" in fresh_conversation.lead.challenge
    assert "თვითდაჯერებულობა" in fresh_conversation.lead.challenge


def test_patch3_manager_handoff_blocks_followup(monkeypatch):
    """When the manager-handoff dict is populated, the conversation's
    follow-up status flips to 'manager_handoff_completed' — but only
    when the user has not already declined (declined takes priority)."""
    from app.agent.tools import parent_tool_executor
    from app.services import conversation_service

    parent_tool_executor.reset_state()
    parent_tool_executor.manager_notified_for_conversation["sim-mh"] = True

    conv = Conversation(sender_id="sim-mh", platform="instagram")
    conv.lead = Lead(sender_id="sim-mh", platform="instagram", segment="PARENT")
    conversation_service._record_post_response_followup_markers(conv)
    assert conv.followup_blocked_reason == "manager_handoff_completed"

    # Decline takes priority — flip it back and verify it sticks.
    parent_tool_executor.reset_state()
    parent_tool_executor.manager_notified_for_conversation["sim-mh-2"] = True
    conv2 = Conversation(sender_id="sim-mh-2", platform="instagram")
    conv2.followup_blocked_reason = "declined"
    conv2.lead = Lead(sender_id="sim-mh-2", platform="instagram", segment="PARENT")
    conversation_service._record_post_response_followup_markers(conv2)
    assert conv2.followup_blocked_reason == "declined"


# =========================================================================
# P3-C PATCH 5 — wording, fake-confirmation guard, pending-booking commit
# =========================================================================


# -- PATCH 5.A — wording rewrites ----------------------------------------


def test_patch5_sanitiser_drops_rom_stsorad_gitkhrat():
    from app.agent.llm.parent_llm_engine import sanitise_response_wording

    cases = (
        "რომ სწორად გითხრათ, რამდენი წლისაა შვილი?",
        "რომ სწორად გითხრათ რამდენი წლისაა?",
        "რომ სწორად გითხრათ",
    )
    for original in cases:
        rewritten = sanitise_response_wording(original)
        assert "რომ სწორად გითხრათ" not in rewritten, f"leak: {original!r}"


def test_patch5_sanitiser_rewrites_gagivlit_to_agikhsnit():
    from app.agent.llm.parent_llm_engine import sanitise_response_wording

    cases = (
        "მენეჯერი დეტალურად გაგივლით პროგრამას.",
        "მენეჯერი დეტალებს გაგივლით.",
        "გაგივლით პროგრამას.",
    )
    for original in cases:
        rewritten = sanitise_response_wording(original)
        assert "გაგივლით" not in rewritten, f"leak: {original!r}"
        assert "აგიხსნით" in rewritten, f"missing replacement in: {original!r}"


def test_patch5_sanitiser_rewrites_dagibarot_to_chavnishnot():
    from app.agent.llm.parent_llm_engine import sanitise_response_wording

    cases = (
        "კონსულტაცია 27 მაისს 13:00 საათზე დაგიბარებთ.",
        "კონსულტაცია დაგიბაროთ.",
        "27 მაისს დაგიბარებთ.",
    )
    for original in cases:
        rewritten = sanitise_response_wording(original)
        assert "დაგიბარებთ" not in rewritten, f"leak: {original!r}"
        assert "დაგიბაროთ" not in rewritten, f"leak: {original!r}"


def test_patch5_engine_strips_combined_patch5_phrases_end_to_end(
    enable_engine, monkeypatch, fresh_conversation,
):
    from app.services import messenger_service, openai_service

    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    monkeypatch.setattr(
        openai_service, "chat_with_tools",
        lambda **kwargs: _mk_response(content=(
            "რომ სწორად გითხრათ, კონსულტაცია 13:00 საათზე დაგიბარებთ. "
            "მენეჯერი დეტალურად გაგივლით პროგრამას."
        )),
    )

    # PATCH 8 — non-greeting trigger so the engine path runs.
    out = parent_flow.handle(fresh_conversation, "ბანაკი მაინტერესებს")
    for forbidden in ("რომ სწორად გითხრათ", "დაგიბარებთ", "გაგივლით"):
        assert forbidden not in out, f"leak past sanitiser: {forbidden!r}"


# -- PATCH 5.B — tool-result-gated booking confirmation -------------------


def test_patch5_guard_blocks_fake_chaginishnet_without_tool_success(
    enable_engine, monkeypatch, fresh_conversation,
):
    """LLM says 'კონსულტაცია ჩაგინიშნეთ' without book_consultation
    actually succeeding — guard rewrites to safe fallback."""
    from app.services import calendar_service, messenger_service, openai_service

    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    monkeypatch.setattr(
        calendar_service, "book_slot",
        lambda **kwargs: pytest.fail("must not run"),
    )
    monkeypatch.setattr(
        openai_service, "chat_with_tools",
        lambda **kwargs: _mk_response(
            content="კონსულტაცია 27 მაისს 13:00 ჩაგინიშნეთ.",
        ),
    )

    out = parent_flow.handle(fresh_conversation, "ნიკოლოზი 595999733")
    assert "ჩაგინიშნე" not in out
    assert "ვერ დავადასტურე" in out or "ვერ მოხერხდა" in out or "მენეჯერ" in out
    assert fresh_conversation.lead.calendly_booked is False


def test_patch5_guard_allows_chaginishnet_with_tool_success(
    enable_engine, monkeypatch, fresh_conversation, camp_registration_open,):
    from app.services import (
        calendar_service, messenger_service, notification_service,
        openai_service, sheets_service,
    )

    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    monkeypatch.setattr(calendar_service, "check_slot_available", lambda dt: True)
    monkeypatch.setattr(calendar_service, "book_slot", _mock_book_slot_ok)
    monkeypatch.setattr(sheets_service, "create_lead", lambda lead: True)
    monkeypatch.setattr(
        notification_service, "send_manager_notification",
        lambda lead, summary: True,
    )
    monkeypatch.setattr(openai_service, "generate_summary", lambda h: "ქართული.")

    call_count = {"n": 0}

    def _chat(**kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _mk_response(tool_calls=[{
                "id": "b1",
                "name": TOOL_BOOK_CONSULTATION,
                "arguments": json.dumps({
                    "name": "ნიკოლოზი",
                    "phone": "595999733",
                    "datetime_iso": "2030-05-27T13:00:00+04:00",
                    "child_age": "14",
                    "user_confirmed_datetime": True,
                }),
            }])
        return _mk_response(content="კონსულტაცია 27 მაისს 13:00 ჩაგინიშნეთ.")

    monkeypatch.setattr(openai_service, "chat_with_tools", _chat)

    # Slot-merge fix (2026-06-25): the child age is a required booking slot, so a
    # complete one-shot booking must include it (previously the age was omitted
    # and the LLM booked with a fabricated value). The guard-allows-confirmation
    # behaviour under test is unchanged.
    out = parent_flow.handle(
        fresh_conversation, "ნიკოლოზი 595999733, 14 წლის, 27 მაისს 13:00",
    )
    assert "ჩაგინიშნე" in out, f"legit confirmation rejected: {out!r}"
    assert fresh_conversation.lead.calendly_booked is True


def test_patch5_tool_success_flag_resets_each_turn(
    enable_engine, monkeypatch, fresh_conversation,
):
    """After a successful book in turn 1, turn 2 must NOT inherit the
    success flag — a hallucinated confirmation must still be blocked."""
    from app.agent.tools.parent_tool_executor import (
        book_consultation_success_for_conversation,
    )
    from app.services import messenger_service, openai_service

    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    # Simulate a stale success bit from a previous booking.
    book_consultation_success_for_conversation[fresh_conversation.sender_id] = True

    monkeypatch.setattr(
        openai_service, "chat_with_tools",
        lambda **kwargs: _mk_response(content="კონსულტაცია ჩაგინიშნეთ."),
    )

    # PATCH 8 — non-greeting trigger so the engine runs.
    out = parent_flow.handle(fresh_conversation, "ბანაკი მაინტერესებს")
    # No real booking → the flag should have been reset and the guard
    # should reject the confirmation.
    assert "ჩაგინიშნე" not in out


# -- PATCH 5.C — pending booking commit (engine path) ---------------------


def test_patch5_explicit_slot_choice_records_pending_booking(
    enable_engine, monkeypatch, fresh_conversation,
):
    """User picks '13:00 საათზე იყოს' after slots were offered →
    pending_booking is recorded with user_confirmed_datetime=True and
    source='user_selected_slot'."""
    from app.agent.tools import parent_tool_executor
    from app.services import messenger_service, openai_service

    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})

    # Pre-seed the offered-slots cache as if get_available_slots had run.
    cache_key = conversation_cache_key(fresh_conversation)
    parent_tool_executor._last_slots_by_sender[cache_key] = [
        {
            "slot_id": 1,
            "datetime_iso": "2030-05-27T13:00:00+04:00",
            "display": "27 მაისი, 13:00",
        },
        {
            "slot_id": 2,
            "datetime_iso": "2030-05-27T16:00:00+04:00",
            "display": "27 მაისი, 16:00",
        },
    ]

    monkeypatch.setattr(
        openai_service, "chat_with_tools",
        lambda **kwargs: _mk_response(
            content="კარგი, სახელი და ნომერი მომწერეთ.",
        ),
    )

    out = parent_flow.handle(fresh_conversation, "13:00 საათზე იყოს")
    pending = fresh_conversation.pending_booking or {}
    assert pending.get("user_confirmed_datetime") is True
    assert pending.get("requested_datetime_iso") == "2030-05-27T13:00:00+04:00"
    assert pending.get("source") == "user_selected_slot"
    assert "name" in (pending.get("missing_fields") or [])
    assert "phone" in (pending.get("missing_fields") or [])
    # No booking yet — only the selection was recorded.
    assert fresh_conversation.lead.calendly_booked is False
    assert out  # bot still replied with the asking-for-contact message


def test_patch5_pending_booking_uses_p1_record_shape(fresh_conversation):
    """Verify pending_booking dict reuses P1 keys + adds PATCH 5
    fields, no new parallel structure."""
    from app.flows.parent_flow import _record_pending_booking_for_slot

    lead = Lead(sender_id="x", platform="instagram", segment="PARENT")
    fresh_conversation.lead = lead
    slot = {
        "slot_id": 1,
        "datetime_iso": "2030-05-27T13:00:00+04:00",
        "display": "27 მაისი, 13:00",
    }
    _record_pending_booking_for_slot(fresh_conversation, lead, slot)
    pending = fresh_conversation.pending_booking
    assert pending is not None
    # P1 keys reused.
    for key in (
        "requested_datetime_iso", "requested_date_text",
        "requested_time_text", "source", "missing_fields",
        "created_at", "attempts",
    ):
        assert key in pending, f"P1 key missing: {key}"
    # PATCH 5 additions.
    assert pending["user_confirmed_datetime"] is True
    assert pending["source"] == "user_selected_slot"


def test_patch5_pending_booking_round_trips_through_serialisation(fresh_conversation):
    """A populated pending_booking must JSON-serialise cleanly."""
    import json as _json
    from app.flows.parent_flow import _record_pending_booking_for_slot

    lead = Lead(sender_id="x", platform="instagram", segment="PARENT")
    fresh_conversation.lead = lead
    slot = {
        "slot_id": 1,
        "datetime_iso": "2030-05-27T13:00:00+04:00",
        "display": "27 მაისი, 13:00",
    }
    _record_pending_booking_for_slot(fresh_conversation, lead, slot)
    data = fresh_conversation.to_dict()
    raw = _json.dumps(data, ensure_ascii=False)
    restored = Conversation.from_dict(_json.loads(raw))
    assert restored.pending_booking is not None
    assert restored.pending_booking["user_confirmed_datetime"] is True
    assert restored.pending_booking["requested_datetime_iso"] == \
        "2030-05-27T13:00:00+04:00"


def test_patch5_modality_question_preserves_pending_booking(
    enable_engine, monkeypatch, fresh_conversation, camp_registration_open,
):
    """User asks about modality after selecting slot — pending_booking
    must survive."""
    from app.services import (
        calendar_service, messenger_service, openai_service, sheets_service,
        notification_service,
    )

    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    monkeypatch.setattr(
        calendar_service, "book_slot",
        lambda **kwargs: pytest.fail("must not book on modality question"),
    )
    monkeypatch.setattr(
        sheets_service, "create_lead",
        lambda lead: pytest.fail("must not save"),
    )
    monkeypatch.setattr(
        notification_service, "send_manager_notification",
        lambda lead, summary: pytest.fail("must not notify"),
    )

    fresh_conversation.pending_booking = {
        "requested_datetime_iso": "2030-05-27T13:00:00+04:00",
        "requested_date_text": "27 მაისი",
        "requested_time_text": "13:00",
        "source": "user_selected_slot",
        "user_confirmed_datetime": True,
        "missing_fields": ["name", "phone"],
        "created_at": "2030-05-24T10:00:00",
        "attempts": 0,
    }
    fresh_conversation.lead = Lead(
        sender_id=fresh_conversation.sender_id, platform="instagram",
        segment="PARENT", child_age="14",
    )

    monkeypatch.setattr(
        openai_service, "chat_with_tools",
        lambda **kwargs: _mk_response(content=(
            "კონსულტაცია ძირითადად ტელეფონით ან ვიდეოზარით ტარდება."
        )),
    )

    out = parent_flow.handle(
        fresh_conversation, "ადგილზე ხდება კონსულტაცია თუ ტელეფონით?",
    )
    assert fresh_conversation.pending_booking is not None
    assert fresh_conversation.pending_booking["requested_datetime_iso"] == \
        "2030-05-27T13:00:00+04:00"
    assert "დაგიბარებთ" not in out
    assert fresh_conversation.lead.calendly_booked is False


def test_patch5_name_phone_after_pending_commits_booking(
    enable_engine, monkeypatch, fresh_conversation, camp_registration_open,):
    """After pending_booking is set with user_confirmed=True and the
    user provides name+phone, backend commits the booking
    deterministically without relying on the LLM."""
    from app.services import (
        calendar_service, messenger_service, notification_service,
        openai_service, sheets_service,
    )

    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    monkeypatch.setattr(calendar_service, "check_slot_available", lambda dt: True)
    booked: list = []
    monkeypatch.setattr(
        calendar_service, "book_slot",
        lambda **kwargs: (booked.append(kwargs), setattr(kwargs["lead"], "calendar_event_id", "evt_mock_test_id"))[0] or True,
    )
    sheets_calls: list = []
    monkeypatch.setattr(
        sheets_service, "create_lead",
        lambda lead: sheets_calls.append(lead) or True,
    )
    notify_calls: list = []
    monkeypatch.setattr(
        notification_service, "send_manager_notification",
        lambda lead, summary: notify_calls.append(lead) or True,
    )
    monkeypatch.setattr(openai_service, "generate_summary", lambda h: "ქართული.")

    # Engine must NOT be consulted when the commit hook succeeds.
    monkeypatch.setattr(
        openai_service, "chat_with_tools",
        lambda **kwargs: pytest.fail("engine should be skipped on deterministic commit"),
    )

    fresh_conversation.pending_booking = {
        "requested_datetime_iso": "2030-05-27T13:00:00+04:00",
        "requested_date_text": "27 მაისი",
        "requested_time_text": "13:00",
        "source": "user_selected_slot",
        "user_confirmed_datetime": True,
        "missing_fields": ["name", "phone"],
        "created_at": "2030-05-24T10:00:00",
        "attempts": 0,
    }
    fresh_conversation.lead = Lead(
        sender_id=fresh_conversation.sender_id, platform="instagram",
        segment="PARENT", child_age="14",
        challenge="ეკრანისგან დისტანცია",
    )

    out = parent_flow.handle(fresh_conversation, "ნიკოლოზი 595999733")

    assert len(booked) == 1
    assert len(sheets_calls) == 1
    assert len(notify_calls) == 1
    assert fresh_conversation.lead.calendly_booked is True
    assert fresh_conversation.state == "DONE"
    assert fresh_conversation.pending_booking is None
    assert fresh_conversation.lead.challenge == "ეკრანისგან დისტანცია"
    # Confirmation language allowed because tool success flag is True.
    assert any(kw in out for kw in ("ჩაგინიშნე", "13:00", "მენეჯერი"))


def test_patch5_pending_commit_skips_when_only_name_no_phone(
    enable_engine, monkeypatch, fresh_conversation,
):
    """User selects slot, then only sends a name — booking must NOT
    fire, engine continues to ask for phone."""
    from app.services import calendar_service, messenger_service, openai_service

    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    monkeypatch.setattr(
        calendar_service, "book_slot",
        lambda **kwargs: pytest.fail("must not book without phone"),
    )

    fresh_conversation.pending_booking = {
        "requested_datetime_iso": "2030-05-27T13:00:00+04:00",
        "source": "user_selected_slot",
        "user_confirmed_datetime": True,
        "missing_fields": ["name", "phone"],
    }
    fresh_conversation.lead = Lead(
        sender_id=fresh_conversation.sender_id, platform="instagram",
        segment="PARENT", child_age="14",
    )

    monkeypatch.setattr(
        openai_service, "chat_with_tools",
        lambda **kwargs: _mk_response(content="ნომერი მომწერეთ."),
    )

    out = parent_flow.handle(fresh_conversation, "ნიკოლოზი")
    assert fresh_conversation.lead.calendly_booked is False
    assert fresh_conversation.pending_booking is not None
    assert out


def test_patch5_pending_commit_skips_when_only_phone_no_name(
    enable_engine, monkeypatch, fresh_conversation,
):
    from app.services import calendar_service, messenger_service, openai_service

    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    monkeypatch.setattr(
        calendar_service, "book_slot",
        lambda **kwargs: pytest.fail("must not book without name"),
    )

    fresh_conversation.pending_booking = {
        "requested_datetime_iso": "2030-05-27T13:00:00+04:00",
        "source": "user_selected_slot",
        "user_confirmed_datetime": True,
        "missing_fields": ["name", "phone"],
    }
    fresh_conversation.lead = Lead(
        sender_id=fresh_conversation.sender_id, platform="instagram",
        segment="PARENT", child_age="14",
    )

    monkeypatch.setattr(
        openai_service, "chat_with_tools",
        lambda **kwargs: _mk_response(content="სახელი მომწერეთ."),
    )

    out = parent_flow.handle(fresh_conversation, "595999733")
    assert fresh_conversation.lead.calendly_booked is False
    assert fresh_conversation.pending_booking is not None
    assert out


def test_patch5_executor_honours_pending_user_confirmed(monkeypatch, fresh_conversation, camp_registration_open):
    """When pending_booking already has user_confirmed_datetime=True
    AND the LLM forgets to pass the flag, _book_consultation must
    still proceed (using the pending datetime)."""
    from app.services import (
        calendar_service, notification_service, openai_service, sheets_service,
    )

    monkeypatch.setattr(calendar_service, "check_slot_available", lambda dt: True)
    monkeypatch.setattr(calendar_service, "book_slot", _mock_book_slot_ok)
    monkeypatch.setattr(sheets_service, "create_lead", lambda lead: True)
    monkeypatch.setattr(
        notification_service, "send_manager_notification",
        lambda lead, summary: True,
    )
    monkeypatch.setattr(openai_service, "generate_summary", lambda h: "ქართული.")

    fresh_conversation.pending_booking = {
        "requested_datetime_iso": "2030-05-27T13:00:00+04:00",
        "user_confirmed_datetime": True,
        "source": "user_selected_slot",
    }
    lead = Lead(
        sender_id=fresh_conversation.sender_id, platform="instagram",
        segment="PARENT",
    )
    fresh_conversation.lead = lead
    executor = ParentToolExecutor(
        conversation=fresh_conversation, lead=lead,
        sender_id=fresh_conversation.sender_id, platform="instagram",
    )
    result = executor.execute(TOOL_BOOK_CONSULTATION, {
        "name": "ნიკოლოზი",
        "phone": "595999733",
        "datetime_iso": "2030-05-27T13:00:00+04:00",
        "child_age": "14",
        # user_confirmed_datetime intentionally absent — pending has it.
    })
    assert result["success"] is True
    assert lead.calendly_booked is True


def test_patch5_executor_phone_mask_helper():
    """Phone never appears in full inside log lines."""
    from app.agent.tools.parent_tool_executor import _mask_phone

    assert _mask_phone("595999733") == "595***733"
    assert _mask_phone("+995595999733") == "995***733"
    assert _mask_phone("") == ""
    assert _mask_phone(None) == ""
    assert _mask_phone("123") == "***"


def test_patch5_executor_logs_do_not_leak_full_phone(
    caplog, fresh_conversation, monkeypatch, camp_registration_open,):
    """Run _book_consultation, scan caplog records, assert the full
    9-digit local phone never appears in any log message."""
    import logging
    from app.services import (
        calendar_service, notification_service, openai_service, sheets_service,
    )

    monkeypatch.setattr(calendar_service, "check_slot_available", lambda dt: True)
    monkeypatch.setattr(calendar_service, "book_slot", _mock_book_slot_ok)
    monkeypatch.setattr(sheets_service, "create_lead", lambda lead: True)
    monkeypatch.setattr(
        notification_service, "send_manager_notification",
        lambda lead, summary: True,
    )
    monkeypatch.setattr(openai_service, "generate_summary", lambda h: "x")

    lead = Lead(
        sender_id=fresh_conversation.sender_id, platform="instagram",
        segment="PARENT",
    )
    fresh_conversation.lead = lead
    executor = ParentToolExecutor(
        conversation=fresh_conversation, lead=lead,
        sender_id=fresh_conversation.sender_id, platform="instagram",
    )
    with caplog.at_level(logging.INFO, logger="app.agent.tools.parent_tool_executor"):
        result = executor.execute(TOOL_BOOK_CONSULTATION, {
            "name": "ნიკოლოზი",
            "phone": "595999733",
            "datetime_iso": "2030-05-27T13:00:00+04:00",
            "child_age": "14",
            "user_confirmed_datetime": True,
        })
    assert result["success"] is True
    for record in caplog.records:
        msg = record.getMessage()
        # The full 9-digit phone must NEVER appear together; the masked
        # form 595***733 is fine.
        assert "595999733" not in msg, (
            f"full phone leaked in log line: {msg!r}"
        )


def test_patch5_known_age_and_challenge_reused_in_commit(
    enable_engine, monkeypatch, fresh_conversation, camp_registration_open,):
    """The deterministic commit reuses lead.child_age + lead.challenge
    without re-asking them."""
    from app.services import (
        calendar_service, messenger_service, notification_service,
        openai_service, sheets_service,
    )

    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    monkeypatch.setattr(calendar_service, "check_slot_available", lambda dt: True)
    booked: list = []
    monkeypatch.setattr(
        calendar_service, "book_slot",
        lambda **kwargs: (booked.append(kwargs), setattr(kwargs["lead"], "calendar_event_id", "evt_mock_test_id"))[0] or True,
    )
    monkeypatch.setattr(sheets_service, "create_lead", lambda lead: True)
    monkeypatch.setattr(
        notification_service, "send_manager_notification",
        lambda lead, summary: True,
    )
    monkeypatch.setattr(openai_service, "generate_summary", lambda h: "x")
    monkeypatch.setattr(
        openai_service, "chat_with_tools",
        lambda **kwargs: pytest.fail("engine should be skipped"),
    )

    fresh_conversation.pending_booking = {
        "requested_datetime_iso": "2030-05-27T13:00:00+04:00",
        "user_confirmed_datetime": True,
        "source": "user_selected_slot",
        "missing_fields": ["name", "phone"],
    }
    fresh_conversation.lead = Lead(
        sender_id=fresh_conversation.sender_id, platform="instagram",
        segment="PARENT", child_age="14",
        challenge="ეკრანისგან დისტანცია",
    )

    parent_flow.handle(fresh_conversation, "ნიკოლოზი 595999733")

    assert booked, "calendar_service.book_slot should have been called"
    assert fresh_conversation.lead.child_age == "14"
    assert fresh_conversation.lead.challenge == "ეკრანისგან დისტანცია"


def test_patch5_profile_failure_does_not_block_booking(
    enable_engine, monkeypatch, fresh_conversation, camp_registration_open,):
    """Even when the Meta profile fetch raises (live v19 400 case),
    a deterministic commit must still succeed."""
    from app.services import (
        calendar_service, messenger_service, notification_service,
        openai_service, sheets_service,
    )

    def _explode(sid, plat):
        raise RuntimeError("Graph API 400")

    monkeypatch.setattr(messenger_service, "get_user_profile", _explode)
    monkeypatch.setattr(calendar_service, "check_slot_available", lambda dt: True)
    monkeypatch.setattr(calendar_service, "book_slot", _mock_book_slot_ok)
    monkeypatch.setattr(sheets_service, "create_lead", lambda lead: True)
    monkeypatch.setattr(
        notification_service, "send_manager_notification",
        lambda lead, summary: True,
    )
    monkeypatch.setattr(openai_service, "generate_summary", lambda h: "x")
    monkeypatch.setattr(
        openai_service, "chat_with_tools",
        lambda **kwargs: pytest.fail("engine should be skipped"),
    )

    fresh_conversation.pending_booking = {
        "requested_datetime_iso": "2030-05-27T13:00:00+04:00",
        "user_confirmed_datetime": True,
        "source": "user_selected_slot",
        "missing_fields": ["name", "phone"],
    }
    fresh_conversation.lead = Lead(
        sender_id=fresh_conversation.sender_id, platform="instagram",
        segment="PARENT", child_age="14",
    )

    parent_flow.handle(fresh_conversation, "ნიკოლოზი 595999733")
    assert fresh_conversation.lead.calendly_booked is True


def test_patch5_engine_context_exposes_pending_booking(
    enable_engine, monkeypatch, fresh_conversation,
):
    from app.services import messenger_service, openai_service

    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    seen: list[list[dict]] = []
    monkeypatch.setattr(
        openai_service, "chat_with_tools",
        lambda **kwargs: (seen.append(kwargs.get("messages") or []),
                          _mk_response(content="გასაგებია."))[1],
    )

    fresh_conversation.pending_booking = {
        "requested_datetime_iso": "2030-05-27T13:00:00+04:00",
        "user_confirmed_datetime": True,
        "source": "user_selected_slot",
        "missing_fields": ["name"],
    }
    fresh_conversation.lead = Lead(
        sender_id=fresh_conversation.sender_id, platform="instagram",
        segment="PARENT", child_age="14",
        # phone present so we DON'T trip the commit hook in this test
        phone="595999733",
    )

    parent_flow.handle(fresh_conversation, "მთხოვს კონსულტაცია?")
    assert seen
    # The guarantee is that the pending slot REACHES the model, not which role
    # carries it. Measured 2026-08-01: the model ignored lead facts delivered in
    # a system block and used the identical text delivered as a user message, so
    # the block moved roles; asserting on system blocks alone pinned the
    # transport rather than the contract.
    joined = "\n".join(m.get("content") or "" for m in seen[0])
    assert "pending_booking_iso" in joined
    assert "2030-05-27T13:00:00+04:00" in joined


def test_patch5_get_slots_logs_call(monkeypatch, fresh_conversation, caplog, camp_registration_open):
    import logging
    from app.flows import parent_flow as pf
    monkeypatch.setattr(
        pf, "_load_available_slots",
        lambda sid: [
            {"date": "26 მაისი", "time": "12:00",
             "datetime_iso": "2030-05-26T12:00:00+04:00"},
        ],
    )
    lead = Lead(sender_id="x", platform="instagram", segment="PARENT")
    fresh_conversation.lead = lead
    executor = ParentToolExecutor(
        conversation=fresh_conversation, lead=lead,
        sender_id="x", platform="instagram",
    )
    with caplog.at_level(logging.INFO, logger="app.agent.tools.parent_tool_executor"):
        executor.execute(TOOL_GET_AVAILABLE_SLOTS, {})
    messages = [r.getMessage() for r in caplog.records]
    assert any("[get_slots] called" in m for m in messages)
    assert any("[get_slots] calendar returned" in m for m in messages)


# =========================================================================
# P3-C PATCH 6 — exact-slot availability + buffer-today fix
# =========================================================================


from app.agent.tools.parent_tools import (  # noqa: E402
    TOOL_CHECK_CONSULTATION_SLOT,
)


# -- PATCH 6.A — is_within_business_hours helper --------------------------


def test_patch6_is_within_business_hours_accepts_15_00_weekday():
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo
    from app.services.calendar_service import is_within_business_hours

    # Pick a Wednesday far in the future at 15:00 Asia/Tbilisi.
    slot = _dt(2030, 6, 5, 15, 0, tzinfo=ZoneInfo("Asia/Tbilisi"))
    ok, reason = is_within_business_hours(slot)
    assert ok is True, f"15:00 weekday must be accepted, got reason={reason!r}"
    assert reason == ""


def test_patch6_is_within_business_hours_rejects_22_00():
    # Booking Availability Patch (2026-06-03): 20:00 is now a VALID
    # 1-hour slot (20:00–21:00, within the widened 10:00–21:00 window).
    # 22:00 + 1h = 23:00 still falls outside the window — that's the
    # new "after hours" check.
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo
    from app.services.calendar_service import is_within_business_hours

    slot = _dt(2030, 6, 5, 22, 0, tzinfo=ZoneInfo("Asia/Tbilisi"))
    ok, reason = is_within_business_hours(slot)
    assert ok is False
    assert reason == "outside_business_hours"


def test_patch6_is_within_business_hours_rejects_weekend():
    """Scheduling policy update (2026-06-16): only Sunday is rejected as a
    weekend; Saturday is now an open booking day."""
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo
    from app.services.calendar_service import is_within_business_hours

    tbilisi = ZoneInfo("Asia/Tbilisi")
    # 2030-06-09 is a Sunday — still closed.
    sunday = _dt(2030, 6, 9, 12, 0, tzinfo=tbilisi)
    ok, reason = is_within_business_hours(sunday)
    assert ok is False
    assert reason == "weekend"

    # 2030-06-08 is a Saturday — now allowed (inside 10:00–21:00).
    saturday = _dt(2030, 6, 8, 12, 0, tzinfo=tbilisi)
    ok, reason = is_within_business_hours(saturday)
    assert ok is True, f"Saturday in-hours must be allowed; got reason={reason!r}"
    assert reason == ""


def test_patch6_is_within_business_hours_rejects_past_datetime():
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo
    from app.services.calendar_service import is_within_business_hours

    slot = _dt(2000, 1, 3, 12, 0, tzinfo=ZoneInfo("Asia/Tbilisi"))
    ok, reason = is_within_business_hours(slot)
    assert ok is False
    assert reason == "past_datetime"


# -- PATCH 6.B — buffer applies only to today -----------------------------


def test_patch6_buffer_only_excludes_today_slots(monkeypatch):
    """Slots on a future date must not be pruned by the today-only
    buffer."""
    from datetime import datetime as _dt, timedelta as _td
    from zoneinfo import ZoneInfo
    from app.services import calendar_service as cs

    fixed_now = _dt(2030, 6, 10, 13, 30, tzinfo=ZoneInfo("Asia/Tbilisi"))

    class _FakeDT(cs.datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return fixed_now.replace(tzinfo=None)
            return fixed_now.astimezone(tz)

    monkeypatch.setattr(cs, "datetime", _FakeDT)
    monkeypatch.setattr(cs, "_free_busy_intervals", lambda s, e: [])

    # tomorrow weekday
    tomorrow = fixed_now.date() + _td(days=1)
    while tomorrow.weekday() >= 5:
        tomorrow = tomorrow + _td(days=1)
    slots = cs._get_free_slots_for_day(tomorrow, 30)
    # 15:00 must be in the list — buffer only applies to today.
    expected_iso = f"{tomorrow.isoformat()}T15:00:00+04:00"
    assert any(s["datetime_iso"] == expected_iso for s in slots), (
        f"tomorrow 15:00 pruned: {slots!r}"
    )


def test_patch6_buffer_still_excludes_today_near_slots(monkeypatch):
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo
    from app.services import calendar_service as cs

    fixed_now = _dt(2030, 6, 10, 13, 30, tzinfo=ZoneInfo("Asia/Tbilisi"))

    class _FakeDT(cs.datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return fixed_now.replace(tzinfo=None)
            return fixed_now.astimezone(tz)

    monkeypatch.setattr(cs, "datetime", _FakeDT)
    monkeypatch.setattr(cs, "_free_busy_intervals", lambda s, e: [])

    today = fixed_now.date()
    slots = cs._get_free_slots_for_day(today, 30)
    near_iso = f"{today.isoformat()}T14:00:00+04:00"  # < now+2h
    far_iso = f"{today.isoformat()}T16:00:00+04:00"   # ≥ now+2h
    assert not any(s["datetime_iso"] == near_iso for s in slots), (
        f"14:00 must be excluded by buffer: {slots!r}"
    )
    assert any(s["datetime_iso"] == far_iso for s in slots), (
        f"16:00 must remain: {slots!r}"
    )


# -- PATCH 6.C — check_consultation_slot executor -------------------------


def test_patch6_check_consultation_slot_available(monkeypatch, fresh_conversation, camp_registration_open):
    """Inside business hours + Calendar free → available=True and a
    confirmed pending_booking is recorded."""
    from app.services import calendar_service

    monkeypatch.setattr(
        calendar_service, "is_within_business_hours",
        lambda dt, dur=30: (True, ""),
    )
    monkeypatch.setattr(
        calendar_service, "check_slot_calendar_only",
        lambda dt, dur=30: True,
    )
    monkeypatch.setattr(
        calendar_service, "get_free_slots",
        lambda *a, **k: [],
    )

    lead = Lead(sender_id="x", platform="instagram", segment="PARENT")
    fresh_conversation.lead = lead
    executor = ParentToolExecutor(
        conversation=fresh_conversation, lead=lead,
        sender_id="x", platform="instagram",
    )
    result = executor.execute(TOOL_CHECK_CONSULTATION_SLOT, {
        "datetime_iso": "2030-05-27T15:00:00+04:00",
    })
    assert result["success"] is True
    assert result["available"] is True
    assert result["inside_business_hours"] is True
    assert result["calendar_available"] is True
    assert result["reason"] == ""
    pending = fresh_conversation.pending_booking or {}
    assert pending.get("user_confirmed_datetime") is True
    assert pending.get("requested_datetime_iso") == "2030-05-27T15:00:00+04:00"
    assert pending.get("source") == "user_requested_exact_slot"


def test_patch6_check_consultation_slot_outside_business_hours(
    monkeypatch, fresh_conversation, camp_registration_open,):
    from app.services import calendar_service

    monkeypatch.setattr(
        calendar_service, "is_within_business_hours",
        lambda dt, dur=30: (False, "outside_business_hours"),
    )
    # Calendar must NOT be consulted on a business-hour rejection.
    monkeypatch.setattr(
        calendar_service, "check_slot_calendar_only",
        lambda dt, dur=30: pytest.fail("must not run on outside-hours"),
    )
    monkeypatch.setattr(
        calendar_service, "get_free_slots",
        lambda *a, **k: [
            {"date": "27", "time": "11:00",
             "datetime_iso": "2030-05-27T11:00:00+04:00"},
        ],
    )

    lead = Lead(sender_id="x", platform="instagram", segment="PARENT")
    fresh_conversation.lead = lead
    executor = ParentToolExecutor(
        conversation=fresh_conversation, lead=lead,
        sender_id="x", platform="instagram",
    )
    result = executor.execute(TOOL_CHECK_CONSULTATION_SLOT, {
        "datetime_iso": "2030-05-27T20:00:00+04:00",
    })
    assert result["success"] is True
    assert result["available"] is False
    assert result["inside_business_hours"] is False
    assert result["calendar_available"] is False
    assert result["reason"] == "outside_business_hours"
    assert len(result["alternative_slots"]) >= 1
    # No pending_booking on unavailable.
    pending = fresh_conversation.pending_booking
    if pending:
        assert pending.get("user_confirmed_datetime") is not True


def test_patch6_check_consultation_slot_calendar_busy(
    monkeypatch, fresh_conversation, camp_registration_open,):
    from app.services import calendar_service

    monkeypatch.setattr(
        calendar_service, "is_within_business_hours",
        lambda dt, dur=30: (True, ""),
    )
    monkeypatch.setattr(
        calendar_service, "check_slot_calendar_only",
        lambda dt, dur=30: False,
    )
    monkeypatch.setattr(
        calendar_service, "get_free_slots",
        lambda *a, **k: [
            {"date": "27", "time": "11:00",
             "datetime_iso": "2030-05-27T11:00:00+04:00"},
            {"date": "27", "time": "14:00",
             "datetime_iso": "2030-05-27T14:00:00+04:00"},
        ],
    )

    lead = Lead(sender_id="x", platform="instagram", segment="PARENT")
    fresh_conversation.lead = lead
    executor = ParentToolExecutor(
        conversation=fresh_conversation, lead=lead,
        sender_id="x", platform="instagram",
    )
    result = executor.execute(TOOL_CHECK_CONSULTATION_SLOT, {
        "datetime_iso": "2030-05-27T15:00:00+04:00",
    })
    assert result["available"] is False
    assert result["inside_business_hours"] is True
    assert result["calendar_available"] is False
    assert result["reason"] == "calendar_busy"
    assert len(result["alternative_slots"]) == 2
    # Pending booking should NOT carry user_confirmed for a busy slot.
    pending = fresh_conversation.pending_booking
    if pending:
        assert pending.get("user_confirmed_datetime") is not True


def test_patch6_check_consultation_slot_invalid_datetime(fresh_conversation, camp_registration_open):
    lead = Lead(sender_id="x", platform="instagram", segment="PARENT")
    fresh_conversation.lead = lead
    executor = ParentToolExecutor(
        conversation=fresh_conversation, lead=lead,
        sender_id="x", platform="instagram",
    )
    result = executor.execute(TOOL_CHECK_CONSULTATION_SLOT, {
        "datetime_iso": "not-a-date",
    })
    assert result["available"] is False
    assert result["reason"] == "invalid_datetime"


def test_patch6_check_consultation_slot_missing_datetime(fresh_conversation, camp_registration_open):
    lead = Lead(sender_id="x", platform="instagram", segment="PARENT")
    fresh_conversation.lead = lead
    executor = ParentToolExecutor(
        conversation=fresh_conversation, lead=lead,
        sender_id="x", platform="instagram",
    )
    result = executor.execute(TOOL_CHECK_CONSULTATION_SLOT, {})
    assert result["available"] is False
    assert result["reason"] == "invalid_datetime"


def test_patch6_check_consultation_slot_logs_have_buffer_and_inside_hours(
    monkeypatch, fresh_conversation, caplog, camp_registration_open,):
    import logging
    from app.services import calendar_service

    monkeypatch.setattr(
        calendar_service, "is_within_business_hours",
        lambda dt, dur=30: (True, ""),
    )
    monkeypatch.setattr(
        calendar_service, "check_slot_calendar_only",
        lambda dt, dur=30: True,
    )

    lead = Lead(sender_id="x", platform="instagram", segment="PARENT")
    fresh_conversation.lead = lead
    executor = ParentToolExecutor(
        conversation=fresh_conversation, lead=lead,
        sender_id="x", platform="instagram",
    )
    with caplog.at_level(logging.INFO, logger="app.agent.tools.parent_tool_executor"):
        executor.execute(TOOL_CHECK_CONSULTATION_SLOT, {
            "datetime_iso": "2030-05-27T15:00:00+04:00",
        })
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "[slot_check] requested_datetime=" in text
    assert "parsed_tbilisi=" in text
    assert "inside_business_hours=True" in text
    assert "buffer_applied=" in text
    assert "calendar_available=True" in text
    assert "available=True" in text


# -- PATCH 6.D — exact slot + later name/phone commits booking (end-to-end)


def test_patch6_exact_available_then_name_phone_commits_booking(
    enable_engine, monkeypatch, fresh_conversation, camp_registration_open,):
    """Live-bug regression: user asks 27 May 15:00, then sends
    name+phone — the deterministic PATCH 5 commit must fire on the
    pending_booking that check_consultation_slot recorded."""
    from app.services import (
        calendar_service, messenger_service, notification_service,
        openai_service, sheets_service,
    )

    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    monkeypatch.setattr(
        calendar_service, "is_within_business_hours",
        lambda dt, dur=30: (True, ""),
    )
    monkeypatch.setattr(
        calendar_service, "check_slot_calendar_only",
        lambda dt, dur=30: True,
    )
    monkeypatch.setattr(
        calendar_service, "check_slot_available",
        lambda dt, dur=30: True,
    )
    booked: list = []
    monkeypatch.setattr(
        calendar_service, "book_slot",
        lambda **kwargs: (booked.append(kwargs), setattr(kwargs["lead"], "calendar_event_id", "evt_mock_test_id"))[0] or True,
    )
    monkeypatch.setattr(sheets_service, "create_lead", lambda lead: True)
    monkeypatch.setattr(
        notification_service, "send_manager_notification",
        lambda lead, summary: True,
    )
    monkeypatch.setattr(openai_service, "generate_summary", lambda h: "ქართული.")

    # Pre-seed lead with child_age so commit isn't blocked.
    fresh_conversation.lead = Lead(
        sender_id=fresh_conversation.sender_id, platform="instagram",
        segment="PARENT", child_age="10",
    )

    call_count = {"n": 0}

    def _chat(**kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _mk_response(tool_calls=[{
                "id": "c1",
                "name": TOOL_CHECK_CONSULTATION_SLOT,
                "arguments": json.dumps({
                    "datetime_iso": "2030-05-27T15:00:00+04:00",
                }),
            }])
        return _mk_response(content=(
            "27 მაისს, 15:00 თავისუფალია. მომწერეთ თქვენი სახელი და "
            "საკონტაქტო ნომერი."
        ))

    monkeypatch.setattr(openai_service, "chat_with_tools", _chat)

    # Turn 1: exact slot check.
    out1 = parent_flow.handle(
        fresh_conversation, "27 მაისს 15:00-ზე შეიძლება?",
    )
    assert "თავისუფალია" in out1 or "შესაძლებელია" in out1
    pending = fresh_conversation.pending_booking
    assert pending is not None
    assert pending["user_confirmed_datetime"] is True
    assert pending["source"] == "user_requested_exact_slot"
    assert not booked

    # Turn 2: name + phone — deterministic commit.
    # Engine must NOT be consulted when the pre-engine commit succeeds.
    monkeypatch.setattr(
        openai_service, "chat_with_tools",
        lambda **kwargs: pytest.fail("engine should be skipped on commit"),
    )
    out2 = parent_flow.handle(fresh_conversation, "ლელა 595999733")
    assert len(booked) == 1
    assert fresh_conversation.lead.calendly_booked is True
    assert fresh_conversation.state == "DONE"
    assert fresh_conversation.pending_booking is None
    assert fresh_conversation.lead.booked_datetime_iso == "2030-05-27T15:00:00+04:00"
    assert any(kw in out2 for kw in ("ჩაგინიშნე", "15:00", "მენეჯერი"))


# -- PATCH 6.E — get_available_slots truncation does not block exact slot -


def test_patch6_truncated_slot_list_does_not_imply_unavailable(
    monkeypatch, fresh_conversation, camp_registration_open,):
    """Even if get_available_slots returns only 6 morning slots,
    check_consultation_slot for an afternoon slot must still succeed
    when Calendar+business-hours say it's free."""
    from app.services import calendar_service

    # Stub get_free_slots to return ONLY morning slots, mimicking the
    # live truncation symptom.
    monkeypatch.setattr(
        calendar_service, "get_free_slots",
        lambda *a, **k: [
            {"date": "27 მაისი", "time": "10:00",
             "datetime_iso": "2030-05-27T10:00:00+04:00"},
            {"date": "27 მაისი", "time": "10:30",
             "datetime_iso": "2030-05-27T10:30:00+04:00"},
        ],
    )
    monkeypatch.setattr(
        calendar_service, "is_within_business_hours",
        lambda dt, dur=30: (True, ""),
    )
    monkeypatch.setattr(
        calendar_service, "check_slot_calendar_only",
        lambda dt, dur=30: True,
    )

    lead = Lead(sender_id="x", platform="instagram", segment="PARENT")
    fresh_conversation.lead = lead
    executor = ParentToolExecutor(
        conversation=fresh_conversation, lead=lead,
        sender_id="x", platform="instagram",
    )
    # The exact-slot tool must report 15:00 as available even though
    # 15:00 is NOT in the truncated get_available_slots list.
    result = executor.execute(TOOL_CHECK_CONSULTATION_SLOT, {
        "datetime_iso": "2030-05-27T15:00:00+04:00",
    })
    assert result["available"] is True
    assert result["calendar_available"] is True
    assert result["reason"] == ""


# =========================================================================
# P3-C PATCH 7 — final QA: time-change, decline, adult intents, wording
# =========================================================================


# -- PATCH 7.A — time-change before booking finalisation -----------------


def _stub_calendar_for_commit(monkeypatch, busy_iso=None):
    """Helper that wires Calendar layer for time-change tests.

    `busy_iso` (optional) marks one ISO datetime as Calendar-busy so
    tests can simulate the "new time unavailable" branch.
    """
    from app.services import (
        calendar_service, notification_service, openai_service, sheets_service,
    )

    monkeypatch.setattr(
        calendar_service, "is_within_business_hours",
        lambda dt, dur=30: (True, ""),
    )
    monkeypatch.setattr(
        calendar_service, "check_slot_calendar_only",
        lambda dt, dur=30: dt.isoformat() != busy_iso if busy_iso else True,
    )
    monkeypatch.setattr(
        calendar_service, "check_slot_available",
        lambda dt, dur=30: dt.isoformat() != busy_iso if busy_iso else True,
    )
    monkeypatch.setattr(
        calendar_service, "get_free_slots",
        lambda *a, **k: [
            {"date": "28 მაისი", "time": "11:00",
             "datetime_iso": "2030-05-28T11:00:00+04:00"},
            {"date": "28 მაისი", "time": "14:00",
             "datetime_iso": "2030-05-28T14:00:00+04:00"},
        ],
    )
    monkeypatch.setattr(sheets_service, "create_lead", lambda lead: True)
    monkeypatch.setattr(
        notification_service, "send_manager_notification",
        lambda lead, summary: True,
    )
    monkeypatch.setattr(openai_service, "generate_summary", lambda h: "ქართული.")


# The legacy `_parse_booking_datetime` uses `datetime.now().year` to fill
# in the year (and advances to next year only when the day is strictly
# in the past). Mirror that semantics so the helper agrees with the
# production parser regardless of clock-time within the same calendar
# day — earlier `candidate <= now` form rolled forward when the test
# ran in the afternoon on the exact date used in the message, which
# also triggered the executor's `datetime_in_past` guard.
def _next_year_iso(month: int, day: int, hh: int, mm: int = 0) -> str:
    from datetime import datetime as _dt, date as _date
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("Asia/Tbilisi")
    now = _dt.now(tz)
    year = now.year
    if _date(year, month, day) < now.date():
        year += 1
    return _dt(year, month, day, hh, mm, tzinfo=tz).isoformat()


def test_patch7_time_change_updates_pending_iso(
    enable_engine, monkeypatch, fresh_conversation, camp_registration_open,):
    from app.services import calendar_service, messenger_service, openai_service

    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    # After the time-change commit hook returns None (still missing
    # name/phone), parent_flow.handle continues into the engine. Block
    # any further LLM tool calls so the engine cannot re-invoke
    # ``check_consultation_slot`` (which would rewrite
    # ``pending["source"]`` back to ``user_requested_exact_slot``).
    monkeypatch.setattr(
        openai_service, "chat_with_tools",
        lambda **kwargs: _mk_response(content=""),
    )
    _stub_calendar_for_commit(monkeypatch)
    booked: list = []
    monkeypatch.setattr(
        calendar_service, "book_slot",
        lambda **kwargs: (booked.append(kwargs), setattr(kwargs["lead"], "calendar_event_id", "evt_mock_test_id"))[0] or True,
    )

    # Use a safely-future month/day so neither the test helper nor the
    # production parser collides with today's date (env-bound issue when
    # the suite happens to run on the exact day-of-month used here).
    old_iso = _next_year_iso(7, 28, 13)
    new_iso = _next_year_iso(7, 28, 15)

    fresh_conversation.lead = Lead(
        sender_id=fresh_conversation.sender_id, platform="instagram",
        segment="PARENT", child_age="10",
    )
    fresh_conversation.pending_booking = {
        "requested_datetime_iso": old_iso,
        "requested_date_text": "28 ივლისი",
        "requested_time_text": "13:00",
        "selected_slot_display": "28 ივლისი, 13:00",
        "user_confirmed_datetime": True,
        "source": "user_selected_slot",
        "missing_fields": ["name", "phone"],
        "created_at": "2026-05-25T10:00:00",
        "attempts": 0,
    }

    parent_flow.handle(
        fresh_conversation, "ახლა ვიფიქრე და 28 ივლისს 15:00 მირჩევნია",
    )
    pending = fresh_conversation.pending_booking or {}
    assert pending["requested_datetime_iso"] == new_iso
    assert pending["source"] == "user_changed_slot"
    assert not booked  # no commit on time-change turn


def test_patch7_time_change_then_name_phone_books_new_slot(
    enable_engine, monkeypatch, fresh_conversation, camp_registration_open,):
    from app.services import calendar_service, messenger_service

    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    _stub_calendar_for_commit(monkeypatch)
    booked: list = []
    monkeypatch.setattr(
        calendar_service, "book_slot",
        lambda **kwargs: (booked.append(kwargs), setattr(kwargs["lead"], "calendar_event_id", "evt_mock_test_id"))[0] or True,
    )

    # Use a safely-future month/day so the executor's `datetime_in_past`
    # guard doesn't block the booking when this suite runs late in the
    # day on the exact date the test message references.
    old_iso = _next_year_iso(7, 28, 13)
    new_iso = _next_year_iso(7, 28, 15)

    fresh_conversation.lead = Lead(
        sender_id=fresh_conversation.sender_id, platform="instagram",
        segment="PARENT", child_age="10",
    )
    fresh_conversation.pending_booking = {
        "requested_datetime_iso": old_iso,
        "user_confirmed_datetime": True,
        "source": "user_selected_slot",
        "missing_fields": ["name", "phone"],
    }

    # Turn 1: change slot.
    parent_flow.handle(
        fresh_conversation, "ახლა ვიფიქრე და 28 ივლისს 15:00 მირჩევნია",
    )
    # Turn 2: name+phone.
    parent_flow.handle(fresh_conversation, "ლელა 595999733")
    assert len(booked) == 1
    assert booked[0]["datetime_iso"] == new_iso
    assert fresh_conversation.lead.calendly_booked is True
    assert fresh_conversation.state == "DONE"


def test_patch7_time_change_unavailable_restores_original_pending(
    enable_engine, monkeypatch, fresh_conversation, camp_registration_open,):
    """When the NEW time is busy, the old pending slot must NOT be
    silently committed; pending is restored and the user is asked."""
    from app.services import calendar_service, messenger_service

    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    # Safely-future month/day so helper and production parser agree on
    # the year regardless of today's date.
    old_iso = _next_year_iso(7, 28, 13)
    new_iso = _next_year_iso(7, 28, 15)
    _stub_calendar_for_commit(monkeypatch, busy_iso=new_iso)
    booked: list = []
    monkeypatch.setattr(
        calendar_service, "book_slot",
        lambda **kwargs: (booked.append(kwargs), setattr(kwargs["lead"], "calendar_event_id", "evt_mock_test_id"))[0] or True,
    )

    fresh_conversation.lead = Lead(
        sender_id=fresh_conversation.sender_id, platform="instagram",
        segment="PARENT", child_age="10",
    )
    fresh_conversation.pending_booking = {
        "requested_datetime_iso": old_iso,
        "requested_date_text": "28 ივლისი",
        "requested_time_text": "13:00",
        "selected_slot_display": "28 ივლისი, 13:00",
        "user_confirmed_datetime": True,
        "source": "user_selected_slot",
        "missing_fields": ["name", "phone"],
    }

    out = parent_flow.handle(
        fresh_conversation, "ახლა ვიფიქრე და 28 ივლისს 15:00 მირჩევნია",
    )
    assert not booked, "must not silently commit the old slot"
    pending = fresh_conversation.pending_booking or {}
    assert pending["requested_datetime_iso"] == old_iso
    assert "13:00" in out
    assert "დაკავებულია" in out


def test_patch7_no_time_change_signal_is_a_noop(
    enable_engine, monkeypatch, fresh_conversation, camp_registration_open,):
    """Messages that don't look like time changes must not touch
    pending_booking. They should fall through to the existing commit
    flow (which will extract name+phone)."""
    from app.services import calendar_service, messenger_service

    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    _stub_calendar_for_commit(monkeypatch)
    booked: list = []
    monkeypatch.setattr(
        calendar_service, "book_slot",
        lambda **kwargs: (booked.append(kwargs), setattr(kwargs["lead"], "calendar_event_id", "evt_mock_test_id"))[0] or True,
    )

    # Safely-future month/day so the executor's `datetime_in_past`
    # guard doesn't block a same-day-past slot during late-day test runs.
    old_iso = _next_year_iso(7, 28, 13)
    fresh_conversation.lead = Lead(
        sender_id=fresh_conversation.sender_id, platform="instagram",
        segment="PARENT", child_age="10",
    )
    fresh_conversation.pending_booking = {
        "requested_datetime_iso": old_iso,
        "user_confirmed_datetime": True,
        "source": "user_selected_slot",
        "missing_fields": ["name", "phone"],
    }

    parent_flow.handle(fresh_conversation, "ლელა 595999733")
    # Books the original 13:00 slot.
    assert len(booked) == 1
    assert booked[0]["datetime_iso"] == old_iso


# -- PATCH 7.B — decline / will-think wording -----------------------------


def test_patch7_will_think_returns_short_supportive_close(
    enable_engine, monkeypatch, fresh_conversation,
):
    from app.services import messenger_service, openai_service

    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    # Engine must NOT be consulted — deterministic decline runs first.
    monkeypatch.setattr(
        openai_service, "chat_with_tools",
        lambda **kwargs: pytest.fail("engine should not run on decline"),
    )

    out = parent_flow.handle(fresh_conversation, "დავფიქრდები მადლობა")
    assert "მშვიდად დაფიქრდით" in out or "რა თქმა უნდა" in out
    # Forbidden duplications and robotic phrases.
    assert "შემეხმიანეთ დაგეხმაროთ" not in out
    assert "თუ მომავალში რაიმე კითხვა გაგიჩნდებათ, თუ" not in out
    # stopped_after captured by conversation service via process_message,
    # NOT by direct parent_flow.handle. So we only verify wording here.


def test_patch7_hard_decline_clears_pending_booking_and_no_cta(
    enable_engine, monkeypatch, fresh_conversation,
):
    from app.services import messenger_service, openai_service

    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    monkeypatch.setattr(
        openai_service, "chat_with_tools",
        lambda **kwargs: pytest.fail("engine should not run on hard decline"),
    )
    fresh_conversation.pending_booking = {
        "requested_datetime_iso": "2030-05-28T13:00:00+04:00",
        "user_confirmed_datetime": True,
        "source": "user_selected_slot",
    }

    out = parent_flow.handle(fresh_conversation, "არა მადლობა")
    assert "გასაგებია" in out
    assert fresh_conversation.pending_booking is None
    # No sales CTA after a hard decline.
    for cta in ("ჩაგწერ", "კონსულტაცი", "ჩავნიშნ"):
        assert cta not in out, f"CTA leaked: {cta!r}"


def test_patch7_decline_marker_captured_by_conversation_service(monkeypatch):
    """conversation_service marker writer continues to set
    followup_blocked_reason='declined' even when the deterministic
    decline handler short-circuits the engine."""
    from app.services import conversation_service, messenger_service, openai_service

    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    monkeypatch.setattr(openai_service, "detect_start_intent", lambda m: "GREETING")
    conversation_service.process_message(
        "sim-p7-decline", "გამარჯობა", "instagram",
    )
    conversation_service.process_message(
        "sim-p7-decline", "არა მადლობა", "instagram",
    )
    conv = conversation_service.conversations["sim-p7-decline"]
    assert conv.followup_blocked_reason == "declined"


def test_patch7_will_think_marker_captured_by_conversation_service(monkeypatch):
    from app.services import conversation_service, messenger_service, openai_service

    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    monkeypatch.setattr(openai_service, "detect_start_intent", lambda m: "GREETING")
    conversation_service.process_message(
        "sim-p7-think", "გამარჯობა", "instagram",
    )
    conversation_service.process_message(
        "sim-p7-think", "დავფიქრდები მადლობა", "instagram",
    )
    conv = conversation_service.conversations["sim-p7-think"]
    assert conv.stopped_after == "will_think"


def test_patch7_decline_does_not_trip_on_questions():
    """A message with '?' must not be treated as a decline even when
    a decline phrase happens to appear inside it."""
    from app.flows.parent_flow import _maybe_handle_decline_engine
    conv = Conversation(sender_id="x", platform="instagram")
    out = _maybe_handle_decline_engine(conv, "არ მინდა ვიცი ფასი?")
    assert out is None


# -- PATCH 7.C — adult global intent guard --------------------------------


def test_patch7_adult_identity_breaks_event_loop():
    from app.flows import adult_flow

    conv = Conversation(sender_id="sim-p7-adult-id", platform="instagram")
    conv.segment = "ADULT"
    conv.state = "SHOW_EVENTS"
    out = adult_flow.handle(conv, "შენ ვინ ხარ?")
    assert "ასისტენტი" in out
    assert "რომელი საღამო" not in out


def test_patch7_adult_human_vs_robot_breaks_event_loop():
    from app.flows import adult_flow

    conv = Conversation(sender_id="sim-p7-adult-bot", platform="instagram")
    conv.segment = "ADULT"
    conv.state = "ANSWER_QUESTIONS"
    out = adult_flow.handle(conv, "ადამიანი ხარ თუ რობოტი?")
    assert "ონლაინ ასისტენტი" in out
    assert "რომელი საღამო" not in out


def test_patch7_adult_greeting_breaks_event_loop():
    from app.flows import adult_flow

    conv = Conversation(sender_id="sim-p7-adult-hi", platform="instagram")
    conv.segment = "ADULT"
    conv.state = "SHOW_EVENTS"
    out = adult_flow.handle(conv, "გამარჯობა")
    assert "გამარჯობა" in out


def test_patch7_adult_thanks_breaks_event_loop():
    from app.flows import adult_flow

    conv = Conversation(sender_id="sim-p7-adult-thx", platform="instagram")
    conv.segment = "ADULT"
    conv.state = "ANSWER_QUESTIONS"
    out = adult_flow.handle(conv, "მადლობა")
    assert "სიამოვნებით" in out


def test_patch7_adult_decline_breaks_event_loop():
    from app.flows import adult_flow

    conv = Conversation(sender_id="sim-p7-adult-no", platform="instagram")
    conv.segment = "ADULT"
    conv.state = "SHOW_EVENTS"
    out = adult_flow.handle(conv, "არ მინდა")
    assert "გასაგებია" in out
    assert "რომელი საღამო" not in out


def test_patch7_adult_manager_request_asks_phone_when_unknown():
    from app.flows import adult_flow

    conv = Conversation(sender_id="sim-p7-adult-mgr", platform="instagram")
    conv.segment = "ADULT"
    conv.state = "ANSWER_QUESTIONS"
    out = adult_flow.handle(conv, "მენეჯერს დამაკავშირეთ")
    assert "ნომერი" in out or "ნომერ" in out


def test_patch7_adult_state_machine_still_works():
    """Non-global-intent input continues to drive the state machine."""
    from app.flows import adult_flow

    conv = Conversation(sender_id="sim-p7-adult-flow", platform="instagram")
    conv.segment = "ADULT"
    conv.state = "START"
    out = adult_flow.handle(conv, "ღონისძიება მაინტერესებს")
    # State must have advanced past START as the state machine runs.
    assert conv.state != "START"
    assert out


# -- PATCH 7.D — sanitiser wording polish ---------------------------------


def test_patch7_sanitiser_removes_precisely():
    from app.agent.llm.parent_llm_engine import sanitise_response_wording
    out = sanitise_response_wording("Precisely, ეს ასაკი შესაფერისია.")
    assert "precisely" not in out
    assert "Precisely" not in out


def test_patch7_sanitiser_fixes_screen_genitive():
    from app.agent.llm.parent_llm_engine import sanitise_response_wording
    out = sanitise_response_wording("ბავშვი ეკრან რეჟიმიდან გამოდის.")
    assert "ეკრან რეჟიმიდან" not in out
    assert "ეკრანის რეჟიმიდან" in out


def test_patch7_sanitiser_naturalises_age_suitability():
    from app.agent.llm.parent_llm_engine import sanitise_response_wording
    for original in (
        "ბავშვი სრულად ერგება ბანაკის ასაკობრივ ჩარჩოს.",
        "სრულად ერგება 9–17 წლის ბავშვების ბანაკს.",
        "სრულად ერგება.",
    ):
        out = sanitise_response_wording(original)
        assert "სრულად ერგება" not in out, f"failed: {original!r}"


def test_patch7_sanitiser_collapses_duplicated_tu_clauses():
    from app.agent.llm.parent_llm_engine import sanitise_response_wording
    out = sanitise_response_wording(
        "თუ მომავალში რაიმე კითხვა გაგიჩნდებათ, თუ კიდევ რაიმე "
        "გაგიჩნდებათ, შემეხმიანეთ დაგეხმაროთ."
    )
    assert "თუ მომავალში რაიმე კითხვა გაგიჩნდებათ, თუ" not in out
    assert "შემეხმიანეთ დაგეხმაროთ" not in out
    assert "მომწერეთ და დაგეხმარებით" in out


def test_patch7_engine_strips_combined_patch7_phrases_end_to_end(
    enable_engine, monkeypatch, fresh_conversation,
):
    from app.services import messenger_service, openai_service

    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    monkeypatch.setattr(
        openai_service, "chat_with_tools",
        lambda **kwargs: _mk_response(content=(
            "Precisely, ბავშვი სრულად ერგება ბანაკის ასაკობრივ ჩარჩოს. "
            "ეკრან რეჟიმიდან გამოდის. თუ მომავალში რაიმე კითხვა "
            "გაგიჩნდებათ, თუ კიდევ რაიმე გაგიჩნდებათ, შემეხმიანეთ "
            "დაგეხმაროთ."
        )),
    )
    # PATCH 8 — non-greeting trigger so the engine runs.
    out = parent_flow.handle(fresh_conversation, "ბანაკი მაინტერესებს")
    for forbidden in (
        "precisely",
        "Precisely",
        "ეკრან რეჟიმიდან",
        "სრულად ერგება",
        "შემეხმიანეთ დაგეხმაროთ",
        "თუ მომავალში რაიმე კითხვა გაგიჩნდებათ, თუ",
    ):
        assert forbidden not in out, f"leaked: {forbidden!r}  →  {out!r}"


# -- PATCH 7.E — test isolation helper ------------------------------------


def test_patch7_reset_conversation_for_sender_clears_per_sender_state():
    from app.services import conversation_service
    from app.agent.tools import parent_tool_executor

    sender_id = "sim-p7-reset"
    conv = Conversation(sender_id=sender_id, platform="instagram")
    conversation_service.conversations[sender_id] = conv
    parent_flow.available_slots[sender_id] = [{"datetime_iso": "x"}]
    parent_flow.slots_shown_for_state[sender_id] = True
    parent_tool_executor._last_slots_by_sender[sender_id] = [{}]
    parent_tool_executor.manager_notified_for_conversation[sender_id] = True
    parent_tool_executor.book_consultation_success_for_conversation[sender_id] = True

    cleared = conversation_service.reset_conversation_for_sender(sender_id)
    assert cleared is True
    assert sender_id not in conversation_service.conversations
    assert sender_id not in parent_flow.available_slots
    assert sender_id not in parent_flow.slots_shown_for_state
    assert sender_id not in parent_tool_executor._last_slots_by_sender
    assert sender_id not in parent_tool_executor.manager_notified_for_conversation
    assert sender_id not in parent_tool_executor.book_consultation_success_for_conversation


def test_patch7_reset_conversation_for_sender_isolated():
    """Resetting one sender must NOT clear another sender's state."""
    from app.services import conversation_service

    conv_a = Conversation(sender_id="sim-p7-iso-a", platform="instagram")
    conv_b = Conversation(sender_id="sim-p7-iso-b", platform="instagram")
    conversation_service.conversations["sim-p7-iso-a"] = conv_a
    conversation_service.conversations["sim-p7-iso-b"] = conv_b

    conversation_service.reset_conversation_for_sender("sim-p7-iso-a")
    assert "sim-p7-iso-a" not in conversation_service.conversations
    assert "sim-p7-iso-b" in conversation_service.conversations


# =========================================================================
# P3-C PATCH 8 — final wording cleanup
# =========================================================================


# -- PATCH 8.A — static welcome bypass for first-bot-reply at START ------
#
# The parent flow opens every conversation with the static
# PARENT_WELCOME two-option menu — regardless of what the user wrote
# first. The LLM engine is never consulted on the bot's first reply at
# state=START.


def _build_truly_fresh_conv(sender_id: str = "sim-fresh"):
    """Conversation with NO prior assistant turn, so the static
    PARENT_WELCOME bypass actually fires. The module-level
    ``fresh_conversation`` fixture pre-seeds a fake assistant turn so
    the bulk of the engine tests skip the bypass; static-welcome tests
    use this helper instead.
    """
    return Conversation(sender_id=sender_id, platform="instagram")


def test_patch8_pure_greeting_returns_static_menu_engine_on(
    enable_engine, monkeypatch,
):
    from app.services import openai_service

    monkeypatch.setattr(
        openai_service, "chat_with_tools",
        lambda **kwargs: pytest.fail(
            "engine must NOT be consulted at START on first bot reply",
        ),
    )
    conv = _build_truly_fresh_conv("sim-p8-greeting-engine-on")
    conv.segment = "PARENT"  # locked, bypass conversation_service
    out = parent_flow.handle(conv, "გამარჯობა")
    assert "გვითხარით, რა გაინტერესებთ" in out
    assert "ბავშვების საზაფხულო ბანაკი" in out
    assert "ზრდასრულთა კულტურული საღამოები" in out


def test_patch8_pure_greeting_returns_static_menu_engine_off(
    disable_engine, monkeypatch,
):
    """Static welcome must also work without the engine flag — it's a
    brand decision, not an engine-only behaviour."""
    monkeypatch.setattr(
        parent_flow, "_handle_impl",
        lambda c, m: pytest.fail("legacy must NOT run on first bot reply at START"),
    )
    conv = _build_truly_fresh_conv("sim-p8-greeting-engine-off")
    conv.segment = "PARENT"
    out = parent_flow.handle(conv, "გამარჯობა")
    assert "გვითხარით, რა გაინტერესებთ" in out


def test_parent_greeting_intent_first_message_skips_menu(
    enable_engine, monkeypatch,
):
    """P0 Live Demo UX — ISSUE 1: when the parent's first message has clear
    camp intent ("საზაფხულო ბანაკი მაინტერესებს"), the bot must NOT re-ask
    the generic two-option menu — it greets and continues the camp flow.
    The static-welcome bypass yields to the engine, which replies in
    Georgian. (Updated 2026-06-13 — was: returns the static menu.)
    """
    from app.services import openai_service

    monkeypatch.setattr(
        openai_service, "chat_with_tools",
        lambda **kwargs: _mk_response(content=(
            "გამარჯობა. ბანაკის შესახებ დაგეხმარებით. "
            "მითხარით, რამდენი წლისაა თქვენი შვილი?"
        )),
    )
    conv = _build_truly_fresh_conv("sim-greeting-intent-first")
    conv.segment = "PARENT"
    # The detector itself yields (returns None) for clear camp intent.
    assert parent_flow._maybe_static_welcome(
        conv, "საზაფხულო ბანაკი მაინტერესებს",
    ) is None
    out = parent_flow.handle(conv, "საზაფხულო ბანაკი მაინტერესებს")
    assert "გვითხარით, რა გაინტერესებთ" not in out


def test_parent_greeting_price_first_message_skips_menu(
    enable_engine, monkeypatch,
):
    """P0 Live Demo UX — ISSUE 1: an explicit camp-price-interest first
    message ("ბანაკის ფასი მაინტერესებს") is clear camp intent — it skips
    the generic menu and continues the camp flow (engine consulted, replies
    in Georgian). (Updated 2026-06-13 — was: returns the static menu.)
    """
    from app.services import openai_service

    monkeypatch.setattr(
        openai_service, "chat_with_tools",
        lambda **kwargs: _mk_response(content=(
            "ბანაკის სრული ღირებულებაა 2150 ლარი. "
            "მითხარით, რამდენი წლისაა თქვენი შვილი?"
        )),
    )
    conv = _build_truly_fresh_conv("sim-greeting-price-first")
    conv.segment = "PARENT"
    assert parent_flow._maybe_static_welcome(
        conv, "ბანაკის ფასი მაინტერესებს",
    ) is None
    out = parent_flow.handle(conv, "ბანაკის ფასი მაინტერესებს")
    assert "გვითხარით, რა გაინტერესებთ" not in out


def test_parent_greeting_does_not_contain_mogesalmebti(
    enable_engine, monkeypatch,
):
    """The static menu must not contain 'მოგესალმებით' — the rejected
    LLM-generated greeting starts with that word.
    """
    from app.services import openai_service

    monkeypatch.setattr(
        openai_service, "chat_with_tools",
        lambda **kwargs: pytest.fail("engine must NOT run"),
    )
    conv = _build_truly_fresh_conv("sim-greeting-no-mog")
    conv.segment = "PARENT"
    out = parent_flow.handle(conv, "გამარჯობა")
    assert "მოგესალმებით" not in out


def test_parent_greeting_does_not_immediately_ask_age(
    enable_engine, monkeypatch,
):
    """The first bot reply must NOT contain the age question — the age
    question is asked only after the user picks the camp option on the
    next turn.
    """
    from app.services import openai_service

    monkeypatch.setattr(
        openai_service, "chat_with_tools",
        lambda **kwargs: pytest.fail("engine must NOT run"),
    )
    conv = _build_truly_fresh_conv("sim-greeting-no-age")
    conv.segment = "PARENT"
    out = parent_flow.handle(conv, "გამარჯობა")
    assert "რამდენი წლისაა" not in out
    assert "რამდენი წლისაა თქვენი შვილი" not in out


def test_parent_greeting_returns_exact_static_template():
    """First bot reply at START is byte-identical to PARENT_WELCOME."""
    from data.prompts import PARENT_WELCOME

    conv = _build_truly_fresh_conv("sim-greeting-exact")
    conv.segment = "PARENT"
    out = parent_flow._maybe_static_welcome(conv, "გამარჯობა")
    assert out == PARENT_WELCOME.strip()


def test_parent_greeting_bypass_does_not_fire_after_first_bot_reply(
    enable_engine, monkeypatch, camp_registration_open,
):
    """Once the bot has replied once, subsequent state=START turns
    route through the engine — the static welcome only fires on the
    very first reply.
    """
    from app.services import openai_service

    monkeypatch.setattr(
        openai_service, "chat_with_tools",
        lambda **kwargs: _mk_response(content="რამდენი წლისაა შვილი?"),
    )
    conv = _build_truly_fresh_conv("sim-greeting-bypass-once")
    conv.segment = "PARENT"
    # Simulate: bot already replied once with the menu earlier.
    conv.history.append({"role": "assistant", "content": "(menu already sent)"})

    out = parent_flow.handle(conv, "ბავშვების საზაფხულო ბანაკი")
    assert "რამდენი წლისაა" in out
    assert "გვითხარით, რა გაინტერესებთ" not in out


def test_patch8_static_welcome_only_at_start_state():
    """Once the parent is past START, a bare 'გამარჯობა' must NOT
    short-circuit (it might be a polite reopen mid-conversation; the
    state machine continues to handle it)."""
    conv = Conversation(sender_id="sim-p8-not-start", platform="instagram")
    conv.state = "ASK_CHALLENGE"
    out = parent_flow._maybe_static_welcome(conv, "გამარჯობა")
    assert out is None


def test_patch8_pure_greeting_token_detection():
    from app.flows.parent_flow import _is_pure_greeting_token
    assert _is_pure_greeting_token("გამარჯობა")
    assert _is_pure_greeting_token("გამარჯობა!")
    assert _is_pure_greeting_token("hello")
    assert _is_pure_greeting_token("Hi")
    # Anything with extra content is not a pure greeting.
    assert not _is_pure_greeting_token("გამარჯობა, ფასი მაინტერესებს")
    assert not _is_pure_greeting_token("ბანაკი მაინტერესებს")
    assert not _is_pure_greeting_token("")


def test_parent_greeting_sanitiser_replaces_mogesalmebti_leak():
    """Belt-and-braces: if a later turn produces the rejected
    LLM-generated greeting, the sanitiser strips it.
    """
    from app.agent.llm.parent_llm_engine import sanitise_response_wording

    out = sanitise_response_wording(
        "მოგესალმებით! როგორ შემიძლია დაგეხმაროთ ბავშვთა საზაფხულო "
        "ბანაკის შესახებ?",
    )
    assert "მოგესალმებით" not in out
    assert "გვითხარით, რა გაინტერესებთ" in out


# -- PATCH 8.B — adult wording cleanup ----------------------------------


def test_patch8_sanitiser_removes_erti_tutshi():
    from app.agent.llm.parent_llm_engine import sanitise_response_wording
    out = sanitise_response_wording(
        "გასაგებია, ზრდასრულთა ღონისძიებებზე გადაგამისამართებთ — "
        "ერთ წუთში გავხსნი თქვენთვის სწორ მიმართულებას."
    )
    assert "ერთ წუთში" not in out
    assert "გადაგამისამართებთ —" not in out


def test_patch8_sanitiser_removes_other_delayed_promises():
    from app.agent.llm.parent_llm_engine import sanitise_response_wording
    for original in (
        "ერთ წუთში გავხსნი თქვენთვის სწორ მიმართულებას.",
        "ცოტა ხანში მოგწერთ.",
    ):
        out = sanitise_response_wording(original)
        assert "ერთ წუთში" not in out
        assert "ცოტა ხანში მოგწერთ" not in out


def test_patch8_adult_switch_engine_response_clean_end_to_end(
    enable_engine, monkeypatch, fresh_conversation,
):
    from app.services import messenger_service, openai_service

    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    monkeypatch.setattr(
        openai_service, "chat_with_tools",
        lambda **kwargs: _mk_response(content=(
            "გასაგებია, ზრდასრულთა ღონისძიებებზე გადაგამისამართებთ — "
            "ერთ წუთში გავხსნი თქვენთვის სწორ მიმართულებას."
        )),
    )
    out = parent_flow.handle(
        fresh_conversation, "ზრდასრულთა ღონისძიება მაინტერესებს",
    )
    assert "ერთ წუთში" not in out


# -- PATCH 8.C — ineligible-age CTA scrubber ----------------------------


def _set_ineligible_lead(conversation, age: str = "8") -> None:
    conversation.lead = Lead(
        sender_id=conversation.sender_id, platform="instagram",
        segment="PARENT", child_age=age,
    )


def test_patch8_strip_cta_removes_consultation_offer_for_ineligible():
    conv = Conversation(sender_id="x", platform="instagram")
    _set_ineligible_lead(conv, age="8")
    response = (
        "ეს ბანაკი 9–17 წლის ბავშვებისთვისაა, ამიტომ ჩაწერას ვერ "
        "დაგიდასტურებთ. თუ გნებავთ, კონსულტაციაზე ჩაგწერთ."
    )
    out = parent_flow._strip_consultation_cta_if_ineligible(conv, response)
    assert "კონსულტაციაზე ჩაგწერთ" not in out
    assert "მენეჯერთან" in out


def test_patch8_strip_cta_handles_multiple_cta_variants():
    conv = Conversation(sender_id="x", platform="instagram")
    _set_ineligible_lead(conv, age="7")
    response = (
        "ეს ბანაკი 9–17 წლისაა. კონსულტაცია ჩავნიშნოთ. "
        "კონსულტაცია ჩაგინიშნავთ. თუ გნებავთ, კონსულტაციაზე ჩაგწერთ."
    )
    out = parent_flow._strip_consultation_cta_if_ineligible(conv, response)
    for cta in (
        "კონსულტაცია ჩავნიშნოთ",
        "კონსულტაცია ჩაგინიშნავთ",
        "კონსულტაციაზე ჩაგწერთ",
    ):
        assert cta not in out, f"leaked: {cta!r}"


def test_patch8_strip_cta_is_noop_for_eligible_lead():
    """Eligible age must NOT have its consultation CTA scrubbed."""
    conv = Conversation(sender_id="x", platform="instagram")
    conv.lead = Lead(
        sender_id="x", platform="instagram", segment="PARENT",
        child_age="14",
    )
    response = (
        "ბანაკის ფასი 2150 ლარია. თუ გნებავთ, კონსულტაციაზე ჩაგწერთ."
    )
    out = parent_flow._strip_consultation_cta_if_ineligible(conv, response)
    assert "კონსულტაციაზე ჩაგწერთ" in out


def test_patch8_strip_cta_is_noop_for_unknown_age():
    conv = Conversation(sender_id="x", platform="instagram")
    conv.lead = Lead(
        sender_id="x", platform="instagram", segment="PARENT",
        child_age="",
    )
    response = "თუ გნებავთ, კონსულტაციაზე ჩაგწერთ."
    out = parent_flow._strip_consultation_cta_if_ineligible(conv, response)
    assert out == response


def test_patch8_ineligible_age_18_strips_cta():
    conv = Conversation(sender_id="x", platform="instagram")
    _set_ineligible_lead(conv, age="18")
    response = (
        "ეს ბანაკი 9–17 წლისაა. თუ გნებავთ, კონსულტაციაზე ჩაგწერთ."
    )
    out = parent_flow._strip_consultation_cta_if_ineligible(conv, response)
    assert "კონსულტაციაზე ჩაგწერთ" not in out


def test_patch8_ineligible_age_engine_response_end_to_end(
    enable_engine, monkeypatch, fresh_conversation,
):
    """End-to-end: engine emits CTA, parent_flow scrubs it because
    lead.child_age=8 is ineligible."""
    from app.services import messenger_service, openai_service

    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    _set_ineligible_lead(fresh_conversation, age="8")
    monkeypatch.setattr(
        openai_service, "chat_with_tools",
        lambda **kwargs: _mk_response(content=(
            "ეს ბანაკი 9–17 წლის ბავშვებისთვისაა. "
            "თუ გნებავთ, კონსულტაციაზე ჩაგწერთ."
        )),
    )
    out = parent_flow.handle(fresh_conversation, "more details please")
    assert "კონსულტაციაზე ჩაგწერთ" not in out
    assert "მენეჯერთან" in out


# -- PATCH 8.D — generic assistant greeting rewrites --------------------


def test_patch8_sanitiser_replaces_rogor_shemidzlia():
    from app.agent.llm.parent_llm_engine import sanitise_response_wording
    out = sanitise_response_wording(
        "გამარჯობა! როგორ შემიძლია დაგეხმაროთ დღეს?"
    )
    assert "როგორ შემიძლია დაგეხმაროთ დღეს" not in out
    assert "გვითხარით, რა გაინტერესებთ" in out


def test_patch8_sanitiser_replaces_robotic_assistant_closing():
    from app.agent.llm.parent_llm_engine import sanitise_response_wording
    out = sanitise_response_wording(
        "თუ რაიმეში დაგჭირდებათ დახმარება, მზად ვარ დაგეხმაროთ."
    )
    assert "თუ რაიმეში დაგჭირდებათ დახმარება" not in out
    assert "მზად ვარ დაგეხმაროთ" not in out


# -- PATCH 8.E — _age_status_for_lead helper ---------------------------


def test_patch8_age_status_helper():
    """The local helper must agree with the engine's classification."""
    from app.flows.parent_flow import _age_status_for_lead

    eligible = Lead(sender_id="x", platform="instagram", segment="PARENT",
                    child_age="12")
    ineligible_low = Lead(sender_id="x", platform="instagram", segment="PARENT",
                          child_age="7")
    ineligible_high = Lead(sender_id="x", platform="instagram", segment="PARENT",
                           child_age="18")
    unknown = Lead(sender_id="x", platform="instagram", segment="PARENT",
                   child_age="")
    non_numeric = Lead(sender_id="x", platform="instagram", segment="PARENT",
                       child_age="abc")
    assert _age_status_for_lead(eligible) == "eligible"
    assert _age_status_for_lead(ineligible_low) == "ineligible"
    assert _age_status_for_lead(ineligible_high) == "ineligible"
    assert _age_status_for_lead(unknown) == "unknown"
    assert _age_status_for_lead(non_numeric) == "unknown"
    assert _age_status_for_lead(None) == "unknown"


# -- PATCH 8.F — system prompt updated ---------------------------------


def test_patch8_system_prompt_has_ineligible_cta_ban():
    """The on-disk prompt must explicitly forbid the consultation CTA
    for ineligible ages."""
    from app.agent.llm.prompt_loader import load_prompt, reset_cache

    reset_cache()
    text = load_prompt("system_parent_v2")
    assert "კონსულტაციაზე ჩაგწერთ" in text
    # The ban phrase must be present.
    assert "სრულად აკრძალულია" in text


def test_patch8_system_prompt_screen_concern_is_conditional():
    """Prompt must say 'mention screen only if user mentioned it'."""
    from app.agent.llm.prompt_loader import load_prompt, reset_cache

    reset_cache()
    text = load_prompt("system_parent_v2")
    assert "ეკრანის რეჟიმიდან გამოსვლა" in text
    # The conditional language must be there.
    assert "მხოლოდ მაშინ" in text


def test_patch8_system_prompt_adult_switch_example_cleaned():
    """The system prompt example for adult-switch must no longer use
    the misleading "ერთ წუთში გავხსნი" wording. The phrase still
    appears in the forbidden-list as a counter-example — but the
    positive example the LLM is meant to mimic must be the cleaned
    "ზრდასრულთა ღონისძიებებზე დაგეხმარებით" wording."""
    from app.agent.llm.prompt_loader import load_prompt, reset_cache

    reset_cache()
    text = load_prompt("system_parent_v2")
    # The cleaned example must be the only adult-switch positive sample.
    assert "ზრდასრულთა ღონისძიებებზე დაგეხმარებით" in text
    # And the forbidden rule must also be present so the LLM knows not
    # to use it.
    assert "სისტემაში დაგვიანებული მესიჯის გაგზავნა" in text


# =========================================================================
# Post-turn child_age structured-state fallback
# =========================================================================
#
# Belt-and-braces capture in ``parent_llm_engine.maybe_capture_child_age_fallback``
# for the case where the LLM acknowledges the age in prose but never
# calls ``save_lead_info`` on that turn.


def _mk_lead(child_age: str = "") -> Lead:
    return Lead(
        sender_id="age-fb", platform="instagram",
        segment="PARENT", child_age=child_age,
    )


def test_age_fallback_captures_simple_14():
    from app.agent.llm.parent_llm_engine import maybe_capture_child_age_fallback
    lead = _mk_lead()
    maybe_capture_child_age_fallback(lead, "14 წლის")
    assert lead.child_age == "14"


def test_age_fallback_captures_simple_10():
    from app.agent.llm.parent_llm_engine import maybe_capture_child_age_fallback
    lead = _mk_lead()
    maybe_capture_child_age_fallback(lead, "10 წლის ბავშვი")
    assert lead.child_age == "10"


def test_age_fallback_does_not_overwrite_existing_age():
    from app.agent.llm.parent_llm_engine import maybe_capture_child_age_fallback
    lead = _mk_lead(child_age="12")
    maybe_capture_child_age_fallback(lead, "14 წლის")
    assert lead.child_age == "12"


def test_age_fallback_ignores_long_phone_number():
    from app.agent.llm.parent_llm_engine import maybe_capture_child_age_fallback
    lead = _mk_lead()
    maybe_capture_child_age_fallback(lead, "595999733")
    assert lead.child_age == ""


def test_age_fallback_ignores_phone_with_plus995():
    from app.agent.llm.parent_llm_engine import maybe_capture_child_age_fallback
    lead = _mk_lead()
    maybe_capture_child_age_fallback(lead, "ჩემი ნომერია +995595999733")
    assert lead.child_age == ""


def test_age_fallback_rejects_age_above_20():
    """Conservative range — 5..20 inclusive. Adult ages flow through the
    adult-switch / executor eligibility paths, not this fallback."""
    from app.agent.llm.parent_llm_engine import maybe_capture_child_age_fallback
    lead = _mk_lead()
    maybe_capture_child_age_fallback(lead, "50 წლის ვარ")
    assert lead.child_age == ""


def test_age_fallback_rejects_age_below_5():
    from app.agent.llm.parent_llm_engine import maybe_capture_child_age_fallback
    lead = _mk_lead()
    maybe_capture_child_age_fallback(lead, "4 წლისაა")
    assert lead.child_age == ""


def test_age_fallback_two_children_keeps_first_valid():
    """Documented behaviour: the helper takes the FIRST valid age from
    a multi-age message and stops; the LLM can refine via
    ``save_lead_info`` for the second child once the parent commits."""
    from app.agent.llm.parent_llm_engine import maybe_capture_child_age_fallback
    lead = _mk_lead()
    maybe_capture_child_age_fallback(lead, "ორი ბავშვი მყავს 11 და 14 წლის")
    assert lead.child_age == "11"


def test_age_fallback_noop_on_empty_message():
    from app.agent.llm.parent_llm_engine import maybe_capture_child_age_fallback
    lead = _mk_lead()
    maybe_capture_child_age_fallback(lead, "")
    assert lead.child_age == ""


def test_age_fallback_noop_when_no_digits():
    from app.agent.llm.parent_llm_engine import maybe_capture_child_age_fallback
    lead = _mk_lead()
    maybe_capture_child_age_fallback(lead, "გასაგებია, კარგია")
    assert lead.child_age == ""


def test_age_fallback_handles_none_lead():
    """Defensive: never raises on missing lead."""
    from app.agent.llm.parent_llm_engine import maybe_capture_child_age_fallback
    maybe_capture_child_age_fallback(None, "14 წლის")  # type: ignore[arg-type]


def test_age_fallback_does_not_trigger_external_services(monkeypatch):
    """The fallback must be a pure Lead mutation — no Calendar, no
    Sheets, no notification, no Redis."""
    from app.agent.llm.parent_llm_engine import maybe_capture_child_age_fallback
    from app.services import calendar_service, notification_service, sheets_service

    def _explode(*a, **k):
        raise AssertionError("must not be called")

    monkeypatch.setattr(calendar_service, "book_slot", _explode)
    monkeypatch.setattr(sheets_service, "create_lead", _explode)
    monkeypatch.setattr(
        notification_service, "send_manager_notification", _explode,
    )
    lead = _mk_lead()
    maybe_capture_child_age_fallback(lead, "14 წლის")
    assert lead.child_age == "14"


# =========================================================================
# Post-turn challenge structured-state fallback
# =========================================================================


def _mk_lead_with_age(age: str = "14", challenge: str = "") -> Lead:
    return Lead(
        sender_id="chal-fb", platform="instagram",
        segment="PARENT", child_age=age, challenge=challenge,
    )


def test_challenge_fallback_screen_concern():
    from app.agent.llm.parent_llm_engine import maybe_capture_challenge_fallback
    lead = _mk_lead_with_age()
    maybe_capture_challenge_fallback(lead, "ეკრანისგან დისტანცია")
    assert "ეკრან" in (lead.challenge or "")


def test_challenge_fallback_communication():
    from app.agent.llm.parent_llm_engine import maybe_capture_challenge_fallback
    lead = _mk_lead_with_age()
    maybe_capture_challenge_fallback(lead, "კომუნიკაცია უჭირს")
    assert "კომუნიკაცი" in (lead.challenge or "")


def test_challenge_fallback_confidence():
    from app.agent.llm.parent_llm_engine import maybe_capture_challenge_fallback
    lead = _mk_lead_with_age()
    maybe_capture_challenge_fallback(lead, "თავდაჯერებულობა აკლია")
    assert "თავდაჯერ" in (lead.challenge or "")


def test_challenge_fallback_development_keyword():
    from app.agent.llm.parent_llm_engine import maybe_capture_challenge_fallback
    lead = _mk_lead_with_age()
    maybe_capture_challenge_fallback(lead, "ახალი გარემო და განვითარება მინდა")
    captured = lead.challenge or ""
    assert "განვითარ" in captured or "ახალი გარემო" in captured


def test_challenge_fallback_does_not_overwrite_existing():
    from app.agent.llm.parent_llm_engine import maybe_capture_challenge_fallback
    lead = _mk_lead_with_age(challenge="ეკრანი")
    maybe_capture_challenge_fallback(lead, "კომუნიკაცია უჭირს")
    assert lead.challenge == "ეკრანი"


def test_challenge_fallback_skips_phone_message():
    from app.agent.llm.parent_llm_engine import maybe_capture_challenge_fallback
    lead = _mk_lead_with_age()
    maybe_capture_challenge_fallback(lead, "ნომერი 595999733")
    assert lead.challenge == ""


def test_challenge_fallback_skips_slot_message():
    from app.agent.llm.parent_llm_engine import maybe_capture_challenge_fallback
    lead = _mk_lead_with_age()
    maybe_capture_challenge_fallback(lead, "11:00 საათზე")
    assert lead.challenge == ""


def test_challenge_fallback_skips_short_filler():
    from app.agent.llm.parent_llm_engine import maybe_capture_challenge_fallback
    lead = _mk_lead_with_age()
    maybe_capture_challenge_fallback(lead, "კი")
    assert lead.challenge == ""


def test_challenge_fallback_caps_long_message():
    """A 1000-char rant is capped at 200 chars on the Lead."""
    from app.agent.llm.parent_llm_engine import maybe_capture_challenge_fallback
    lead = _mk_lead_with_age()
    long_text = "ეკრანი ძალიან აწუხებს " * 50  # > 200 chars
    maybe_capture_challenge_fallback(lead, long_text)
    assert lead.challenge
    assert len(lead.challenge) <= 200


def test_challenge_fallback_handles_none_lead():
    from app.agent.llm.parent_llm_engine import maybe_capture_challenge_fallback
    maybe_capture_challenge_fallback(None, "ეკრანი")  # type: ignore[arg-type]


# =========================================================================
# Compound-booking commit hook (datetime + name + phone in one message)
# =========================================================================


def test_compound_booking_books_when_message_has_datetime_phone(
    enable_engine, monkeypatch, fresh_conversation, camp_registration_open,):
    """User volunteers a full booking in one message; the deterministic
    commit hook must book even when no pending_booking was recorded by
    a previous turn."""
    from app.flows import parent_flow as pf
    from app.services import calendar_service, messenger_service

    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    monkeypatch.setattr(
        calendar_service, "is_within_business_hours",
        lambda dt, dur=30: (True, ""),
    )
    monkeypatch.setattr(
        calendar_service, "check_slot_calendar_only",
        lambda dt, dur=30: True,
    )
    monkeypatch.setattr(
        calendar_service, "check_slot_available", lambda dt, dur=30: True,
    )
    monkeypatch.setattr(
        calendar_service, "get_free_slots", lambda *a, **k: [],
    )
    booked: list = []
    monkeypatch.setattr(
        calendar_service, "book_slot",
        lambda **kwargs: (booked.append(kwargs), setattr(kwargs["lead"], "calendar_event_id", "evt_mock_test_id"))[0] or True,
    )

    # Stub Sheets / notification so the commit can complete.
    from app.services import notification_service, openai_service, sheets_service
    monkeypatch.setattr(sheets_service, "create_lead", lambda lead: True)
    monkeypatch.setattr(
        notification_service, "send_manager_notification",
        lambda lead, summary: True,
    )
    monkeypatch.setattr(openai_service, "generate_summary", lambda h: "ქართული.")

    # Block any LLM follow-up from re-asking — empty content forces the
    # commit-hook output to be the final response.
    monkeypatch.setattr(
        openai_service, "chat_with_tools",
        lambda **kwargs: _mk_response(content=""),
    )

    # Future-dated July 28 — safely > today by months.
    fresh_conversation.lead = Lead(
        sender_id=fresh_conversation.sender_id, platform="instagram",
        segment="PARENT", child_age="14",
    )
    message = "ნიკა 595999733 28 ივლისს 15:00-ზე ჩამიწერეთ"

    parent_flow.handle(fresh_conversation, message)
    assert len(booked) == 1, "compound booking must commit in one turn"
    assert fresh_conversation.lead.calendly_booked is True


def test_compound_booking_skips_when_no_phone(
    enable_engine, monkeypatch, fresh_conversation,
):
    """Without a valid phone the compound-booking fallback must NOT
    book and must defer to the engine to ask for it."""
    from app.services import calendar_service, messenger_service, openai_service

    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    booked: list = []
    monkeypatch.setattr(
        calendar_service, "book_slot",
        lambda **kwargs: (booked.append(kwargs), setattr(kwargs["lead"], "calendar_event_id", "evt_mock_test_id"))[0] or True,
    )
    monkeypatch.setattr(
        openai_service, "chat_with_tools",
        lambda **kwargs: _mk_response(content="მომწერეთ თქვენი 9-ნიშნა საკონტაქტო ნომერი."),
    )

    fresh_conversation.lead = Lead(
        sender_id=fresh_conversation.sender_id, platform="instagram",
        segment="PARENT", child_age="14",
    )
    parent_flow.handle(fresh_conversation, "28 ივლისს 15:00-ზე ჩამიწერეთ")
    assert booked == []
    assert fresh_conversation.lead.calendly_booked is False


# =========================================================================
# Wording sanitiser — Georgian quality patch
# =========================================================================


def test_sanitiser_collapses_duplicated_romeli_dro():
    from app.agent.llm.parent_llm_engine import sanitise_response_wording
    out = sanitise_response_wording(
        "1 ივნისს, 15:00 საათზე თავისუფალი დრო არ არის. "
        "თავისუფალია 1 ივნისს 10:00. რომელი დრო რომელი დრო გაწყობთ?"
    )
    assert "რომელი დრო რომელი დრო" not in out
    assert "მოსახერხებელი" in out or "რომელი დრო" in out


def test_sanitiser_fixes_natural_ordering_phrase():
    from app.agent.llm.parent_llm_engine import sanitise_response_wording
    out = sanitise_response_wording("ეს ბუნებრივია სრულად, გვითხარით კიდევ რამე.")
    assert "ეს ბუნებრივია სრულად" not in out
    assert "სრულიად ბუნებრივია" in out


def test_sanitiser_replaces_motivation_for_price_objection():
    from app.agent.llm.parent_llm_engine import sanitise_response_wording
    out = sanitise_response_wording(
        "ეს გასაგები მოტივაციაა. ფასი იძლევა მთელ პროგრამას."
    )
    assert "ეს გასაგები მოტივაცია" not in out
    assert "ფასი" in out


def test_sanitiser_replaces_bureaucratic_detail_phrase():
    from app.agent.llm.parent_llm_engine import sanitise_response_wording
    out = sanitise_response_wording(
        "კონსულტაციაზე ჩაწერისთვის საჭირო დეტალების გარკვევისთვის "
        "გვითხარით, გთხოვთ, თქვენი სახელი."
    )
    assert "საჭირო დეტალების" not in out
    assert ("სახელი" in out) and ("9-ნიშნა" in out)


def test_sanitiser_replaces_harsh_ineligibility_phrase():
    from app.agent.llm.parent_llm_engine import sanitise_response_wording
    out = sanitise_response_wording(
        "ამ პროგრამაში თქვენი ბავშვის ჩაწერას ვერ დავადასტურებთ."
    )
    assert "ვერ დავადასტურებთ" not in out
    assert "9–17" in out


# =========================================================================
# Adult-pivot prompt rule (age ≥ 18)
# =========================================================================


def test_system_prompt_has_age_outside_range_adult_pivot_rule():
    """ADULT LLM Engine Patch — Part 9: when the child's age is outside
    [age_min, age_max] (including ≥ 18), the engine must ask a polite
    follow-up question BEFORE switching to the adult flow — never auto-
    pivot. The prompt now describes a two-step sequence: (a) ask „თუ
    გაინტერესებთ ჩვენი ზრდასრულთა კულტურული საღამოები, სიამოვნებით
    გაგაცნობთ პროგრამას"; (b) only call ``switch_to_adult_flow`` if the
    user confirms.
    """
    from app.agent.llm.prompt_loader import load_prompt, reset_cache
    reset_cache()
    text = load_prompt("system_parent_v2")
    # New Part 9 wording: polite question, not auto-switch.
    assert "ასაკი დიაპაზონს არ ერგება" in text
    assert "ზრდასრულთა კულტურული საღამოები" in text
    assert "switch_to_adult_flow" in text
    # Polite phrase from the patch spec.
    assert (
        "სიამოვნებით გაგაცნობთ პროგრამას" in text
    ), "Polite adult-events question must be in the prompt."


# =========================================================================
# Identity-question short-circuit + booked-state segment guard
# =========================================================================


def test_identity_reply_handles_boti_question():
    from app.services.conversation_service import _maybe_identity_reply
    out = _maybe_identity_reply("ბოტი ხარ?")
    assert out is not None
    assert "სიტყვის აკადემიის" in out
    assert "გვითხარით" in out
    for forbidden in ("GPT", "Claude", "OpenAI", "Anthropic"):
        assert forbidden not in out


def test_identity_reply_handles_ai_question():
    from app.services.conversation_service import _maybe_identity_reply
    out = _maybe_identity_reply("AI ხარ?")
    assert out is not None
    assert "სიტყვის აკადემიის" in out


def test_identity_reply_noop_on_non_identity_message():
    from app.services.conversation_service import _maybe_identity_reply
    assert _maybe_identity_reply("ბანაკი მაინტერესებს") is None
    assert _maybe_identity_reply("") is None
    assert _maybe_identity_reply("გამარჯობა") is None


def test_booked_state_segment_guard_keeps_parent_route():
    """A DONE conversation with a booked lead must route to PARENT
    flow on the next message, never to the UNCLEAR routing menu."""
    from app.services import conversation_service

    conversation_service.conversations.clear()
    sender_id = "booked-guard-1"
    conv = Conversation(sender_id=sender_id, platform="instagram")
    conv.state = "DONE"
    conv.lead = Lead(
        sender_id=sender_id, platform="instagram", segment="PARENT",
        child_age="14", name="ნინო", phone="595000000",
        calendly_booked=True, status="Booked",
    )
    conversation_service.conversations[sender_id] = conv

    # Sanity: this message has NO camp keyword. Before the booked-
    # state guard it would re-classify to UNCLEAR.
    out = conversation_service.process_message(
        sender_id, "რა ხდება შემდეგ?", "instagram",
    )
    assert "გვითხარით, რა გაინტერესებთ" not in out, (
        "DONE conversation must not fall back to the UNCLEAR menu"
    )
    # State stays DONE; lead unchanged.
    assert conv.state == "DONE"
    assert conv.lead.calendly_booked is True
    conversation_service.conversations.clear()


# =========================================================================
# Past-date wording — sanitiser + scenario calibration backing
# =========================================================================


def test_sanitiser_rewrites_uk_already_past_phrase():
    from app.agent.llm.parent_llm_engine import sanitise_response_wording
    out = sanitise_response_wording(
        "ეს დრო უკვე გასულია. შემიძლია მომავალი დროები შემოგთავაზოთ."
    )
    assert "უკვე გასულია" not in out
    assert "წარსულ თარიღზე" in out
    assert "თავისუფალი დროები" in out or "შემოგთავაზოთ" in out


def test_sanitiser_rewrites_bare_uk_gasulia():
    from app.agent.llm.parent_llm_engine import sanitise_response_wording
    out = sanitise_response_wording("ეს დრო უკვე გასულია.")
    assert "უკვე გასულია" not in out


# =========================================================================
# Angry-user defensive-wording sanitiser
# =========================================================================


def test_sanitiser_drops_defensive_apology_phrasing():
    from app.agent.llm.parent_llm_engine import sanitise_response_wording
    out = sanitise_response_wording(
        "ბოდიშს გიხდით, თუ პასუხი დაგვიანებულად ან არასაკმარისად "
        "მოგეჩვენათ. ვცდილობთ მაქსიმუმს."
    )
    assert "თუ პასუხი დაგვიანებულად ან არასაკმარისად მოგეჩვენათ" not in out
    assert "ვეცდები, სწრაფად და ზუსტად დაგეხმაროთ" in out


# =========================================================================
# English camp intent detection
# =========================================================================


def test_english_camp_intent_matches_basic_phrase():
    from app.flows.parent_flow import _has_explicit_english_camp_intent
    assert _has_explicit_english_camp_intent("Hello I want camp for my child")
    assert _has_explicit_english_camp_intent("I'm interested in camp")
    assert _has_explicit_english_camp_intent("Summer camp for my kid")


def test_english_camp_intent_does_not_match_georgian():
    """A Georgian message that happens to mention 'camp' should NOT
    trigger the English bypass — the static welcome should still fire
    for plain Georgian first turns."""
    from app.flows.parent_flow import _has_explicit_english_camp_intent
    assert not _has_explicit_english_camp_intent("გამარჯობა")
    assert not _has_explicit_english_camp_intent("ბანაკი მაინტერესებს")
    assert not _has_explicit_english_camp_intent("")


def test_english_camp_intent_classifier_routes_to_parent():
    """conversation_service._classify_segment should now route plain
    English camp messages to PARENT instead of UNCLEAR."""
    from app.services.conversation_service import _classify_segment
    assert _classify_segment("Hello I want camp for my child") == "PARENT"
    assert _classify_segment("I'm interested in summer camp") == "PARENT"


def test_static_welcome_yields_to_engine_on_english_intent(
    enable_engine, monkeypatch,
):
    """When the parent's very first message is an unambiguous English
    camp enquiry, the static welcome bypass must yield so the engine
    can answer (in Georgian) instead of returning the menu."""
    from app.services import messenger_service, openai_service
    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    monkeypatch.setattr(
        openai_service, "chat_with_tools",
        lambda **kwargs: _mk_response(content="რამდენი წლისაა თქვენი შვილი?"),
    )
    conv = Conversation(sender_id="english-static", platform="instagram")
    conv.segment = "PARENT"
    out = parent_flow.handle(conv, "Hello I want camp for my child")
    # Engine answered → response is the age-question; the menu must not
    # have shipped instead.
    assert "გვითხარით, რა გაინტერესებთ" not in out
    assert "წლისაა" in out or "ასაკი" in out


def test_static_welcome_still_fires_on_plain_georgian_greeting(
    enable_engine, monkeypatch,
):
    """Defensive: the static welcome guard is unchanged for normal
    Georgian first messages."""
    from app.services import openai_service
    monkeypatch.setattr(
        openai_service, "chat_with_tools",
        lambda **kwargs: pytest.fail("engine must not run for plain Georgian first turn"),
    )
    conv = Conversation(sender_id="georgian-static", platform="instagram")
    conv.segment = "PARENT"
    out = parent_flow.handle(conv, "გამარჯობა")
    assert "გვითხარით, რა გაინტერესებთ" in out


# =========================================================================
# System-prompt rule presence checks (defensive)
# =========================================================================


def test_system_prompt_has_price_objection_rule():
    from app.agent.llm.prompt_loader import load_prompt, reset_cache
    reset_cache()
    text = load_prompt("system_parent_v2")
    assert "ფასის წინააღმდეგობა" in text
    assert "მნიშვნელოვანი ფაქტორი" in text
    assert "TBC" in text and "საქართველოს ბანკის" in text


def test_system_prompt_has_multi_child_rule():
    from app.agent.llm.prompt_loader import load_prompt, reset_cache
    reset_cache()
    text = load_prompt("system_parent_v2")
    assert "რამდენიმე შვილი" in text
    assert "დედმამიშვილებისთვის" in text
    assert "10%-იანი ფასდაკლება" in text


def test_system_prompt_has_angry_user_rule():
    from app.agent.llm.prompt_loader import load_prompt, reset_cache
    reset_cache()
    text = load_prompt("system_parent_v2")
    # The angry/dissatisfied rule still exists (empathy + manager), but the FORCED
    # canned „ბოდიშს გიხდით. ვეცდები…" text was REMOVED (2026-07-26) so the
    # `dissatisfied-customer` skill / natural LLM handle it — de-scripting the
    # camp-centric prompt per the operator's „no hardcode" rule.
    assert "უკმაყოფილო მომხმარებელი" in text
    assert "თანაგრძნობ" in text                       # empathy guidance
    assert "მენეჯერთან დაკავშირება" in text           # offers the manager
    assert "ბოდიშს გიხდით. ვეცდები, სწრაფად და ზუსტად დაგეხმაროთ." not in text


def test_system_prompt_has_past_date_rule():
    from app.agent.llm.prompt_loader import load_prompt, reset_cache
    reset_cache()
    text = load_prompt("system_parent_v2")
    assert "წარსული თარიღი" in text
    assert "წარსულ თარიღზე კონსულტაციას ვერ ჩავნიშნავთ" in text
