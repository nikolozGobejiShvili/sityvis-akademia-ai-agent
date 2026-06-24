"""Manager WhatsApp notification — email-parallel for booking + handoff (2026-06-18).

The manager WhatsApp notification failed with "Missing access token for
platform=whatsapp" because the send paths gate on `settings.WHATSAPP_TOKEN`.
This change centralises WhatsApp config resolution (alias-aware token +
recipient, E.164 normalisation) behind `settings.get_whatsapp_access_token()`
/ `get_whatsapp_phone_number_id()` / `get_manager_whatsapp_number()` /
`is_whatsapp_configured()`, and confirms WhatsApp is attempted IN PARALLEL
with email for both the consultation-booking and manager-handoff
notifications — non-blocking, with email staying independent.

All tests are offline — `httpx` is mocked; no real WhatsApp / email /
Calendar / Sheets / Meta / Redis. No real WhatsApp message is sent.
"""

from __future__ import annotations

import dataclasses
import logging
from datetime import datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

import app.config as config
from app.agent.tools import parent_tool_executor
from app.agent.tools.parent_tool_executor import ParentToolExecutor
from app.agent.tools.parent_tools import TOOL_BOOK_CONSULTATION
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import calendar_service, notification_service, sheets_service


TBILISI = ZoneInfo("Asia/Tbilisi")
SAT = (2030, 6, 8)   # Saturday
WED = (2030, 6, 5)   # Wednesday
SUN = (2030, 6, 9)   # Sunday


def _env_values_without(*names):
    d = dict(config.ENV_VALUES)
    for n in names:
        d.pop(n, None)
    return d


def _cfg(**overrides):
    # These tests exercise the live-send wiring with a MOCKED httpx transport, so
    # the live-send flag is enabled by default (the ALLOW_LIVE_WHATSAPP guard,
    # 2026-06-23, otherwise blocks the send before httpx). Individual tests can
    # still override it (e.g. to assert the blocked path).
    overrides.setdefault("ALLOW_LIVE_WHATSAPP", True)
    return dataclasses.replace(notification_service.settings, **overrides)


def _booked_lead(sender_id="wa-book"):
    return Lead(
        sender_id=sender_id, platform="instagram", segment="PARENT",
        name="ნიკოლოზი", phone="595999733", child_age="14",
        calendly_booked=True, booked_datetime_iso=_iso(SAT, 12),
        status="Booked",
    )


def _iso(ymd, hour):
    return datetime(ymd[0], ymd[1], ymd[2], hour, 0, tzinfo=TBILISI).isoformat()


# =========================================================================
# 1–3 — access token resolution (alias-aware) + safe-missing.
# =========================================================================


def test_token_loads_from_whatsapp_token(monkeypatch):
    monkeypatch.setattr(
        config, "ENV_VALUES",
        _env_values_without("WHATSAPP_ACCESS_TOKEN", "WHATSAPP_TOKEN"),
    )
    monkeypatch.delenv("WHATSAPP_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("WHATSAPP_TOKEN", raising=False)
    monkeypatch.setenv("WHATSAPP_TOKEN", "TOKEN_A")
    s = config.Settings.from_env()
    assert s.get_whatsapp_access_token() == "TOKEN_A"


def test_token_loads_from_whatsapp_access_token_fallback(monkeypatch):
    monkeypatch.setattr(
        config, "ENV_VALUES",
        _env_values_without("WHATSAPP_ACCESS_TOKEN", "WHATSAPP_TOKEN"),
    )
    monkeypatch.delenv("WHATSAPP_TOKEN", raising=False)
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "TOKEN_B")
    s = config.Settings.from_env()
    assert s.get_whatsapp_access_token() == "TOKEN_B"


