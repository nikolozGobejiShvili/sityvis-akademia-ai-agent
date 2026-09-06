"""Two live defects from the client's test of 2026-09-06.

1. The camp answered for a programme that was not the camp.

   „6 წლის ბავშვის მოყვანას შევძლებ?", inside a Sunday-School conversation,
   came back „ბანაკი განკუთვნილია 9–17 წლის ბავშვებისთვის…" — with the camp
   switched off, and with the programme's own brackets starting at 7.

   `_maybe_handle_out_of_range_age` writes „ბანაკი" into its message and reads
   `_camp_age_bounds()`, but it fires on ANY under-age disclosure in the PARENT
   flow, and every kids programme is served by that flow. The sixth place where
   PARENT was read as camp — the previous five (status gate, age question,
   decline, registration, topic facts) were narrowed the same way this one is:
   defer when the conversation is demonstrably on another active programme.

2. The agent told the parent that THEY understand.

   „გესმით, სამი შვილი ერთდროულად — …". „გესმით" is second person: it says the
   parent is the one who understands. The empathic form is „გვესმის" (we).

   The prompt already names both wrong forms (system_parent_v2.md:41) and the
   model wrote one anyway — the same way the singular „გესმის" was ignored
   before it became a mechanical rewrite. So the plural joins it there, beside
   the genitive fix, and nothing is added to the prohibition table.
"""
import dataclasses

import pytest

from app import config as config_module
from app.agent.llm import parent_llm_engine as eng
from app.flows import parent_flow as pf
from app.models.conversation import Conversation

# ── 1. the camp leak ───────────────────────────────────────────────────────

_SS = {
    "id": "sunday_school", "name": "საკვირაო სკოლა", "type": "kids_program",
    "status": "active", "age_min": 7, "age_max": 17,
    "description_short": "საკვირაო სკოლა — 3-თვიანი პროგრამა.",
    "description_full": "ჯგუფები: 7-8, 9-10, 11-12, 13-14, 15-16-17.",
}
_UNDER_AGE = "6 წლის ბავშვის მოყვანას შევძლებ?"


@pytest.fixture
def flow(monkeypatch):
    swapped = dataclasses.replace(
        config_module.settings,
        USE_PROGRAM_ISOLATION=True,
        USE_RESERVED_PROGRAMS_DYNAMIC=True,
    )
    monkeypatch.setattr(pf, "settings", swapped)
    monkeypatch.setattr("app.services.admin_config_service.get_active_sections",
                        lambda: [dict(_SS)])
    return pf


def _conv(history=None):
    conv = Conversation(sender_id="s", platform="messenger", segment="PARENT")
    conv.history = list(history or [])
    return conv


def test_under_age_in_another_programmes_conversation_defers(flow):
    """The engine answers, with that programme's own age fields behind it."""
    conv = _conv([{"role": "user", "content": "საკვირაო სკოლა მაინტერესებს"}])
    assert flow._maybe_handle_out_of_range_age(conv, _UNDER_AGE) is None


def test_the_camp_answer_never_mentions_another_programmes_child(flow):
    """The exact live wording must not reach a Sunday-School parent."""
    conv = _conv([{"role": "user", "content": "საკვირაო სკოლა მაინტერესებს"}])
    out = flow._maybe_handle_out_of_range_age(conv, _UNDER_AGE)
    assert out is None or "ბანაკი" not in out


def test_the_age_is_still_captured_so_it_cannot_become_a_name(flow):
    """This handler exists to stop „6 წლის არის…" being stored as the parent's
    name. Deferring must not cost that — the age lands on the lead first."""
    conv = _conv([{"role": "user", "content": "საკვირაო სკოლა მაინტერესებს"}])
    flow._maybe_handle_out_of_range_age(conv, _UNDER_AGE)
    assert (conv.lead.child_age or "").strip() == "6"


def test_a_camp_conversation_is_untouched(flow):
    """Camp keeps its curated answer — the narrowing is about OTHER programmes,
    not about disabling the handler."""
    conv = _conv([{"role": "user", "content": "ბანაკი მაინტერესებს"}])
    out = flow._maybe_handle_out_of_range_age(conv, _UNDER_AGE)
    assert out is not None
    assert "ბანაკი" in out


def test_a_conversation_with_no_programme_is_untouched(flow):
    """Every camp fixture in the suite looks like this."""
    out = flow._maybe_handle_out_of_range_age(_conv(), _UNDER_AGE)
    assert out is not None
    assert "ბანაკი" in out


def test_an_eligible_age_still_passes_through(flow):
    conv = _conv([{"role": "user", "content": "საკვირაო სკოლა მაინტერესებს"}])
    assert flow._maybe_handle_out_of_range_age(conv, "12 წლის არის") is None


# ── 2. the person mistake ──────────────────────────────────────────────────

def test_the_plural_person_mistake_is_corrected():
    """The live sentence, unchanged apart from the verb."""
    out = eng._normalise_polite_address(
        "გესმით, სამი შვილი ერთდროულად — ეს ნამდვილად სერიოზული გადაწყვეტილებაა!")
    assert out.startswith("გვესმის,")
    assert "გესმით" not in out


@pytest.mark.parametrize("bad", ["გესმის", "გესმით"])
def test_both_wrong_persons_become_the_same_right_one(bad):
    assert eng._normalise_polite_address(
        f"{bad} თქვენი უკმაყოფილება") == "გვესმის თქვენი უკმაყოფილება"


def test_the_correct_form_is_left_alone():
    """Idempotent — the output of the rewrite must not be rewritten again."""
    text = "გვესმის თქვენი უკმაყოფილება"
    assert eng._normalise_polite_address(text) == text
    assert eng._normalise_polite_address(
        eng._normalise_polite_address(text)) == text


def test_it_is_a_grammar_rewrite_not_a_new_prohibition():
    """The prohibition table selects its wording mandates BY INDEX, so adding
    to it silently reclassifies its neighbours. This correction belongs with
    the other mechanical person/genitive fixes and must stay there."""
    assert ("გესმით", "გვესმის") in eng._POLITE_ADDRESS_REWRITES
    assert "გესმით" not in str(eng.FORBIDDEN_PHRASE_REPLACEMENTS)
