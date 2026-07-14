"""Camp Stream Date Filter (2026-06-20).

Business rule: once a camp stream's START date arrives, that stream must
stop being shown to users — even while it is still marked „active" in
Admin/config. We never delete streams from config and never mutate event /
KB data; this is a user-facing display / eligibility filter only.

  active stream AND today <  start_date  → visible
  active stream AND today >= start_date  → hidden  (hidden ON the start day)
  inactive stream                        → hidden  (regardless of date)

The 2026 streams under test:
  * I ნაკადი   — 23-29 ივნისი  → start 23 June
  * II ნაკადი  — 5-11 ივლისი   → start 5 July
  * III ნაკადი — 14-20 ივლისი  → start 14 July

Pure-function tests pass a frozen Tbilisi ``now`` directly. Integration
tests freeze the clock by monkeypatching ``admin_config_service._now_tbilisi``
(the same seam the sibling adult-event filter uses) and stub
``get_camp_facts`` so they are independent of shipped-config drift.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.services import admin_config_service as acs

TBILISI = ZoneInfo("Asia/Tbilisi")


def _now(month: int, day: int, hour: int = 12) -> datetime:
    return datetime(2026, month, day, hour, 0, tzinfo=TBILISI)


def _streams(*, status: str | None = "active") -> list[dict]:
    """The three canonical 2026 camp streams (admin shape)."""
    base = [
        {"name": "I ნაკადი", "dates_text": "23-29 ივნისი"},
        {"name": "II ნაკადი", "dates_text": "5-11 ივლისი"},
        {"name": "III ნაკადი", "dates_text": "14-20 ივლისი"},
    ]
    if status is not None:
        for s in base:
            s["status"] = status
    return base


def _names(streams: list[dict]) -> list[str]:
    return [s["name"] for s in streams]


CAMP_FACTS = {
    "name": "სიტყვის აკადემიის ბანაკი",
    "year": 2026,
    "location": "ამბასადორი კაჭრეთი",
    "age_min": 9,
    "age_max": 17,
    "duration_days": 7,
    "price_gel": 2150,
    "includes": ["ტრანსპორტი", "განთავსება", "კვება", "პროგრამა"],
    "streams": _streams(),
    "registration_url": "https://tinyurl.com/36jcae8z",
    "phone": "558 67 47 33",
}


# ===========================================================================
# 1. _parse_camp_stream_start_date — extract the START day of the range
# ===========================================================================


@pytest.mark.parametrize("dates_text, expected", [
    ("23-29 ივნისი", (2026, 6, 23)),
    ("5-11 ივლისი", (2026, 7, 5)),
    ("14-20 ივლისი", (2026, 7, 14)),
    ("23 ივნისი", (2026, 6, 23)),          # single day, no range
    ("2027 წლის 3-9 აგვისტო", (2027, 8, 3)),  # explicit year wins
])
def test_parse_start_date(dates_text, expected):
    d = acs._parse_camp_stream_start_date(dates_text, year=2026)
    assert (d.year, d.month, d.day) == expected


def test_parse_start_date_unparseable_returns_none():
    assert acs._parse_camp_stream_start_date("მალე გაცნობებთ", year=2026) is None
    assert acs._parse_camp_stream_start_date("", year=2026) is None


# ===========================================================================
# 2. get_visible_camp_streams on the required calendar boundaries
# ===========================================================================


def test_june_22_all_three_visible():
    vis = acs.get_visible_camp_streams(_streams(), now=_now(6, 22), year=2026)
    assert _names(vis) == ["I ნაკადი", "II ნაკადი", "III ნაკადი"]


def test_june_23_first_hidden_rest_visible():
    vis = acs.get_visible_camp_streams(_streams(), now=_now(6, 23), year=2026)
    assert _names(vis) == ["II ნაკადი", "III ნაკადი"]


def test_july_4_first_hidden_rest_visible():
    vis = acs.get_visible_camp_streams(_streams(), now=_now(7, 4), year=2026)
    assert _names(vis) == ["II ნაკადი", "III ნაკადი"]


def test_july_5_first_two_hidden_third_visible():
    vis = acs.get_visible_camp_streams(_streams(), now=_now(7, 5), year=2026)
    assert _names(vis) == ["III ნაკადი"]


def test_july_14_all_hidden():
    vis = acs.get_visible_camp_streams(_streams(), now=_now(7, 14), year=2026)
    assert vis == []


def test_boundary_day_before_start_visible_on_start_hidden():
    """today == start-1 → visible; today == start → hidden (the start day)."""
    one_stream = [{"name": "I", "dates_text": "23-29 ივნისი", "status": "active"}]
    assert acs.is_camp_stream_visible(one_stream[0], now=_now(6, 22), year=2026) is True
    assert acs.is_camp_stream_visible(one_stream[0], now=_now(6, 23, hour=0), year=2026) is False
    assert acs.is_camp_stream_visible(one_stream[0], now=_now(6, 23, hour=23), year=2026) is False


# ===========================================================================
# 3. active / inactive rule preserved (regardless of date)
# ===========================================================================


def test_inactive_stream_hidden_even_when_future():
    streams = _streams(status="active")
    streams[0]["status"] = "inactive"  # I is future on 22 June but inactive
    vis = acs.get_visible_camp_streams(streams, now=_now(6, 22), year=2026)
    assert _names(vis) == ["II ნაკადი", "III ნაკადი"]


def test_inactive_future_only_stream_hidden():
    only = [{"name": "X ნაკადი", "dates_text": "25-31 დეკემბერი", "status": "inactive"}]
    assert acs.get_visible_camp_streams(only, now=_now(6, 22), year=2026) == []


def test_active_false_flag_hidden():
    only = [{"name": "Y", "dates_text": "25-31 დეკემბერი", "active": False}]
    assert acs.get_visible_camp_streams(only, now=_now(6, 22), year=2026) == []


def test_no_status_field_treated_as_active():
    """camp_2026.yaml streams carry no `status` → treated active, date-filtered."""
    streams = _streams(status=None)
    assert _names(acs.get_visible_camp_streams(streams, now=_now(6, 22), year=2026)) == [
        "I ნაკადი", "II ნაკადი", "III ნაკადი",
    ]
    assert _names(acs.get_visible_camp_streams(streams, now=_now(6, 23), year=2026)) == [
        "II ნაკადი", "III ნაკადი",
    ]


def test_empty_dates_text_is_visible():
    only = [{"name": "TBD", "dates_text": "", "status": "active"}]
    assert _names(acs.get_visible_camp_streams(only, now=_now(6, 23), year=2026)) == ["TBD"]


def test_unparseable_dates_text_hidden(caplog):
    caplog.set_level("WARNING")
    only = [{"name": "Z", "dates_text": "თარიღი მოგვიანებით", "status": "active"}]
    assert acs.get_visible_camp_streams(only, now=_now(6, 23), year=2026) == []


# ===========================================================================
# 4. purity — never mutates the input or the source config / KB data
# ===========================================================================


def test_filter_does_not_mutate_input():
    streams = _streams()
    snapshot = [dict(s) for s in streams]
    out = acs.get_visible_camp_streams(streams, now=_now(7, 5), year=2026)
    assert streams == snapshot          # input untouched
    assert out is not streams           # new list returned


# ===========================================================================
# 5. get_camp_info tool surface — engine path
# ===========================================================================


def _make_executor():
    from app.agent.tools.parent_tool_executor import ParentToolExecutor
    from app.models.conversation import Conversation
    from app.models.lead import Lead

    conv = Conversation(sender_id="u_camp", platform="instagram")
    lead = Lead(sender_id="u_camp", platform="instagram", segment="PARENT")
    conv.lead = lead
    return ParentToolExecutor(
        conversation=conv, lead=lead, sender_id="u_camp", platform="instagram",
    )


@pytest.fixture
def frozen_camp(monkeypatch):
    """Freeze the clock + pin camp facts for the executor's get_camp_info."""
    def _freeze(month, day):
        monkeypatch.setattr(acs, "_now_tbilisi", lambda: (_now(month, day), TBILISI))
        monkeypatch.setattr(acs, "get_camp_facts", lambda: {
            **CAMP_FACTS, "streams": _streams(),
        })
    return _freeze


