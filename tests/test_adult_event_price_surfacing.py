"""Live QA Patch (2026-06-08) — adult event price not shown despite
Admin Panel `price_text` / `price_gel`.

Tests:
  * Admin save → YAML preservation
  * Normaliser preserves both fields
  * Executor compact (`get_adult_events`) surfaces price_text + price_gel
  * Executor details (`get_adult_event_details`) surfaces price_text +
    price_gel
  * Per-conversation `adult_price_disclosed_for_conversation` flag is
    flipped when the executor returns a non-blank price
  * Sanitiser strips invented „price missing" copy when the flag is set
  * Sanitiser preserves canonical „ფასი ამ ეტაპზე მითითებული არ არის."
    when the flag is NOT set (genuine missing-price branch)
"""

from __future__ import annotations

import textwrap

import pytest
import yaml

from app.agent.llm.adult_llm_engine import sanitise_adult_response
from app.agent.tools import adult_tool_executor
from app.agent.tools.adult_tool_executor import AdultToolExecutor
from app.agent.tools.adult_tools import (
    TOOL_GET_ADULT_EVENT_DETAILS,
    TOOL_GET_ADULT_EVENTS,
)
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import admin_config_service


@pytest.fixture(autouse=True)
def reset_state():
    adult_tool_executor.reset_state()
    yield
    adult_tool_executor.reset_state()


@pytest.fixture
def sections_path(monkeypatch, tmp_path):
    path = tmp_path / "sections.yaml"
    monkeypatch.setattr(admin_config_service, "SECTIONS_PATH", path)
    return path


def _seed_yaml(path, events: list[dict]) -> None:
    body = yaml.safe_dump(
        {"sections": [
            {
                "id": "adult_events",
                "name": "ზრდასრულთა ღონისძიებები",
                "type": "adult_events",
                "status": "active",
                "hashtags": ["ღონისძიება"],
                "age_min": 13,
                "auto_dm_template_id": "adult_events_comment_dm",
                "events": events,
            },
        ]},
        allow_unicode=True, sort_keys=False, default_flow_style=False,
    )
    path.write_text(body, encoding="utf-8")


def _build_executor(sender_id: str = "tester") -> AdultToolExecutor:
    lead = Lead(sender_id=sender_id, platform="instagram", segment="ADULT")
    conv = Conversation(sender_id=sender_id, platform="instagram", segment="ADULT")
    return AdultToolExecutor(
        conversation=conv, lead=lead, sender_id=sender_id, platform="instagram",
    )


# ---------------------------------------------------------------------------
# 1. Service layer — both fields round-trip through YAML
# ---------------------------------------------------------------------------


def test_save_event_with_price_text_and_price_gel_preserves_both(sections_path):
    _seed_yaml(sections_path, [])
    admin_config_service.save_adult_event(
        {
            "id": "poetry", "title": "ქართული პოეზიის საღამო",
            "status": "active", "min_age": 13,
            "price_text": "150", "price_gel": 150,
        },
    )
    raw = yaml.safe_load(sections_path.read_text(encoding="utf-8"))
    events = raw["sections"][0]["events"]
    assert events[0]["price_text"] == "150"
    assert events[0]["price_gel"] == 150


def test_normaliser_preserves_price_text_and_price_gel(sections_path):
    _seed_yaml(sections_path, [
        {
            "id": "poetry", "title": "T", "status": "active",
            "min_age": 13, "price_text": "150 ლარი", "price_gel": 150,
        },
    ])
    events = admin_config_service.get_adult_events()
    assert events[0]["price_text"] == "150 ლარი"
    assert events[0]["price_gel"] == 150


# ---------------------------------------------------------------------------
# 2. Executor — both list and details payloads surface both fields
# ---------------------------------------------------------------------------


def test_compact_payload_includes_price_text(sections_path):
    _seed_yaml(sections_path, [
        {
            "id": "p", "title": "T", "status": "active",
            "min_age": 13, "price_text": "150",
        },
    ])
    executor = _build_executor()
    result = executor.execute(TOOL_GET_ADULT_EVENTS, {"user_age": 30})
    assert result["events"][0]["price_text"] == "150"


