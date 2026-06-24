"""Adult Subscription Confirmation + Write Patch (2026-06-11).

Covers the live bug where the user explicitly consented to future
adult-event notifications („კი გამომიგზავნეთ" / „ჩამწერეთ სადმე? რომ
ღონისძიება ავტომატურად მომივიდეს?") but the stochastic LLM either
off-topic-redirected the reply or merely acknowledged WITHOUT calling
`subscribe_to_adult_event_updates` — so no Sheets `events` row was
written yet the agent implied „შეგატყობინებთ" success.

Test groups (per task PART 3):
  A. Subscription consent after a pending offer (1–4)
  B. Direct subscription intent, no pending offer (5–8)
  C. Honest confirmation — success / already / failed (9–13)
  D. Sheet write fields (14–18)
  E. Sanitiser safety net — false success claims stripped
  F. Broadcast safety (19–21)
  G. Adult state reuse (22, 26 + context)
  H. Pending-offer marker + negative + token-boundary regressions
"""

from __future__ import annotations

from typing import Any

import pytest

from app.agent.llm import adult_llm_engine
from app.agent.tools import adult_tool_executor
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import (
    adult_subscription_service,
    sheets_service,
)


# ---------------------------------------------------------------------------
# Fake Sheets `events` worksheet (mirrors test_adult_event_subscription.py)
# ---------------------------------------------------------------------------


class _FakeEventsWorksheet:
    def __init__(self):
        from app.services.sheets_service import EVENT_SUBSCRIBER_HEADERS
        self.rows: list[list[str]] = [list(EVENT_SUBSCRIBER_HEADERS)]

    def row_values(self, row_index: int) -> list[str]:
        if 1 <= row_index <= len(self.rows):
            return list(self.rows[row_index - 1])
        return []

    def col_values(self, col_index: int) -> list[str]:
        out: list[str] = []
        for row in self.rows:
            out.append(row[col_index - 1] if col_index - 1 < len(row) else "")
        return out

    def get_all_values(self) -> list[list[str]]:
        return [list(r) for r in self.rows]

    def append_row(self, row: list[Any], value_input_option: str = "RAW") -> None:
        from app.services.sheets_service import EVENT_SUBSCRIBER_HEADERS
        padded = [str(v) for v in row]
        while len(padded) < len(EVENT_SUBSCRIBER_HEADERS):
            padded.append("")
        self.rows.append(padded)

    def update_cell(self, row: int, col: int, value: Any) -> None:
        while len(self.rows) < row:
            self.rows.append([""] * len(self.rows[0]))
        target = self.rows[row - 1]
        while len(target) < col:
            target.append("")
        target[col - 1] = str(value)

    def update(self, rng: str, values: list[list[Any]]) -> None:
        if not values:
            return
        row_values = [str(v) for v in values[0]]
        try:
            row_idx = int("".join(ch for ch in rng.split(":")[0] if ch.isdigit()))
        except ValueError:
            return
        from app.services.sheets_service import EVENT_SUBSCRIBER_HEADERS
        while len(row_values) < len(EVENT_SUBSCRIBER_HEADERS):
            row_values.append("")
        while len(self.rows) < row_idx:
            self.rows.append([""] * len(EVENT_SUBSCRIBER_HEADERS))
        self.rows[row_idx - 1] = row_values

    def resize(self, *, cols: int) -> None:
        pass


@pytest.fixture
def fake_events_ws(monkeypatch):
    ws = _FakeEventsWorksheet()
    monkeypatch.setattr(
        sheets_service, "_event_subscribers_worksheet", lambda: ws,
    )
    return ws


@pytest.fixture(autouse=True)
def reset_executor_state():
    adult_tool_executor.reset_state()
    yield
    adult_tool_executor.reset_state()


@pytest.fixture(autouse=True)
def no_real_openai(monkeypatch):
    """Default: any fall-through to the LLM raises so a deterministic
    test that *should* short-circuit never makes a real OpenAI call.
    Tests that legitimately need the LLM path override this."""
    from app.services import openai_service

    def _boom(*a, **kw):  # pragma: no cover - guard
        raise AssertionError("OpenAI should not be called on this path")

    monkeypatch.setattr(openai_service, "chat_with_tools", _boom)


def _mk_response(*, content: str = "", tool_calls=None):
    from types import SimpleNamespace
    tc_objs = []
    for tc in tool_calls or []:
        tc_objs.append(SimpleNamespace(
            id=tc["id"],
            function=SimpleNamespace(
                name=tc["name"], arguments=tc.get("arguments", "{}"),
            ),
        ))
    msg = SimpleNamespace(content=content or None, tool_calls=tc_objs or None)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


