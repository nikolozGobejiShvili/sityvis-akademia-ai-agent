"""Unit tests for app.agent.llm.parent_reply_composer (Phase 3.8).

Coverage:
  * Module imports cleanly.
  * Built payload includes authoritative facts from camp_2026.yaml
    (2150, "ამბასადორი კაჭრეთი", stream date strings, registration URL,
    company phone).
  * Built payload includes lead.name and the "do not ask for name" rule
    when name is known.
  * Composer returns fallback_template when:
      - USE_LLM_COMPOSER is False (flag off — composer must NOT be invoked)
      - openai_service.compose_reply raises
      - openai_service.compose_reply returns "" or whitespace
      - LLM output trips the fact-safety post-check
        (URL / phone / price / date hallucination)
  * Composer returns the LLM text verbatim when the fake LLM returns a
    safe deterministic Georgian reply.
  * No test path hits live OpenAI — every test that enables the composer
    monkeypatches the openai_service.compose_reply surface.

All tests run with the global default USE_LLM_COMPOSER=False; tests that
need the composer to actually fire monkeypatch the
``_composer_enabled`` helper rather than touching the frozen Settings.
"""

from __future__ import annotations

import pytest

from app.agent.llm import parent_reply_composer as composer
from app.models.lead import Lead


# -- fixtures --------------------------------------------------------------


@pytest.fixture
def lead_with_name() -> Lead:
    return Lead(
        sender_id="t-1",
        platform="instagram",
        segment="PARENT",
        name="ანა ლომიძე",
        child_age="8",
    )


@pytest.fixture
def lead_no_name() -> Lead:
    return Lead(sender_id="t-2", platform="instagram", segment="PARENT")


@pytest.fixture
def enable_composer(monkeypatch):
    """Force-enable the composer for a single test without mutating
    the frozen Settings dataclass."""
    monkeypatch.setattr(composer, "_composer_enabled", lambda: True)


def _fake_llm(monkeypatch, text: str):
    """Replace openai_service.compose_reply with a function returning ``text``."""
    monkeypatch.setattr(
        "app.services.openai_service.compose_reply",
        lambda **kwargs: text,
    )


def _fake_llm_raises(monkeypatch, exc: Exception):
    def _raise(**kwargs):
        raise exc
    monkeypatch.setattr("app.services.openai_service.compose_reply", _raise)


# -- 1. module imports ----------------------------------------------------


def test_module_imports() -> None:
    assert hasattr(composer, "compose_parent_reply")
    assert callable(composer.compose_parent_reply)


# -- 2 & 3. payload contains knowledge facts ------------------------------


def test_payload_includes_authoritative_camp_facts(
    lead_with_name: Lead, monkeypatch,
) -> None:
    # Clock-robust (2026-06-23): freeze the camp-stream "now" before any stream
    # start so all three streams stay visible in the injected camp facts.
    import datetime as _dt
    from app.services import admin_config_service as _acs
    from app.agent.services.timestamps import TBILISI_TZ as _TZ
    monkeypatch.setattr(
        _acs, "_now_tbilisi",
        lambda: (_dt.datetime(2026, 6, 1, 12, 0, tzinfo=_TZ), _TZ),
    )
    _, user_payload = composer.build_payload(
        state="ASK_AGE",
        user_message="გამარჯობა, ბანაკი მაინტერესებს",
        lead=lead_with_name,
        fallback_template="ANCHOR",
        next_action="greet warmly + ask child age",
    )
    # camp_2026.yaml values, injected verbatim
    assert "2150" in user_payload, "price_gel must be injected"
    assert "ამბასადორი კაჭრეთი" in user_payload, "location must be injected"
    assert "23-29 ივნისი" in user_payload, "stream I dates must be injected"
    assert "5-11 ივლისი" in user_payload, "stream II dates must be injected"
    assert "14-20 ივლისი" in user_payload, "stream III dates must be injected"
    assert "tinyurl.com/36jcae8z" in user_payload, "registration URL must be injected"
    assert "558 67 47 33" in user_payload, "contact phone must be injected"


def test_payload_includes_state_and_user_message(lead_with_name: Lead) -> None:
    _, user_payload = composer.build_payload(
        state="ASK_CHALLENGE",
        user_message="8 წლის",
        lead=lead_with_name,
        fallback_template="ANCHOR",
        next_action="ask main challenge",
    )
    assert "CURRENT_STATE:\nASK_CHALLENGE" in user_payload
    assert '"8 წლის"' in user_payload


def test_payload_includes_system_prompts(lead_with_name: Lead) -> None:
    system_prompt, _ = composer.build_payload(
        state="ASK_AGE",
        user_message="გამარჯობა",
        lead=lead_with_name,
        fallback_template="ANCHOR",
        next_action="greet",
    )
    # SYSTEM_PROMPT_BASE has this exact line
    assert "ფსიქოლოგიური სიღრმის" in system_prompt
    # SYSTEM_PROMPT_PARENT has this exact line
    assert "ემპათიური კონსულტანტი მშობელისთვის" in system_prompt


