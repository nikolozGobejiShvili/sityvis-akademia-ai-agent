"""Every camp question is answered from the panel (2026-09-08).

A camp's whole vocabulary is generic — „საზაფხულო ბანაკი" is made of words the
matcher refuses on purpose — so no camp could ever be identified as a
programme. Every camp turn fell past the dynamic path into handlers that answer
for ONE camp, whichever the parent meant. With a second camp in the panel that
is simply wrong: measured live 2026-09-08, with „პარიზის ბანაკი" active and the
summer camp switched off,

    „ბანაკი მაინტერესებს"           → „ბანაკის მიმდინარე ნაკადები დასრულებულია"
    „ბანაკის ფასი რა არის?"          → „ბანაკის ფასი არის 2150 ლარი"
    „ბანაკზე როგორ დავრეგისტრირდე?"  → the summer camp's registration answer

`_program_id_for_turn` is the one place that decides which programme a turn is
about: a NAME, or a generic word exactly one active programme answers to — and
with one camp in the panel „ბანაკი" is as precise as the title. A non-reserved
answer routes the turn to the engine with that programme's own fields, so every
question type follows at once instead of one guard per handler.

The summer camp stays reserved, so when it is the answer nothing changes: its
curated, operator-approved copy still owns those turns.
"""
import dataclasses

import pytest

from app import config as config_module
from app.agent.llm import parent_llm_engine as eng
from app.flows import parent_flow as pf
from app.models.conversation import Conversation

_PRICE, _URL = "8500 ლარი", "https://example.ge/paris"
_FULL = "ვრცელი პანელიდან: ჯგუფში 14 ბავშვი."
_PARIS = {
    "id": "disneyland", "name": "პარიზის ბანაკი", "type": "kids_program",
    "status": "active", "price_text": _PRICE, "registration_url": _URL,
    "registration_status": "open", "age_min": 12, "age_max": 16,
    "description_short": "პარიზის ბანაკი — 10 დღე.", "description_full": _FULL,
}
_CAMP = {
    "id": "summer_camp", "name": "საზაფხულო ბანაკი", "type": "camp",
    "status": "ended", "hashtags": ["ბანაკი", "banaki", "camp"],
    "description_short": "საზაფხულო ბანაკი — 7 დღე.",
}
_SCHOOL = {
    "id": "sunday_school", "name": "საკვირაო სკოლა", "type": "kids_program",
    "status": "active", "description_short": "საკვირაო სკოლა — 3 თვე.",
}

_CAMP_QUESTIONS = [
    "ბანაკის ფასი რა არის?",
    "ბანაკზე როგორ დავრეგისტრირდე?",
    "ბანაკი რამდენხნიანია?",
    "ბანაკში რა ასაკიდან იღებთ?",
    "ბანაკი რამდენი ღირს?",
]


@pytest.fixture
def flow(monkeypatch):
    def _install(sections):
        active = [s for s in sections if s.get("status") == "active"]
        monkeypatch.setattr(
            "app.services.admin_config_service.get_active_sections",
            lambda: [dict(s) for s in active])
        monkeypatch.setattr("app.services.admin_config_service.load_sections",
                            lambda: [dict(s) for s in sections])
        monkeypatch.setattr("app.services.admin_config_service.get_section",
                            lambda pid: next((dict(s) for s in sections
                                              if s["id"] == pid), None))
        monkeypatch.setattr("app.services.admin_config_service.get_camp_status",
                            lambda: next((s["status"] for s in sections
                                          if s["id"] == "summer_camp"), "ended"))
        monkeypatch.setattr("app.services.messenger_service.get_user_profile",
                            lambda sid, plat: {})
        swapped = dataclasses.replace(
            config_module.settings, USE_PARENT_LLM_ENGINE=True,
            USE_DYNAMIC_PROGRAMS=True, USE_CAMP_OFF_GATE=True,
            USE_RESERVED_PROGRAMS_DYNAMIC=True, USE_PER_PRODUCT_BOOKING=True)
        monkeypatch.setattr(pf, "settings", swapped)
        monkeypatch.setattr(eng, "settings", swapped)
        seen = {}

        def _engine(conv, msg):
            lead = getattr(conv, "lead", None) or pf._ensure_lead(conv)
            seen["ctx"] = eng._build_context_message(conv, lead, msg)
            return "[engine]"
        monkeypatch.setattr(pf, "_run_llm_engine_safely", _engine)

        def _ask(msg):
            seen.clear()
            conv = Conversation(sender_id="c", platform="messenger",
                                segment="PARENT")
            return pf.handle(conv, msg), seen.get("ctx", "")
        return _ask
    return _install


