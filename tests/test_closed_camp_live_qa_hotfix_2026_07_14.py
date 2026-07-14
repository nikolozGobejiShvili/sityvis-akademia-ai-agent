from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.reasoning import camp_topic_facts
from app.services import admin_config_service, conversation_service


def _parent_conv(sender_id: str = "closed-live") -> Conversation:
    conv = Conversation(
        sender_id=sender_id,
        platform="instagram",
        page_id="page-live",
        segment="PARENT",
    )
    conv.lead = Lead(
        sender_id=sender_id,
        platform="instagram",
        segment="PARENT",
        child_age="12",
    )
    return conv


@pytest.fixture
def closed_registration(monkeypatch):
    monkeypatch.setattr(
        admin_config_service,
        "get_camp_registration_status",
        lambda: "closed",
    )


@pytest.fixture
def current_stream_clock(monkeypatch):
    tbilisi = ZoneInfo("Asia/Tbilisi")
    now = datetime(2026, 7, 14, 12, 0, tzinfo=tbilisi)
    monkeypatch.setattr(admin_config_service, "_now_tbilisi", lambda: (now, tbilisi))


def test_closed_camp_price_keeps_facts_but_suppresses_consultation_cta(closed_registration):
    out = parent_flow._camp_price_direct_answer()

    for expected in ("2150", "ტრანსპორტირება", "გადანაწილება", "TBC", "საქართველოს ბანკ", "10%"):
        assert expected in out
    assert "კონსულტაციაზე ჩაგწერთ" not in out
    assert "რეგისტრაციის" not in out
    assert "http" not in out.lower()


@pytest.mark.parametrize(
    "message",
    [
        "შეიძლება ახლა ჩაწერა?",
        "რეგისტრაციის ლინკზე",
        "რეგისტრაციის ლინკი გამომიგზავნეთ",
    ],
)
def test_unclear_registration_requests_return_closed_camp_answer(closed_registration, message):
    conversation_service.conversations.clear()

    out = conversation_service.process_message(
        f"closed-registration-{abs(hash(message))}",
        message,
        platform="instagram",
        page_id="page-live",
    )

    assert out == parent_flow._camp_registration_closed_short_answer()
    assert "http" not in out.lower()
    assert "რომელი მიმართულების" not in out
    assert "საკვირაო" not in out


def test_stream_date_question_uses_current_stream_lifecycle_fact(current_stream_clock, closed_registration):
    out = parent_flow._maybe_handle_camp_stream_lifecycle(
        _parent_conv("stream-date"),
        "ნაკადები როდის არის ბანაკის?",
    )

    assert out is not None
    assert "ბანაკის მე-3 ნაკადი ტარდება" in out
    assert "14–20 ივლისს" in out
    assert "7-დღ" not in out
    assert "კონსულტაციაზე" not in out
    assert "http" not in out.lower()


def test_started_camp_question_uses_lifecycle_fact_not_manager_deferral(current_stream_clock, closed_registration):
    out = parent_flow._maybe_handle_camp_stream_lifecycle(
        _parent_conv("stream-started"),
        "დაიწყო უკვე ბანაკი?",
    )

    assert out is not None
    assert out.startswith("დიახ, ")
    assert "ბანაკის მე-3 ნაკადი ტარდება" in out
    assert "14–20 ივლისს" in out
    assert "მენეჯერი" not in out
    assert "http" not in out.lower()


def test_transport_fallback_uses_canonical_contact_source(monkeypatch):
    sentinel = "MANAGER_CONTACT_SENTINEL"
    monkeypatch.setattr(admin_config_service, "get_manager_phone", lambda: sentinel)
    monkeypatch.setattr(parent_flow, "_approved_camp_copy", lambda *args, **kwargs: None)

    out = parent_flow._transport_answer("", pickup=False)

    assert "ტრანსპორტირება" in out
    assert sentinel in out
    assert "558" not in out
    assert "http" not in out.lower()


def test_unknown_detail_ending_uses_canonical_contact_source(monkeypatch):
    sentinel = "MANAGER_CONTACT_SENTINEL"
    monkeypatch.setattr(admin_config_service, "get_manager_phone", lambda: sentinel)

    out = camp_topic_facts.resolve_operational("ოთახებში როგორ ანაწილებთ ბავშვებს?")

    assert out is not None
    assert sentinel in out
    assert "558" not in out
