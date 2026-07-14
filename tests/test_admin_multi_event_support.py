"""Admin Panel multi-event support tests.

Covers the Multi-event Patch (2026-06-08) — the operator-facing roster
for adult/cultural events.

Test groups (per task spec):
  1. Admin add multiple events
  2. Admin edit event
  3. Admin deactivate / activate event (soft toggle, not delete)
  4. YAML persistence under adult_events.events[]
  5. Section-level metadata preservation across event edits
  6. Default min_age = 13
  7. min_age floor 13 enforced
  8. Active / inactive filtering at the service layer
  9. Age eligibility filtering
 10. Agent (executor) surfaces multiple eligible events
 11. Agent excludes inactive / ineligible events
 12. Agent handles event selection by title
 13. reservation_url handling
 14. facebook_post_id persistence
 15. No fallback duplicate when events[] is populated

The HTTP layer is exercised via FastAPI TestClient against admin
routes. The service + executor layers are exercised directly.
"""

from __future__ import annotations

import base64
import dataclasses
import textwrap
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from app.agent.tools import adult_tool_executor
from app.agent.tools.adult_tool_executor import AdultToolExecutor
from app.agent.tools.adult_tools import (
    TOOL_GET_ADULT_EVENT_DETAILS,
    TOOL_GET_ADULT_EVENTS,
    TOOL_PROVIDE_ADULT_RESERVATION_LINK,
)
from app.config import settings as global_settings
from app.main import app
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.routes import admin as admin_routes
from app.services import admin_config_service


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


SEED_SECTIONS_YAML = textwrap.dedent(
    """\
    sections:
    - id: summer_camp
      name: საზაფხულო ბანაკი
      type: camp
      status: active
      hashtags: [ბანაკი]
      age_min: 9
      age_max: 17
      auto_dm_template_id: summer_camp_comment_dm
    - id: adult_events
      name: ზრდასრულთა ღონისძიებები
      type: adult_events
      status: active
      hashtags: [ღონისძიება]
      age_min: 13
      auto_dm_template_id: adult_events_comment_dm
      description_short: ''
      events: []
    """,
)


@pytest.fixture
def sections_path(monkeypatch, tmp_path):
    """Redirect sections.yaml to a per-test tmp file with the canonical
    seed (camp section + empty adult_events.events[])."""
    path = tmp_path / "sections.yaml"
    path.write_text(SEED_SECTIONS_YAML, encoding="utf-8")
    monkeypatch.setattr(admin_config_service, "SECTIONS_PATH", path)
    return path


@pytest.fixture
def admin_enabled(monkeypatch):
    """Flip Admin Panel on with a known basic-auth password for the
    HTTP-layer tests."""
    swapped = dataclasses.replace(
        global_settings,
        ADMIN_PANEL_ENABLED=True,
        ADMIN_USERNAME="admin",
        ADMIN_PASSWORD="testpw",
    )
    monkeypatch.setattr(admin_routes, "settings", swapped)
    yield swapped


@pytest.fixture(autouse=True)
def reset_executor_state():
    adult_tool_executor.reset_state()
    yield
    adult_tool_executor.reset_state()


def _auth() -> dict[str, str]:
    raw = b"admin:testpw"
    return {"Authorization": "Basic " + base64.b64encode(raw).decode("ascii")}


def _read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _adult_events_in_yaml(path: Path) -> list[dict]:
    raw = _read_yaml(path).get("sections", [])
    for s in raw:
        if s.get("id") == "adult_events":
            return s.get("events") or []
    return []


def _adult_section_in_yaml(path: Path) -> dict:
    raw = _read_yaml(path).get("sections", [])
    for s in raw:
        if s.get("id") == "adult_events":
            return s
    return {}


def _build_executor(lead: Lead | None = None) -> AdultToolExecutor:
    lead = lead or Lead(sender_id="test_user", platform="instagram", segment="ADULT")
    conv = Conversation(sender_id="test_user", platform="instagram", segment="ADULT")
    return AdultToolExecutor(
        conversation=conv,
        lead=lead,
        sender_id="test_user",
        platform="instagram",
    )


# ---------------------------------------------------------------------------
# 1. Service layer — multi-event CRUD
# ---------------------------------------------------------------------------