_OFFER_QUESTION = (
    "გსურთ, როცა ახალი ზრდასრულთა ღონისძიება დაემატება, დეტალები "
    "და ბილეთის ბმული პირად შეტყობინებაში გამოგიგზავნოთ?"
)


def _conv_lead(
    *,
    sender_id: str = "sub_user",
    platform: str = "messenger",
    name: str = "ნინო",
    phone: str = "595999733",
    adult_age: str = "",
    status: str = "",
    history: list | None = None,
    offer_last: bool | None = None,
):
    """Build a (conversation, lead) pair.

    `offer_last` controls whether the subscription OFFER question is the
    last assistant turn in history. Defaults to True when status=="asked"
    (the realistic flow: the agent just asked the offer), so short
    affirmations („კი" / „დიახ" / pure „მინდა") — which require immediate
    adjacency to the offer — are recognised. Pass offer_last=False to
    simulate a STALE „asked" marker (an earlier offer, then a different
    bot turn)."""
    lead = Lead(sender_id=sender_id, platform=platform, segment="ADULT")
    lead.name = name
    lead.phone = phone
    if adult_age:
        lead.adult_age = adult_age
    conv = Conversation(sender_id=sender_id, platform=platform, segment="ADULT")
    conv.lead = lead
    conv.adult_subscription_status = status
    if history is not None:
        conv.history = history
    elif offer_last is True or (offer_last is None and status == "asked"):
        conv.history = [{"role": "assistant", "content": _OFFER_QUESTION}]
    else:
        conv.history = []
    return conv, lead


def _run(conv, lead, message):
    return adult_llm_engine.run_adult_llm_turn(
        user_message=message,
        conversation=conv,
        lead=lead,
        sender_id=conv.sender_id,
        platform=conv.platform,
    )


# ---------------------------------------------------------------------------
# A. Subscription consent after a pending offer
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("message", [
    "კი გამომიგზავნეთ",
    "კი",
    "მინდა",
    "გამომიგზავნეთ",
    "დიახ",
    "კი, მინდა",
])
def test_consent_after_pending_offer_writes_row(fake_events_ws, message):
    conv, lead = _conv_lead(status="asked")
    out = _run(conv, lead, message)
    record = sheets_service.get_event_subscriber("messenger", "sub_user")
    assert record is not None, f"no subscriber row written for {message!r}"
    assert record["status"] == "subscribed"
    assert record["consent"] is True
    assert "ჩაგწერეთ სიაში" in out


def test_consent_pending_inferred_from_history(fake_events_ws):
    """The pending offer is inferred from the last assistant turn even
    when the status marker was not persisted."""
    offer = (
        "გსურთ, როცა ახალი ზრდასრულთა ღონისძიება დაემატება, დეტალები "
        "და ბილეთის ბმული პირად შეტყობინებაში გამოგიგზავნოთ?"
    )
    conv, lead = _conv_lead(
        status="", history=[{"role": "assistant", "content": offer}],
    )
    out = _run(conv, lead, "კი")
    record = sheets_service.get_event_subscriber("messenger", "sub_user")
    assert record is not None
    assert record["status"] == "subscribed"
    assert "ჩაგწერეთ სიაში" in out


def test_bare_yes_without_pending_offer_does_not_subscribe(
    fake_events_ws, monkeypatch,
):
    """A bare „კი" with NO pending offer must NOT subscribe — it routes
    to the LLM instead."""
    from app.services import openai_service
    called = {"n": 0}

    def _llm(*a, **kw):
        called["n"] += 1
        return _mk_response(content="გასაგებია.")

    monkeypatch.setattr(openai_service, "chat_with_tools", _llm)

    conv, lead = _conv_lead(status="")
    _run(conv, lead, "კი")
    assert sheets_service.get_event_subscriber("messenger", "sub_user") is None
    assert called["n"] == 1, "LLM must handle a bare yes with no offer"


def test_kidev_with_pending_offer_does_not_subscribe(
    fake_events_ws, monkeypatch,
):
    """„კიდევ ერთი კითხვა მაქვს" contains „კი" as a substring but is NOT
    consent — token-boundary matching must keep it out of the
    subscription path even with a pending offer."""
    from app.services import openai_service
    called = {"n": 0}

    def _llm(*a, **kw):
        called["n"] += 1
        return _mk_response(content="რა თქმა უნდა, რას დააზუსტებთ?")

    monkeypatch.setattr(openai_service, "chat_with_tools", _llm)

    conv, lead = _conv_lead(status="asked")
    _run(conv, lead, "კიდევ ერთი კითხვა მაქვს")
    assert sheets_service.get_event_subscriber("messenger", "sub_user") is None
    assert called["n"] == 1