def test_compact_payload_includes_price_gel(sections_path):
    _seed_yaml(sections_path, [
        {
            "id": "p", "title": "T", "status": "active",
            "min_age": 13, "price_gel": 150,
        },
    ])
    executor = _build_executor()
    result = executor.execute(TOOL_GET_ADULT_EVENTS, {"user_age": 30})
    assert result["events"][0]["price_gel"] == 150


def test_compact_payload_omits_price_gel_when_zero(sections_path):
    _seed_yaml(sections_path, [
        {
            "id": "p", "title": "T", "status": "active",
            "min_age": 13,
        },
    ])
    executor = _build_executor()
    result = executor.execute(TOOL_GET_ADULT_EVENTS, {"user_age": 30})
    assert "price_gel" not in result["events"][0]


def test_details_payload_includes_price_text_and_price_gel(sections_path):
    _seed_yaml(sections_path, [
        {
            "id": "poetry", "title": "ქართული პოეზიის საღამო",
            "status": "active", "min_age": 13,
            "price_text": "150", "price_gel": 150,
        },
    ])
    executor = _build_executor()
    result = executor.execute(
        TOOL_GET_ADULT_EVENT_DETAILS,
        {"event_id_or_title": "ქართული პოეზიის საღამო"},
    )
    assert result["success"] is True
    assert result["event"]["price_text"] == "150"
    assert result["event"]["price_gel"] == 150


def test_details_payload_with_only_price_gel(sections_path):
    """`price_text` blank but `price_gel` set: details payload must
    still surface `price_gel` so the LLM has a fallback."""
    _seed_yaml(sections_path, [
        {
            "id": "p", "title": "T", "status": "active",
            "min_age": 13, "price_gel": 200,
        },
    ])
    executor = _build_executor()
    result = executor.execute(
        TOOL_GET_ADULT_EVENT_DETAILS,
        {"event_id_or_title": "T"},
    )
    assert result["event"]["price_gel"] == 200
    # price_text in the normalised event is the empty string.
    assert result["event"]["price_text"] == ""


def test_details_payload_omits_price_gel_when_zero(sections_path):
    _seed_yaml(sections_path, [
        {
            "id": "p", "title": "T", "status": "active",
            "min_age": 13,
        },
    ])
    executor = _build_executor()
    result = executor.execute(
        TOOL_GET_ADULT_EVENT_DETAILS,
        {"event_id_or_title": "T"},
    )
    assert "price_gel" not in result["event"]


# ---------------------------------------------------------------------------
# 3. Per-conversation price-disclosure flag
# ---------------------------------------------------------------------------


def test_price_disclosed_flag_set_when_price_text_returned(sections_path):
    _seed_yaml(sections_path, [
        {
            "id": "p", "title": "T", "status": "active",
            "min_age": 13, "price_text": "150",
        },
    ])
    executor = _build_executor("price_sender")
    executor.execute(TOOL_GET_ADULT_EVENTS, {"user_age": 30})
    assert adult_tool_executor.is_price_disclosed("price_sender")


def test_price_disclosed_flag_set_when_only_price_gel_returned(sections_path):
    _seed_yaml(sections_path, [
        {
            "id": "p", "title": "T", "status": "active",
            "min_age": 13, "price_gel": 200,
        },
    ])
    executor = _build_executor("gel_sender")
    executor.execute(TOOL_GET_ADULT_EVENTS, {"user_age": 30})
    assert adult_tool_executor.is_price_disclosed("gel_sender")


def test_price_disclosed_flag_NOT_set_when_no_price(sections_path):
    _seed_yaml(sections_path, [
        {
            "id": "p", "title": "T", "status": "active",
            "min_age": 13,
        },
    ])
    executor = _build_executor("no_price_sender")
    executor.execute(TOOL_GET_ADULT_EVENTS, {"user_age": 30})
    assert not adult_tool_executor.is_price_disclosed("no_price_sender")


