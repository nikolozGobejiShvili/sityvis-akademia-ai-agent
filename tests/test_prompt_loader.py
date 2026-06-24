"""Unit tests for app.agent.llm.prompt_loader.

Covers:
  * each migrated prompt loads successfully
  * UTF-8 Georgian round-trip (loader == raw .md bytes decoded)
  * placeholders survive loading unchanged
  * missing prompt raises a clear PromptNotFound
  * caching (same call returns same string object on second invocation)
  * loader accepts "name" and "name.md" interchangeably
  * existing data.prompts imports still resolve to the loader values
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agent.llm import prompt_loader as pl


ALL_PROMPTS = [
    "system_base",
    "system_parent",
    "system_adult",
    "detect_segment",
    "detect_start_intent",
    "detect_comment_intent",
    "summary",
    "parent_present_value",
]


@pytest.fixture(autouse=True)
def _clear_cache():
    pl.reset_cache()
    yield
    pl.reset_cache()


def _raw(name: str) -> str:
    """Read the .md file directly (bypassing the loader)."""
    with (pl.PROMPTS_DIR / f"{name}.md").open(
        "r", encoding="utf-8", newline=""
    ) as fh:
        return fh.read()


# -- coverage ---------------------------------------------------------------


@pytest.mark.parametrize("name", ALL_PROMPTS)
def test_each_prompt_loads_successfully(name: str) -> None:
    value = pl.load_prompt(name)
    assert isinstance(value, str)
    assert len(value) > 0


@pytest.mark.parametrize("name", ALL_PROMPTS)
def test_loader_matches_raw_file_byte_for_byte(name: str) -> None:
    assert pl.load_prompt(name) == _raw(name)


# -- UTF-8 Georgian ---------------------------------------------------------


def test_georgian_roundtrip_in_system_parent() -> None:
    value = pl.load_prompt("system_parent")
    assert "ემპათიური კონსულტანტი" in value
    assert "ამბასადორი კაჭრეთი" in value
    assert "—" in value
    assert "🌿" not in value  # leaf emoji belongs to user-facing welcome, not the system prompt


def test_georgian_roundtrip_in_system_base() -> None:
    value = pl.load_prompt("system_base")
    assert "ფსიქოლოგიური სიღრმის" in value
    assert "✅" in value
    assert "❌" in value
    assert "{company_name}" in value


# -- placeholders preserved -------------------------------------------------


@pytest.mark.parametrize(
    "name,placeholders",
    [
        ("system_base", ["{company_name}"]),
        ("summary", ["{conversation_history}"]),
        ("detect_comment_intent", ["{comment_text}"]),
        (
            "parent_present_value",
            ["{child_age}", "{challenge}", "{deeper_concern}", "{desired_change}"],
        ),
    ],
)
def test_placeholders_survive_loading(
    name: str, placeholders: list[str]
) -> None:
    value = pl.load_prompt(name)
    for ph in placeholders:
        assert ph in value, (
            f"placeholder {ph!r} missing from {name}.md; "
            f"value head: {value[:80]!r}"
        )


def test_format_call_renders_company_name_placeholder() -> None:
    raw = pl.load_prompt("system_base")
    rendered = raw.format(company_name="ცისარტყელა")
    assert "ცისარტყელა" in rendered
    assert "{company_name}" not in rendered


# -- missing-prompt error ---------------------------------------------------


def test_missing_prompt_raises_prompt_not_found_with_path() -> None:
    with pytest.raises(pl.PromptNotFound) as excinfo:
        pl.load_prompt("does_not_exist")
    msg = str(excinfo.value)
    assert "does_not_exist" in msg
    assert ".md" in msg


def test_prompt_not_found_is_file_not_found_error() -> None:
    # FileNotFoundError subclass — callers can `except FileNotFoundError`.
    with pytest.raises(FileNotFoundError):
        pl.load_prompt("definitely_missing")


# -- caching ----------------------------------------------------------------


def test_repeated_lookups_return_cached_object() -> None:
    a = pl.load_prompt("system_base")
    b = pl.load_prompt("system_base")
    assert a is b


def test_reset_cache_forces_reload(tmp_path: Path, monkeypatch) -> None:
    pl.reset_cache()
    monkeypatch.setattr(pl, "PROMPTS_DIR", tmp_path)
    with pytest.raises(pl.PromptNotFound):
        pl.load_prompt("system_base")


# -- suffix handling --------------------------------------------------------


def test_loader_accepts_explicit_md_suffix() -> None:
    assert pl.load_prompt("summary") == pl.load_prompt("summary.md")


# -- backward-compat with data.prompts -------------------------------------


@pytest.mark.parametrize(
    "constant_name,prompt_name",
    [
        ("SYSTEM_PROMPT_BASE", "system_base"),
        ("SYSTEM_PROMPT_PARENT", "system_parent"),
        ("SYSTEM_PROMPT_ADULT", "system_adult"),
        ("DETECT_SEGMENT", "detect_segment"),
        ("START_INTENT_DETECT", "detect_start_intent"),
        ("COMMENT_INTENT_PROMPT", "detect_comment_intent"),
        ("SUMMARY_PROMPT", "summary"),
        ("PARENT_PRESENT_VALUE_CONTEXT", "parent_present_value"),
    ],
)
def test_data_prompts_aliases_resolve_to_loader_values(
    constant_name: str, prompt_name: str
) -> None:
    from data import prompts

    assert getattr(prompts, constant_name) == pl.load_prompt(prompt_name)


def test_openai_context_label_stays_python_literal() -> None:
    """Spec-required: short single-line label remains Python literal,
    not migrated to .md."""
    from data import prompts

    assert prompts.OPENAI_CONTEXT_LABEL == "კონტექსტი:"
    # Sanity: the literal does not have a corresponding .md file.
    assert not (pl.PROMPTS_DIR / "openai_context_label.md").exists()