# ── one camp in the panel: every question is that camp's ───────────────────

@pytest.mark.parametrize("msg", _CAMP_QUESTIONS)
def test_every_camp_question_reaches_the_panel_programme(flow, msg):
    ask = flow([_CAMP, _SCHOOL, _PARIS])          # summer camp switched off
    out, ctx = ask(msg)
    assert out == "[engine]", msg
    assert "active_program=პარიზის ბანაკი" in ctx
    assert _PRICE in ctx and _URL in ctx and _FULL in ctx


def test_the_general_question_is_the_panels_own_text(flow):
    ask = flow([_CAMP, _SCHOOL, _PARIS])
    out, _ = ask("ბანაკი მაინტერესებს")
    assert out == _PARIS["description_short"]


@pytest.mark.parametrize("msg", _CAMP_QUESTIONS)
def test_no_answer_carries_the_other_camps_figures(flow, msg):
    """The defect in one line: another camp's approved price and link."""
    ask = flow([_CAMP, _SCHOOL, _PARIS])
    out, _ = ask(msg)
    assert "2150" not in out
    assert "ნაკადი" not in out


# ── the summer camp alone: nothing changes ─────────────────────────────────

@pytest.mark.parametrize("msg", _CAMP_QUESTIONS + ["ბანაკი მაინტერესებს"])
def test_the_curated_camp_still_owns_its_turns(flow, msg):
    """It is reserved, so its approved copy is untouched — the whole point of
    keeping the reserved list rather than dissolving it."""
    ask = flow([dict(_CAMP, status="active"), _SCHOOL])
    out, _ = ask(msg)
    assert out != "[engine]", msg


# ── two camps: ask, never guess ────────────────────────────────────────────

@pytest.mark.parametrize("msg", _CAMP_QUESTIONS + ["ბანაკი მაინტერესებს"])
def test_two_camps_are_asked_about_never_guessed(flow, msg):
    ask = flow([dict(_CAMP, status="active"), _SCHOOL, _PARIS])
    out, _ = ask(msg)
    assert "საზაფხულო ბანაკი" in out and "პარიზის ბანაკი" in out
    assert "2150" not in out and _PRICE not in out


# ── the decision lives in one place ────────────────────────────────────────

def test_a_name_and_a_generic_word_resolve_the_same_way(flow):
    flow([_CAMP, _SCHOOL, _PARIS])
    assert pf._program_id_for_turn("პარიზის ბანაკი მაინტერესებს") == "disneyland"
    assert pf._program_id_for_turn("ბანაკი მაინტერესებს") == "disneyland"


def test_two_candidates_resolve_to_nothing(flow):
    flow([dict(_CAMP, status="active"), _SCHOOL, _PARIS])
    assert pf._program_id_for_turn("ბანაკი მაინტერესებს") == ""


def test_the_reserved_camp_resolves_to_itself(flow):
    """Resolution and routing are separate: this names the camp, and the caller
    keeps it out of the dynamic path because it is reserved."""
    flow([dict(_CAMP, status="active"), _SCHOOL])
    assert pf._program_id_for_turn("ბანაკი მაინტერესებს") == "summer_camp"
    assert pf._is_dynamic_program_turn("ბანაკი მაინტერესებს") is False
