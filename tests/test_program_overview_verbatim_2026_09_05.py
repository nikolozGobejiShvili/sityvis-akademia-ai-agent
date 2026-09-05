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
import pytest

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