# ---------------------------------------------------------------------------
# B. Direct subscription intent (no pending offer)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("message", [
    "ჩამწერეთ სადმე? რომ ღონისძიება ავტომატურად მომივიდეს?",
    "შემატყობინეთ როცა ახალი ღონისძიება დაემატება",
    "სიაში ჩამწერეთ",
    "ახალი ღონისძიებების შესახებ მომწერეთ",
    "ღონისძიებები ავტომატურად მომივიდეს",
])
def test_direct_intent_writes_row_without_pending_offer(fake_events_ws, message):
    conv, lead = _conv_lead(status="")
    out = _run(conv, lead, message)
    record = sheets_service.get_event_subscriber("messenger", "sub_user")
    assert record is not None, f"no subscriber row written for {message!r}"
    assert record["status"] == "subscribed"
    assert record["consent"] is True
    assert "ჩაგწერეთ სიაში" in out


# ---------------------------------------------------------------------------
# C. Honest confirmation
# ---------------------------------------------------------------------------


def test_successful_subscription_says_chagwzeret(fake_events_ws):
    conv, lead = _conv_lead(status="asked")
    out = _run(conv, lead, "კი გამომიგზავნეთ")
    assert "ჩაგწერეთ სიაში" in out


def test_already_subscribed_says_already(fake_events_ws):
    # Pre-subscribe.
    adult_subscription_service.subscribe(
        platform="messenger", sender_id="sub_user",
        name="ნინო", phone="595999733",
    )
    conv, lead = _conv_lead(status="asked")
    out = _run(conv, lead, "კი გამომიგზავნეთ")
    assert "უკვე ხართ სიაში" in out
    assert "ჩაგწერეთ სიაში" not in out
    # No duplicate row.
    rows = fake_events_ws.get_all_values()
    assert len(rows) == 2  # header + one body row


def test_failed_write_does_not_say_success(fake_events_ws, monkeypatch):
    monkeypatch.setattr(
        sheets_service, "save_event_subscriber",
        lambda *a, **kw: (False, "write_failed"),
    )
    conv, lead = _conv_lead(status="asked")
    out = _run(conv, lead, "კი გამომიგზავნეთ")
    assert "ჩაგწერეთ" not in out


def test_failed_write_does_not_imply_send(fake_events_ws, monkeypatch):
    monkeypatch.setattr(
        sheets_service, "save_event_subscriber",
        lambda *a, **kw: (False, "write_failed"),
    )
    conv, lead = _conv_lead(status="asked")
    out = _run(conv, lead, "კი გამომიგზავნეთ")
    # Must not claim the subscription send happened.
    assert "ჩაგწერეთ" not in out
    assert "გამოგიგზავნით" not in out


def test_failed_write_returns_technical_fallback(fake_events_ws, monkeypatch):
    monkeypatch.setattr(
        sheets_service, "save_event_subscriber",
        lambda *a, **kw: (False, "write_failed"),
    )
    conv, lead = _conv_lead(status="asked")
    out = _run(conv, lead, "კი გამომიგზავნეთ")
    assert "ვერ მოხერხდა" in out
    assert "მენეჯერ" in out


def test_missing_phone_asks_for_phone_and_does_not_subscribe(fake_events_ws):
    conv, lead = _conv_lead(status="asked", name="ნინო", phone="")
    out = _run(conv, lead, "კი გამომიგზავნეთ")
    assert sheets_service.get_event_subscriber("messenger", "sub_user") is None
    assert "ნომერი" in out
    assert "ჩაგწერეთ" not in out
    # Offer stays pending so the follow-up contact turn is still in scope.
    assert conv.adult_subscription_status == "asked"


# ---------------------------------------------------------------------------
# D. Sheet write fields
# ---------------------------------------------------------------------------


def test_row_has_subscribed_status_and_consent(fake_events_ws):
    conv, lead = _conv_lead(status="asked")
    _run(conv, lead, "კი გამომიგზავნეთ")
    record = sheets_service.get_event_subscriber("messenger", "sub_user")
    assert record["status"] == "subscribed"
    assert record["consent"] is True


def test_row_stores_platform_and_sender(fake_events_ws):
    conv, lead = _conv_lead(
        sender_id="ig_user", platform="instagram", status="asked",
    )
    _run(conv, lead, "კი გამომიგზავნეთ")
    record = sheets_service.get_event_subscriber("instagram", "ig_user")
    assert record is not None
    assert record["platform"] == "instagram"
    assert record["sender_id"] == "ig_user"


