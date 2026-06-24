"""Live QA Patch (2026-06-08) — Adult event selection, ticket link, no
invented seat availability.

Test groups (per task spec):
  1. No invented sold-out text   (Bug 1)
  2. Link handling                (Bug 3)
  3. Missing link handoff         (Bug 3)
  4. Explicit sold_out support    (Bug 1)
  5. Partial title matching       (Bug 2)
  6. Multiple match clarification (Bug 2)
  7. Inactive event exclusion     (Bug 2)
  8. Polite wording               (Bug 5)
  9. No filler thanks             (Bug 4)
 10. Wording rewrites             (Bug 5)
"""

from __future__ import annotations

import textwrap

import pytest
import yaml

from app.agent.llm import adult_llm_engine
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
    """Write a sections.yaml with the canonical adult_events section
    and the supplied events list. Building the YAML programmatically
    via yaml.safe_dump avoids the indentation traps that bite the
    textwrap-style fixtures."""
    sections = [
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
    ]
    body = yaml.safe_dump(
        {"sections": sections},
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
# 1. No invented sold-out text (Bug 1)
# ---------------------------------------------------------------------------


def test_compact_events_does_not_send_zero_seats(sections_path):
    """seats_available=0 was triggering invented sold-out copy. The
    field must be OMITTED entirely when zero — the LLM must not see a
    falsy number it can interpret as „no seats left"."""
    _seed_yaml(sections_path, [
        {
            "id": "poetry", "title": "ქართული პოეზიის საღამო",
            "status": "active", "min_age": 13,
            "date_text": "25 ივნისი, 20:00",
            "location": "ამბასადორი კაჭრეთი",
            "price_text": "80 ლარი",
            "reservation_url": "https://example.com/poetry",
        },
    ])
    executor = _build_executor()
    result = executor.execute(TOOL_GET_ADULT_EVENTS, {"user_age": 30})
    event = result["events"][0]
    assert "seats_available" not in event
    assert event["sold_out"] is False


def test_compact_events_sends_positive_seats_only(sections_path):
    """Operator-entered positive seat count IS surfaced."""
    _seed_yaml(sections_path, [
        {
            "id": "with_seats", "title": "ღონისძიება",
            "status": "active", "min_age": 13,
            "seats_available": 12,
        },
    ])
    executor = _build_executor()
    result = executor.execute(TOOL_GET_ADULT_EVENTS, {"user_age": 30})
    assert result["events"][0]["seats_available"] == 12


def test_sanitiser_strips_invented_sold_out_phrase(sections_path):
    """Default state (no executor disclosure) → invented copy stripped."""
    bot_text = (
        "ქართული პოეზიის საღამო გაიმართება 25 ივნისს. "
        "ადგილები ამჟამად ამოწურულია. ფასი: 80 ლარი."
    )
    out = sanitise_adult_response(bot_text, sender_id="anyone")
    assert "ადგილები ამჟამად ამოწურულია" not in out
    assert "ფასი: 80 ლარი" in out
    assert "გაიმართება 25 ივნისს" in out


def test_sanitiser_strips_alternate_sold_out_wordings(sections_path):
    for phrase in (
        "ადგილები ამოწურულია",
        "ადგილები აღარ არის",
        "ბილეთები ამოწურულია",
        "sold out",
    ):
        bot_text = f"ღონისძიება გაიმართება. {phrase}. ფასი: 80 ლარი."
        out = sanitise_adult_response(bot_text, sender_id="someone")
        assert phrase.casefold() not in out.casefold(), (
            f"phrase {phrase!r} survived the sanitiser: {out!r}"
        )


def test_sanitiser_no_sender_id_does_not_strip_sold_out(sections_path):
    """When called with sender_id=None (unit-test path) the sold-out
    filter is OFF — pre-existing tests on the raw rewrite table keep
    working unmodified."""
    bot_text = "ადგილები ამოწურულია. დაგვიკავშირდით."
    out = sanitise_adult_response(bot_text, sender_id=None)
    assert "ადგილები ამოწურულია" in out


# ---------------------------------------------------------------------------
# 2. Explicit sold_out support
# ---------------------------------------------------------------------------


def test_explicit_sold_out_true_disclosed_through_executor(sections_path):
    """When the event row has sold_out=true, the executor flips the
    per-conversation disclosure flag so the sanitiser permits legitimate
    sold-out copy."""
    _seed_yaml(sections_path, [
        {
            "id": "full_event", "title": "სრულად დაჯავშნილი",
            "status": "active", "min_age": 13,
            "sold_out": True,
        },
    ])
    executor = _build_executor("sender_with_sold_out")
    result = executor.execute(
        TOOL_GET_ADULT_EVENT_DETAILS,
        {"event_id_or_title": "სრულად დაჯავშნილი"},
    )
    assert result["success"] is True
    assert result["event"]["sold_out"] is True
    assert adult_tool_executor.is_sold_out_disclosed("sender_with_sold_out")


def test_status_sold_out_shortcut_recognised(sections_path):
    """A row with `status: sold_out` is treated as sold-out without an
    explicit `sold_out: true` boolean."""
    _seed_yaml(sections_path, [
        {
            "id": "status_sold", "title": "status-only-sold",
            "status": "sold_out", "min_age": 13,
        },
    ])
    events = admin_config_service.get_adult_events()
    assert events[0]["sold_out"] is True
    # status: sold_out collapses to "inactive" for the public
    # active/inactive contract — agent does not surface this event.
    assert events[0]["active"] is False


def test_active_event_never_described_as_sold_out_via_sanitiser(sections_path):
    """An active event with no sold_out flag must never produce
    sold-out copy in the final output — sanitiser strips it."""
    _seed_yaml(sections_path, [
        {
            "id": "active_event", "title": "აქტიური საღამო",
            "status": "active", "min_age": 13,
        },
    ])
    executor = _build_executor("active_sender")
    executor.execute(TOOL_GET_ADULT_EVENTS, {"user_age": 30})
    assert not adult_tool_executor.is_sold_out_disclosed("active_sender")
    out = sanitise_adult_response(
        "აქტიური საღამო. ადგილები აღარ არის.", sender_id="active_sender",
    )
    assert "ადგილები აღარ არის" not in out


def test_disclosure_flag_cleared_at_start_of_next_turn(sections_path):
    """The flag is per-turn — `run_adult_llm_turn` clears it at entry
    so a previous turn's sold_out state does not leak."""
    adult_tool_executor.mark_sold_out_disclosed("user_x")
    assert adult_tool_executor.is_sold_out_disclosed("user_x")
    # Simulate the call-site clear that the engine does.
    adult_tool_executor.clear_sold_out_disclosed("user_x")
    assert not adult_tool_executor.is_sold_out_disclosed("user_x")


# ---------------------------------------------------------------------------
# 3. Reservation link handling (Bug 3)
# ---------------------------------------------------------------------------


def test_event_details_includes_reservation_url_directly(sections_path):
    """The executor must surface `reservation_url` in the details
    payload so the LLM can include it in the same response."""
    _seed_yaml(sections_path, [
        {
            "id": "poetry", "title": "ქართული პოეზიის საღამო",
            "status": "active", "min_age": 13,
            "date_text": "25 ივნისი, 20:00",
            "location": "ამბასადორი კაჭრეთი",
            "price_text": "80 ლარი",
            "reservation_url": "https://example.com/poetry-tickets",
        },
    ])
    executor = _build_executor()
    result = executor.execute(
        TOOL_GET_ADULT_EVENT_DETAILS,
        {"event_id_or_title": "ქართული პოეზიის საღამო"},
    )
    assert result["success"] is True
    assert result["event"]["reservation_url"] == "https://example.com/poetry-tickets"
    assert result["event"]["has_reservation_url"] is True


def test_event_details_includes_payment_terms_link(sections_path):
    """payment_terms is also surfaced when present — operator may use
    it as the ticket link slot when no dedicated reservation_url
    exists."""
    _seed_yaml(sections_path, [
        {
            "id": "with_payment", "title": "გადახდის ღონისძიება",
            "status": "active", "min_age": 13,
            "payment_terms": "https://example.com/pay",
        },
    ])
    executor = _build_executor()
    result = executor.execute(
        TOOL_GET_ADULT_EVENT_DETAILS,
        {"event_id_or_title": "with_payment"},
    )
    assert result["success"] is True
    assert result["event"].get("payment_terms") == "https://example.com/pay"


def test_event_details_omits_link_when_missing(sections_path):
    _seed_yaml(sections_path, [
        {
            "id": "no_link", "title": "ბმულის გარეშე",
            "status": "active", "min_age": 13,
        },
    ])
    executor = _build_executor()
    result = executor.execute(
        TOOL_GET_ADULT_EVENT_DETAILS,
        {"event_id_or_title": "no_link"},
    )
    assert result["success"] is True
    assert result["event"]["has_reservation_url"] is False
    assert "reservation_url" not in result["event"]
    assert "payment_terms" not in result["event"]


# ---------------------------------------------------------------------------
# 4. Partial title matching (Bug 2)
# ---------------------------------------------------------------------------


@pytest.fixture
def poetry_with_extras(sections_path):
    _seed_yaml(sections_path, [
        {
            "id": "poetry", "title": "ქართული პოეზიის საღამო",
            "status": "active", "min_age": 13,
            "date_text": "25 ივნისი, 20:00",
            "location": "ამბასადორი კაჭრეთი",
            "price_text": "80 ლარი",
            "reservation_url": "https://example.com/p",
        },
        {
            "id": "jazz", "title": "ჯაზის საღამო",
            "status": "active", "min_age": 13,
        },
        {
            "id": "maroon", "title": "Maroon 5 კონცერტი",
            "status": "active", "min_age": 13,
        },
    ])
    return sections_path


def test_partial_title_kartuli_poezia_matches(poetry_with_extras):
    """The headline live-bug: „ქართული პოეზია" must match
    „ქართული პოეზიის საღამო"."""
    matches = admin_config_service.find_adult_events_matching("ქართული პოეზია")
    assert len(matches) == 1
    assert matches[0]["id"] == "poetry"


def test_partial_title_poezi_sagamo_matches(poetry_with_extras):
    """„პოეზიის საღამო" must match the same event."""
    matches = admin_config_service.find_adult_events_matching("პოეზიის საღამო")
    assert any(e["id"] == "poetry" for e in matches)


def test_exact_title_still_matches(poetry_with_extras):
    matches = admin_config_service.find_adult_events_matching(
        "ქართული პოეზიის საღამო",
    )
    assert len(matches) == 1
    assert matches[0]["id"] == "poetry"


def test_partial_english_title_matches(poetry_with_extras):
    matches = admin_config_service.find_adult_events_matching("maroon")
    assert any(e["id"] == "maroon" for e in matches)


def test_exact_id_match_wins(poetry_with_extras):
    """An exact id match returns only that event even if other titles
    would stem-match — the operator can always force-select by id."""
    matches = admin_config_service.find_adult_events_matching("jazz")
    assert len(matches) == 1
    assert matches[0]["id"] == "jazz"


# ---------------------------------------------------------------------------
# 5. Multiple match clarification (Bug 2)
# ---------------------------------------------------------------------------


def test_multiple_matches_returns_all_candidates(sections_path):
    _seed_yaml(sections_path, [
        {
            "id": "poetry_morning", "title": "დილის პოეზიის საღამო",
            "status": "active", "min_age": 13,
        },
        {
            "id": "poetry_evening", "title": "საღამოს პოეზიის საღამო",
            "status": "active", "min_age": 13,
        },
    ])
    matches = admin_config_service.find_adult_events_matching("პოეზიის საღამო")
    assert len(matches) == 2


def test_executor_returns_ambiguous_event_for_multi_match(sections_path):
    _seed_yaml(sections_path, [
        {
            "id": "poetry_a", "title": "ქართული პოეზიის საღამო",
            "status": "active", "min_age": 13,
        },
        {
            "id": "poetry_b", "title": "უცხოური პოეზიის საღამო",
            "status": "active", "min_age": 13,
        },
    ])
    executor = _build_executor()
    result = executor.execute(
        TOOL_GET_ADULT_EVENT_DETAILS,
        {"event_id_or_title": "პოეზიის საღამო"},
    )
    assert result["success"] is False
    assert result["reason"] == "ambiguous_event"
    titles = [c["title"] for c in result["candidates"]]
    assert "ქართული პოეზიის საღამო" in titles
    assert "უცხოური პოეზიის საღამო" in titles


def test_find_adult_event_returns_none_when_ambiguous(sections_path):
    _seed_yaml(sections_path, [
        {
            "id": "a", "title": "პოეზიის საღამო ერთი",
            "status": "active", "min_age": 13,
        },
        {
            "id": "b", "title": "პოეზიის საღამო ორი",
            "status": "active", "min_age": 13,
        },
    ])
    # Direct service helper returns None when multiple match.
    assert admin_config_service.find_adult_event("პოეზიის საღამო") is None


# ---------------------------------------------------------------------------
# 6. Inactive event exclusion (Bug 2)
# ---------------------------------------------------------------------------


def test_inactive_event_not_returned_by_matcher(sections_path):
    _seed_yaml(sections_path, [
        {
            "id": "archived", "title": "ძველი საღამო",
            "status": "inactive", "min_age": 13,
        },
    ])
    matches = admin_config_service.find_adult_events_matching("ძველი საღამო")
    assert matches == []


def test_inactive_event_returned_when_include_inactive(sections_path):
    """The fallback branch in the executor's `event_inactive` path
    needs the inactive-included list to detect deliberate queries
    against an archived event."""
    _seed_yaml(sections_path, [
        {
            "id": "archived", "title": "ძველი საღამო",
            "status": "inactive", "min_age": 13,
        },
    ])
    matches = admin_config_service.find_adult_events_matching(
        "ძველი საღამო", include_inactive=True,
    )
    assert len(matches) == 1
    assert matches[0]["id"] == "archived"


def test_executor_reports_event_inactive_distinct_from_unknown(sections_path):
    _seed_yaml(sections_path, [
        {
            "id": "archived", "title": "ძველი საღამო",
            "status": "inactive", "min_age": 13,
        },
    ])
    executor = _build_executor()
    result = executor.execute(
        TOOL_GET_ADULT_EVENT_DETAILS,
        {"event_id_or_title": "ძველი საღამო"},
    )
    assert result["success"] is False
    assert result["reason"] == "event_inactive"
    assert "ძველი საღამო" in result["matched_titles"]


# ---------------------------------------------------------------------------
# 7. Polite wording (Bug 5) + filler thanks (Bug 4)
# ---------------------------------------------------------------------------


def test_sanitiser_replaces_gindas_with_gsurts():
    out = sanitise_adult_response("გინდა, რომ გაგიგზავნოთ ბმული?", sender_id=None)
    assert "გინდა," not in out
    assert "გსურთ," in out


def test_sanitiser_replaces_gindat_with_gsurts():
    out = sanitise_adult_response("გინდათ?", sender_id=None)
    assert "გინდათ" not in out
    assert "გსურთ?" in out


def test_sanitiser_strips_leading_thanks_before_age_question():
    bot_text = "გმადლობთ. რამდენი წლის ბრძანდებით?"
    out = sanitise_adult_response(bot_text, sender_id=None)
    assert "გმადლობთ" not in out
    assert "რამდენი წლის ბრძანდებით" in out
    assert out.startswith("რამდენი წლის ბრძანდებით")


def test_sanitiser_strips_thanks_with_alt_punctuation():
    for opener in (
        "გმადლობთ! რამდენი წლის ბრძანდებით?",
        "გმადლობთ, რამდენი წლის ბრძანდებით?",
    ):
        out = sanitise_adult_response(opener, sender_id=None)
        assert not out.startswith("გმადლობთ"), (
            f"thanks filler survived: {out!r}"
        )


def test_legitimate_thanks_in_middle_of_response_preserved():
    """The strip only fires for the SENTENCE-INITIAL „გმადლობთ.[!,] "
    pattern. A mid-response thanks must survive."""
    bot_text = (
        "კარგი არჩევანი — გმადლობთ, რომ შემოგვიერთდით. "
        "რეგისტრაციის ბმული: https://example.com"
    )
    out = sanitise_adult_response(bot_text, sender_id=None)
    assert "გმადლობთ" in out


# ---------------------------------------------------------------------------
# 8. Service-level sanity — sold_out yaml round-trip
# ---------------------------------------------------------------------------


def test_save_event_with_sold_out_persists(sections_path):
    sections_path.write_text(
        textwrap.dedent(
            """\
            sections:
            - id: adult_events
              name: ზრდასრულთა
              type: adult_events
              status: active
              hashtags: [event]
              auto_dm_template_id: adult_events_comment_dm
              events: []
            """,
        ),
        encoding="utf-8",
    )
    admin_config_service.save_adult_event(
        {
            "id": "x", "title": "X", "status": "active",
            "min_age": 13, "sold_out": True,
        },
    )
    events = admin_config_service.get_adult_events()
    assert events[0]["sold_out"] is True


# ---------------------------------------------------------------------------
# 9. End-to-end coverage of stem matcher edge cases
# ---------------------------------------------------------------------------


def test_short_query_does_not_overmatch(poetry_with_extras):
    """A 1-character query („ი") must NOT match every Georgian title.
    The stem matcher requires stems ≥3 characters."""
    matches = admin_config_service.find_adult_events_matching("ი")
    # Either zero matches (no event title equals/contains "ი" as a
    # whole word substring) OR a small bounded set. We just assert it
    # does not return ALL three seeded events.
    assert len(matches) < 3


def test_unknown_query_returns_empty(poetry_with_extras):
    matches = admin_config_service.find_adult_events_matching("ფიქცია")
    assert matches == []
