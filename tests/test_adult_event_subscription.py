"""Adult Event Subscription Patch (2026-06-08) — subscribe / unsubscribe /
phrase detection tests.

Test groups (per task spec PART 13):
  1. Consent detection (positive + negative)
  2. Unsubscribe phrase detection
  3. Sheets events tab — schema + headers
  4. Subscriber save / update / upsert
  5. Duplicate subscriber prevention
  6. Unsubscribe row flip
  7. subscribe() requires name + phone (returns missing_*)
  8. subscribe() Sheets failure surfaced as sheets_save_failed
  9. ADULT executor tool: subscribe_to_adult_event_updates
 10. Already-subscribed lookup
"""

from __future__ import annotations

from typing import Any

import pytest

from app.agent.tools import adult_tool_executor
from app.agent.tools.adult_tool_executor import AdultToolExecutor
from app.agent.tools.adult_tools import TOOL_SUBSCRIBE_TO_ADULT_EVENT_UPDATES
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import adult_subscription_service, sheets_service


# ---------------------------------------------------------------------------
# Fake Sheets worksheet
# ---------------------------------------------------------------------------


class _FakeEventsWorksheet:
    """In-memory mimic of the slice of gspread.Worksheet that the
    `events` tab CRUD uses. Keeps the test surface tight: header row +
    body rows as a list of lists; col_values / row_values / update_cell /
    update / append_row mirror gspread semantics 1:1."""

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
        # We only use update(...) for the full-row case
        # "A{N}:Z{N}" → take the first sub-list as the row payload.
        if not values:
            return
        row_values = [str(v) for v in values[0]]
        # Parse trailing row index from the range, e.g. "A3:R3" → 3.
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


def _build_executor(sender_id: str = "user_x") -> AdultToolExecutor:
    lead = Lead(sender_id=sender_id, platform="messenger", segment="ADULT")
    conv = Conversation(sender_id=sender_id, platform="messenger", segment="ADULT")
    return AdultToolExecutor(
        conversation=conv, lead=lead, sender_id=sender_id, platform="messenger",
    )


# ---------------------------------------------------------------------------
# 1. Consent phrase detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", [
    "კი",
    "დიახ",
    "მინდა",
    "გამომიგზავნეთ",
    "კი, გამომიგზავნეთ",
    "მინდა რომ გამომიგზავნოთ",
    "დამამატეთ",
    "შემატყობინეთ",
    "კი, შემატყობინეთ",
    "მომწერეთ როცა ახალი იქნება",
    "კი, მინდა მსგავსი ღონისძიებების მიღება",
    "yes",
    "ok",
])
def test_consent_phrase_detector_matches_positive(text):
    assert adult_subscription_service.is_subscription_consent_phrase(text)


@pytest.mark.parametrize("text", [
    "არა",
    "არ მინდა",
    "არ გამომიგზავნოთ",
    "ჯერ არა",
    "მოგვიანებით",
    "არ შემატყობინოთ",
    "no",
    "not now",
])
def test_consent_phrase_detector_rejects_negative(text):
    assert not adult_subscription_service.is_subscription_consent_phrase(text)
    assert adult_subscription_service.is_negative_subscription_phrase(text)


def test_consent_detector_negative_wins_over_positive_substring():
    """The user message „არა, არ მინდა" must NOT trigger consent just
    because „მინდა" appears as a substring."""
    assert not adult_subscription_service.is_subscription_consent_phrase(
        "არა, არ მინდა",
    )


# ---------------------------------------------------------------------------
# 2. Unsubscribe phrase detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", [
    "აღარ გამომიგზავნოთ",
    "აღარ მინდა შეტყობინებები",
    "აღარ მინდა ღონისძიებები",
    "გამთიშეთ",
    "unsubscribe",
    "stop",
    "აღარ მომწეროთ",
])
def test_unsubscribe_phrase_detector(text):
    assert adult_subscription_service.is_unsubscribe_phrase(text)


def test_unsubscribe_phrase_detector_no_false_match():
    assert not adult_subscription_service.is_unsubscribe_phrase("გილოცავთ!")
    assert not adult_subscription_service.is_unsubscribe_phrase("მინდა")


# ---------------------------------------------------------------------------
# 3 + 4 + 5. Sheets tab schema + subscriber upsert
# ---------------------------------------------------------------------------


def test_save_event_subscriber_appends_row(fake_events_ws):
    ok, reason = sheets_service.save_event_subscriber({
        "platform": "messenger",
        "sender_id": "user_1",
        "name": "ნინო",
        "phone": "595999733",
        "status": "subscribed",
        "consent": True,
        "consent_at": "2026-06-08T10:00:00+04:00",
        "source_event_id": "poetry",
        "source_event_title": "ქართული პოეზიის საღამო",
        "source_event_link": "https://example.com/p",
    })
    assert (ok, reason) == (True, "ok")
    record = sheets_service.get_event_subscriber("messenger", "user_1")
    assert record is not None
    assert record["name"] == "ნინო"
    assert record["status"] == "subscribed"
    assert record["consent"] is True