def test_row_stores_age_from_lead(fake_events_ws):
    conv, lead = _conv_lead(status="asked", adult_age="30")
    _run(conv, lead, "კი გამომიგზავნეთ")
    record = sheets_service.get_event_subscriber("messenger", "sub_user")
    assert record["age"] == "30"


def test_existing_subscriber_update_does_not_duplicate(fake_events_ws):
    conv, lead = _conv_lead(status="asked")
    _run(conv, lead, "კი გამომიგზავნეთ")
    # Second consent in a fresh turn — already subscribed, no new row.
    conv2, lead2 = _conv_lead(status="asked")
    _run(conv2, lead2, "კი")
    rows = fake_events_ws.get_all_values()
    assert len(rows) == 2  # header + one body row


# ---------------------------------------------------------------------------
# E. Sanitiser safety net — false success claims
# ---------------------------------------------------------------------------


def test_sanitiser_strips_false_success_when_not_confirmed():
    adult_tool_executor.clear_subscription_confirmed("s1")
    bad = "ჩაგწერეთ სიაში. მალე შეგატყობინებთ."
    out = adult_llm_engine.sanitise_adult_response(bad, sender_id="s1")
    assert "ჩაგწერეთ სიაში" not in out
    assert "ვერ მოხერხდა" in out


def test_sanitiser_keeps_success_when_confirmed():
    adult_tool_executor.mark_subscription_confirmed("s2")
    good = "ჩაგწერეთ სიაში. ახალ ღონისძიებებს გამოგიგზავნით."
    out = adult_llm_engine.sanitise_adult_response(good, sender_id="s2")
    assert "ჩაგწერეთ სიაში" in out
    adult_tool_executor.clear_subscription_confirmed("s2")


def test_sanitiser_no_sender_id_does_not_strip():
    """The bare sanitiser pipeline (sender_id=None, used by unit tests)
    must not strip subscription copy."""
    text = "ჩაგწერეთ სიაში."
    out = adult_llm_engine.sanitise_adult_response(text, sender_id=None)
    assert "ჩაგწერეთ სიაში" in out


# ---------------------------------------------------------------------------
# F. Broadcast safety
# ---------------------------------------------------------------------------


def test_subscription_does_not_call_broadcast(fake_events_ws, monkeypatch):
    from app.services import adult_event_broadcast_service
    called = {"n": 0}

    def _spy(*a, **kw):
        called["n"] += 1
        return {"success": False}

    monkeypatch.setattr(adult_event_broadcast_service, "broadcast_event", _spy)
    conv, lead = _conv_lead(status="asked")
    _run(conv, lead, "კი გამომიგზავნეთ")
    assert called["n"] == 0


def test_subscription_works_with_live_broadcast_disabled(
    fake_events_ws, monkeypatch,
):
    import dataclasses
    import app.config as config_module
    swapped = dataclasses.replace(
        config_module.settings, LIVE_BROADCAST_ENABLED=False,
    )
    monkeypatch.setattr(config_module, "settings", swapped)
    conv, lead = _conv_lead(status="asked")
    _run(conv, lead, "კი გამომიგზავნეთ")
    record = sheets_service.get_event_subscriber("messenger", "sub_user")
    assert record is not None
    assert record["status"] == "subscribed"


def test_subscription_does_not_send_messenger_dm(fake_events_ws, monkeypatch):
    from app.services import messenger_service
    sent = {"n": 0}

    def _spy(*a, **kw):
        sent["n"] += 1
        return True

    monkeypatch.setattr(messenger_service, "send_message", _spy)
    conv, lead = _conv_lead(status="asked")
    _run(conv, lead, "კი გამომიგზავნეთ")
    assert sent["n"] == 0


# ---------------------------------------------------------------------------
# G. Adult state reuse
# ---------------------------------------------------------------------------


def test_thanks_after_subscription_does_not_reset_adult_age(
    fake_events_ws, monkeypatch,
):
    from app.services import openai_service
    conv, lead = _conv_lead(status="asked", adult_age="30")
    _run(conv, lead, "კი გამომიგზავნეთ")
    assert lead.adult_age == "30"

    # A „მადლობა" turn goes to the LLM; it must not clear adult_age.
    monkeypatch.setattr(
        openai_service, "chat_with_tools",
        lambda *a, **kw: _mk_response(content="სიამოვნებით."),
    )
    _run(conv, lead, "მადლობა")
    assert lead.adult_age == "30"


def test_child_age_and_adult_age_coexist_through_subscribe(fake_events_ws):
    conv, lead = _conv_lead(status="asked", adult_age="30")
    lead.child_age = "12"
    _run(conv, lead, "კი გამომიგზავნეთ")
    assert lead.adult_age == "30"
    assert lead.child_age == "12"