def test_save_adult_event_writes_to_events_list(sections_path):
    errors = admin_config_service.save_adult_event(
        {
            "id": "maroon_5",
            "title": "Maroon 5 კონცერტი",
            "status": "active",
            "min_age": 13,
            "date_text": "23 ივნისი, 19:00",
            "location": "ბორის პაიჭაძის სტადიონი",
            "price_text": "200 ლარი",
            "description": "კულტურული საღამო / კონცერტი",
            "reservation_url": "https://example.com/maroon5",
            "facebook_post_id": "fb_post_123",
            "tags": ["კონცერტი", "საღამო"],
        },
    )
    assert errors == []
    persisted = _adult_events_in_yaml(sections_path)
    assert len(persisted) == 1
    assert persisted[0]["id"] == "maroon_5"
    assert persisted[0]["title"] == "Maroon 5 კონცერტი"
    assert persisted[0]["facebook_post_id"] == "fb_post_123"
    assert persisted[0]["tags"] == ["კონცერტი", "საღამო"]


def test_save_second_event_preserves_first(sections_path):
    admin_config_service.save_adult_event(
        {"id": "maroon_5", "title": "Maroon 5", "status": "active"},
    )
    admin_config_service.save_adult_event(
        {"id": "poetry", "title": "პოეზიის საღამო", "status": "active"},
    )
    persisted = _adult_events_in_yaml(sections_path)
    ids = [e["id"] for e in persisted]
    assert ids == ["maroon_5", "poetry"], (
        f"both events should persist in insertion order, got {ids}"
    )


def test_update_adult_event_updates_only_selected_event(sections_path):
    admin_config_service.save_adult_event(
        {
            "id": "maroon_5", "title": "Maroon 5", "status": "active",
            "price_text": "200 ლარი",
        },
    )
    admin_config_service.save_adult_event(
        {
            "id": "poetry", "title": "პოეზიის საღამო", "status": "active",
            "price_text": "80 ლარი",
        },
    )
    errors = admin_config_service.update_adult_event(
        "poetry", {"price_text": "100 ლარი"},
    )
    assert errors == []
    by_id = {e["id"]: e for e in _adult_events_in_yaml(sections_path)}
    assert by_id["maroon_5"]["price_text"] == "200 ლარი"
    assert by_id["poetry"]["price_text"] == "100 ლარი"
    assert by_id["poetry"]["title"] == "პოეზიის საღამო"


def test_update_adult_event_rejects_unknown_id(sections_path):
    errors = admin_config_service.update_adult_event(
        "does_not_exist", {"title": "x"},
    )
    assert errors and "not found" in errors[0].lower()


def test_deactivate_adult_event_sets_status_inactive(sections_path):
    admin_config_service.save_adult_event(
        {"id": "maroon_5", "title": "Maroon 5", "status": "active"},
    )
    assert admin_config_service.deactivate_adult_event("maroon_5") is True
    persisted = _adult_events_in_yaml(sections_path)
    assert persisted[0]["status"] == "inactive"


def test_activate_adult_event_sets_status_active(sections_path):
    admin_config_service.save_adult_event(
        {"id": "maroon_5", "title": "Maroon 5", "status": "inactive"},
    )
    assert admin_config_service.activate_adult_event("maroon_5") is True
    persisted = _adult_events_in_yaml(sections_path)
    assert persisted[0]["status"] == "active"


def test_deactivate_unknown_event_returns_false(sections_path):
    assert admin_config_service.deactivate_adult_event("nope") is False


def test_activate_unknown_event_returns_false(sections_path):
    assert admin_config_service.activate_adult_event("nope") is False


def test_save_adult_event_missing_title_rejected(sections_path):
    errors = admin_config_service.save_adult_event(
        {"id": "blank", "status": "active"},
    )
    assert errors and "title" in errors[0].lower()


def test_save_adult_event_invalid_status_rejected(sections_path):
    errors = admin_config_service.save_adult_event(
        {"id": "x", "title": "x", "status": "completely-bogus"},
    )
    assert errors and "status" in errors[0].lower()


# ---------------------------------------------------------------------------
# 2. Section-level metadata preservation
# ---------------------------------------------------------------------------


def test_section_metadata_preserved_after_event_save(sections_path):
    """Saving / editing events must NEVER blow away the section-level
    fields (hashtags, age_min, auto_dm_template_id, …) that the comment
    flow relies on."""
    admin_config_service.save_adult_event(
        {"id": "maroon_5", "title": "Maroon 5", "status": "active"},
    )
    section = _adult_section_in_yaml(sections_path)
    assert section["hashtags"] == ["ღონისძიება"]
    assert section["auto_dm_template_id"] == "adult_events_comment_dm"
    assert section["age_min"] == 13