def test_save_event_subscriber_upsert_does_not_duplicate(fake_events_ws):
    sheets_service.save_event_subscriber({
        "platform": "messenger", "sender_id": "user_1",
        "name": "ნინო", "phone": "595999733",
        "consent": True,
    })
    sheets_service.save_event_subscriber({
        "platform": "messenger", "sender_id": "user_1",
        "name": "ნინო", "phone": "595999733",
        "consent": True,
        "source_event_id": "poetry_v2",
    })
    rows = fake_events_ws.get_all_values()
    # 1 header + 1 body row.
    assert len(rows) == 2


def test_save_event_subscriber_partial_update_preserves_notified_ids(
    fake_events_ws,
):
    """A partial save must NOT wipe notified_event_ids — that column
    is the duplicate-prevention store and is owned by the broadcast
    service."""
    sheets_service.save_event_subscriber({
        "platform": "messenger", "sender_id": "user_1",
        "name": "ნინო", "phone": "595999733", "consent": True,
        "notified_event_ids": "evt_1, evt_2",
    })
    sheets_service.save_event_subscriber({
        "platform": "messenger", "sender_id": "user_1",
        "name": "ნინო-changed", "phone": "595999733",
        "consent": True,
    })
    record = sheets_service.get_event_subscriber("messenger", "user_1")
    assert "evt_1" in record["notified_event_ids"]
    assert "evt_2" in record["notified_event_ids"]
    assert record["name"] == "ნინო-changed"


def test_save_event_subscriber_rejects_missing_identity(fake_events_ws):
    ok, reason = sheets_service.save_event_subscriber({
        "platform": "", "sender_id": "user_1", "consent": True,
    })
    assert (ok, reason) == (False, "missing_identity")


# ---------------------------------------------------------------------------
# 6. Unsubscribe row flip
# ---------------------------------------------------------------------------


def test_unsubscribe_event_subscriber_flips_status(fake_events_ws):
    sheets_service.save_event_subscriber({
        "platform": "messenger", "sender_id": "user_1",
        "name": "ნ", "phone": "595999733", "consent": True,
    })
    ok, reason = sheets_service.unsubscribe_event_subscriber(
        "messenger", "user_1",
    )
    assert (ok, reason) == (True, "ok")
    record = sheets_service.get_event_subscriber("messenger", "user_1")
    assert record["status"] == "unsubscribed"
    assert record["unsubscribe_at"]


def test_unsubscribe_event_subscriber_unknown_returns_not_subscribed(
    fake_events_ws,
):
    ok, reason = sheets_service.unsubscribe_event_subscriber(
        "messenger", "ghost_user",
    )
    assert (ok, reason) == (False, "not_subscribed")


# ---------------------------------------------------------------------------
# 7. subscribe() name + phone validation
# ---------------------------------------------------------------------------


def test_subscribe_requires_name_and_phone(fake_events_ws):
    result = adult_subscription_service.subscribe(
        platform="messenger", sender_id="user_x",
        name=None, phone=None,
    )
    assert result == {"success": False, "reason": "missing_name_and_phone"}


def test_subscribe_requires_phone_when_name_present(fake_events_ws):
    result = adult_subscription_service.subscribe(
        platform="messenger", sender_id="user_x",
        name="ნინო", phone=None,
    )
    assert result == {"success": False, "reason": "missing_phone"}


def test_subscribe_requires_name_when_phone_present(fake_events_ws):
    result = adult_subscription_service.subscribe(
        platform="messenger", sender_id="user_x",
        name=None, phone="595999733",
    )
    assert result == {"success": False, "reason": "missing_name"}


def test_subscribe_succeeds_with_name_and_phone(fake_events_ws):
    result = adult_subscription_service.subscribe(
        platform="messenger", sender_id="user_x",
        name="ნინო", phone="595999733",
        source_event_id="poetry",
        source_event_title="ქართული პოეზიის საღამო",
        source_event_link="https://example.com/p",
    )
    assert result == {"success": True, "status": "subscribed"}
    record = sheets_service.get_event_subscriber("messenger", "user_x")
    assert record["name"] == "ნინო"
    assert record["phone"] == "595999733"
    assert record["consent"] is True
    assert record["source_event_id"] == "poetry"


def test_subscribe_extracts_phone_via_parser(fake_events_ws):
    """The phone arg is validated via parent_flow._parse_name_phone, so
    a raw "595 999 733" string also works."""
    result = adult_subscription_service.subscribe(
        platform="messenger", sender_id="user_x",
        name="ნინო", phone="595 999 733",
    )
    assert result == {"success": True, "status": "subscribed"}
    record = sheets_service.get_event_subscriber("messenger", "user_x")
    assert "595" in record["phone"]


def test_subscribe_invalid_phone_returns_missing_phone(fake_events_ws):
    result = adult_subscription_service.subscribe(
        platform="messenger", sender_id="user_x",
        name="ნინო", phone="abc",
    )
    assert result == {"success": False, "reason": "missing_phone"}


# ---------------------------------------------------------------------------
# 8. subscribe() Sheets failure surfaced
# ---------------------------------------------------------------------------


