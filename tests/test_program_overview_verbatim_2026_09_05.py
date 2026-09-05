"""„<programme> მაინტერესებს" answers with the operator's own text (2026-09-05).

As a FACT in the turn context the short description is read and rewritten by the
model, so the opening answer lost the operator's paragraphing („📍 ლოკაციები"
ended up glued to the end of the previous sentence) and gained the discounts,
which are a separate field and not part of the text the client wrote.

`description_short` is now returned exactly as the panel holds it for a general
„tell me about this programme" turn. Nothing is hardcoded — every character
comes from the panel — and the handler is deliberately narrow: anything
transactional, priced, or specific goes to the engine, which still has
`description_full` and every other field behind it. That separation is the
point: the overview answers „what is this", the engine answers „how many
children per group".

A non-reserved id is used throughout: none of this is specific to Sunday School.
"""
import dataclasses

import pytest

from app import config as config_module
from app.flows import parent_flow as pf
from app.models.conversation import Conversation

_NAME = "რობოტიკის სტუდია"
_SHORT = (
    "3-თვიანი პროგრამა აერთიანებს 12 ინტერაქციულ შეხვედრას.\n\n"
    "შეხვედრები გაიმართება შაბათს.\n\n"
    "ღირებულება: 450 ლარი"
)
_SECTION = {
    "id": "robotics_club",
    "name": _NAME,
    "type": "kids_program",
    "status": "active",
    "description_short": _SHORT,
    "description_full": "ვრცელი აღწერა: ჯგუფში მაქსიმუმ 8 მოსწავლე.",
    "discounts": ["10% დედმამიშვილებზე"],
}


@pytest.fixture
def ask(monkeypatch):
    monkeypatch.setattr("app.services.admin_config_service.get_active_sections",
                        lambda: [dict(_SECTION)])
    conv = Conversation(sender_id="s", platform="messenger", segment="PARENT")
    return lambda msg: pf._maybe_handle_program_overview(conv, msg)


@pytest.mark.parametrize("msg", [
    f"{_NAME} მაინტერესებს",
    f"{_NAME} რა არის?",
    f"{_NAME}-ის შესახებ ინფორმაცია",
    f"მომწერეთ ინფორმაცია {_NAME}-ზე",
    f"{_NAME}-ის პირობები რომ მომწეროთ",
])
def test_overview_returns_the_panel_text_unchanged(ask, msg):
    assert ask(msg) == _SHORT, msg


def test_information_request_is_not_mistaken_for_a_form_request(ask):
    """„ინ-ფორმა-ცია" contains „ფორმ". The shipped marker list matches that as a
    bare substring, which excluded the plainest overview request there is; the
    word-boundary regex the codebase already keeps for this is used instead."""
    assert ask(f"{_NAME}-ის შესახებ ინფორმაცია") == _SHORT
    assert ask(f"{_NAME}-ის სარეგისტრაციო ფორმა სად არის?") is None


@pytest.mark.parametrize("msg", [
    f"{_NAME}-ის ფასი რა არის?",          # price has its own handler
    f"{_NAME}-ზე როგორ დავრეგისტრირდე?",  # registration does too
    f"{_NAME}-ზე კონსულტაცია მინდა",      # so does booking
    "ჯგუფში რამდენი ბავშვია?",            # a specific question → engine
    "პედაგოგები ვინ არიან?",
    "გაცდენა ანაზღაურდება?",
    "გამარჯობა",                          # names no programme
    "ბანაკი მაინტერესებს",                # a different programme
])
def test_specific_and_transactional_turns_go_to_the_engine(ask, msg):
    assert ask(msg) is None, msg


def test_the_answer_carries_no_field_the_client_text_does_not(ask):
    """The discounts live in their own field and are not in the operator's text,
    so they must not appear in the opening answer."""
    out = ask(f"{_NAME} მაინტერესებს")
    assert "10%" not in out
    assert "ჯგუფში მაქსიმუმ 8" not in out    # that is description_full's job


def test_paragraphing_survives(ask):
    """The reason this is deterministic: the model reflowed the text."""
    assert ask(f"{_NAME} მაინტერესებს").count("\n\n") == _SHORT.count("\n\n") == 2


def test_nothing_is_hardcoded(monkeypatch):
    """Change the panel, change the answer — no wording lives in the code."""
    section = dict(_SECTION, description_short="სულ სხვა ტექსტი.")
    monkeypatch.setattr("app.services.admin_config_service.get_active_sections",
                        lambda: [section])
    conv = Conversation(sender_id="s", platform="messenger", segment="PARENT")
    assert pf._maybe_handle_program_overview(conv, f"{_NAME} მაინტერესებს") == "სულ სხვა ტექსტი."


def test_empty_short_description_defers(monkeypatch):
    """With nothing to return the engine answers as before."""
    section = dict(_SECTION, description_short="")
    monkeypatch.setattr("app.services.admin_config_service.get_active_sections",
                        lambda: [section])
    conv = Conversation(sender_id="s", platform="messenger", segment="PARENT")
    assert pf._maybe_handle_program_overview(conv, f"{_NAME} მაინტერესებს") is None


def test_switched_off_program_never_answers(monkeypatch):
    monkeypatch.setattr("app.services.admin_config_service.get_active_sections",
                        lambda: [])
    conv = Conversation(sender_id="s", platform="messenger", segment="PARENT")
    assert pf._maybe_handle_program_overview(conv, f"{_NAME} მაინტერესებს") is None


_ENGINE_STUB = "<<<engine>>>"