def test_section_metadata_preserved_across_multiple_events(sections_path):
    for i in range(3):
        admin_config_service.save_adult_event(
            {"id": f"evt_{i}", "title": f"ღონისძიება {i}", "status": "active"},
        )
    section = _adult_section_in_yaml(sections_path)
    # Original metadata intact.
    assert section["hashtags"] == ["ღონისძიება"]
    assert section["auto_dm_template_id"] == "adult_events_comment_dm"
    # All three events landed.
    assert len(section["events"]) == 3


# ---------------------------------------------------------------------------
# 3. min_age default + floor
# ---------------------------------------------------------------------------


def test_missing_min_age_defaults_to_13(sections_path):
    admin_config_service.save_adult_event(
        {"id": "x", "title": "x", "status": "active"},
    )
    persisted = _adult_events_in_yaml(sections_path)
    assert persisted[0]["min_age"] == 13


def test_min_age_below_13_floored_to_13_on_save(sections_path):
    admin_config_service.save_adult_event(
        {"id": "x", "title": "x", "status": "active", "min_age": 8},
    )
    persisted = _adult_events_in_yaml(sections_path)
    assert persisted[0]["min_age"] == 13


def test_min_age_above_13_preserved(sections_path):
    admin_config_service.save_adult_event(
        {"id": "x", "title": "x", "status": "active", "min_age": 18},
    )
    persisted = _adult_events_in_yaml(sections_path)
    assert persisted[0]["min_age"] == 18


def test_min_age_below_13_normalised_to_13_on_read(sections_path):
    """Even when the YAML on disk somehow carries a sub-13 value
    (legacy data, hand-edit), get_adult_events floors it to 13."""
    sections_path.write_text(
        textwrap.dedent(
            """\
            sections:
            - id: adult_events
              name: ზრდასრულთა ღონისძიებები
              type: adult_events
              status: active
              hashtags: [ღონისძიება]
              auto_dm_template_id: adult_events_comment_dm
              events:
              - id: x
                title: x
                status: active
                min_age: 8
            """,
        ),
        encoding="utf-8",
    )
    events = admin_config_service.get_adult_events()
    assert events[0]["min_age"] == 13


# ---------------------------------------------------------------------------
# 4. Active / inactive filtering
# ---------------------------------------------------------------------------


def _seed_multi_status(sections_path):
    admin_config_service.save_adult_event(
        {"id": "a", "title": "A", "status": "active", "min_age": 13},
    )
    admin_config_service.save_adult_event(
        {"id": "b", "title": "B", "status": "active", "min_age": 16},
    )
    admin_config_service.save_adult_event(
        {"id": "c", "title": "C", "status": "inactive", "min_age": 13},
    )


def test_get_active_adult_events_excludes_inactive(sections_path):
    _seed_multi_status(sections_path)
    ids = [e["id"] for e in admin_config_service.get_active_adult_events()]
    assert set(ids) == {"a", "b"}
    assert "c" not in ids


def test_get_adult_events_includes_all_regardless_of_status(sections_path):
    _seed_multi_status(sections_path)
    ids = [e["id"] for e in admin_config_service.get_adult_events()]
    assert set(ids) == {"a", "b", "c"}


# ---------------------------------------------------------------------------
# 5. Age eligibility filtering
# ---------------------------------------------------------------------------


def _seed_age_matrix(sections_path):
    admin_config_service.save_adult_event(
        {"id": "13", "title": "T13", "status": "active", "min_age": 13},
    )
    admin_config_service.save_adult_event(
        {"id": "16", "title": "T16", "status": "active", "min_age": 16},
    )
    admin_config_service.save_adult_event(
        {"id": "18", "title": "T18", "status": "active", "min_age": 18},
    )
    admin_config_service.save_adult_event(
        {"id": "20", "title": "T20", "status": "active", "min_age": 20},
    )


def test_age_filter_15_returns_only_under_16(sections_path):
    _seed_age_matrix(sections_path)
    ids = {e["id"] for e in admin_config_service.get_active_adult_events(user_age=15)}
    assert ids == {"13"}


def test_age_filter_17_returns_13_and_16(sections_path):
    _seed_age_matrix(sections_path)
    ids = {e["id"] for e in admin_config_service.get_active_adult_events(user_age=17)}
    assert ids == {"13", "16"}


def test_age_filter_21_returns_all(sections_path):
    _seed_age_matrix(sections_path)
    ids = {e["id"] for e in admin_config_service.get_active_adult_events(user_age=21)}
    assert ids == {"13", "16", "18", "20"}


