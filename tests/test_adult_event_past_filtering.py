"""Adult Event Date Filter (2026-06-10).

Business rule: a PAST adult event must NEVER be offered to a user as
available/current — even when ``active=True`` in the Admin Panel. The
operator-entered ``date_text`` is parsed against Asia/Tbilisi „now":
date+time → past when < now; date-only → past once the day ended; empty
date → shown; non-empty-unparseable → hidden from public lists (but not
reported as „ended"). Year assumed current, rolling +1 only when > 180
days in the past.

Pure-function tests freeze ``now`` to 2026-06-10 12:00 Asia/Tbilisi.
Integration tests (resolver / broadcast / details) compute dates
relative to the real Tbilisi „now" so they hold whenever they run.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
import yaml

from app.services import admin_config_service as acs
from app.services import comment_service

TBILISI = ZoneInfo("Asia/Tbilisi")
NOW = datetime(2026, 6, 10, 12, 0, tzinfo=TBILISI)

_KA_MONTHS = {
    1: "იანვარი", 2: "თებერვალი", 3: "მარტი", 4: "აპრილი", 5: "მაისი",
    6: "ივნისი", 7: "ივლისი", 8: "აგვისტო", 9: "სექტემბერი",
    10: "ოქტომბერი", 11: "ნოემბერი", 12: "დეკემბერი",
}


def _ka_date(dt: datetime, with_time: bool = False) -> str:
    base = f"{dt.day} {_KA_MONTHS[dt.month]}"
    return f"{base} {dt.strftime('%H:%M')}" if with_time else base


def _ev(date_text: str, **over) -> dict:
    e = {
        "id": over.get("id", "e1"),
        "title": over.get("title", "ღონისძიება"),
        "status": over.get("status", "active"),
        "active": over.get("active", True),
        "min_age": 13,
        "date_text": date_text,
    }
    e.update({k: v for k, v in over.items() if k not in ("id", "title", "status", "active")})
    return e


# ===========================================================================
# 1. is_adult_event_past — frozen now = 2026-06-10 12:00
# ===========================================================================


@pytest.mark.parametrize("date_text, expected_past", [
    ("9 ივნისი", True),                  # yesterday, date-only
    ("10 ივნისი", False),                # today, date-only → not past (all day)
    ("10 ივნისი 08:00", True),           # today earlier time → past
    ("10 ივნისი 18:00", False),          # today later time → future
    ("11 ივნისი", False),                # tomorrow
    ("28 აგვისტო 19:00", False),         # later this year
    ("25 ივნისი  20:00", False),         # double space, future
    ("", False),                         # empty → not past
    ("გაურკვეველი", False),              # unparseable → not "past"
])
def test_is_adult_event_past(date_text, expected_past):
    assert acs.is_adult_event_past(_ev(date_text), now=NOW) is expected_past


def test_year_rollover_january_viewed_in_december():
    dec_now = datetime(2026, 12, 20, 12, 0, tzinfo=TBILISI)
    # „5 იანვარი" viewed in December → next-year event, NOT past.
    assert acs.is_adult_event_past(_ev("5 იანვარი"), now=dec_now) is False


def test_january_viewed_in_june_is_past():
    # „5 იანვარი" viewed in June (≈156 days ago, < 180) → past this year.
    assert acs.is_adult_event_past(_ev("5 იანვარი"), now=NOW) is True


# ===========================================================================
# 2. _adult_event_visible_to_public
# ===========================================================================


def test_visible_active_future():
    assert acs._adult_event_visible_to_public(_ev("11 ივნისი"), now=NOW) is True


def test_hidden_active_past():
    assert acs._adult_event_visible_to_public(_ev("9 ივნისი"), now=NOW) is False


def test_hidden_inactive_even_if_future():
    assert acs._adult_event_visible_to_public(
        _ev("11 ივნისი", active=False, status="inactive"), now=NOW,
    ) is False


def test_empty_date_is_visible():
    assert acs._adult_event_visible_to_public(_ev(""), now=NOW) is True


def test_unparseable_date_hidden_from_public(caplog):
    caplog.set_level("WARNING")
    assert acs._adult_event_visible_to_public(_ev(" თარიღი მოგვიანებით"), now=NOW) is False


# ===========================================================================
# 3. get_active_adult_events — future-only by default; include_past opt-in
# ===========================================================================


@pytest.fixture
def seeded(monkeypatch, tmp_path):
    """Seed sections.yaml with a past + future + today + unparseable event."""
    now = acs._now_tbilisi()[0]
    past = now - timedelta(days=2)
    future = now + timedelta(days=5)
    path = tmp_path / "sections.yaml"
    body = yaml.safe_dump({"sections": [{
        "id": "adult_events", "name": "ზრდასრულთა", "type": "adult_events",
        "status": "active", "hashtags": ["event", "ღონისძიება"], "age_min": 13,
        "auto_dm_template_id": "adult_events_comment_dm",
        "events": [
            {"id": "past_ev", "title": "ძველი საღამო", "status": "active",
             "min_age": 13, "date_text": _ka_date(past, True),
             "tags": ["ძველი საღამო"], "reservation_url": "https://x/past"},
            {"id": "future_ev", "title": "summer fest", "status": "active",
             "min_age": 13, "date_text": _ka_date(future, True),
             "location": "ლისი", "price_text": "100",
             "tags": ["fest"], "reservation_url": "https://x/future"},
        ],
    }]}, allow_unicode=True, sort_keys=False)
    path.write_text(body, encoding="utf-8")
    monkeypatch.setattr(acs, "SECTIONS_PATH", path)
    return {"past": past, "future": future}


def test_get_active_excludes_past_by_default(seeded):
    events = acs.get_active_adult_events()
    ids = {e["id"] for e in events}
    assert "future_ev" in ids
    assert "past_ev" not in ids


def test_get_active_include_past_keeps_past(seeded):
    events = acs.get_active_adult_events(include_past=True)
    ids = {e["id"] for e in events}
    assert "past_ev" in ids and "future_ev" in ids


def test_number_selection_indexes_only_future(seeded):
    """The user-facing list (and therefore any 1-based number index) must
    contain only future events."""
    events = acs.get_active_adult_events()
    assert all(not acs.is_adult_event_past(e) for e in events)


# ===========================================================================
# 4. Generic #event comment DM uses future-only list
# ===========================================================================


def test_generic_comment_list_excludes_past(seeded):
    dm = comment_service._build_active_adult_events_list_dm()
    assert "summer fest" in dm
    assert "ძველი საღამო" not in dm


def test_all_past_yields_no_current_list(monkeypatch, tmp_path):
    now = acs._now_tbilisi()[0]
    past = now - timedelta(days=3)
    path = tmp_path / "sections.yaml"
    body = yaml.safe_dump({"sections": [{
        "id": "adult_events", "name": "ზრდასრულთა", "type": "adult_events",
        "status": "active", "hashtags": ["event"], "age_min": 13,
        "auto_dm_template_id": "adult_events_comment_dm",
        "events": [
            {"id": "old", "title": "ძველი", "status": "active", "min_age": 13,
             "date_text": _ka_date(past, True), "reservation_url": "https://x/o"},
        ],
    }]}, allow_unicode=True, sort_keys=False)
    path.write_text(body, encoding="utf-8")
    monkeypatch.setattr(acs, "SECTIONS_PATH", path)
    # No future events → empty list builder → caller uses fallback.
    assert comment_service._build_active_adult_events_list_dm() == ""


# ===========================================================================
# 5. Specific past-event tag → ended-event message (no ticket link)
# ===========================================================================


def _run(coro):
    return asyncio.run(coro)


def test_specific_past_tag_returns_past_event_reason(seeded):
    event, candidates, reason = _run(
        comment_service.resolve_specific_adult_event(
            comment_text="ძველი საღამო მაინტერესებს",
            post_id="", platform="facebook",
        ),
    )
    assert reason == "past_event"
    assert event is not None and event["id"] == "past_ev"


def test_future_tag_still_resolves_normally(seeded):
    event, candidates, reason = _run(
        comment_service.resolve_specific_adult_event(
            comment_text="fest მაინტერესებს", post_id="", platform="facebook",
        ),
    )
    assert reason == "comment_tag"
    assert event["id"] == "future_ev"


def test_send_dm_past_event_sends_ended_message_no_link(seeded, monkeypatch):
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(
        comment_service.messenger_service, "send_private_reply",
        lambda cid, msg: (sent.append((cid, msg)) or True),
    )

    async def _fake_section(post_id, platform):
        return {"id": "adult_events", "type": "adult_events", "status": "active",
                "auto_dm_template_id": "adult_events_comment_dm"}
    monkeypatch.setattr(comment_service, "resolve_section_from_post", _fake_section)

    ok = _run(comment_service.send_dm_from_comment(
        sender_id="u1", platform="facebook", post_id="p", segment="ADULT",
        comment_id="cm1", comment_text="ძველი საღამო ფასი?",
    ))
    assert ok
    body = sent[0][1]
    assert "დასრულებულია" in body
    assert "https://x/past" not in body  # never the past event's ticket link


def test_past_event_dm_builder_no_link():
    dm = comment_service._build_past_event_dm()
    assert "დასრულებულია" in dm


# ===========================================================================
# 6. Broadcast blocks past events
# ===========================================================================


@pytest.fixture
def _mock_broadcast_io(monkeypatch):
    """Broadcast Safety Patch (2026-06-11): NEVER touch real Messenger /
    Sheets from a test. Mock the subscriber read + the outbound send so
    these tests are hermetic — and assert no real DM is attempted."""
    from app.services import adult_event_broadcast_service as bsvc
    from app.services import sheets_service as sheets_service_mod
    sent: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        sheets_service_mod, "list_event_subscribers", lambda **kw: [],
        raising=False,
    )
    from app.services import messenger_service as ms
    monkeypatch.setattr(
        ms, "send_message",
        lambda *a, **k: (sent.append(a) or True),
    )
    return sent


def test_broadcast_blocks_past_event(seeded, _mock_broadcast_io):
    from app.services import adult_event_broadcast_service as bsvc
    result = bsvc.broadcast_event("past_ev", source="test")
    assert result["reason"] == "event_past"
    assert result.get("sent", 0) == 0
    assert _mock_broadcast_io == []  # no send attempted


def test_broadcast_allows_future_event_resolution(seeded, _mock_broadcast_io):
    from app.services import adult_event_broadcast_service as bsvc
    # A future event must NOT be blocked as past. With no subscribers
    # (mocked empty) and the dry-run default, NO real DM is ever sent.
    result = bsvc.broadcast_event("future_ev", source="test")
    assert result["reason"] != "event_past"
    assert _mock_broadcast_io == []  # no real DM


def test_broadcast_is_dry_run_by_default_no_send(seeded, monkeypatch):
    """Even WITH a (mocked) subscriber present, the default dry-run guard
    must prevent any real send and any notified-mark."""
    from app.services import adult_event_broadcast_service as bsvc
    from app.services import messenger_service as ms
    from app.services import sheets_service as sheets_service_mod
    sent: list = []
    monkeypatch.setattr(ms, "send_message", lambda *a, **k: (sent.append(a) or True))
    monkeypatch.setattr(
        sheets_service_mod, "list_event_subscribers",
        lambda **kw: [{"platform": "messenger", "sender_id": "sub1",
                       "notified_event_ids": []}],
        raising=False,
    )
    marked: list = []
    monkeypatch.setattr(
        sheets_service_mod, "mark_event_subscriber_notified",
        lambda *a, **k: (marked.append(a) or (True, "ok")),
        raising=False,
    )
    result = bsvc.broadcast_event("future_ev", source="test")
    assert result["dry_run"] is True
    assert result["sent"] == 0
    assert sent == []      # never sent a real DM
    assert marked == []    # never marked notified
    assert result.get("dry_run_would_send", 0) >= 1


# ===========================================================================
# 7. Executor _get_adult_event_details — past event → event_past reason
# ===========================================================================


def test_executor_details_past_event(seeded):
    from app.agent.tools.adult_tool_executor import AdultToolExecutor
    from app.models.conversation import Conversation
    from app.models.lead import Lead
    conv = Conversation(sender_id="u", platform="instagram")
    lead = Lead(sender_id="u", platform="instagram", segment="ADULT")
    conv.lead = lead
    ex = AdultToolExecutor(
        conversation=conv, lead=lead, sender_id="u", platform="instagram",
    )
    out = ex._get_adult_event_details({"event_id_or_title": "ძველი საღამო"})
    assert out["success"] is False
    assert out["reason"] == "event_past"


def test_executor_details_future_event_ok(seeded):
    from app.agent.tools.adult_tool_executor import AdultToolExecutor
    from app.models.conversation import Conversation
    from app.models.lead import Lead
    conv = Conversation(sender_id="u", platform="instagram")
    lead = Lead(sender_id="u", platform="instagram", segment="ADULT")
    conv.lead = lead
    ex = AdultToolExecutor(
        conversation=conv, lead=lead, sender_id="u", platform="instagram",
    )
    out = ex._get_adult_event_details({"event_id_or_title": "summer fest"})
    assert out["success"] is True
    assert out["event"]["id"] == "future_ev"