def test_price_disclosed_flag_set_via_details_handler(sections_path):
    _seed_yaml(sections_path, [
        {
            "id": "p", "title": "T", "status": "active",
            "min_age": 13, "price_text": "150",
        },
    ])
    executor = _build_executor("details_sender")
    executor.execute(
        TOOL_GET_ADULT_EVENT_DETAILS, {"event_id_or_title": "T"},
    )
    assert adult_tool_executor.is_price_disclosed("details_sender")


# ---------------------------------------------------------------------------
# 4. Sanitiser — strips invented "price missing" copy when disclosed
# ---------------------------------------------------------------------------


_LIVE_HALLUCINATED_PHRASES = (
    "დასწრების საფასური ღონისძიების კონფიგურაციაში მითითებული არაა",
    "დასწრების საფასური მითითებული არ არის",
    "საფასური კონფიგურაციაში მითითებული არაა",
    "ფასი ღონისძიების კონფიგურაციაში არ მოდის",
    "ფასი კონფიგურაციაში მითითებული არ არის",
    "ფასი ცნობილი არ არის",
    "ფასი მოცემული არ არის",
)


@pytest.mark.parametrize("phrase", _LIVE_HALLUCINATED_PHRASES)
def test_sanitiser_strips_invented_price_missing_when_disclosed(
    sections_path, phrase,
):
    """When the executor flagged price-disclosed for this turn, any
    „price missing" copy is a hallucination and must be stripped."""
    adult_tool_executor.mark_price_disclosed("active_sender")
    bot_text = (
        "ქართული პოეზიის საღამო გაიმართება 25 ივნისს. "
        f"{phrase}. ფასი: 150 ლარი."
    )
    out = sanitise_adult_response(bot_text, sender_id="active_sender")
    assert phrase not in out, f"phrase {phrase!r} survived: {out!r}"
    assert "ფასი: 150 ლარი" in out


def test_sanitiser_keeps_canonical_missing_price_when_not_disclosed(
    sections_path,
):
    """When the executor did NOT flag price-disclosed, the legitimate
    canonical „ფასი ამ ეტაპზე მითითებული არ არის." passes through."""
    bot_text = "ფასი ამ ეტაპზე მითითებული არ არის. დაგვიკავშირდით."
    out = sanitise_adult_response(bot_text, sender_id="no_flag_sender")
    assert "ფასი ამ ეტაპზე მითითებული არ არის" in out


def test_sanitiser_no_sender_id_does_not_strip_price_missing():
    """Unit-test path (sender_id=None) leaves the price filter OFF so
    legacy tests on the rewrite table do not regress."""
    bot_text = "ფასი მოცემული არ არის."
    out = sanitise_adult_response(bot_text, sender_id=None)
    assert "ფასი მოცემული არ არის" in out


def test_disclosure_flag_cleared_independently():
    """Each disclosure flag is per-sender and per-purpose."""
    adult_tool_executor.mark_price_disclosed("alice")
    adult_tool_executor.mark_sold_out_disclosed("bob")
    assert adult_tool_executor.is_price_disclosed("alice")
    assert not adult_tool_executor.is_price_disclosed("bob")
    assert adult_tool_executor.is_sold_out_disclosed("bob")
    assert not adult_tool_executor.is_sold_out_disclosed("alice")
    adult_tool_executor.clear_price_disclosed("alice")
    assert not adult_tool_executor.is_price_disclosed("alice")


# ---------------------------------------------------------------------------
# 5. Reservation URL behaviour unchanged
# ---------------------------------------------------------------------------


def test_reservation_url_still_surfaces_alongside_price(sections_path):
    """Sanity check that the price patch didn't break the Bug 3 fix —
    reservation_url is still surfaced in the details payload."""
    _seed_yaml(sections_path, [
        {
            "id": "p", "title": "T", "status": "active",
            "min_age": 13, "price_text": "150 ლარი",
            "reservation_url": "https://example.com/p",
        },
    ])
    executor = _build_executor()
    result = executor.execute(
        TOOL_GET_ADULT_EVENT_DETAILS, {"event_id_or_title": "T"},
    )
    assert result["event"]["reservation_url"] == "https://example.com/p"
    assert result["event"]["price_text"] == "150 ლარი"
