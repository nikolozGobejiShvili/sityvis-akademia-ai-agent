"""BUG (2026-07-26 live test #2): after a Disneyland (per-product) booking, a camp
question („ბანაკი დამთავრდა?") was HOISTED straight to the camp-centric LLM — the hoist
returns to the engine and BYPASSES _maybe_handle_camp_status — so the agent OFFERED camp
(asked the child's age → „ბანაკი ამ ასაკისთვის შესაბამისია"). The hoist now runs the
camp-off status gate first when USE_CAMP_OFF_GATE is on ⇒ camp-off is respected on the
dynamic/per-product path too. OFF ⇒ byte-identical (straight to the engine).
"""
import dataclasses

from app import config
from app.flows import parent_flow as pf
from app.services import admin_config_service
from app.models.conversation import Conversation
from app.models.lead import Lead


def _conv():
    c = Conversation(sender_id="s", platform="facebook")
    c.lead = Lead(sender_id="s", platform="facebook", segment="PARENT")
    return c


def _pin(monkeypatch, camp_off_gate, camp_status="ended"):
    monkeypatch.setattr(pf, "settings", dataclasses.replace(
        config.settings, USE_PARENT_LLM_ENGINE=True, USE_CAMP_OFF_GATE=camp_off_gate))
    # force the hoist to fire (as if a Disneyland per-product booking is active)
    monkeypatch.setattr(pf, "_is_active_per_product_booking", lambda conv: True)
    monkeypatch.setattr(admin_config_service, "get_camp_status", lambda: camp_status)
    # any reach into the LLM engine is a canary — the camp-off gate must beat it
    monkeypatch.setattr(pf, "_run_llm_engine_safely", lambda conv, msg: "ENGINE_SENTINEL")


def test_hoist_camp_off_returns_ended_not_engine(monkeypatch):
    _pin(monkeypatch, camp_off_gate=True)
    out = pf._handle_core(_conv(), "ბანაკი დამთავრდა?")
    assert "დასრულებულია" in out            # deterministic „camp ended"
    assert "ENGINE_SENTINEL" not in out      # the camp-centric LLM is NOT reached


def test_hoist_off_gate_goes_to_engine(monkeypatch):
    _pin(monkeypatch, camp_off_gate=False)
    out = pf._handle_core(_conv(), "ბანაკი დამთავრდა?")
    assert "ENGINE_SENTINEL" in out          # byte-identical: hoist → engine


def test_hoist_camp_active_goes_to_engine(monkeypatch):
    _pin(monkeypatch, camp_off_gate=True, camp_status="active")
    out = pf._handle_core(_conv(), "ბანაკი დამთავრდა?")
    assert "ENGINE_SENTINEL" in out          # camp active → camp_status None → engine


def test_hoist_non_camp_question_goes_to_engine(monkeypatch):
    _pin(monkeypatch, camp_off_gate=True)
    out = pf._handle_core(_conv(), "დისნეილენდი როდის იწყება?")
    assert "ENGINE_SENTINEL" in out          # not a camp question → engine


def test_hoist_camp_criticism_does_not_pitch_camp(monkeypatch):
    """Live test #2 step-34: an INSULT that names camp („თქვენი ბანაკი მხოლოდ მდიდარი
    ბავშვებისთვის…") made the camp-centric LLM DEFEND/pitch camp („ბანაკი 9–17 წლისაა,
    სადაც ბავშვები…"). It mentions ბანაკი, so the camp-off gate now answers „camp ended
    + alternatives" instead of routing to the pitch."""
    _pin(monkeypatch, camp_off_gate=True)
    insult = "საზიზღარი კომპანია გაქვთ თვენი ბანაკი მხოლოდ მდიდარი ბავშვებისთვის არის"
    out = pf._handle_core(_conv(), insult)
    assert "დასრულებულია" in out
    assert "ENGINE_SENTINEL" not in out      # the camp-centric LLM (pitch) is NOT reached
