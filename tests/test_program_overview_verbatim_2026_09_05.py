"""„<programme> მაინტერესებს" answers with the operator's own text.

Carried as a fact in the turn context the short description is re-written: live
2026-09-05 the opening answer lost the operator's paragraphing („📍 ლოკაციები"
glued to the previous sentence) and gained the discounts, which live in a
separate field and are not in the text the client wrote. Measured again against
the real model on 2026-09-06: 0 of 3 turns reproduced it. So the code sends the
bytes.

Which word list, and which way round (rewritten 2026-09-06)
-----------------------------------------------------------
The first version excluded price / registration / topic words. A misspelling in
one of THOSE defeated the exclusion:

    in='რა არის საკვირაო სკოლის ღირებულრბა?'   → the general description

One letter wrong in „ღირებულება" and a PRICE question got the overview. Four
typos appeared in that single conversation („ღირებულრბა", „პიროვები",
„მისმართები", „ინფრომაცია"), so mistyping is the normal case.

Handing the judgement to the model was tried and measured: a `general_overview`
argument on `get_program_info`. In 12 of 12 real turns the model never called
that tool — it already has the programme's facts in the turn context, so it has
no reason to. That mechanism was removed rather than left as dead code.

What ships instead inverts the list. It is an ALLOWLIST of words that carry no
subject („მაინტერესებს", „შესახებ", „პირობები"). Anything else in the message —
including a misspelt word — counts as a subject and the turn goes to the engine,
which answers it from the full facts. A typo can now only cost the verbatim
formatting; it can no longer produce the wrong answer.

A non-reserved id is used throughout: none of this is specific to Sunday School.
"""
import pytest

from app.flows import parent_flow as pf
from app.models.conversation import Conversation