def test_age_filter_boundary_equal_to_min_age(sections_path):
    _seed_age_matrix(sections_path)
    ids = {e["id"] for e in admin_config_service.get_active_adult_events(user_age=18)}
    assert ids == {"13", "16", "18"}


# ---------------------------------------------------------------------------
# 6. Fallback semantics — events[] takes precedence
# ---------------------------------------------------------------------------


def test_events_list_prevents_section_level_fallback(sections_path):
    """When events[] has at least one entry, the section-level fallback
    (Bug 1A patch) must NOT add a duplicate phantom entry."""
    # Populate section with event-like fields AND a single real event.
    sections_path.write_text(
        textwrap.dedent(
            """\
            sections:
            - id: adult_events
              name: ზრდასრულთა ღონისძიებები
              type: adult_events
              status: active
              hashtags: [ღონისძიება]
              age_min: 13
              auto_dm_template_id: adult_events_comment_dm
              description_short: section-level title that would fallback
              price_text: '200'
              location: ბორის პაიჭაძის სტადიონი
              events:
              - id: real_event
                title: რეალური ღონისძიება
                status: active
                min_age: 13
            """,
        ),
        encoding="utf-8",
    )
    events = admin_config_service.get_adult_events()
    assert len(events) == 1, (
        f"events[] should be source of truth, no fallback duplicate; got {events}"
    )
    assert events[0]["id"] == "real_event"


def test_fallback_event_still_synthesised_when_events_list_empty(sections_path):
    """The Bug 1A behaviour must keep working — operator-saved section
    metadata without events[] still surfaces ONE fallback event."""
    sections_path.write_text(
        textwrap.dedent(
            """\
            sections:
            - id: adult_events
              name: ზრდასრულთა ღონისძიებები
              type: adult_events
              status: active
              hashtags: [ღონისძიება]
              auto_dm_template_id: adult_events_comment_dm
              description_short: სექციის დონის ღონისძიება
              price_text: '200'
              location: ბორის პაიჭაძის სტადიონი
            """,
        ),
        encoding="utf-8",
    )
    events = admin_config_service.get_adult_events()
    assert len(events) == 1
    assert events[0]["title"] == "სექციის დონის ღონისძიება"


# ---------------------------------------------------------------------------
# 7. facebook_post_id round-trip
# ---------------------------------------------------------------------------


def test_facebook_post_id_persists_in_yaml(sections_path):
    admin_config_service.save_adult_event(
        {
            "id": "x", "title": "x", "status": "active",
            "facebook_post_id": "fb_post_xyz",
        },
    )
    persisted = _adult_events_in_yaml(sections_path)
    assert persisted[0]["facebook_post_id"] == "fb_post_xyz"


def test_facebook_post_id_preserved_after_edit(sections_path):
    admin_config_service.save_adult_event(
        {
            "id": "x", "title": "Maroon 5", "status": "active",
            "facebook_post_id": "fb_post_xyz",
        },
    )
    # Edit a different field — fb id must survive.
    admin_config_service.update_adult_event(
        "x", {"price_text": "300 ლარი"},
    )
    persisted = _adult_events_in_yaml(sections_path)
    assert persisted[0]["facebook_post_id"] == "fb_post_xyz"
    assert persisted[0]["price_text"] == "300 ლარი"


def test_missing_facebook_post_id_is_allowed(sections_path):
    errors = admin_config_service.save_adult_event(
        {"id": "x", "title": "x", "status": "active"},
    )
    assert errors == []
    persisted = _adult_events_in_yaml(sections_path)
    # Either absent or empty — never a crash.
    assert persisted[0].get("facebook_post_id", "") in ("", None)


def test_facebook_post_id_surfaces_through_normalize(sections_path):
    admin_config_service.save_adult_event(
        {
            "id": "x", "title": "x", "status": "active",
            "facebook_post_id": "fb_post_xyz",
        },
    )
    events = admin_config_service.get_adult_events()
    assert events[0]["facebook_post_id"] == "fb_post_xyz"


# ---------------------------------------------------------------------------
# 8. Unicode / Georgian round-trip
# ---------------------------------------------------------------------------


def test_unicode_georgian_round_trip(sections_path):
    admin_config_service.save_adult_event(
        {
            "id": "poetry",
            "title": "პოეზიის საღამო",
            "status": "active",
            "date_text": "28 ივნისი, 20:00",
            "location": "თბილისი",
            "description": "პოეზიის საღამო სტუმართან ერთად",
        },
    )
    events = admin_config_service.get_adult_events()
    assert events[0]["title"] == "პოეზიის საღამო"
    assert events[0]["location"] == "თბილისი"
    assert events[0]["description"] == "პოეზიის საღამო სტუმართან ერთად"