def test_missing_token_is_unconfigured_no_exception(monkeypatch):
    monkeypatch.setattr(
        config, "ENV_VALUES",
        _env_values_without("WHATSAPP_ACCESS_TOKEN", "WHATSAPP_TOKEN"),
    )
    monkeypatch.delenv("WHATSAPP_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("WHATSAPP_TOKEN", raising=False)
    s = config.Settings.from_env()
    assert s.get_whatsapp_access_token() == ""
    assert s.is_whatsapp_configured() is False


# =========================================================================
# 4–5 — manager recipient resolution (alias-aware).
# =========================================================================


def test_manager_number_used_when_set():
    s = _cfg(MANAGER_WHATSAPP_NUMBER="995595999733")
    assert s.get_manager_whatsapp_number() == "995595999733"


def test_manager_number_from_manager_whatsapp_fallback(monkeypatch):
    monkeypatch.setattr(
        config, "ENV_VALUES",
        _env_values_without("MANAGER_WHATSAPP", "MANAGER_WHATSAPP_NUMBER"),
    )
    monkeypatch.delenv("MANAGER_WHATSAPP_NUMBER", raising=False)
    monkeypatch.setenv("MANAGER_WHATSAPP", "995595999733")
    s = config.Settings.from_env()
    assert s.get_manager_whatsapp_number() == "995595999733"


# =========================================================================
# 6 — phone number normalization to digits-only international (E.164-ish).
# =========================================================================


@pytest.mark.parametrize("raw, expected", [
    ("+995595999733", "995595999733"),
    ("995595999733", "995595999733"),
    ("595999733", "995595999733"),            # bare 9-digit Georgian mobile
    ("+995 595 99 97 33", "995595999733"),    # spaces stripped
    ("0595999733", "995595999733"),           # domestic leading 0
    ("00995595999733", "995595999733"),       # 00 international prefix
    ("", ""),
    ("   ", ""),
])
def test_normalize_whatsapp_number(raw, expected):
    assert config.normalize_whatsapp_number(raw) == expected


# =========================================================================
# 7–8 — booking notification: email + WhatsApp in parallel, non-blocking.
# =========================================================================


def test_booking_notification_attempts_email_and_whatsapp(monkeypatch):
    monkeypatch.setattr(
        notification_service, "settings",
        _cfg(WHATSAPP_TOKEN="TOK", WHATSAPP_PHONE_NUMBER_ID="PID",
             MANAGER_WHATSAPP_NUMBER="995595999733"),
    )
    email_mock = MagicMock(return_value=True)
    wa_mock = MagicMock(return_value=True)
    monkeypatch.setattr(notification_service, "_send_email", email_mock)
    monkeypatch.setattr(notification_service, "_send_manager_whatsapp", wa_mock)

    result = notification_service.send_manager_notification(_booked_lead(), "summary")

    email_mock.assert_called_once()
    wa_mock.assert_called_once()
    assert result is True


def test_booking_still_succeeds_when_whatsapp_fails_email_ok(monkeypatch):
    """End-to-end booking: WhatsApp failing must NOT block the booking,
    Calendar, Sheets, or email."""
    parent_tool_executor.reset_state()
    # Calendar + Sheets mocked; email succeeds, WhatsApp fails.
    monkeypatch.setattr(calendar_service, "check_slot_available", lambda *a, **k: True)

    def _book(**kwargs):
        lead = kwargs.get("lead")
        if lead is not None:
            lead.calendar_event_id = "evt_wa_test"
        return True

    monkeypatch.setattr(calendar_service, "book_slot", _book)
    monkeypatch.setattr(sheets_service, "create_lead", lambda lead: True)
    monkeypatch.setattr(parent_flow, "_generate_summary", lambda conv: "რეზიუმე")
    monkeypatch.setattr(notification_service, "_send_email", lambda **k: True)
    monkeypatch.setattr(
        notification_service, "_send_manager_whatsapp", lambda text: False,
    )

    sid = "wa-booking-e2e"
    conv = Conversation(sender_id=sid, platform="instagram")
    conv.history.append({"role": "user", "content": "ჩამიწერეთ"})
    lead = Lead(sender_id=sid, platform="instagram", segment="PARENT")
    conv.lead = lead
    ex = ParentToolExecutor(conversation=conv, lead=lead, sender_id=sid, platform="instagram")

    result = ex.execute(TOOL_BOOK_CONSULTATION, {
        "name": "ნიკოლოზი", "phone": "595999733",
        "datetime_iso": _iso(WED, 12), "child_age": "14",
        "user_confirmed_datetime": True,
    })
    assert result["success"] is True
    assert lead.calendly_booked is True


# =========================================================================
# 9–10 — manager handoff: email + WhatsApp in parallel, non-blocking.
# =========================================================================


def test_handoff_attempts_email_and_whatsapp(monkeypatch):
    email_mock = MagicMock(return_value=True)
    wa_mock = MagicMock(return_value=True)
    monkeypatch.setattr(notification_service, "_send_email", email_mock)
    monkeypatch.setattr(notification_service, "_send_manager_whatsapp", wa_mock)
    lead = Lead(sender_id="h1", platform="instagram", segment="PARENT",
                name="ნიკოლოზი", phone="595999733")
    assert notification_service.notify_manager_handoff(lead, "8 წლის") is True
    email_mock.assert_called_once()
    wa_mock.assert_called_once()


def test_handoff_succeeds_when_whatsapp_fails_email_ok(monkeypatch):
    monkeypatch.setattr(notification_service, "_send_email", lambda **k: True)
    monkeypatch.setattr(
        notification_service, "_send_manager_whatsapp", lambda text: False,
    )
    lead = Lead(sender_id="h2", platform="instagram", segment="PARENT",
                name="ნიკოლოზი", phone="595999733")
    # email alone is a real dispatch → True (OR semantics for handoff).
    assert notification_service.notify_manager_handoff(lead, "8 წლის") is True


# =========================================================================
# 11 + 13 — underage handoff: dispatch + NO Calendar/Sheets, behaviour intact.
# =========================================================================


def test_underage_handoff_no_sheets_even_when_whatsapp_fails(monkeypatch):
    parent_tool_executor.reset_state()
    monkeypatch.setattr(notification_service, "_send_email", lambda **k: True)
    monkeypatch.setattr(
        notification_service, "_send_manager_whatsapp", lambda text: False,
    )
    for fn in ("save_lead", "create_lead", "append_lead", "update_lead"):
        monkeypatch.setattr(
            sheets_service, fn,
            lambda *a, **k: pytest.fail(f"underage handoff must not call sheets_service.{fn}"),
        )

    conv = Conversation(sender_id="u-wa", platform="instagram")
    lead = Lead(sender_id="u-wa", platform="instagram", segment="PARENT",
                name="ნიკოლოზი", child_age="8")
    conv.lead = lead
    out = parent_flow._maybe_handle_underage_manager_handoff(
        conv, "მენეჯერთან დამაკავშირეთ 595999733",
    )
    assert out is not None  # email dispatched → success message, no Sheets


def test_underage_handoff_behaviour_unchanged_whatsapp_unconfigured(monkeypatch):
    parent_tool_executor.reset_state()
    # Production default: WhatsApp unconfigured → email-only handoff.
    monkeypatch.setattr(notification_service, "settings", _cfg(WHATSAPP_TOKEN=""))
    notified = []
    monkeypatch.setattr(
        notification_service, "notify_manager_handoff",
        lambda lead, reason: (notified.append(reason), True)[1],
    )
    conv = Conversation(sender_id="u-wa2", platform="instagram")
    lead = Lead(sender_id="u-wa2", platform="instagram", segment="PARENT",
                name="ნიკოლოზი", child_age="8")
    conv.lead = lead
    out = parent_flow._maybe_handle_underage_manager_handoff(
        conv, "მენეჯერთან დამაკავშირეთ 595999733",
    )
    assert out is not None
    assert notified, "manager handoff must still dispatch"


# =========================================================================
# 12 — no secret token is logged; real send path with mocked httpx.
# =========================================================================


def test_no_secret_token_logged(monkeypatch, caplog):
    secret = "EAA_SECRET_TOKEN_VALUE_xyz"
    monkeypatch.setattr(
        notification_service, "settings",
        _cfg(WHATSAPP_TOKEN=secret, WHATSAPP_PHONE_NUMBER_ID="PID123",
             MANAGER_WHATSAPP_NUMBER="995595999733"),
    )
    resp = MagicMock()
    resp.is_success = True
    post_mock = MagicMock(return_value=resp)
    monkeypatch.setattr(notification_service.httpx, "post", post_mock)

    with caplog.at_level(logging.INFO):
        assert notification_service._send_manager_whatsapp("body text") is True

    # The token must NEVER appear in any log line; recipient masked to last 4.
    all_logs = "\n".join(r.getMessage() for r in caplog.records)
    assert secret not in all_logs
    assert "995595999733" not in all_logs  # full recipient not logged
    assert "9733" in all_logs              # masked last-4 ok
    # The real API call carries the token in the header (mocked, not logged).
    sent_headers = post_mock.call_args.kwargs["headers"]
    assert sent_headers["Authorization"] == f"Bearer {secret}"
    assert post_mock.call_args.kwargs["json"]["to"] == "995595999733"


def test_send_manager_whatsapp_short_circuits_when_unconfigured(monkeypatch):
    monkeypatch.setattr(notification_service, "settings", _cfg(WHATSAPP_TOKEN=""))
    post_mock = MagicMock()
    monkeypatch.setattr(notification_service.httpx, "post", post_mock)
    assert notification_service._send_manager_whatsapp("body") is False
    post_mock.assert_not_called()


# =========================================================================
# 14–15 — regression guards: Sheets A–Q + Saturday/Sunday scheduling.
# =========================================================================


def test_sheets_aq_schema_unchanged():
    assert sheets_service.HEADERS == [
        "ID", "Sender ID", "Platform", "Segment", "Name", "Phone", "Child Age",
        "Challenge", "Deeper Concern", "Desired Change", "Event Interest",
        "Consultation Booked", "Conversation Summary", "Status", "Created At",
        "Last Activity", "Follow-up Sent",
    ]
    # Row builder still ID-first, header-aligned.
    row = sheets_service._lead_to_row(_booked_lead(), 7)
    assert row[0] == 7 and row[1] == "wa-book"


def test_saturday_sunday_scheduling_unchanged():
    ok_sat, reason_sat = calendar_service.is_within_business_hours(
        datetime(SAT[0], SAT[1], SAT[2], 12, 0, tzinfo=TBILISI),
    )
    assert ok_sat is True and reason_sat == ""
    ok_sun, reason_sun = calendar_service.is_within_business_hours(
        datetime(SUN[0], SUN[1], SUN[2], 12, 0, tzinfo=TBILISI),
    )
    assert ok_sun is False and reason_sun == "weekend"