@pytest.fixture
def live_routing(monkeypatch):
    """`parent_flow.handle` with the production flags, engine stubbed.

    The tests above call the handler directly, which is how the live defect got
    through: `_handle_core` has a Dynamic-Programs HOIST that returns the
    engine's answer ABOVE the whole deterministic chain, and it fires on any
    turn naming a NON-reserved admin programme. With
    `USE_RESERVED_PROGRAMS_DYNAMIC` on — production — that is every programme
    the operator adds from the panel, so the overview handler was unreachable
    for exactly its own subject. These go through the real entry point.
    """
    def _configure(*, reserved_dynamic, section):
        swapped = dataclasses.replace(
            config_module.settings,
            USE_PARENT_LLM_ENGINE=True,
            USE_DYNAMIC_PROGRAMS=True,
            USE_PER_PRODUCT_BOOKING=True,
            USE_CAMP_OFF_GATE=True,
            USE_RESERVED_PROGRAMS_DYNAMIC=reserved_dynamic,
        )
        monkeypatch.setattr(config_module, "settings", swapped)
        monkeypatch.setattr(pf, "settings", swapped)
        monkeypatch.setattr("app.services.admin_config_service.get_active_sections",
                            lambda: [dict(section)])
        monkeypatch.setattr("app.services.admin_config_service.load_sections",
                            lambda: [dict(section)])
        monkeypatch.setattr(pf, "_run_llm_engine_safely",
                            lambda conv, msg: _ENGINE_STUB)

        def _ask(msg):
            conv = Conversation(sender_id="s", platform="messenger",
                                segment="PARENT")
            return pf.handle(conv, msg)
        return _ask
    return _configure


@pytest.mark.parametrize("reserved_dynamic", [True, False])
def test_overview_survives_the_dynamic_program_hoist(live_routing, reserved_dynamic):
    """Live 2026-09-05: „<programme> მაინტერესებს" came back model-written.

    The reply was 791 characters where the panel's `description_short` is 947 —
    the hoist had already returned the engine's answer. Both flag states must
    reach the operator's text through `handle`, not just the flag state that
    leaves the programme reserved.
    """
    ask = live_routing(reserved_dynamic=reserved_dynamic, section=_SECTION)
    assert ask(f"{_NAME} მაინტერესებს") == _SHORT


def test_hoisted_specific_question_still_reaches_the_engine(live_routing):
    """The hoist exists so a dynamic programme's questions are answered from its
    own data. The overview must not swallow that — it answers „what is this",
    the engine answers everything specific, with `description_full` behind it."""
    ask = live_routing(reserved_dynamic=True, section=_SECTION)
    assert ask(f"{_NAME}-ის ფასი რა არის?") == _ENGINE_STUB
    assert ask(f"{_NAME}-ზე როგორ დავრეგისტრირდე?") == _ENGINE_STUB


def test_operator_text_reaches_the_parent_byte_for_byte(live_routing):
    """`handle` applies output polish after `_handle_core` returns — a greeting
    strip and the one-❤️ emoji policy. The operator's text carries emoji, blank
    lines and bullets, and „exactly as written" has to survive all of it."""
    rich = (
        "საკვირაო სკოლა — 3-თვიანი პროგრამა 💙\n\n"
        "📍 ლოკაციები:\n• თბილისი\n• ბათუმი\n\n"
        "🕐 შეხვედრები შაბათს.\n\n"
        "❤️ გელოდებით! ❤️"
    )
    ask = live_routing(reserved_dynamic=True,
                       section=dict(_SECTION, description_short=rich))
    assert ask(f"{_NAME} მაინტერესებს") == rich


def test_the_opening_description_is_sent_once(ask):
    """„description_short leads, description_full serves the follow-ups" — so a
    later „მეტი ინფორმაცია" must not re-send the same block. That turn is the
    engine's, which has the full description behind it."""
    conv = Conversation(sender_id="s", platform="messenger", segment="PARENT")
    first = pf._maybe_handle_program_overview(conv, f"{_NAME} მაინტერესებს")
    assert first == _SHORT
    conv.history = [
        {"role": "user", "content": f"{_NAME} მაინტერესებს"},
        {"role": "assistant", "content": first},
    ]
    assert pf._maybe_handle_program_overview(
        conv, f"{_NAME}-ის შესახებ მეტი ინფორმაცია") is None
    # An unrelated assistant turn in the history does not block it.
    other = Conversation(sender_id="s2", platform="messenger", segment="PARENT")
    other.history = [{"role": "assistant", "content": "გამარჯობა."}]
    assert pf._maybe_handle_program_overview(
        other, f"{_NAME} მაინტერესებს") == _SHORT


def test_adult_programmes_keep_their_own_flow(monkeypatch):
    """An adult programme has its own segment, engine and answers.

    „მე ზრდასრული ვარ და ღონისძიებები მაინტერესებს" matched the adult section by
    name and this handler answered it, so `switch_to_adult_flow` never ran and
    the conversation stayed PARENT. Caught by
    `test_engine_does_not_answer_camp_age_after_adult_switch`.
    """
    adult = {
        "id": "adult_events",
        "name": "ზრდასრულთა ღონისძიებები",
        "type": "adult_events",
        "status": "active",
        "description_short": "ზრდასრულთა ღონისძიებების აღწერა.",
    }
    monkeypatch.setattr("app.services.admin_config_service.get_active_sections",
                        lambda: [adult, dict(_SECTION)])
    conv = Conversation(sender_id="s", platform="messenger", segment="PARENT")
    assert pf._maybe_handle_program_overview(
        conv, "მე ზრდასრული ვარ და ღონისძიებები მაინტერესებს") is None
    # The kids programme in the same panel is unaffected.
    assert pf._maybe_handle_program_overview(conv, f"{_NAME} მაინტერესებს") == _SHORT