# ---------------------------------------------------------------------------
# 9. Tool executor — multi-event surface
# ---------------------------------------------------------------------------


def test_executor_returns_multiple_eligible_events(sections_path):
    _seed_age_matrix(sections_path)
    executor = _build_executor()
    result = executor.execute(TOOL_GET_ADULT_EVENTS, {"user_age": 20})
    assert result["success"] is True
    titles = {e["title"] for e in result["events"]}
    assert titles == {"T13", "T16", "T18", "T20"}


def test_executor_excludes_inactive_events(sections_path):
    admin_config_service.save_adult_event(
        {"id": "a", "title": "A", "status": "active", "min_age": 13},
    )
    admin_config_service.save_adult_event(
        {"id": "b", "title": "B", "status": "inactive", "min_age": 13},
    )
    executor = _build_executor()
    result = executor.execute(TOOL_GET_ADULT_EVENTS, {"user_age": 30})
    titles = {e["title"] for e in result["events"]}
    assert titles == {"A"}


def test_executor_excludes_age_ineligible_events(sections_path):
    _seed_age_matrix(sections_path)
    executor = _build_executor()
    result = executor.execute(TOOL_GET_ADULT_EVENTS, {"user_age": 14})
    titles = {e["title"] for e in result["events"]}
    assert titles == {"T13"}


def test_executor_surfaces_title_date_location_price(sections_path):
    # Clock-relative future date — the active-event filter hides past events, so
    # a hardcoded date-bomb („23 ივნისი" collided with the wall clock once the
    # day arrived). Unrelated to the Turn Intent Gateway (2026-06-23).
    from datetime import timedelta
    from app.agent.services.timestamps import now_tbilisi
    _KA_MONTHS = {
        1: "იანვარი", 2: "თებერვალი", 3: "მარტი", 4: "აპრილი", 5: "მაისი",
        6: "ივნისი", 7: "ივლისი", 8: "აგვისტო", 9: "სექტემბერი",
        10: "ოქტომბერი", 11: "ნოემბერი", 12: "დეკემბერი",
    }
    _future = now_tbilisi() + timedelta(days=30)
    future_date = f"{_future.day} {_KA_MONTHS[_future.month]}, 19:00"
    admin_config_service.save_adult_event(
        {
            "id": "maroon_5",
            "title": "Maroon 5 კონცერტი",
            "status": "active",
            "min_age": 13,
            "date_text": future_date,
            "location": "ბორის პაიჭაძის სტადიონი",
            "price_text": "200 ლარი",
        },
    )
    executor = _build_executor()
    result = executor.execute(TOOL_GET_ADULT_EVENTS, {"user_age": 20})
    e = result["events"][0]
    assert e["title"] == "Maroon 5 კონცერტი"
    assert e["date_text"] == future_date
    assert e["location"] == "ბორის პაიჭაძის სტადიონი"
    assert e["price_text"] == "200 ლარი"


def test_executor_event_details_by_title(sections_path, adult_events_june_2026_clock):
    admin_config_service.save_adult_event(
        {
            "id": "poetry",
            "title": "პოეზიის საღამო",
            "status": "active",
            "min_age": 16,
            "date_text": "28 ივნისი, 20:00",
            "location": "თბილისი",
            "price_text": "80 ლარი",
            "description": "ლექსების საღამო სტუმართან",
        },
    )
    executor = _build_executor()
    result = executor.execute(
        TOOL_GET_ADULT_EVENT_DETAILS,
        {"event_id_or_title": "პოეზიის საღამო"},
    )
    assert result["success"] is True
    assert result["event"]["id"] == "poetry"
    assert result["event"]["price_text"] == "80 ლარი"


def test_executor_event_details_partial_title_match(sections_path):
    admin_config_service.save_adult_event(
        {"id": "poetry", "title": "პოეზიის საღამო", "status": "active"},
    )
    executor = _build_executor()
    result = executor.execute(
        TOOL_GET_ADULT_EVENT_DETAILS,
        {"event_id_or_title": "პოეზიის"},
    )
    assert result["success"] is True
    assert result["event"]["id"] == "poetry"