def test_get_camp_info_dates_filters_started_stream(frozen_camp):
    frozen_camp(6, 23)  # I started today
    out = _make_executor()._get_camp_info({"topic": "dates"})
    assert out["success"] is True
    names = [s["name"] for s in out["streams"]]
    assert names == ["II ნაკადი", "III ნაკადი"]
    assert out["duration_days"] == 7  # other facts unchanged


def test_get_camp_info_all_topic_filters_streams(frozen_camp):
    frozen_camp(7, 5)  # I + II started
    out = _make_executor()._get_camp_info({"topic": "all"})
    assert [s["name"] for s in out["streams"]] == ["III ნაკადი"]
    # Unrelated facts still present and unchanged.
    assert out["price_gel"] == 2150
    assert out["age_min"] == 9 and out["age_max"] == 17


def test_get_camp_info_all_streams_hidden_no_invented_dates(frozen_camp):
    """Test 7 — when every stream has started the tool offers NO dates and
    invents none; the model is left with an empty list, not a fake date."""
    frozen_camp(7, 14)  # all started
    out = _make_executor()._get_camp_info({"topic": "dates"})
    assert out["success"] is True
    assert out["streams"] == []
    # No stream name / date string leaks into the structured answer.
    blob = repr(out)
    for token in ("ნაკადი", "ივნისი", "ივლისი", "23-29", "5-11", "14-20"):
        assert token not in blob


