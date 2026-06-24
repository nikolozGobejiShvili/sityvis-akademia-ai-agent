"""Comment Follow-up Logic Fix + Public Reply Ready (2026-05-31).

Covers the patch:

  * `ENABLE_PUBLIC_COMMENT_REPLY` code default flipped to True
    (Meta App Review pending; .env override still works either way).
  * `sheets_service.get_pending_comment_followups` only returns rows
    where DM Sent == TRUE AND Status == "DMSent". CommentOnly /
    FollowupSent / Expired rows are skipped — fixes the hourly 400
    retry-loop driven by ancient CommentOnly rows.
  * `comment_service.check_comment_followups` skips senders that
    already have an active Conversation (DM follow-up owns the
    cadence in that case).
  * Meta HTTP 400 is treated as permanent: one attempt, no retry,
    row marked Expired, processed-comment guard primed so the same
    id is skipped on the next tick.
  * Meta HTTP 429 / 500 / 502 / 503 / network exceptions keep the
    existing 3-attempt retry path.
  * Success marks the row FollowupSent.
  * `AGENT_ENABLED=false` short-circuits the whole tick.

External services are fully mocked.
"""

from __future__ import annotations

import asyncio
import dataclasses
from types import SimpleNamespace
from typing import Any

import pytest

import app.config as config_module
from app.config import Settings
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.routes import webhook as webhook_module
from app.services import (
    comment_service,
    conversation_service,
    kill_switch,
    sheets_service,
)


# -- helpers --------------------------------------------------------------


def _swap_agent_enabled(monkeypatch, enabled: bool) -> None:
    swapped = dataclasses.replace(config_module.settings, AGENT_ENABLED=enabled)
    monkeypatch.setattr(kill_switch, "settings", swapped)
    monkeypatch.setattr(comment_service, "settings", swapped)


class _FakeAsyncResponse:
    def __init__(self, status_code: int = 200, text: str = ""):
        self.status_code = status_code
        self.text = text

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300


class _RecordingHttpClient:
    """Drop-in for `httpx.AsyncClient(timeout=15)` that records every
    POST and returns the responses passed in. ``responses`` is consumed
    in order; the last entry is reused if the loop runs longer."""

    def __init__(self, responses: list[_FakeAsyncResponse]):
        self._responses = list(responses)
        self.posts: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, *_a, **_k):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return None

    async def post(self, url, headers=None, json=None):
        self.posts.append((url, json or {}))
        if not self._responses:
            return _FakeAsyncResponse(status_code=500)
        if len(self._responses) == 1:
            return self._responses[0]
        return self._responses.pop(0)


def _patch_httpx(monkeypatch, client: _RecordingHttpClient):
    monkeypatch.setattr(
        comment_service, "httpx",
        SimpleNamespace(AsyncClient=client),
    )


@pytest.fixture(autouse=True)
def _reset_state():
    conversation_service.conversations.clear()
    webhook_module._processed_comments_lru.clear()
    yield
    conversation_service.conversations.clear()
    webhook_module._processed_comments_lru.clear()


@pytest.fixture
def updates_recorder(monkeypatch):
    """Capture `sheets_service.update_comment` calls so each test
    can assert the status mutation without hitting Google."""
    records: list[dict] = []

    def fake_update(comment_id, updates):
        records.append({"comment_id": comment_id, "updates": dict(updates)})
        return True

    monkeypatch.setattr(sheets_service, "update_comment", fake_update)
    monkeypatch.setattr(comment_service.sheets_service, "update_comment", fake_update)
    return records


@pytest.fixture
def fast_sleep(monkeypatch):
    """Make `asyncio.sleep` instantaneous so retry tests don't take
    seconds."""
    async def _no_sleep(_seconds):
        return None
    monkeypatch.setattr(comment_service.asyncio, "sleep", _no_sleep)


# =========================================================================
# PART 1 — Public reply default
# =========================================================================


def test_public_reply_default_is_true():
    """Code default now ships ENABLE_PUBLIC_COMMENT_REPLY=True so the
    code is ready for Meta App Review approval."""
    s = Settings()
    assert s.ENABLE_PUBLIC_COMMENT_REPLY is True


def test_public_reply_default_can_still_be_overridden_via_env():
    """An operator that explicitly sets ENABLE_PUBLIC_COMMENT_REPLY=
    false in `.env` must still be able to force-disable."""
    overridden = dataclasses.replace(Settings(), ENABLE_PUBLIC_COMMENT_REPLY=False)
    assert overridden.ENABLE_PUBLIC_COMMENT_REPLY is False