def test_executor_reservation_link_present(sections_path):
    admin_config_service.save_adult_event(
        {
            "id": "maroon_5",
            "title": "Maroon 5",
            "status": "active",
            "min_age": 13,
            "reservation_url": "https://example.com/maroon5",
        },
    )
    executor = _build_executor()
    result = executor.execute(
        TOOL_PROVIDE_ADULT_RESERVATION_LINK, {"event_id": "maroon_5"},
    )
    assert result["success"] is True
    assert result["reservation_url"] == "https://example.com/maroon5"


def test_executor_reservation_link_missing_returns_link_missing(sections_path):
    admin_config_service.save_adult_event(
        {"id": "no_url", "title": "No URL", "status": "active", "min_age": 13},
    )
    executor = _build_executor()
    result = executor.execute(
        TOOL_PROVIDE_ADULT_RESERVATION_LINK, {"event_id": "no_url"},
    )
    assert result["success"] is False
    assert result["reason"] == "link_missing"


def test_executor_returns_no_active_events_when_all_inactive(sections_path):
    admin_config_service.save_adult_event(
        {"id": "a", "title": "A", "status": "inactive", "min_age": 13},
    )
    executor = _build_executor()
    result = executor.execute(TOOL_GET_ADULT_EVENTS, {"user_age": 30})
    assert result["success"] is True
    assert result["events"] == []
    assert result.get("reason") == "no_active_events"


def test_executor_compact_includes_description(sections_path):
    admin_config_service.save_adult_event(
        {
            "id": "x", "title": "X", "status": "active", "min_age": 13,
            "description": "მოკლე აღწერა",
        },
    )
    executor = _build_executor()
    result = executor.execute(TOOL_GET_ADULT_EVENTS, {"user_age": 30})
    assert result["events"][0]["description"] == "მოკლე აღწერა"


# ---------------------------------------------------------------------------
# 10. Admin Panel HTTP routes — list / add / edit / deactivate / activate
# ---------------------------------------------------------------------------


def test_admin_list_renders_with_multiple_events(admin_enabled, sections_path):
    admin_config_service.save_adult_event(
        {"id": "maroon_5", "title": "Maroon 5", "status": "active", "min_age": 13},
    )
    admin_config_service.save_adult_event(
        {"id": "poetry", "title": "პოეზიის საღამო", "status": "active", "min_age": 16},
    )
    client = TestClient(app)
    resp = client.get(
        "/admin/programs/adult_events/events", headers=_auth(),
    )
    assert resp.status_code == 200
    assert "Maroon 5" in resp.text
    assert "პოეზიის საღამო" in resp.text


def test_admin_list_renders_when_empty(admin_enabled, sections_path):
    client = TestClient(app)
    resp = client.get(
        "/admin/programs/adult_events/events", headers=_auth(),
    )
    assert resp.status_code == 200


def test_admin_new_form_renders(admin_enabled, sections_path):
    client = TestClient(app)
    resp = client.get(
        "/admin/programs/adult_events/events/new", headers=_auth(),
    )
    assert resp.status_code == 200
    assert "facebook_post_id" in resp.text


def test_admin_post_creates_event_with_all_fields(admin_enabled, sections_path):
    client = TestClient(app)
    resp = client.post(
        "/admin/programs/adult_events/events/new",
        headers=_auth(),
        data={
            "id": "maroon_5",
            "title": "Maroon 5 კონცერტი",
            "status": "active",
            "min_age": "13",
            "date_text": "23 ივნისი, 19:00",
            "location": "ბორის პაიჭაძის სტადიონი",
            "price_text": "200 ლარი",
            "price_gel": "200",
            "description": "კულტურული საღამო",
            "reservation_url": "https://example.com/m5",
            "facebook_post_id": "fb_post_777",
            "tags": "კონცერტი, საღამო",
        },
        follow_redirects=False,
    )
    assert resp.status_code in (200, 303), resp.text[:200]
    persisted = _adult_events_in_yaml(sections_path)
    assert len(persisted) == 1
    assert persisted[0]["facebook_post_id"] == "fb_post_777"
    assert "კონცერტი" in persisted[0]["tags"]


def test_admin_edit_form_renders(admin_enabled, sections_path):
    admin_config_service.save_adult_event(
        {"id": "x", "title": "Maroon 5", "status": "active", "min_age": 13},
    )
    client = TestClient(app)
    resp = client.get(
        "/admin/programs/adult_events/events/x", headers=_auth(),
    )
    assert resp.status_code == 200
    assert "Maroon 5" in resp.text