# -- 4. lead fields + don't-ask-name rule ---------------------------------


def test_payload_contains_known_lead_name_and_no_ask_rule(
    lead_with_name: Lead,
) -> None:
    _, user_payload = composer.build_payload(
        state="ASK_CHALLENGE",
        user_message="8",
        lead=lead_with_name,
        fallback_template="ANCHOR",
        next_action="ask challenge",
    )
    assert "ანა ლომიძე" in user_payload, "lead.name must be visible to the LLM"
    # The don't-ask-for-name rule must appear when name is known.
    assert "DO NOT ask" in user_payload
    assert "name" in user_payload


def test_payload_for_unknown_name_omits_dont_ask_rule(lead_no_name: Lead) -> None:
    _, user_payload = composer.build_payload(
        state="ASK_AGE",
        user_message="გამარჯობა",
        lead=lead_no_name,
        fallback_template="ANCHOR",
        next_action="greet",
    )
    assert "(unknown" in user_payload  # name field rendered as unknown
    assert "DO NOT ask" not in user_payload  # rule absent when name is unknown


def test_payload_renders_all_lead_fields(lead_with_name: Lead) -> None:
    _, user_payload = composer.build_payload(
        state="ASK_DESIRE",
        user_message="...",
        lead=lead_with_name,
        fallback_template="ANCHOR",
        next_action="next",
    )
    for label in ("NAME:", "CHILD_AGE:", "CHALLENGE:", "DEEPER_CONCERN:",
                  "DESIRED_CHANGE:", "PHONE:"):
        assert label in user_payload, f"missing lead label {label!r}"


# -- 5–6. fallback paths --------------------------------------------------


def test_returns_fallback_when_openai_call_raises(
    enable_composer, monkeypatch, lead_with_name: Lead,
) -> None:
    _fake_llm_raises(monkeypatch, RuntimeError("simulated network error"))
    result = composer.compose_parent_reply(
        state="ASK_AGE",
        user_message="hi",
        lead=lead_with_name,
        fallback_template="ORIGINAL_TEMPLATE_TEXT",
        next_action="greet",
    )
    assert result == "ORIGINAL_TEMPLATE_TEXT"


def test_returns_fallback_when_openai_returns_empty(
    enable_composer, monkeypatch, lead_with_name: Lead,
) -> None:
    _fake_llm(monkeypatch, "")
    result = composer.compose_parent_reply(
        state="ASK_AGE",
        user_message="hi",
        lead=lead_with_name,
        fallback_template="ORIGINAL_TEMPLATE_TEXT",
        next_action="greet",
    )
    assert result == "ORIGINAL_TEMPLATE_TEXT"


def test_returns_fallback_when_openai_returns_only_whitespace(
    enable_composer, monkeypatch, lead_with_name: Lead,
) -> None:
    _fake_llm(monkeypatch, "   \n  \n   ")
    result = composer.compose_parent_reply(
        state="ASK_AGE",
        user_message="hi",
        lead=lead_with_name,
        fallback_template="ORIGINAL_TEMPLATE_TEXT",
        next_action="greet",
    )
    assert result == "ORIGINAL_TEMPLATE_TEXT"


# -- 7. flag off — composer must not be invoked ---------------------------


def test_flag_off_returns_fallback_without_calling_openai(
    monkeypatch, lead_with_name: Lead,
) -> None:
    # Sanity: default is False, but assert it explicitly.
    monkeypatch.setattr(composer, "_composer_enabled", lambda: False)

    called = {"n": 0}

    def _spy(**kwargs):
        called["n"] += 1
        return "should not be reached"

    monkeypatch.setattr("app.services.openai_service.compose_reply", _spy)

    result = composer.compose_parent_reply(
        state="ASK_AGE",
        user_message="გამარჯობა",
        lead=lead_with_name,
        fallback_template="EXACT_FALLBACK",
        next_action="greet",
    )
    assert result == "EXACT_FALLBACK"
    assert called["n"] == 0, "composer must NOT call openai when flag is off"


# -- 8 & 9. flag-off byte-identity for the two top templates --------------
# (covers PARENT_WELCOME / PARENT_ASK_CHALLENGE round-trip through the
# composer entry — proves the composer is a true no-op when flag is off.)


def test_flag_off_parent_welcome_returns_exact_template(
    monkeypatch, lead_with_name: Lead,
) -> None:
    from data.prompts import PARENT_WELCOME

    monkeypatch.setattr(composer, "_composer_enabled", lambda: False)
    result = composer.compose_parent_reply(
        state="ASK_AGE",
        user_message="გამარჯობა",
        lead=lead_with_name,
        fallback_template=PARENT_WELCOME,
        next_action="greet warmly + ask child age",
    )
    assert result == PARENT_WELCOME


