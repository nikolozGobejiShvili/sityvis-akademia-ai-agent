"""Camp answers were reaching questions that were not about the camp (2026-09-03).

Two live failures on the client's page, both deep in a Sunday-School conversation
and both answered „ბანაკის მიმდინარე ნაკადები უკვე დასრულებულია":

* 16:02:29 — „მშობელთან უკუკავშირი იქნება?". No camp word. It matched
  `camp_topic_facts.detect_camp_topic` as topic `parent_communication`. The
  parent's next message was „საიდან მოიტანე ბანაკი?".
* 16:04:48 — „ხო და ბანაკი არ მაინტერესებს". The camp word made every detector
  read a refusal of the camp as a question about it, so the same answer came
  back a second time.

`_msg_has_camp_intent` is two predicates in one: an explicit camp word is
unambiguous, while price / topic / operational / exact-detail describe questions
ANY programme can be asked. The generic tier now counts only when the
conversation is not demonstrably on another active programme, and a refusal that
names the camp is not a camp question.

These tests pin both, and — equally important — that a genuine camp question is
untouched.
"""
import dataclasses

from app import config
from app.flows import parent_flow as pf
from app.models.conversation import Conversation
from app.models.lead import Lead

_SECTIONS = [
    {"id": "summer_camp", "name": "საზაფხულო ბანაკი", "status": "ended", "type": "camp"},
    {"id": "sunday_school", "name": "საკვირაო სკოლა", "status": "active", "type": "kids_program"},
]


def _conv(history=()):
    c = Conversation(sender_id="s", platform="facebook", segment="PARENT")
    c.lead = Lead(sender_id="s", platform="facebook", segment="PARENT")
    for role, text in history:
        c.history.append({"role": role, "content": text})
    return c


def _ask(monkeypatch, history=()):
    """`_maybe_handle_camp_status` with the camp ended, as it is in production."""
    monkeypatch.setattr(pf, "settings", dataclasses.replace(
        config.settings, USE_PROGRAM_ISOLATION=False))
    monkeypatch.setattr("app.services.admin_config_service.get_active_sections",
                        lambda: list(_SECTIONS))
    monkeypatch.setattr("app.services.admin_config_service.get_camp_status", lambda: "ended")
    conv = _conv(history)
    return lambda msg: pf._maybe_handle_camp_status(conv, msg)


_IN_SUNDAY_SCHOOL = (
    ("user", "საკვირაო სკოლა მაინტერესებს"),
    ("assistant", "საკვირაო სკოლა: 595 ლარი, 12 შეხვედრა."),
)


# --- the generic detectors must not claim another programme's conversation ---

def test_generic_topic_question_in_another_program_defers(monkeypatch):
    """The 16:02:29 failure. `parent_communication` is a camp TOPIC, but the
    parent was three turns into Sunday School."""
    ask = _ask(monkeypatch, _IN_SUNDAY_SCHOOL)
    assert ask("მშობელთან უკუკავშირი იქნება?") is None


def test_generic_operational_question_in_another_program_defers(monkeypatch):
    ask = _ask(monkeypatch, _IN_SUNDAY_SCHOOL)
    assert ask("ოთახები როგორია?") is None
    assert ask("ჯგუფში რამდენი ბავშვია?") is None
    assert ask("ძალიან ძვირია") is None


def test_same_questions_still_answer_camp_with_no_other_program(monkeypatch):
    """The other half. With nothing else named, these ARE camp questions and the
    honest approved status is still the right answer — every camp-only fixture
    in the suite depends on this."""
    ask = _ask(monkeypatch)
    assert ask("ოთახები როგორია?") is not None
    assert ask("ბავშვისთვის რა გაქვთ?") is not None


def test_explicit_camp_question_is_never_deferred(monkeypatch):
    """A camp word outranks the conversation — the parent asked about the camp."""
    ask = _ask(monkeypatch, _IN_SUNDAY_SCHOOL)
    assert ask("ბანაკზე რა ხდება?") is not None
    assert ask("ბანაკის ფასი რა არის?") is not None


# --- a refusal that names the camp is not a question about it ---

def test_declining_the_camp_is_not_a_camp_question(monkeypatch):
    """The 16:04:48 failure."""
    ask = _ask(monkeypatch, _IN_SUNDAY_SCHOOL)
    for msg in (
        "ხო და ბანაკი არ მაინტერესებს",
        "ბანაკი აღარ მაინტერესებს",
        "ბანაკი არ მინდა",
        "ბანაკი არ მჭირდება",
    ):
        assert ask(msg) is None, msg


def test_a_negation_inside_a_genuine_camp_question_still_answers(monkeypatch):
    """„არ" alone is not a refusal — the negation has to attach to wanting."""
    ask = _ask(monkeypatch)
    assert ask("ბანაკი არ დამთავრებულა?") is not None
    assert ask("ბანაკი დამთავრდა?") is not None


def test_price_objection_naming_camp_is_not_a_refusal(monkeypatch):
    """`_DECLINE_OVERRIDE_INTEREST` is honoured: a contrast or a price word makes
    „არ მინდა" an objection to answer, not a refusal to close on."""
    ask = _ask(monkeypatch)
    assert ask("ბანაკი არ მინდა, მაგრამ ძვირია") is not None


def test_decline_predicate_needs_a_camp_word(monkeypatch):
    """The predicate is scoped to the camp — a bare refusal is somebody else's job."""
    assert pf._msg_declines_camp("არ მაინტერესებს") is False
    assert pf._msg_declines_camp("ბანაკი არ მაინტერესებს") is True


# --- the camp's age qualifier is the camp's, not every kids' programme's ---

_IN_CAMP = (
    ("user", "ბანაკი მაინტერესებს"),
    ("assistant", "ბანაკის ნაკადები: 23-29 ივნისი."),
)


def _age_question(monkeypatch, history, message, reply):
    monkeypatch.setattr("app.services.admin_config_service.get_active_sections",
                        lambda: list(_SECTIONS))
    out = pf._ensure_camp_age_question(_conv(history), message, reply)
    return "რამდენი წლისაა" in out


def test_age_question_is_not_appended_in_another_program(monkeypatch):
    """Live 2026-09-04: three consecutive Sunday-School replies each ended
    „…თქვენი შვილი რამდენი წლისაა?", one of them grafted onto a registration
    link the parent had just been given.

    The camp needs the age to answer at all — it admits 9–17 and the question
    decides eligibility. Sunday School's answers and its registration link do
    not depend on it, so the question is an interruption there.
    """
    reply = "რეგისტრაცია მარტივია! გადადით ბმულზე: https://wordacademy.ge/course/sakvirao-skola/#124"
    assert _age_question(monkeypatch, _IN_SUNDAY_SCHOOL, "როგორ დავრეგისტრირდე?", reply) is False


def test_age_question_still_appended_for_the_camp(monkeypatch):
    """The other half — the camp keeps its qualifier."""
    assert _age_question(
        monkeypatch, _IN_CAMP, "ბანაკზე როგორ ჩავეწერო?", "ბანაკის ინფორმაცია აქ არის.",
    ) is True


def test_age_question_still_appended_when_no_program_is_named(monkeypatch):
    """Nothing named ⇒ the camp qualifier behaves exactly as it always has."""
    assert _age_question(monkeypatch, (), "ფასი რა არის?", "ფასი 2150 ლარია.") is True