def test_admin_edit_form_unknown_id_returns_404(admin_enabled, sections_path):
    client = TestClient(app)
    resp = client.get(
        "/admin/programs/adult_events/events/does_not_exist", headers=_auth(),
    )
    assert resp.status_code == 404


def test_admin_post_edit_updates_event(admin_enabled, sections_path):
    admin_config_service.save_adult_event(
        {"id": "x", "title": "Maroon 5", "status": "active", "min_age": 13,
         "price_text": "200 ლარი"},
    )
    client = TestClient(app)
    resp = client.post(
        "/admin/programs/adult_events/events/x",
        headers=_auth(),
        data={
            "title": "Maroon 5", "status": "active", "min_age": "13",
            "date_text": "", "location": "",
            "price_text": "300 ლარი", "price_gel": "",
            "description": "", "reservation_url": "",
            "facebook_post_id": "", "tags": "",
        },
        follow_redirects=False,
    )
    assert resp.status_code in (200, 303)
    persisted = _adult_events_in_yaml(sections_path)
    assert persisted[0]["price_text"] == "300 ლარი"


def test_admin_deactivate_route_toggles_status(admin_enabled, sections_path):
    admin_config_service.save_adult_event(
        {"id": "x", "title": "x", "status": "active", "min_age": 13},
    )
    client = TestClient(app)
    resp = client.post(
        "/admin/programs/adult_events/events/x/deactivate",
        headers=_auth(),
        follow_redirects=False,
    )
    assert resp.status_code in (200, 303)
    assert _adult_events_in_yaml(sections_path)[0]["status"] == "inactive"


def test_admin_activate_route_toggles_status(admin_enabled, sections_path):
    admin_config_service.save_adult_event(
        {"id": "x", "title": "x", "status": "inactive", "min_age": 13},
    )
    client = TestClient(app)
    resp = client.post(
        "/admin/programs/adult_events/events/x/activate",
        headers=_auth(),
        follow_redirects=False,
    )
    assert resp.status_code in (200, 303)
    assert _adult_events_in_yaml(sections_path)[0]["status"] == "active"


def test_admin_list_route_shows_inactive_events(admin_enabled, sections_path):
    """Operator must be able to see deactivated events in the Admin
    Panel — otherwise re-activation is impossible from the UI."""
    admin_config_service.save_adult_event(
        {"id": "hidden", "title": "ფარული საღამო",
         "status": "inactive", "min_age": 13},
    )
    client = TestClient(app)
    resp = client.get(
        "/admin/programs/adult_events/events", headers=_auth(),
    )
    assert resp.status_code == 200
    assert "ფარული საღამო" in resp.text


# ---------------------------------------------------------------------------
# 11. Bulk add (operator can manage ≥10 events without truncation)
# ---------------------------------------------------------------------------


def test_can_persist_ten_events(sections_path):
    for i in range(10):
        admin_config_service.save_adult_event(
            {
                "id": f"evt_{i}",
                "title": f"ღონისძიება {i}",
                "status": "active" if i % 2 == 0 else "inactive",
                "min_age": 13 + (i % 5),
            },
        )
    persisted = _adult_events_in_yaml(sections_path)
    assert len(persisted) == 10
    active = admin_config_service.get_active_adult_events()
    assert len(active) == 5  # even-indexed ones


# ---------------------------------------------------------------------------
# 12. Public normalize wrapper
# ---------------------------------------------------------------------------


def test_normalize_adult_event_public_wrapper(sections_path):
    normalised = admin_config_service.normalize_adult_event(
        {"id": "x", "title": "X", "status": "active", "min_age": 16},
    )
    assert normalised["id"] == "x"
    assert normalised["min_age"] == 16
    assert normalised["active"] is True


def test_normalize_adult_event_idx_fallback(sections_path):
    normalised = admin_config_service.normalize_adult_event(
        {"title": "X", "status": "active"}, idx=5,
    )
    assert normalised["id"] == "event_5"


# ---------------------------------------------------------------------------
# 13. UI visibility — operator can reach the multi-event manager
# ---------------------------------------------------------------------------


def test_programs_page_links_to_events_manager(admin_enabled, sections_path):
    """The Programs list page MUST surface a visible "ღონისძიებების
    მართვა" button next to the adult_events row — otherwise the
    operator can never find the new editor."""
    client = TestClient(app)
    resp = client.get("/admin/programs", headers=_auth())
    assert resp.status_code == 200
    assert "ღონისძიებების მართვა" in resp.text
    assert "/admin/programs/adult_events/events" in resp.text