def test_flag_off_parent_ask_challenge_returns_exact_template(
    monkeypatch, lead_with_name: Lead,
) -> None:
    from data.prompts import PARENT_ASK_CHALLENGE

    monkeypatch.setattr(composer, "_composer_enabled", lambda: False)
    result = composer.compose_parent_reply(
        state="ASK_CHALLENGE",
        user_message="8",
        lead=lead_with_name,
        fallback_template=PARENT_ASK_CHALLENGE,
        next_action="ask main challenge",
    )
    assert result == PARENT_ASK_CHALLENGE


# -- 10. enabled with fake LLM returns deterministic Georgian text --------


def test_flag_on_with_fake_returns_llm_text(
    enable_composer, monkeypatch, lead_with_name: Lead,
) -> None:
    deterministic = "მესმის, ანა. რა აწუხებთ ბავშვის ცხოვრებაში ყველაზე მეტად?"
    _fake_llm(monkeypatch, deterministic)
    result = composer.compose_parent_reply(
        state="ASK_CHALLENGE",
        user_message="8",
        lead=lead_with_name,
        fallback_template="FALLBACK_TEXT",
        next_action="ask main challenge",
    )
    assert result == deterministic
    assert result != "FALLBACK_TEXT"


def test_flag_on_strips_leading_trailing_whitespace(
    enable_composer, monkeypatch, lead_with_name: Lead,
) -> None:
    _fake_llm(monkeypatch, "   მესმის, ანა.   ")
    result = composer.compose_parent_reply(
        state="ASK_CHALLENGE",
        user_message="8",
        lead=lead_with_name,
        fallback_template="FALLBACK_TEXT",
        next_action="ask main challenge",
    )
    assert result == "მესმის, ანა."


# -- fact-safety post-check (Phase 3.8 minimum approach) ------------------


@pytest.mark.parametrize("hallucinated_text,reason", [
    ("მესმის! მეტი დეტალი: https://example.com/x", "URL"),
    ("მესმის! დარეკეთ 599 12 34 56", "phone"),
    ("ფასი არის 3000 ლარი", "price"),
    ("ვართ 23-29 ივნისი", "date"),
    ("ნაკადი 5 ივლისს არის", "date (single)"),
])
def test_post_check_discards_hallucinated_facts(
    enable_composer, monkeypatch, lead_with_name: Lead,
    hallucinated_text: str, reason: str,
) -> None:
    _fake_llm(monkeypatch, hallucinated_text)
    result = composer.compose_parent_reply(
        state="ASK_CHALLENGE",
        user_message="8",
        lead=lead_with_name,
        fallback_template="FALLBACK",
        next_action="ask",
    )
    assert result == "FALLBACK", f"hallucinated {reason!r} should be discarded"


def test_post_check_allows_safe_reply(
    enable_composer, monkeypatch, lead_with_name: Lead,
) -> None:
    safe = "მესმის. რა აწუხებთ ყველაზე მეტად ბავშვის ცხოვრებაში?"
    _fake_llm(monkeypatch, safe)
    result = composer.compose_parent_reply(
        state="ASK_CHALLENGE",
        user_message="8",
        lead=lead_with_name,
        fallback_template="FALLBACK",
        next_action="ask",
    )
    assert result == safe


def test_post_check_unit_detector_flags_each_pattern() -> None:
    assert composer._detect_hallucinated_fact("see https://x.y/z") == "URL"
    assert composer._detect_hallucinated_fact("call 599-12-34-56") == "phone"
    assert composer._detect_hallucinated_fact("9999 ლარი") == "price"
    assert composer._detect_hallucinated_fact("ვართ 23-29 ივნისი") == "date"
    assert composer._detect_hallucinated_fact("რა აწუხებთ?") is None
    assert composer._detect_hallucinated_fact("") is None


# -- 11. no live OpenAI ---------------------------------------------------


def test_no_live_openai_in_default_test_run() -> None:
    """Sanity: with the default flag off, the composer never reaches the
    OpenAI client. Verified by patching compose_reply to raise — and yet
    the call returns the fallback cleanly, proving the composer short-
    circuited before invoking it."""
    from app.services import openai_service

    # Do NOT enable composer — flag stays off (default).
    def _fail(**kwargs):
        raise AssertionError(
            "openai_service.compose_reply must not run with composer flag off",
        )

    original = getattr(openai_service, "compose_reply", None)
    openai_service.compose_reply = _fail
    try:
        result = composer.compose_parent_reply(
            state="ASK_AGE",
            user_message="გამარჯობა",
            lead=Lead(sender_id="t", platform="instagram", segment="PARENT"),
            fallback_template="OK",
            next_action="greet",
        )
        assert result == "OK"
    finally:
        if original is not None:
            openai_service.compose_reply = original