def test_subscribe_surfaces_sheets_failure(monkeypatch, fake_events_ws):
    def _fail(*a, **kw):
        return False, "write_failed"

    monkeypatch.setattr(sheets_service, "save_event_subscriber", _fail)
    result = adult_subscription_service.subscribe(
        platform="messenger", sender_id="user_x",
        name="ნინო", phone="595999733",
    )
    assert result["success"] is False
    assert result["reason"] == "sheets_save_failed"
    assert result["detail"] == "write_failed"


# ---------------------------------------------------------------------------
# 9. ADULT executor tool: subscribe_to_adult_event_updates
# ---------------------------------------------------------------------------


def test_executor_subscribe_returns_missing_name_and_phone(fake_events_ws):
    executor = _build_executor()
    result = executor.execute(
        TOOL_SUBSCRIBE_TO_ADULT_EVENT_UPDATES, {},
    )
    assert result["success"] is False
    assert result["reason"] == "missing_name_and_phone"


def test_executor_subscribe_uses_lead_data_when_args_missing(fake_events_ws):
    """The LLM may call the tool right after the user confirms „კი"
    without re-supplying name/phone — the executor pulls them from
    the lead state."""
    executor = _build_executor()
    executor.lead.name = "ნინო"
    executor.lead.phone = "595999733"
    result = executor.execute(
        TOOL_SUBSCRIBE_TO_ADULT_EVENT_UPDATES,
        {"source_event_id": "poetry"},
    )
    assert result["success"] is True
    assert result["status"] == "subscribed"


def test_executor_subscribe_marks_conversation_status(fake_events_ws):
    executor = _build_executor()
    executor.lead.name = "ნინო"
    executor.lead.phone = "595999733"
    executor.execute(
        TOOL_SUBSCRIBE_TO_ADULT_EVENT_UPDATES, {},
    )
    assert executor.conversation.adult_subscription_status == "subscribed"


def test_executor_subscribe_mirrors_name_and_phone_to_lead(fake_events_ws):
    executor = _build_executor()
    executor.execute(
        TOOL_SUBSCRIBE_TO_ADULT_EVENT_UPDATES,
        {"name": "ნინო", "phone": "595999733"},
    )
    assert executor.lead.name == "ნინო"
    assert "595" in executor.lead.phone


def test_executor_subscribe_does_NOT_claim_success_on_sheets_failure(
    monkeypatch, fake_events_ws,
):
    monkeypatch.setattr(
        sheets_service, "save_event_subscriber",
        lambda *a, **kw: (False, "write_failed"),
    )
    executor = _build_executor()
    result = executor.execute(
        TOOL_SUBSCRIBE_TO_ADULT_EVENT_UPDATES,
        {"name": "ნ", "phone": "595999733"},
    )
    assert result["success"] is False
    assert result["reason"] == "sheets_save_failed"


# ---------------------------------------------------------------------------
# 10. Already-subscribed lookup
# ---------------------------------------------------------------------------


def test_is_already_subscribed_returns_true_after_save(fake_events_ws):
    adult_subscription_service.subscribe(
        platform="messenger", sender_id="user_y",
        name="ნ", phone="595999733",
    )
    assert adult_subscription_service.is_already_subscribed(
        "messenger", "user_y",
    )


def test_is_already_subscribed_false_for_unsubscribed_user(fake_events_ws):
    adult_subscription_service.subscribe(
        platform="messenger", sender_id="user_y",
        name="ნ", phone="595999733",
    )
    sheets_service.unsubscribe_event_subscriber("messenger", "user_y")
    assert not adult_subscription_service.is_already_subscribed(
        "messenger", "user_y",
    )


def test_is_already_subscribed_false_for_unknown_user(fake_events_ws):
    assert not adult_subscription_service.is_already_subscribed(
        "messenger", "ghost",
    )


# ---------------------------------------------------------------------------
# 11. unsubscribe service wrapper
# ---------------------------------------------------------------------------


def test_subscription_service_unsubscribe_success(fake_events_ws):
    adult_subscription_service.subscribe(
        platform="messenger", sender_id="user_z",
        name="ნ", phone="595999733",
    )
    result = adult_subscription_service.unsubscribe(
        "messenger", "user_z",
    )
    assert result == {"success": True, "status": "unsubscribed"}


def test_subscription_service_unsubscribe_unknown_user(fake_events_ws):
    result = adult_subscription_service.unsubscribe("messenger", "ghost")
    assert result == {"success": False, "reason": "not_subscribed"}


# ---------------------------------------------------------------------------
# 12. Conversation field round-trip
# ---------------------------------------------------------------------------


def test_conversation_adult_subscription_status_roundtrip():
    conv = Conversation(
        sender_id="x", platform="messenger", segment="ADULT",
    )
    conv.adult_subscription_status = "subscribed"
    data = conv.to_dict()
    assert data["adult_subscription_status"] == "subscribed"
    restored = Conversation.from_dict(data)
    assert restored.adult_subscription_status == "subscribed"