# =========================================================================
# PART 2 — Sheets eligibility (column I + column J)
# =========================================================================


def _fake_worksheet(rows):
    return SimpleNamespace(get_all_records=lambda: rows)


def _eligible_row(**over):
    """Build a row that LOOKS eligible by default; tests override
    individual fields to flip eligibility."""
    base = {
        "Comment ID": "c1",
        "Sender ID": "u1",
        "User Name": "ნინო",
        "Platform": "facebook",
        "DM Sent": "TRUE",
        "Status": "DMSent",
        "Created At": "2024-01-01T10:00:00+04:00",
    }
    base.update(over)
    return base


@pytest.fixture
def stub_sheets(monkeypatch):
    """Replace the gspread worksheet so eligibility tests don't hit
    Google."""
    rows: list[dict] = []
    monkeypatch.setattr(
        sheets_service, "_comments_worksheet", lambda: _fake_worksheet(rows),
    )
    return rows


def test_eligibility_requires_dm_sent_true(stub_sheets):
    stub_sheets.append(_eligible_row(**{"DM Sent": "FALSE"}))
    out = sheets_service.get_pending_comment_followups()
    assert out == []


def test_eligibility_requires_dmsent_status(stub_sheets):
    """CommentOnly rows are the historical bug — must be skipped."""
    stub_sheets.append(_eligible_row(Status="CommentOnly"))
    out = sheets_service.get_pending_comment_followups()
    assert out == []


def test_eligibility_skips_followupsent(stub_sheets):
    stub_sheets.append(_eligible_row(Status="FollowupSent"))
    assert sheets_service.get_pending_comment_followups() == []


def test_eligibility_skips_expired(stub_sheets):
    stub_sheets.append(_eligible_row(Status="Expired"))
    assert sheets_service.get_pending_comment_followups() == []


def test_eligibility_skips_missing_dm_sent(stub_sheets):
    """Empty / missing DM Sent treated as false."""
    row = _eligible_row()
    row["DM Sent"] = ""
    stub_sheets.append(row)
    assert sheets_service.get_pending_comment_followups() == []


def test_eligibility_passes_true_string_uppercase(stub_sheets):
    stub_sheets.append(_eligible_row(**{"DM Sent": "TRUE"}))
    out = sheets_service.get_pending_comment_followups()
    assert len(out) == 1


def test_eligibility_passes_true_string_lowercase(stub_sheets):
    stub_sheets.append(_eligible_row(**{"DM Sent": "true"}))
    out = sheets_service.get_pending_comment_followups()
    assert len(out) == 1


def test_eligibility_passes_bool_true(stub_sheets):
    stub_sheets.append(_eligible_row(**{"DM Sent": True}))
    out = sheets_service.get_pending_comment_followups()
    assert len(out) == 1


def test_eligibility_rejects_bool_false(stub_sheets):
    stub_sheets.append(_eligible_row(**{"DM Sent": False}))
    assert sheets_service.get_pending_comment_followups() == []


def test_eligibility_dms_only_with_old_created_at(stub_sheets):
    """Rows newer than the COMMENT_FOLLOWUP_HOURS cutoff stay warm —
    they're not yet eligible for follow-up."""
    from datetime import datetime, timedelta
    from app.agent.services.timestamps import TBILISI_TZ

    recent = (datetime.now(TBILISI_TZ) - timedelta(hours=1)).isoformat()
    stub_sheets.append(_eligible_row(**{"Created At": recent}))
    assert sheets_service.get_pending_comment_followups() == []


# =========================================================================
# PART 3 — Active-conversation skip
# =========================================================================


def _seed_pending_row(monkeypatch, **over) -> dict:
    item = {
        "comment_id": "cm1",
        "sender_id": "user_x",
        "user_name": "ნინო",
    }
    item.update(over)
    monkeypatch.setattr(
        sheets_service, "get_pending_comment_followups", lambda: [item],
    )
    monkeypatch.setattr(
        comment_service.sheets_service,
        "get_pending_comment_followups", lambda: [item],
    )
    return item


def test_active_conversation_skips_comment_followup(monkeypatch, updates_recorder):
    _swap_agent_enabled(monkeypatch, True)
    item = _seed_pending_row(monkeypatch)
    # Seed an active conversation for the sender.
    conv = Conversation(sender_id=item["sender_id"], platform="facebook")
    conv.segment = "PARENT"
    conv.lead = Lead(sender_id=item["sender_id"], platform="facebook", segment="PARENT")
    conversation_service.conversations[item["sender_id"]] = conv

    client = _RecordingHttpClient([_FakeAsyncResponse(200)])
    _patch_httpx(monkeypatch, client)

    asyncio.run(comment_service.check_comment_followups())

    # No Meta call, no Sheets status change.
    assert client.posts == []
    assert updates_recorder == []


