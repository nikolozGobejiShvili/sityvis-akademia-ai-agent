"""Live test #5 (2026-07-27): two data-driven fixes, both flag-gated (OFF = byte-identical).

Fix A — USE_FUZZY_PROGRAM_MATCH: a typo / transposition / dropped letter in an ACTIVE
program name („დინსეილენდის" for „დისნეილენდი") failed to match, so the message fell
through to the camp answer. Fuzzy matching (bounded edit distance on the aligned name
prefix) now identifies the program for EVERY active program — not just Disneyland. camp /
price / unrelated words still never match (ambiguous-stem + distance guards).

Fix B — adult-intro dead-end on the HOISTED path: with a per-product booking active, an
adult-events question was hoisted to the engine, the sanitiser collapsed the redirect into
a dead-end „…დაგეხმარებით." with no follow-up, and the conversation stopped. The hoist now
re-applies the same `_ensure_adult_intro_followup_for_parent_flow` guard the normal path has.
"""
import dataclasses

from app import config
from app.reasoning.dynamic_program_match import match_dynamic_program
from app.flows import parent_flow as pf
from app.models.conversation import Conversation
from app.models.lead import Lead


_SECS = [
    {"id": "summer_camp", "name": "ბანაკი", "status": "active", "type": "camp"},
    {"id": "disneyland_tour", "name": "დისნეილენდი", "status": "active", "type": "other"},
    {"id": "formula_1", "name": "ფორმულა 1", "status": "active", "type": "other"},
]


def _pid(msg, fuzzy):
    m = match_dynamic_program(msg, _SECS, fuzzy=fuzzy)
    return (m or {}).get("program_id")


# --- Fix A: fuzzy program-name matching ---

def test_fuzzy_off_is_byte_identical():
    # exact + declension still match
    assert _pid("დისნეილენდი მაინტერესებს", False) == "disneyland_tour"
    # the live typo does NOT match with the flag off
    assert _pid("დინსეილენდის რა ღირს?", False) is None


def test_fuzzy_on_matches_typos_for_every_program():
    assert _pid("დინსეილენდის რა ღირს?", True) == "disneyland_tour"    # transposition (live bug)
    assert _pid("დისნეილენდ მაინტერესებს", True) == "disneyland_tour"  # dropped letter
    assert _pid("ფორმულას ფასი", True) == "formula_1"                  # a different program too
    assert _pid("დისნეილენდი", True) == "disneyland_tour"             # exact still works


def test_fuzzy_on_does_not_over_match():
    assert _pid("ბანაკის ფასი", True) is None      # camp word is ambiguous → never a dynamic hit
    assert _pid("ფორმა მინდა", True) is None        # too far from ფორმულა (allowed=1 for len 7)
    assert _pid("რა ღირს?", True) is None           # bare price question names nothing
    assert _pid("გამარჯობა", True) is None


def test_fuzzy_respects_inactive_status():
    inactive = [{"id": "disneyland_tour", "name": "დისნეილენდი", "status": "coming_soon"}]
    assert match_dynamic_program("დინსეილენდის ფასი", inactive, fuzzy=True) is None


# --- Fix B: adult-intro dead-end guard on the hoisted path ---

_DEAD_END = "გასაგებია, ზრდასრულთა ღონისძიებებზე დაგეხმარებით."


def _conv():
    c = Conversation(sender_id="s", platform="facebook")
    c.lead = Lead(sender_id="s", platform="facebook", segment="PARENT")
    return c


def _pin_hoist(monkeypatch, engine_out):
    monkeypatch.setattr(pf, "settings", dataclasses.replace(
        config.settings, USE_PARENT_LLM_ENGINE=True))
    monkeypatch.setattr(pf, "_is_active_per_product_booking", lambda conv: True)  # force hoist
    monkeypatch.setattr(pf, "_run_llm_engine_safely", lambda conv, msg: engine_out)


def test_hoist_adult_intro_dead_end_gets_followup(monkeypatch):
    _pin_hoist(monkeypatch, _DEAD_END)
    out = pf._handle_core(_conv(), "ზრდასრულთა ღონისძიებებში რა შედის?")
    assert "?" in out                                    # no longer a dead-end
    assert "თქვენთვის გსურთ თუ თქვენი შვილისთვის" in out  # the next-step question was appended


def test_hoist_normal_program_answer_is_untouched(monkeypatch):
    normal = "დისნეილენდის ღირებულებაა 4000 ლარი. თუ გსურთ, კონსულტაციაზე ჩაგწერთ."
    _pin_hoist(monkeypatch, normal)
    out = pf._handle_core(_conv(), "დისნეილენდის ფასი რა არის?")
    assert "თქვენთვის გსურთ თუ თქვენი შვილისთვის" not in out  # guard is a no-op here
    assert "4000" in out
