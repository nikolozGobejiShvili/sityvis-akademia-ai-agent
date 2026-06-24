"""Unit tests for app.agent.services.template_loader.

Covers:
  * loading a known template from each of the six groups
  * UTF-8 Georgian round-trip (loader == raw YAML)
  * placeholder preservation ({name}, {company_name}, etc. survive unchanged)
  * missing-key and missing-group errors are explicit and self-describing
  * caching (the same call returns the same object on the second invocation)
  * "group.key" dotted call style is equivalent to the two-arg form

The tests do NOT depend on `data.prompts` so they keep passing even if the
backward-compat aliases are eventually removed.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.agent.services import template_loader as tl


# -- fixtures ----------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_cache():
    tl.reset_cache()
    yield
    tl.reset_cache()


def _raw_value(group: str, key: str) -> str:
    """Read the YAML files directly (no loader) and return the raw string."""
    group_dir = tl.TEMPLATES_DIR / group
    for yaml_path in sorted(group_dir.glob("*.yaml")):
        with yaml_path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        if key in data:
            return data[key]
    raise AssertionError(f"key {group}/{key} not found in any YAML")


# -- group coverage ----------------------------------------------------------


@pytest.mark.parametrize(
    "group,key",
    [
        ("parent", "welcome"),
        ("adult", "welcome"),
        ("common", "unclear_routing"),
        ("comments", "reply_dm_sent"),
        ("notifications", "email_subject"),
        ("calendar", "summary"),
    ],
)
def test_loads_known_template_from_each_group(group: str, key: str) -> None:
    value = tl.get_template(group, key)
    assert isinstance(value, str)
    assert value == _raw_value(group, key)


# -- UTF-8 Georgian round-trip ----------------------------------------------


def test_utf8_georgian_roundtrip_preserves_em_dash_and_greeting() -> None:
    # Agent Wording Cleanup Patch (2026-06-03): production templates no
    # longer carry decorative emojis. The remaining UTF-8 round-trip
    # smoke is the em-dash + Georgian Mkhedruli greeting.
    value = tl.get_template("parent", "welcome")
    assert "🌿" not in value, "emoji must not appear in production template"
    assert "—" in value, "em-dash must survive UTF-8 decode"
    assert "გამარჯობა" in value, "Georgian greeting must round-trip"


def test_utf8_georgian_roundtrip_matches_yaml_source_byte_for_byte() -> None:
    # PARENT_WELCOME is multi-line with newlines; verify them exactly.
    value = tl.get_template("parent", "welcome")
    raw = _raw_value("parent", "welcome")
    assert value == raw
    assert value.count("\n") == raw.count("\n")


# -- placeholders preserved -------------------------------------------------


@pytest.mark.parametrize(
    "group,key,placeholders",
    [
        ("notifications", "email_subject", ["{segment}", "{platform}"]),
        # COMMENT FLOW PATCH 3 — the public reply text is now uniform
        # for every commenter and no longer carries the {name}
        # placeholder. (`reply_to_comment` still accepts user_name in
        # its signature but ignores it.) Keep an entry here that
        # exercises a template WITH a meaningful placeholder so the
        # generic survives-loading guard still has a representative
        # comment-group case.
        ("comments", "reply_fallback", ["{name}", "{fallback_link}"]),
        ("parent", "booking_confirmed", ["{date}", "{time}"]),
        ("parent", "offer_consultation", ["{calendar_slots}"]),
        ("calendar", "summary", ["{lead_name}", "{lead_platform}"]),
        ("calendar", "description",
            ["{child_age}", "{challenge}", "{deeper_concern}", "{desired_change}"]),
    ],
)
def test_placeholders_survive_loading(
    group: str, key: str, placeholders: list[str]
) -> None:
    value = tl.get_template(group, key)
    for ph in placeholders:
        assert ph in value, (
            f"placeholder {ph!r} missing from {group}/{key}; "
            f"value repr: {value!r}"
        )


def test_format_call_renders_placeholders() -> None:
    # Caller renders. Loader returns the raw template.
    raw = tl.get_template("notifications", "email_subject")
    rendered = raw.format(segment="PARENT", platform="instagram")
    assert rendered == "ახალი ლიდი — PARENT — instagram"


# -- error paths -------------------------------------------------------------


def test_missing_key_raises_template_not_found_with_available_keys() -> None:
    with pytest.raises(tl.TemplateNotFound) as excinfo:
        tl.get_template("parent", "does_not_exist")
    msg = str(excinfo.value)
    assert "parent" in msg
    assert "does_not_exist" in msg
    # The error should suggest what *is* available so the developer can fix it.
    assert "welcome" in msg
    assert "Available keys" in msg


def test_missing_group_raises_template_not_found() -> None:
    with pytest.raises(tl.TemplateNotFound) as excinfo:
        tl.get_template("nonexistent_group", "anything")
    assert "nonexistent_group" in str(excinfo.value)


def test_dotted_path_requires_dot_or_explicit_key() -> None:
    with pytest.raises(tl.TemplateNotFound) as excinfo:
        tl.get_template("parent")  # no key, no dot
    assert "group.key" in str(excinfo.value)


def test_dotted_path_equivalent_to_two_arg_form() -> None:
    assert tl.get_template("parent.welcome") == tl.get_template("parent", "welcome")


# -- caching -----------------------------------------------------------------


def test_repeated_lookups_use_cache() -> None:
    a = tl.get_template("parent", "welcome")
    b = tl.get_template("parent", "welcome")
    # Both Python strings should be the exact same object because the cache
    # holds a single dict-of-strings per group.
    assert a is b


def test_reset_cache_forces_reload(tmp_path: Path, monkeypatch) -> None:
    # Point the loader at an empty temp directory, observe the group lookup
    # fails (proving the on-disk read happened again, not the cached value).
    tl.reset_cache()
    monkeypatch.setattr(tl, "TEMPLATES_DIR", tmp_path)
    with pytest.raises(tl.TemplateNotFound):
        tl.get_template("parent", "welcome")


# -- backward-compat check ---------------------------------------------------


def test_data_prompts_aliases_resolve_to_loader_values() -> None:
    """data.prompts still works after Phase 2 swap."""
    from data import prompts

    assert prompts.PARENT_WELCOME == tl.get_template("parent", "welcome")
    assert prompts.MANAGER_EMAIL_SUBJECT == tl.get_template(
        "notifications", "email_subject"
    )
    assert prompts.CALENDAR_OPTIONS_SEPARATOR == tl.get_template(
        "calendar", "options_separator"
    )
