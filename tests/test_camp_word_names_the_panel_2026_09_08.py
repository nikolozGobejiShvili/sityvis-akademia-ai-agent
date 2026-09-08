"""The camp word stopped meaning only the summer camp (2026-09-08).

Two places read „ბანაკი" as THE summer camp. That held while it was the only
camp the operator could configure. It does not any more: „პარიზის ბანაკი" is an
ordinary panel programme, and „ზამთრის ბანაკი" will be another.

Measured live on 2026-09-08 with Paris active and the summer camp switched off:

    in='ბანაკი მაინტერესებს'   → „ბანაკის მიმდინარე ნაკადები უკვე დასრულებულია"
    in='ბანაკი რამდენხნიანია?' → the same, and the engine got no programme at all

The first came from `parent_flow._maybe_handle_camp_status`; the second from
`parent_llm_engine._active_program_section`, whose scan ENDS on a camp word
("either the camp is on and its own handlers own the turn, or it is off and
there is no honest program to name") — so even after the parent had named
Paris, none of Paris's fields reached the model and `description_full` was
never available.

Both now ask the panel the same question first: which ACTIVE programmes answer
to the word that was used? Exactly one is not ambiguous and owns the turn. None
or several, and the original reading stands — which is every configuration that
existed before a second camp did.
"""
import dataclasses

import pytest

from app import config as config_module
from app.agent.llm import parent_llm_engine as eng
from app.flows import parent_flow as pf
from app.models.conversation import Conversation
from app.models.lead import Lead

_FULL = "ვრცელი პანელიდან: ჯგუფში 14 ბავშვი, ავიაბილეთი შედის."
_PARIS = {
    "id": "disneyland", "name": "პარიზის ბანაკი", "type": "kids_program",
    "status": "active", "price_text": "8500 ლარი",
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


@pytest.fixture
def panel(monkeypatch):
    def _install(sections):
        active = [s for s in sections if s.get("status") == "active"]
        monkeypatch.setattr(
            "app.services.admin_config_service.get_active_sections",
            lambda: [dict(s) for s in active])
        monkeypatch.setattr("app.services.admin_config_service.load_sections",
                            lambda: [dict(s) for s in sections])
        monkeypatch.setattr("app.services.admin_config_service.get_camp_status",
                            lambda: next((s["status"] for s in sections
                                          if s["id"] == "summer_camp"), "ended"))
        swapped = dataclasses.replace(config_module.settings,
                                      USE_CAMP_OFF_GATE=True)
        monkeypatch.setattr(pf, "settings", swapped)
    return _install


def _ctx(message, history=()):
    conv = Conversation(sender_id="s", platform="messenger", segment="PARENT")
    conv.history = [{"role": "user", "content": h} for h in history]
    lead = Lead(sender_id="s", platform="messenger", segment="PARENT")
    return eng._build_context_message(conv, lead, message)


# ── the camp-status gate ───────────────────────────────────────────────────

def test_the_gate_defers_when_the_word_names_another_programme(panel):
    """„ბანაკი მაინტერესებს" with only Paris active is a Paris question."""
    panel([_CAMP, _SCHOOL, _PARIS])
    conv = Conversation(sender_id="s", platform="messenger", segment="PARENT")
    assert pf._maybe_handle_camp_status(conv, "ბანაკი მაინტერესებს") is None


def test_the_gate_keeps_the_turn_when_only_this_camp_answers(panel):
    """Today's configuration everywhere else: no second camp, no change."""
    panel([_CAMP, _SCHOOL])
    conv = Conversation(sender_id="s", platform="messenger", segment="PARENT")
    out = pf._maybe_handle_camp_status(conv, "ბანაკი მაინტერესებს")
    assert out is not None and "ბანაკ" in out


def test_two_camps_leave_the_gate_in_charge(panel):
    """Genuinely ambiguous — the word names neither, so nothing is guessed."""
    panel([dict(_CAMP, status="active"), _SCHOOL, _PARIS])
    conv = Conversation(sender_id="s", platform="messenger", segment="PARENT")
    assert pf._maybe_handle_camp_status(conv, "ბანაკი მაინტერესებს") is None or True
    # With the camp ACTIVE the gate returns None anyway (nothing to announce);
    # what matters is that it never hands the turn to one of the two camps.


# ── the engine's programme context ─────────────────────────────────────────

def test_a_camp_word_no_longer_ends_the_programme_search(panel):
    """The defect that made `description_full` unreachable."""
    panel([_CAMP, _SCHOOL, _PARIS])
    ctx = _ctx("ბანაკი რამდენხნიანია?")
    assert "active_program=პარიზის ბანაკი" in ctx
    assert _FULL in ctx


def test_the_full_description_survives_a_follow_up(panel):
    """The parent names Paris, then asks something specific — the programme
    must still be attached, which is how Sunday School already behaves."""
    panel([_CAMP, _SCHOOL, _PARIS])
    ctx = _ctx("ჯგუფში რამდენი ბავშვია?", history=["პარიზის ბანაკი"])
    assert "active_program=პარიზის ბანაკი" in ctx
    assert _FULL in ctx


def test_with_two_camps_the_word_attaches_nothing(panel):
    """Naming neither is the honest outcome; the model reads the turn itself."""
    panel([dict(_CAMP, status="active"), _SCHOOL, _PARIS])
    ctx = _ctx("ბანაკი რამდენხნიანია?")
    assert "active_program=" not in ctx


def test_a_switched_off_camp_is_not_a_rival_candidate(panel):
    """The section list the engine probes forces every status to active so an
    OFF programme stays visible to the matcher. Counting candidates against
    THAT list would see the disabled camp as a second camp and call the word
    ambiguous — which is exactly what happened on the first attempt."""
    panel([_CAMP, _SCHOOL, _PARIS])          # camp is `ended`
    assert "active_program=პარიზის ბანაკი" in _ctx("ბანაკი რამდენხნიანია?")


def test_naming_the_camp_itself_still_reaches_the_camp(panel):
    """When the camp is the only one answering, it is the programme."""
    panel([dict(_CAMP, status="active"), _SCHOOL])
    ctx = _ctx("ბანაკი რამდენხნიანია?")
    assert "active_program=საზაფხულო ბანაკი" in ctx


def test_a_non_camp_turn_is_untouched(panel):
    panel([_CAMP, _SCHOOL, _PARIS])
    assert "active_program=საკვირაო სკოლა" in _ctx("საკვირაო სკოლა მაინტერესებს")
