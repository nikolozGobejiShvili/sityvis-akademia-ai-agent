"""Dissatisfied-customer de-escalation (USE_DISSATISFIED_DEESCALATION, 2026-07-26 live test).

A harsh complaint / insult about the company gets a short empathy + manager number + connect
offer, with NO camp and NO program mention. A plain price objection is NOT an insult (keeps
selling). Runs before camp-status / camp-intro / engine on BOTH the normal and the hoisted path.
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


_INSULT = "საზიზღარი კომპანია გაქვთ თვენი ბანაკი მხოლოდ მდიდარი ბავშვებისთვის არის"


def _pin_helper(monkeypatch, flag):
    monkeypatch.setattr(pf, "settings", dataclasses.replace(
        config.settings, USE_DISSATISFIED_DEESCALATION=flag))
    monkeypatch.setattr(admin_config_service, "get_manager_phone", lambda: "558 67 47 33")


# --- flag + helper ---

def test_flag_defaults_false():
    assert config.Settings().USE_DISSATISFIED_DEESCALATION is False


def test_off_returns_none(monkeypatch):
    _pin_helper(monkeypatch, False)
    assert pf._maybe_handle_dissatisfied_customer(_conv(), _INSULT) is None


def test_insult_gets_empathy_manager_no_camp_no_program(monkeypatch):
    _pin_helper(monkeypatch, True)
    out = pf._maybe_handle_dissatisfied_customer(_conv(), _INSULT)
    assert out is not None
    assert "ვწუხვარ" in out                    # empathy
    assert "558 67 47 33" in out               # manager number
    assert "დაგაკავშირებთ" in out              # connect offer
    assert "ბანაკ" not in out                  # NO camp
    assert "დისნეილენდ" not in out and "პროგრამ" not in out   # NO program


def test_price_objection_is_not_an_insult(monkeypatch):
    _pin_helper(monkeypatch, True)
    assert pf._maybe_handle_dissatisfied_customer(_conv(), "ძვირია ეს ფასი") is None


def test_normal_question_not_matched(monkeypatch):
    _pin_helper(monkeypatch, True)
    assert pf._maybe_handle_dissatisfied_customer(_conv(), "დისნეილენდი როდის იწყება?") is None


# --- integration: normal path (no hoist) ---

def test_handle_core_normal_path_deescalates(monkeypatch):
    monkeypatch.setattr(pf, "settings", dataclasses.replace(
        config.settings, USE_DISSATISFIED_DEESCALATION=True, USE_PARENT_LLM_ENGINE=False))
    monkeypatch.setattr(admin_config_service, "get_manager_phone", lambda: "558 67 47 33")
    out = pf._handle_core(_conv(), _INSULT)
    assert "ვწუხვარ" in out and "558 67 47 33" in out
    assert "9–17" not in out and "შესაბამისია" not in out   # no camp pitch


# --- integration: hoisted path (dynamic/per-product session) ---

def test_handle_core_hoisted_path_deescalates(monkeypatch):
    monkeypatch.setattr(pf, "settings", dataclasses.replace(
        config.settings, USE_DISSATISFIED_DEESCALATION=True, USE_PARENT_LLM_ENGINE=True))
    monkeypatch.setattr(pf, "_is_active_per_product_booking", lambda conv: True)  # hoist fires
    monkeypatch.setattr(admin_config_service, "get_manager_phone", lambda: "558 67 47 33")
    monkeypatch.setattr(pf, "_run_llm_engine_safely", lambda conv, msg: "ENGINE_SENTINEL")
    out = pf._handle_core(_conv(), _INSULT)
    assert "ვწუხვარ" in out and "558 67 47 33" in out
    assert "ENGINE_SENTINEL" not in out          # camp-centric LLM NOT reached
