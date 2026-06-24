"""ADULT LLM Engine — engine + routing + sanitizer tests.

Covers:
  * USE_ADULT_LLM_ENGINE=true → engine called for ADULT segment
  * USE_ADULT_LLM_ENGINE=false → legacy adult_flow state machine runs
  * USE_PARENT_LLM_ENGINE unaffected by the adult flag
  * adult engine uses the adult prompt, not the parent prompt
  * adult engine respects MAX_TOOL_ITERATIONS
  * unknown tool returns safe error (delegated to executor)
  * sanitizer strips "კეთილი იყოს თქვენი ვიზიტი" greeting
  * sanitizer fixes "აკადემიაის" → "აკადემიის"
  * sanitizer strips "სიამოვნებით გაგაცნობთ ჩვენს კულტურულ საღამოებს"
  * sanitizer strips "ბილეთი შეიძინეთ" and "სალარო"
  * sanitizer is idempotent
  * adult-to-parent deterministic switch on "ბანაკის შესახებ მითხარი"
  * adult engine exception → empty string (caller falls back to legacy)
"""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace
from typing import Any

import pytest

import app.config as config_module
from app.agent.llm import adult_llm_engine
from app.flows import adult_flow
from app.models.conversation import Conversation
from app.models.lead import Lead


# -- fixtures -------------------------------------------------------------


def _swap_adult_flag(monkeypatch, value: bool) -> None:
    swapped = dataclasses.replace(
        config_module.settings, USE_ADULT_LLM_ENGINE=value,
    )
    monkeypatch.setattr(adult_flow, "settings", swapped)


@pytest.fixture
def enable_adult_engine(monkeypatch):
    _swap_adult_flag(monkeypatch, True)


@pytest.fixture
def disable_adult_engine(monkeypatch):
    _swap_adult_flag(monkeypatch, False)


@pytest.fixture
def fresh_conversation():
    conv = Conversation(sender_id="sender_adult_eng", platform="instagram", segment="ADULT")
    conv.lead = Lead(sender_id="sender_adult_eng", platform="instagram", segment="ADULT")
    return conv


def _mk_response(*, content: str = "", tool_calls: list[dict[str, Any]] | None = None) -> Any:
    tc_objs: list[Any] = []
    for tc in tool_calls or []:
        tc_objs.append(SimpleNamespace(
            id=tc["id"],
            function=SimpleNamespace(
                name=tc["name"],
                arguments=tc.get("arguments", "{}"),
            ),
        ))
    msg = SimpleNamespace(
        content=content or None,
        tool_calls=tc_objs or None,
    )
    choice = SimpleNamespace(message=msg)
    return SimpleNamespace(choices=[choice])


# =========================================================================
# 1 — adult engine called when USE_ADULT_LLM_ENGINE=true
# =========================================================================


def test_adult_engine_called_when_flag_true(enable_adult_engine, monkeypatch, fresh_conversation):
    called = {"n": 0}

    def _engine(**kwargs):
        called["n"] += 1
        return "ADULT_ENGINE_REPLY"

    monkeypatch.setattr(
        "app.agent.llm.adult_llm_engine.run_adult_llm_turn", _engine,
    )

    out = adult_flow.handle(fresh_conversation, "მაინტერესებს პოეზიის საღამო")
    assert out == "ADULT_ENGINE_REPLY"
    assert called["n"] == 1


# =========================================================================
# 2 — legacy state machine runs when flag is false
# =========================================================================


def test_adult_engine_off_uses_legacy_state_machine(
    disable_adult_engine, monkeypatch, fresh_conversation,
):
    called = {"n": 0}

    def _engine(**kwargs):
        called["n"] += 1
        return "SHOULD_NOT_BE_CALLED"

    monkeypatch.setattr(
        "app.agent.llm.adult_llm_engine.run_adult_llm_turn", _engine,
    )
    out = adult_flow.handle(fresh_conversation, "მაინტერესებს პოეზიის საღამო")

    assert called["n"] == 0, "engine must NOT be called when flag is False"
    assert isinstance(out, str) and out, "legacy state machine must produce a reply"


# =========================================================================
# 3 — Parent engine flag is unaffected by the adult flag
# =========================================================================


def test_parent_engine_flag_unaffected_by_adult_flag():
    swapped = dataclasses.replace(
        config_module.settings, USE_ADULT_LLM_ENGINE=True,
    )
    assert swapped.USE_PARENT_LLM_ENGINE == config_module.settings.USE_PARENT_LLM_ENGINE


# =========================================================================
# 4 — adult engine exception → empty string → legacy fallback
# =========================================================================