def test_context_message_surfaces_adult_age():
    conv, lead = _conv_lead(adult_age="30")
    ctx = adult_llm_engine._build_context_message(conv, lead)
    assert "adult_age=30" in ctx


# ---------------------------------------------------------------------------
# H. Pending-offer marker + negative + regressions
# ---------------------------------------------------------------------------


def test_llm_offer_question_sets_pending_marker(fake_events_ws, monkeypatch):
    from app.services import openai_service
    offer = (
        "გსურთ, როცა ახალი ზრდასრულთა ღონისძიება დაემატება, დეტალები "
        "და ბილეთის ბმული პირად შეტყობინებაში გამოგიგზავნოთ?"
    )
    monkeypatch.setattr(
        openai_service, "chat_with_tools",
        lambda *a, **kw: _mk_response(content=offer),
    )
    conv, lead = _conv_lead(status="")
    _run(conv, lead, "კიდევ რა ღონისძიება გაქვთ?")
    assert conv.adult_subscription_status == "asked"


def test_negative_with_pending_offer_does_not_subscribe(
    fake_events_ws, monkeypatch,
):
    from app.services import openai_service
    monkeypatch.setattr(
        openai_service, "chat_with_tools",
        lambda *a, **kw: _mk_response(content="კარგი, არ შეგაწუხებთ."),
    )
    conv, lead = _conv_lead(status="asked")
    _run(conv, lead, "არა, არ მინდა")
    assert sheets_service.get_event_subscriber("messenger", "sub_user") is None
    assert conv.adult_subscription_status == "declined"


def test_success_marks_conversation_subscribed(fake_events_ws):
    conv, lead = _conv_lead(status="asked")
    _run(conv, lead, "კი გამომიგზავნეთ")
    assert conv.adult_subscription_status == "subscribed"


# ---------------------------------------------------------------------------
# I. Review findings — false-positive regressions (adversarial review fixes)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("message", [
    "ბილეთი მინდა",
    "მინდა ფასი ვიცოდე",
    "მინდა მენეჯერი",
    "სხვა ღონისძიება მინდა ვნახო",
])
def test_unrelated_minda_sentence_does_not_subscribe(
    fake_events_ws, monkeypatch, message,
):
    """„მინდა" inside an unrelated „I want X" sentence must NOT be read as
    subscription consent, even with a pending offer (review finding #1)."""
    from app.services import openai_service
    monkeypatch.setattr(
        openai_service, "chat_with_tools",
        lambda *a, **kw: _mk_response(content="რა თქმა უნდა."),
    )
    conv, lead = _conv_lead(status="asked")  # offer is the last bot turn
    _run(conv, lead, message)
    assert sheets_service.get_event_subscriber("messenger", "sub_user") is None


def test_stale_asked_marker_with_later_bare_yes_does_not_subscribe(
    fake_events_ws, monkeypatch,
):
    """A stale „asked" marker (offer made earlier, then a DIFFERENT bot
    turn) must NOT let a later bare „კი" subscribe (review finding #2)."""
    from app.services import openai_service
    monkeypatch.setattr(
        openai_service, "chat_with_tools",
        lambda *a, **kw: _mk_response(content="გასაგებია."),
    )
    # Marker is „asked" but the LAST assistant turn is NOT the offer.
    conv, lead = _conv_lead(
        status="asked",
        history=[
            {"role": "assistant", "content": _OFFER_QUESTION},
            {"role": "user", "content": "სხვა კითხვა მაქვს"},
            {"role": "assistant", "content": "რა თქმა უნდა, რას დააზუსტებთ?"},
        ],
    )
    _run(conv, lead, "კი")
    assert sheets_service.get_event_subscriber("messenger", "sub_user") is None


def test_stale_asked_marker_still_allows_explicit_send_verb(fake_events_ws):
    """An explicit send/notify verb („გამომიგზავნეთ") is unambiguous, so
    it still subscribes on the broader pending signal even if the offer
    wasn't the immediately-preceding turn."""
    conv, lead = _conv_lead(
        status="asked",
        history=[
            {"role": "assistant", "content": _OFFER_QUESTION},
            {"role": "user", "content": "სხვა კითხვა მაქვს"},
            {"role": "assistant", "content": "რა თქმა უნდა, რას დააზუსტებთ?"},
        ],
    )
    out = _run(conv, lead, "კი გამომიგზავნეთ")
    record = sheets_service.get_event_subscriber("messenger", "sub_user")
    assert record is not None
    assert "ჩაგწერეთ სიაში" in out