# ===========================================================================
# 6. registration link + other answers preserved (tests 8, 9, 10)
# ===========================================================================


def test_registration_link_still_works(frozen_camp, camp_registration_open):
    """Test 9 — registration topic still returns the configured link."""
    frozen_camp(7, 14)  # even when ALL streams are hidden
    out = _make_executor()._get_camp_info({"topic": "registration"})
    assert out["success"] is True
    assert out["registration_url"] == "https://tinyurl.com/36jcae8z"


def test_dates_answer_does_not_leak_registration_link(frozen_camp):
    """Test 8 — a dates question never returns the registration URL; the
    link is only served on the explicit registration topic."""
    frozen_camp(6, 22)
    out = _make_executor()._get_camp_info({"topic": "dates"})
    assert "registration_url" not in out
    assert "tinyurl" not in repr(out)


def test_price_program_age_answers_unchanged(frozen_camp):
    """Test 10 — price / includes / age / conditions answers are unaffected."""
    frozen_camp(7, 14)  # date filter active, but these topics don't touch streams
    ex = _make_executor()
    price = ex._get_camp_info({"topic": "price"})
    assert price["price_gel"] == 2150
    assert "ტრანსპორტი" in price["includes"]
    age = ex._get_camp_info({"topic": "age_range"})
    assert age["age_min"] == 9 and age["age_max"] == 17
    cond = ex._get_camp_info({"topic": "conditions"})
    assert cond["age_min"] == 9 and cond["age_max"] == 17
    assert cond["location"] == "ამბასადორი კაჭრეთი"


# ===========================================================================
# 7. legacy router dates answer — manager fallback when all hidden
# ===========================================================================


def test_legacy_router_dates_answer_filters_and_falls_back(monkeypatch):
    from app.flows import parent_turn_router as ptr

    monkeypatch.setattr(acs, "_now_tbilisi", lambda: (_now(6, 23), TBILISI))
    monkeypatch.setattr(ptr, "_camp", lambda: {**CAMP_FACTS, "streams": _streams()})
    answer = ptr._build_premium_dates_answer()
    assert "5-11 ივლისი" in answer and "14-20 ივლისი" in answer
    assert "23-29 ივნისი" not in answer

    # All started → no invented dates, manager-handoff line instead.
    monkeypatch.setattr(acs, "_now_tbilisi", lambda: (_now(7, 14), TBILISI))
    fallback = ptr._build_premium_dates_answer()
    assert "მენეჯერ" in fallback
    for token in ("23-29 ივნისი", "5-11 ივლისი", "14-20 ივლისი"):
        assert token not in fallback


# ===========================================================================
# 8. isolation — the filter never touches Calendar / Sheets / WhatsApp /
#    notification logic (tests 11, 12)
# ===========================================================================


def test_get_camp_info_does_not_touch_booking_sheets_or_whatsapp(frozen_camp, monkeypatch):
    """Tests 11 + 12 — exercising the stream filter via get_camp_info must
    not reach Calendar, Sheets, Messenger/WhatsApp or notification code."""
    from app.services import calendar_service, sheets_service
    from app.services import messenger_service, notification_service

    def _boom(*a, **k):
        raise AssertionError("camp stream filter reached an external service")

    for mod, fn in [
        (calendar_service, "get_free_slots"),
        (calendar_service, "create_event"),
        (sheets_service, "save_lead"),
        (sheets_service, "create_lead"),
        (messenger_service, "send_message"),
        (messenger_service, "send_whatsapp_message"),
        (notification_service, "send_manager_notification"),
    ]:
        if hasattr(mod, fn):
            monkeypatch.setattr(mod, fn, _boom, raising=False)

    frozen_camp(7, 5)
    ex = _make_executor()
    # Every topic that involves streams must still succeed with no external call.
    assert ex._get_camp_info({"topic": "dates"})["success"] is True
    assert ex._get_camp_info({"topic": "all"})["success"] is True
    # And the pure helper is side-effect free as well.
    assert acs.get_visible_camp_streams(_streams(), now=_now(7, 5), year=2026)