_NAME = "რობოტიკის სტუდია"
_SHORT = (
    "3-თვიანი პროგრამა აერთიანებს 12 ინტერაქციულ შეხვედრას. 💙\n\n"
    "📍 შეხვედრები გაიმართება შაბათს.\n\n"
    "ჯგუფები ასაკის მიხედვით."
)
_SECTION = {
    "id": "robotics_club",
    "name": _NAME,
    "type": "kids_program",
    "status": "active",
    "price_text": "450 ლარი",
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


# -- it fires on a request that names nothing but the programme -------------

@pytest.mark.parametrize("msg", [
    f"{_NAME}",
    f"{_NAME} მაინტერესებს",
    f"გამარჯობა, {_NAME} მაინტერესებს",
    f"{_NAME}-ის შესახებ ინფორმაცია",
    f"{_NAME}-ის დეტალები მაინტერესებს",
    f"{_NAME}-ის პირობები შეგიძლიათ მომწეროთ?",
    f"{_NAME} რა არის?",
    f"მინდა ვიცოდე {_NAME}-ის შესახებ",
])
def test_a_request_with_no_subject_gets_the_panel_text(ask, msg):
    assert ask(msg) == _SHORT, msg


# -- a subject of its own belongs to the engine, misspelt or not ------------

@pytest.mark.parametrize("msg", [
    f"{_NAME}-ის ღირებულება რა არის?",
    f"{_NAME}-ის ღირებულრბა რა არის?",   # the live typo — must behave the same
    f"{_NAME}-ის ფასი?",
    f"{_NAME}-ზე როგორ დავრეგისტრირდე?",
    f"{_NAME}-ზე კონსულტაცია მინდა",
    f"{_NAME}-ში ჯგუფში რამდენი ბავშვია?",
    f"{_NAME}-ის პედაგოგები ვინ არიან?",
    f"{_NAME} სად ტარდება?",
    f"{_NAME} როდის იწყება?",
])
def test_a_question_about_something_goes_to_the_engine(ask, msg):
    assert ask(msg) is None, msg


def test_the_typo_and_the_correct_spelling_behave_identically(ask):
    """The point of the inversion. Before, these two diverged: the correctly
    spelled one deferred and the misspelt one was answered with the overview."""
    assert ask(f"{_NAME}-ის ღირებულება რა არის?") is None
    assert ask(f"{_NAME}-ის ღირებულრბა რა არის?") is None


@pytest.mark.parametrize("msg", [
    f"{_NAME}-ის შესახებ ინფრომაცია",       # the operator's habitual typo
    f"{_NAME} მაინტერსებს",
    f"{_NAME}-ის დეტალბი მომწერთ",
    f"{_NAME}-ის პიროვები",
])
def test_a_typo_in_a_generic_word_still_gets_the_panel_text(ask, msg):
    """The allowlist tolerates a typo in ITS OWN words, so the operator's text
    still arrives when the parent mistypes „ინფორმაცია". Without this the
    opening description came back re-written for a one-letter slip."""
    assert ask(msg) == _SHORT, msg


@pytest.mark.parametrize("word", [
    "ფასი", "ღირებულება", "ღირებულრბა", "მისამართები", "მისმართები",
    "პედაგოგები", "რეგისტრაცია", "განრიგი", "ასაკი", "ჯგუფში", "გადახდა",
    "ფასდაკლება", "კონსულტაცია", "ტარდება", "იწყება", "რამდენი", "ღირს",
])
def test_no_subject_word_is_mistaken_for_a_generic_one(word):
    """The tolerance must never widen into the subjects, or the defect this
    handler was rewritten for comes straight back.

    „ფასი" is what forces the shape of the rule: it is only 2 edits from „რას",
    which IS generic. A flat two-edit budget would make PRICE a generic word.
    Short entries are therefore excluded from fuzzy matching entirely."""
    assert pf._is_generic_word(word) is False, word


def test_the_price_word_is_the_reason_short_entries_are_excluded():
    """Pin the near-collision itself, so a later edit that lowers the length
    floor fails here instead of in production."""
    from app.reasoning.dynamic_program_match import _bounded_levenshtein
    assert _bounded_levenshtein("ფასი", "რას", 3) == 2
    assert "რას" in pf._GENERIC_PROGRAM_WORDS
    assert len("რას") < pf._GENERIC_FUZZY_MIN_LEN


# -- other flows keep their turns ------------------------------------------

@pytest.mark.parametrize("msg", [
    "გამარჯობა",                          # names no programme
    "ბანაკი მაინტერესებს",                # a different programme
    "ჯგუფში რამდენი ბავშვია?",            # names no programme
])
def test_turns_that_name_no_programme_are_untouched(ask, msg):
    assert ask(msg) is None, msg


def test_adult_programmes_keep_their_own_flow(monkeypatch):
    """An adult programme has its own segment and engine; answering here meant
    `switch_to_adult_flow` never ran — caught by
    `test_engine_does_not_answer_camp_age_after_adult_switch`."""
    adult = {
        "id": "adult_events", "name": "ზრდასრულთა ღონისძიებები",
        "type": "adult_events", "status": "active",
        "description_short": "ზრდასრულთა ღონისძიებების აღწერა.",
    }
    monkeypatch.setattr("app.services.admin_config_service.get_active_sections",
                        lambda: [adult, dict(_SECTION)])
    conv = Conversation(sender_id="s", platform="messenger", segment="PARENT")
    assert pf._maybe_handle_program_overview(
        conv, "მე ზრდასრული ვარ და ღონისძიებები მაინტერესებს") is None
    assert pf._maybe_handle_program_overview(
        conv, f"{_NAME} მაინტერესებს") == _SHORT


# -- the text itself --------------------------------------------------------

def test_the_answer_carries_no_field_the_client_text_does_not(ask):
    out = ask(f"{_NAME} მაინტერესებს")
    assert "10%" not in out                    # discounts are their own field
    assert "ჯგუფში მაქსიმუმ 8" not in out      # that is description_full's job


def test_paragraphing_survives(ask):
    """The reason this is deterministic at all: the model reflowed it."""
    assert ask(f"{_NAME} მაინტერესებს").count("\n\n") == _SHORT.count("\n\n") == 2


def test_nothing_is_hardcoded(monkeypatch):
    """Change the panel, change the answer."""
    section = dict(_SECTION, description_short="სულ სხვა ტექსტი.")
    monkeypatch.setattr("app.services.admin_config_service.get_active_sections",
                        lambda: [section])
    conv = Conversation(sender_id="s", platform="messenger", segment="PARENT")
    assert pf._maybe_handle_program_overview(
        conv, f"{_NAME} მაინტერესებს") == "სულ სხვა ტექსტი."


def test_empty_short_description_defers(monkeypatch):
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


def test_the_opening_description_is_sent_once(ask):
    """`description_short` opens; `description_full` serves what follows."""
    conv = Conversation(sender_id="s", platform="messenger", segment="PARENT")
    first = pf._maybe_handle_program_overview(conv, f"{_NAME} მაინტერესებს")
    assert first == _SHORT
    conv.history = [
        {"role": "user", "content": f"{_NAME} მაინტერესებს"},
        {"role": "assistant", "content": first},
    ]
    assert pf._maybe_handle_program_overview(
        conv, f"{_NAME}-ის შესახებ ინფორმაცია") is None


def test_the_dead_tool_mechanism_is_gone():
    """Measured: in 12 of 12 real turns the model never called the tool, because
    the programme's facts are already in the turn context. Dead code is a path
    someone will later believe in, so it was removed rather than left."""
    from app.agent.tools import parent_tool_executor as pte, parent_tools
    assert not hasattr(pte, "program_overview_text_for_conversation")
    assert "general_overview" not in str(parent_tools.PARENT_TOOLS)