def test_active_declined_conversation_skips(monkeypatch, updates_recorder):
    _swap_agent_enabled(monkeypatch, True)
    item = _seed_pending_row(monkeypatch)
    conv = Conversation(sender_id=item["sender_id"], platform="facebook")
    conv.segment = "PARENT"
    conv.followup_blocked_reason = "declined"
    conversation_service.conversations[item["sender_id"]] = conv

    client = _RecordingHttpClient([_FakeAsyncResponse(200)])
    _patch_httpx(monkeypatch, client)
    asyncio.run(comment_service.check_comment_followups())
    assert client.posts == []


def test_active_no_more_messages_skips(monkeypatch, updates_recorder):
    _swap_agent_enabled(monkeypatch, True)
    item = _seed_pending_row(monkeypatch)
    conv = Conversation(sender_id=item["sender_id"], platform="facebook")
    conv.segment = "PARENT"
    conv.followup_blocked_reason = "asked_no_more_messages"
    conversation_service.conversations[item["sender_id"]] = conv

    client = _RecordingHttpClient([_FakeAsyncResponse(200)])
    _patch_httpx(monkeypatch, client)
    asyncio.run(comment_service.check_comment_followups())
    assert client.posts == []


def test_no_active_conversation_proceeds(monkeypatch, updates_recorder):
    _swap_agent_enabled(monkeypatch, True)
    _seed_pending_row(monkeypatch)
    client = _RecordingHttpClient([_FakeAsyncResponse(200)])
    _patch_httpx(monkeypatch, client)
    asyncio.run(comment_service.check_comment_followups())
    assert len(client.posts) == 1


# =========================================================================
# PART 4 — Meta 400 handling
# =========================================================================


def test_meta_400_is_not_retried(monkeypatch, updates_recorder, fast_sleep):
    _swap_agent_enabled(monkeypatch, True)
    _seed_pending_row(monkeypatch)
    client = _RecordingHttpClient([_FakeAsyncResponse(400, text="permission denied")])
    _patch_httpx(monkeypatch, client)

    asyncio.run(comment_service.check_comment_followups())

    # Single attempt — no retry loop.
    assert len(client.posts) == 1


def test_meta_400_marks_row_expired(monkeypatch, updates_recorder, fast_sleep):
    _swap_agent_enabled(monkeypatch, True)
    _seed_pending_row(monkeypatch)
    client = _RecordingHttpClient([_FakeAsyncResponse(400, text="permission")])
    _patch_httpx(monkeypatch, client)
    asyncio.run(comment_service.check_comment_followups())

    assert len(updates_recorder) == 1
    assert updates_recorder[0]["updates"] == {"status": "Expired"}


def test_meta_400_primes_processed_guard_lru(monkeypatch, updates_recorder, fast_sleep):
    _swap_agent_enabled(monkeypatch, True)
    item = _seed_pending_row(monkeypatch)
    client = _RecordingHttpClient([_FakeAsyncResponse(400)])
    _patch_httpx(monkeypatch, client)
    asyncio.run(comment_service.check_comment_followups())

    # Same comment_id is now in the in-process LRU guard the webhook
    # uses for duplicate-comment short-circuit.
    assert webhook_module._is_comment_processed_local(item["comment_id"])


def test_meta_400_body_logged_safely(monkeypatch, updates_recorder, fast_sleep, caplog):
    _swap_agent_enabled(monkeypatch, True)
    _seed_pending_row(monkeypatch)
    client = _RecordingHttpClient([_FakeAsyncResponse(400, text="some error")])
    _patch_httpx(monkeypatch, client)

    with caplog.at_level("WARNING"):
        asyncio.run(comment_service.check_comment_followups())

    joined = "\n".join(r.message for r in caplog.records)
    assert "permanently skipped" in joined
    # No raw access token in logs.
    assert "Bearer" not in joined
    assert "access_token" not in joined.lower()


# =========================================================================
# PART 5 — Meta 429 / 500 keep retry behavior
# =========================================================================


