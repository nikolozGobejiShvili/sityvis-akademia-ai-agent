"""ADULT LLM Engine — admin_config min_age + adult-event loader tests.

Covers the data layer feeding the engine:
  * adult_events list loads with min_age field
  * missing min_age defaults to 18
  * age filtering hides events the user is too young for
  * age filtering shows events the user is old enough for
  * inactive events are hidden
  * summer_camp / sunday_school configs still load unchanged
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from app.services import admin_config_service


@pytest.fixture
def admin_sections_with_adult_events(monkeypatch, tmp_path):
    sections_yaml = textwrap.dedent(
        """\
        sections:
        - id: summer_camp
          name: საზაფხულო ბანაკი
          type: camp
          status: active
          hashtags: [ბანაკი]
          age_min: 9
          age_max: 17
          location: ამბასადორი კაჭრეთი
          price_text: '2200'
          price_gel: 2200
          auto_dm_template_id: summer_camp_comment_dm
        - id: sunday_school
          name: საკვირაო სკოლა
          type: kids_program
          status: coming_soon
          hashtags: [სკოლა]
          auto_dm_template_id: sunday_school_comment_dm
        - id: adult_events
          name: ზრდასრულთა ღონისძიებები
          type: adult_events
          status: active
          hashtags: [ღონისძიება]
          auto_dm_template_id: adult_events_comment_dm
          events:
          - id: poetry_evening
            title: პოეზიის საღამო
            status: active
            min_age: 13
            date_text: ივლისი
            location: თბილისი
            theme: პოეზია
            reservation_url: https://example.com/poetry
            seats_available: 20
          - id: adult_book_club
            title: წიგნის კლუბი
            status: active
            min_age: 18
            date_text: აგვისტო
            location: თბილისი
          - id: legacy_no_min_age
            title: ლექცია ფილოსოფიაში
            status: active
            # min_age intentionally omitted — should default to 18.
            date_text: სექტემბერი
          - id: archived_event
            title: ძველი საღამო
            status: hidden
            min_age: 18
        """,
    )
    sections_path = tmp_path / "sections.yaml"
    sections_path.write_text(sections_yaml, encoding="utf-8")
    monkeypatch.setattr(admin_config_service, "SECTIONS_PATH", sections_path)
    return sections_path


def test_adult_events_loads_with_min_age(admin_sections_with_adult_events):
    events = admin_config_service.get_adult_events()
    by_id = {e["id"]: e for e in events}

    assert "poetry_evening" in by_id
    assert by_id["poetry_evening"]["min_age"] == 13
    assert by_id["poetry_evening"]["reservation_url"] == "https://example.com/poetry"
    assert by_id["poetry_evening"]["seats_available"] == 20


def test_missing_min_age_defaults_to_13(admin_sections_with_adult_events):
    """ADULT Off-Topic Guard + Default Min-Age Fix (2026-06-02):
    the loader default for missing ``min_age`` is now 13 (was 18).
    """
    events = admin_config_service.get_adult_events()
    by_id = {e["id"]: e for e in events}

    assert by_id["legacy_no_min_age"]["min_age"] == 13, (
        "Loader must default min_age to 13 when the event omits the field."
    )


def test_age_filter_hides_event_user_too_young(admin_sections_with_adult_events):
    # User is 12. poetry_evening requires 13, book_club requires 18,
    # legacy_no_min_age defaults to 13 (under-12 still). None should pass.
    events = admin_config_service.get_active_adult_events(user_age=12)
    assert events == [], f"expected no events for age 12, got {events}"


def test_age_filter_shows_event_user_old_enough(admin_sections_with_adult_events):
    # User is 30. All three active events should be returned.
    events = admin_config_service.get_active_adult_events(user_age=30)
    ids = {e["id"] for e in events}
    assert ids == {"poetry_evening", "adult_book_club", "legacy_no_min_age"}


def test_age_filter_boundary_equal_to_min_age(admin_sections_with_adult_events):
    # User is exactly 13. poetry_evening requires 13 → shown.
    # adult_book_club requires 18 → hidden. legacy_no_min_age now
    # defaults to 13 → ALSO shown (was hidden under the old default=18).
    events = admin_config_service.get_active_adult_events(user_age=13)
    ids = {e["id"] for e in events}
    assert ids == {"poetry_evening", "legacy_no_min_age"}


def test_explicit_min_age_18_still_hides_age_13(admin_sections_with_adult_events):
    """Per-event ``min_age`` must STILL override the default. An
    event with explicit ``min_age: 18`` is hidden from a 13-year-old
    even after the default fell to 13.
    """
    events = admin_config_service.get_active_adult_events(user_age=13)
    ids = {e["id"] for e in events}
    assert "adult_book_club" not in ids, (
        "Per-event min_age must override the default."
    )


def test_inactive_events_hidden(admin_sections_with_adult_events):
    # No age filter — hidden status should still be excluded.
    events = admin_config_service.get_active_adult_events()
    ids = {e["id"] for e in events}
    assert "archived_event" not in ids


def test_summer_camp_config_unchanged(admin_sections_with_adult_events):
    section = admin_config_service.get_section("summer_camp")
    assert section is not None
    assert section.get("type") == "camp"
    assert section.get("age_min") == 9
    assert section.get("age_max") == 17


def test_sunday_school_config_unchanged(admin_sections_with_adult_events):
    section = admin_config_service.get_section("sunday_school")
    assert section is not None
    assert section.get("type") == "kids_program"


def test_find_adult_event_by_id(admin_sections_with_adult_events):
    event = admin_config_service.find_adult_event("poetry_evening")
    assert event is not None
    assert event["title"] == "პოეზიის საღამო"


def test_find_adult_event_by_title_partial_match(admin_sections_with_adult_events):
    event = admin_config_service.find_adult_event("პოეზიის")
    assert event is not None
    assert event["id"] == "poetry_evening"


def test_find_adult_event_unknown_returns_none(admin_sections_with_adult_events):
    assert admin_config_service.find_adult_event("რაც-არ-არსებობს") is None


def test_get_manager_phone_prefers_settings(monkeypatch):
    """When MANAGER_PHONE_NUMBER is set in settings, that wins over
    fallbacks (after manager_contacts.yaml miss)."""
    monkeypatch.setattr(
        admin_config_service,
        "load_manager_contacts_mirror",
        lambda: {},
    )
    import dataclasses

    from app.config import settings as global_settings
    swapped = dataclasses.replace(global_settings, MANAGER_PHONE_NUMBER="558 67 47 33")
    # Patch the lazy import path inside get_manager_phone.
    import app.config as config_module
    monkeypatch.setattr(config_module, "settings", swapped)

    phone = admin_config_service.get_manager_phone()
    assert phone == "558 67 47 33"


def test_get_manager_phone_never_hardcoded(monkeypatch):
    """When neither admin mirror nor settings provide a phone, must
    fall back to company.yaml (which the test repo has) — but the
    return value must NEVER include the literal hardcoded string
    'HARDCODED' or similar."""
    monkeypatch.setattr(
        admin_config_service, "load_manager_contacts_mirror", lambda: {},
    )
    import dataclasses

    from app.config import settings as global_settings
    swapped = dataclasses.replace(global_settings, MANAGER_PHONE_NUMBER="")
    import app.config as config_module
    monkeypatch.setattr(config_module, "settings", swapped)

    phone = admin_config_service.get_manager_phone()
    # Either company.yaml value or "" — never a hardcoded sentinel.
    assert isinstance(phone, str)
    assert "HARDCODED" not in phone