def test_adult_engine_exception_returns_empty(enable_adult_engine, monkeypatch, fresh_conversation):
    def _boom(**kwargs):
        raise RuntimeError("engine kaboom")

    monkeypatch.setattr(
        "app.agent.llm.adult_llm_engine.run_adult_llm_turn", _boom,
    )

    # The wrapper in adult_flow catches and falls through to legacy.
    out = adult_flow.handle(fresh_conversation, "მაინტერესებს პოეზიის საღამო")
    # Legacy state machine returns some non-empty response.
    assert isinstance(out, str) and out


# =========================================================================
# 5 — adult engine uses adult prompt, not the parent prompt
# =========================================================================


def test_adult_engine_uses_adult_prompt(monkeypatch):
    captured: dict[str, Any] = {}

    def _capture(*, messages, **kwargs):
        captured["messages"] = messages
        return _mk_response(content="ok")

    from app.services import openai_service
    monkeypatch.setattr(openai_service, "chat_with_tools", _capture)

    conv = Conversation(sender_id="s", platform="instagram", segment="ADULT")
    lead = Lead(sender_id="s", platform="instagram", segment="ADULT")
    conv.lead = lead

    adult_llm_engine.run_adult_llm_turn(
        user_message="გამარჯობა",
        conversation=conv,
        lead=lead,
        sender_id="s",
        platform="instagram",
    )

    system_msg = captured["messages"][0]["content"]
    # Must mention adult cultural events, not "საზაფხულო ბანაკი" as
    # the brand product.
    assert "ზრდასრულთა" in system_msg or "კულტურული" in system_msg
    # Parent-only token should NOT be in the system prompt.
    assert "9–17 წლის მოზარდებისთვისაა" not in system_msg


# =========================================================================
# 6 — adult engine respects MAX_TOOL_ITERATIONS
# =========================================================================


def test_adult_engine_caps_iterations(monkeypatch):
    calls = {"n": 0}

    def _loop(*, messages, tools, **kwargs):
        calls["n"] += 1
        # Always return a tool call so the loop never terminates.
        return _mk_response(tool_calls=[{
            "id": f"call_{calls['n']}",
            "name": "get_adult_events",
            "arguments": "{}",
        }])

    from app.services import openai_service
    monkeypatch.setattr(openai_service, "chat_with_tools", _loop)

    conv = Conversation(sender_id="s", platform="instagram", segment="ADULT")
    lead = Lead(sender_id="s", platform="instagram", segment="ADULT")
    conv.lead = lead

    out = adult_llm_engine.run_adult_llm_turn(
        user_message="გამარჯობა",
        conversation=conv,
        lead=lead,
        sender_id="s",
        platform="instagram",
    )

    assert out == ""
    assert calls["n"] == adult_llm_engine.MAX_TOOL_ITERATIONS


# =========================================================================
# 7-12 — Sanitizer: forbidden phrases
# =========================================================================


def test_sanitizer_strips_keti_li_ikos_greeting():
    bad = (
        "კეთილი იყოს თქვენი ვიზიტი სიტყვის აკადემიაის კულტურულ "
        "სივრცეში. ღონისძიება დაიწყება ივლისში."
    )
    out = adult_llm_engine.sanitise_adult_response(bad)
    assert "კეთილი იყოს თქვენი ვიზიტი" not in out
    assert "აკადემიაის" not in out


def test_sanitizer_fixes_akademiaais_genitive():
    bad = "სიტყვის აკადემიაის პროგრამა საინტერესოა."
    out = adult_llm_engine.sanitise_adult_response(bad)
    assert "აკადემიაის" not in out
    assert "სიტყვის აკადემიის" in out


def test_sanitizer_strips_siamovnebit_gagatsnobt_opener():
    bad = "სიამოვნებით გაგაცნობთ ჩვენს კულტურულ საღამოებს. დაიწყება მალე."
    out = adult_llm_engine.sanitise_adult_response(bad)
    assert "სიამოვნებით გაგაცნობთ ჩვენს კულტურულ საღამოებს" not in out


def test_sanitizer_strips_bileti_sheidzineti():
    bad = "ბილეთი შეიძინეთ ახლავე. ფასი 50 ლარი."
    out = adult_llm_engine.sanitise_adult_response(bad)
    assert "ბილეთი შეიძინეთ" not in out


def test_sanitizer_strips_salaro_style_words():
    bad = "სალაროდან ბილეთის ყიდვა შესაძლებელია."
    out = adult_llm_engine.sanitise_adult_response(bad)
    assert "სალარო" not in out


def test_sanitizer_strips_pressure_urgency_words():
    bad = "იჩქარეთ, ბოლო ადგილებია."
    out = adult_llm_engine.sanitise_adult_response(bad)
    assert "იჩქარეთ" not in out
    assert "ბოლო ადგილები" not in out