def test_meta_500_retries_existing_behavior(monkeypatch, updates_recorder, fast_sleep):
    _swap_agent_enabled(monkeypatch, True)
    _seed_pending_row(monkeypatch)
    # All 3 attempts fail with 500.
    client = _RecordingHttpClient([_FakeAsyncResponse(500)])
    _patch_httpx(monkeypatch, client)

    asyncio.run(comment_service.check_comment_followups())

    # Three attempts made — existing retry path preserved.
    assert len(client.posts) == 3
    # Failure does NOT mark Expired — the row stays DMSent so the
    # next scheduler tick can try again. (Sentry / log will surface.)
    assert updates_recorder == []


def test_meta_429_retries_existing_behavior(monkeypatch, updates_recorder, fast_sleep):
    _swap_agent_enabled(monkeypatch, True)
    _seed_pending_row(monkeypatch)
    client = _RecordingHttpClient([_FakeAsyncResponse(429)])
    _patch_httpx(monkeypatch, client)
    asyncio.run(comment_service.check_comment_followups())
    assert len(client.posts) == 3
    assert updates_recorder == []


def test_network_exception_retries_existing_behavior(monkeypatch, updates_recorder, fast_sleep):
    _swap_agent_enabled(monkeypatch, True)
    _seed_pending_row(monkeypatch)

    class _BoomClient(_RecordingHttpClient):
        async def post(self, url, headers=None, json=None):
            self.posts.append((url, json or {}))
            raise RuntimeError("network timeout")

    client = _BoomClient([])
    _patch_httpx(monkeypatch, client)
    asyncio.run(comment_service.check_comment_followups())
    assert len(client.posts) == 3
    assert updates_recorder == []


# =========================================================================
# PART 6 — Success
# =========================================================================


def test_success_marks_followupsent(monkeypatch, updates_recorder, fast_sleep):
    _swap_agent_enabled(monkeypatch, True)
    _seed_pending_row(monkeypatch)
    client = _RecordingHttpClient([_FakeAsyncResponse(200)])
    _patch_httpx(monkeypatch, client)

    asyncio.run(comment_service.check_comment_followups())

    assert len(client.posts) == 1
    assert len(updates_recorder) == 1
    assert updates_recorder[0]["updates"] == {"status": "FollowupSent"}


def test_success_no_double_send_on_next_tick(monkeypatch, updates_recorder, fast_sleep):
    """Once a row is marked FollowupSent, the eligibility query no
    longer returns it — modeled here by an empty pending list on the
    second tick, just like the real Sheets query would behave."""
    _swap_agent_enabled(monkeypatch, True)
    _seed_pending_row(monkeypatch)
    client = _RecordingHttpClient([_FakeAsyncResponse(200)])
    _patch_httpx(monkeypatch, client)
    asyncio.run(comment_service.check_comment_followups())
    # Second tick: pending is empty (Sheets eligibility now skips
    # FollowupSent).
    monkeypatch.setattr(
        comment_service.sheets_service,
        "get_pending_comment_followups", lambda: [],
    )
    asyncio.run(comment_service.check_comment_followups())
    # Still only the original POST.
    assert len(client.posts) == 1


# =========================================================================
# PART 7 — Kill switch
# =========================================================================


def test_kill_switch_skips_entire_tick(monkeypatch, updates_recorder, fast_sleep):
    _swap_agent_enabled(monkeypatch, False)
    # Pending list MUST NOT even be read — assert by raising.
    monkeypatch.setattr(
        comment_service.sheets_service, "get_pending_comment_followups",
        lambda: (_ for _ in ()).throw(AssertionError("should not be called")),
    )
    client = _RecordingHttpClient([_FakeAsyncResponse(200)])
    _patch_httpx(monkeypatch, client)

    asyncio.run(comment_service.check_comment_followups())
    assert client.posts == []
    assert updates_recorder == []


# =========================================================================
# PART 8 — DM follow-up unchanged sanity
# =========================================================================


def test_dm_follow_up_loop_not_invoked_by_comment_scheduler(monkeypatch, fast_sleep):
    """The comment scheduler MUST NOT call the DM scheduler. They are
    independent loops; mixing them would double-send to the same
    sender."""
    _swap_agent_enabled(monkeypatch, True)
    _seed_pending_row(monkeypatch)
    client = _RecordingHttpClient([_FakeAsyncResponse(200)])
    _patch_httpx(monkeypatch, client)

    from app.services import followup_service
    called = {"dm": 0}
    monkeypatch.setattr(
        followup_service, "check_and_send_followups",
        lambda: called.__setitem__("dm", called["dm"] + 1),
    )
    asyncio.run(comment_service.check_comment_followups())
    assert called["dm"] == 0