def test_adult_events_section_form_links_to_events_manager(
    admin_enabled, sections_path,
):
    """The legacy section-metadata form for adult_events MUST link to
    the multi-event manager — otherwise an operator who clicks the
    standard "Edit" button never sees the events roster."""
    client = TestClient(app)
    resp = client.get(
        "/admin/programs/adult_events", headers=_auth(),
    )
    assert resp.status_code == 200
    assert "ღონისძიებების მართვა" in resp.text
    assert "/admin/programs/adult_events/events" in resp.text


def test_other_section_forms_do_not_show_events_manager_banner(
    admin_enabled, sections_path,
):
    """The events-manager banner is scoped to adult_events only. Camp /
    sunday-school section forms must stay unchanged."""
    client = TestClient(app)
    resp = client.get(
        "/admin/programs/summer_camp", headers=_auth(),
    )
    assert resp.status_code == 200
    assert "ღონისძიებების მართვა" not in resp.text


def test_events_list_page_returns_200(admin_enabled, sections_path):
    """Spec contract: GET /admin/programs/adult_events/events → 200."""
    client = TestClient(app)
    resp = client.get(
        "/admin/programs/adult_events/events", headers=_auth(),
    )
    assert resp.status_code == 200


def test_empty_events_page_shows_spec_wording(admin_enabled, sections_path):
    """When events[] is empty, the page must show
    'ჯერ ღონისძიებები არ არის დამატებული.' + an add button."""
    client = TestClient(app)
    resp = client.get(
        "/admin/programs/adult_events/events", headers=_auth(),
    )
    assert resp.status_code == 200
    assert "ჯერ ღონისძიებები არ არის დამატებული." in resp.text
    assert "ახალი ღონისძიების დამატება" in resp.text


def test_add_event_form_reachable_from_browser(admin_enabled, sections_path):
    """Spec contract: GET /admin/programs/adult_events/events/new → 200."""
    client = TestClient(app)
    resp = client.get(
        "/admin/programs/adult_events/events/new", headers=_auth(),
    )
    assert resp.status_code == 200
    # The form must expose every spec-required field.
    for field_name in (
        "title", "status", "min_age", "date_text", "location",
        "price_text", "price_gel", "description", "reservation_url",
        "facebook_post_id", "tags",
    ):
        assert f'name="{field_name}"' in resp.text, (
            f"add form is missing the {field_name!r} input"
        )


def test_save_new_event_redirects_to_events_list(admin_enabled, sections_path):
    """POST /admin/programs/adult_events/events/new with a valid event
    must redirect (303) back to the events list."""
    client = TestClient(app)
    resp = client.post(
        "/admin/programs/adult_events/events/new",
        headers=_auth(),
        data={
            "id": "redirect_check",
            "title": "Redirect Check",
            "status": "active",
            "min_age": "13",
            "date_text": "", "location": "",
            "price_text": "", "price_gel": "",
            "description": "", "reservation_url": "",
            "facebook_post_id": "", "tags": "",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/admin/programs/adult_events/events"


def test_events_list_shows_saved_event_with_edit_and_deactivate(
    admin_enabled, sections_path,
):
    """After saving an active event the list must show its title, an
    edit link, and a deactivate button (because the event is active)."""
    admin_config_service.save_adult_event(
        {
            "id": "maroon_5", "title": "Maroon 5 კონცერტი",
            "status": "active", "min_age": 13,
        },
    )
    client = TestClient(app)
    resp = client.get(
        "/admin/programs/adult_events/events", headers=_auth(),
    )
    assert resp.status_code == 200
    assert "Maroon 5 კონცერტი" in resp.text
    assert "/admin/programs/adult_events/events/maroon_5" in resp.text
    assert "რედაქტირება" in resp.text
    assert "/admin/programs/adult_events/events/maroon_5/deactivate" in resp.text


def test_events_list_shows_activate_button_for_inactive_event(
    admin_enabled, sections_path,
):
    """An inactive event row must show an activate button — otherwise
    re-enabling is impossible from the UI."""
    admin_config_service.save_adult_event(
        {
            "id": "sleeping", "title": "Sleeping Event",
            "status": "inactive", "min_age": 13,
        },
    )
    client = TestClient(app)
    resp = client.get(
        "/admin/programs/adult_events/events", headers=_auth(),
    )
    assert resp.status_code == 200
    assert "/admin/programs/adult_events/events/sleeping/activate" in resp.text
    # And the deactivate button MUST NOT appear for an already-inactive event.
    assert "/admin/programs/adult_events/events/sleeping/deactivate" not in resp.text