def test_sanitizer_idempotent():
    bad = "სიტყვის აკადემიაის პროგრამა."
    once = adult_llm_engine.sanitise_adult_response(bad)
    twice = adult_llm_engine.sanitise_adult_response(once)
    assert once == twice


def test_sanitizer_passes_clean_text_unchanged():
    clean = "სიტყვის აკადემიის პოეზიის საღამო ივლისში გაიმართება."
    out = adult_llm_engine.sanitise_adult_response(clean)
    assert out == clean


# =========================================================================
# 13-16 — Deterministic adult-to-parent switch
# =========================================================================


def test_switch_to_parent_on_banakis_shesakheb():
    conv = Conversation(sender_id="s", platform="instagram", segment="ADULT")
    lead = Lead(sender_id="s", platform="instagram", segment="ADULT")
    conv.lead = lead

    out = adult_llm_engine.run_adult_llm_turn(
        user_message="ბანაკის შესახებ მითხარი",
        conversation=conv,
        lead=lead,
        sender_id="s",
        platform="instagram",
    )

    assert conv.segment == "PARENT"
    assert "ბანაკის შესახებ დაგეხმარებით" in out


def test_switch_to_parent_on_child_age_in_camp_range(monkeypatch):
    """Live QA Patch (2026-06-05) — Bug 2 tightening: bare „12 წლის
    ბავშვისთვის" without an explicit camp keyword stays ADULT now.
    The LLM/relative-capture asks for the child's age and offers
    adult-event matches. Hard camp keyword still switches — see the
    immediately-prior test."""
    conv = Conversation(sender_id="s", platform="instagram", segment="ADULT")
    lead = Lead(sender_id="s", platform="instagram", segment="ADULT")
    conv.lead = lead

    # The deterministic parent-switch is OFF for this input; the LLM
    # path runs. Mock chat_with_tools so no real OpenAI call is made.
    from app.services import openai_service

    def _mock(*, messages, **kwargs):
        return _mk_response(content="გასაგებია.")

    monkeypatch.setattr(openai_service, "chat_with_tools", _mock)

    out = adult_llm_engine.run_adult_llm_turn(
        user_message="12 წლის ბავშვისთვის მინდა",
        conversation=conv,
        lead=lead,
        sender_id="s",
        platform="instagram",
    )

    assert conv.segment == "ADULT"
    assert isinstance(out, str) and out


def test_no_switch_for_pure_adult_inquiry():
    """A regular adult-events inquiry must NOT trigger the deterministic
    parent switch."""
    conv = Conversation(sender_id="s", platform="instagram", segment="ADULT")
    lead = Lead(sender_id="s", platform="instagram", segment="ADULT")
    conv.lead = lead

    def _ok(*, messages, **kwargs):
        return _mk_response(content="ღონისძიების შესახებ ვუპასუხებ.")

    from app.services import openai_service
    import pytest as _pytest
    captured = {}

    def _capture(*, messages, **kwargs):
        captured["called"] = True
        return _mk_response(content="ღონისძიების შესახებ ვუპასუხებ.")

    # Patch only after declaring fixture-style capture.
    import contextlib
    with contextlib.ExitStack() as stack:
        from unittest.mock import patch
        stack.enter_context(patch.object(openai_service, "chat_with_tools", _capture))
        out = adult_llm_engine.run_adult_llm_turn(
            user_message="რომელი ღონისძიება გაქვთ ივლისში?",
            conversation=conv,
            lead=lead,
            sender_id="s",
            platform="instagram",
        )

    assert conv.segment == "ADULT", "must stay ADULT for pure adult inquiry"
    assert captured.get("called") is True, "LLM must be consulted"


def test_no_switch_for_adult_age_inquiry():
    """'30 წლის ვარ' is an ADULT inquiry — must NOT trigger the
    parent switch (parent switch only fires for ages 9–17 paired with
    a child keyword)."""
    conv = Conversation(sender_id="s", platform="instagram", segment="ADULT")
    lead = Lead(sender_id="s", platform="instagram", segment="ADULT")
    conv.lead = lead

    from app.services import openai_service
    from unittest.mock import patch
    with patch.object(
        openai_service, "chat_with_tools",
        return_value=_mk_response(content="გასაგებია, აი მაშინ შემოგთავაზებთ."),
    ):
        out = adult_llm_engine.run_adult_llm_turn(
            user_message="30 წლის ვარ",
            conversation=conv,
            lead=lead,
            sender_id="s",
            platform="instagram",
        )

    assert conv.segment == "ADULT"
    assert "გასაგებია" in out
