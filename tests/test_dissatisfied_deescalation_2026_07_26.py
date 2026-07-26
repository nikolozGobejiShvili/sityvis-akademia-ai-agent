"""Dissatisfied-customer de-escalation — converted to a SKILL (2026-07-26, plan-aligned).

Per the interceptors→tools plan, advisory de-escalation is NOT a substring interceptor — it is
the operator-editable `dissatisfied-customer` SKILL (`app/agent/skills/dissatisfied-customer.md`),
selected at the LLM layer when USE_SKILLS is on. parent_flow keeps only a thin ROUTING predicate
(`_msg_is_dissatisfaction`) so camp-status does NOT treat an insult that happens to name camp as a
camp question — it must reach the engine + skill (empathy + manager), not „camp ended".
"""
from unittest.mock import patch

from app.flows import parent_flow as pf
from app.services import skills_service
from app.models.conversation import Conversation
from app.models.lead import Lead


_INSULT = "საზიზღარი კომპანია გაქვთ თვენი ბანაკი მხოლოდ მდიდარი ბავშვებისთვის არის"


def _conv():
    c = Conversation(sender_id="s", platform="facebook")
    c.lead = Lead(sender_id="s", platform="facebook", segment="PARENT")
    return c


# --- the skill exists as operator-editable data ---

def test_skill_file_present_and_active():
    skills = {s["id"]: s for s in skills_service.load_skills()}
    assert "dissatisfied-customer" in skills
    sk = skills["dissatisfied-customer"]
    assert sk["status"] == "active"
    assert any("საზიზღარ" in t for t in sk["triggers"])
    assert "მენეჯერ" in sk["body"]           # offers the manager
    assert "558 67 47 33" in sk["body"]


def test_skill_selected_for_insult():
    picked = {s["id"] for s in skills_service.select_skills(_INSULT, "PARENT")}
    assert "dissatisfied-customer" in picked


def test_skill_not_selected_for_price_objection():
    picked = {s["id"] for s in skills_service.select_skills("ძვირია ეს ფასი", "PARENT")}
    assert "dissatisfied-customer" not in picked


# --- thin routing predicate (no handler, no flag) ---

def test_predicate_true_for_insult():
    assert pf._msg_is_dissatisfaction(_INSULT)


def test_predicate_false_for_price_objection():
    assert not pf._msg_is_dissatisfaction("ძვირია ეს ფასი")


def test_no_interceptor_or_flag_left():
    # the old substring interceptor + flag are gone (un-bloated parent_flow)
    assert not hasattr(pf, "_maybe_handle_dissatisfied_customer")
    from app.config import Settings
    assert not hasattr(Settings(), "USE_DISSATISFIED_DEESCALATION")


# --- camp-status routes an insult to the engine (not „camp ended") ---

def test_camp_status_defers_on_insult():
    conv = _conv()
    with patch("app.services.admin_config_service.get_camp_status", return_value="ended"):
        # an insult that names camp is NOT a camp question → None → engine + skill
        assert pf._maybe_handle_camp_status(conv, _INSULT) is None
        # a genuine camp question still gets the deterministic „camp ended"
        assert "დასრულებულია" in (pf._maybe_handle_camp_status(conv, "ბანაკი დამთავრდა?") or "")
