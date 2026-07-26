"""Dynamic contact capture — USE_DYNAMIC_CONTACT_CAPTURE (2026-07-23).

In a dynamic (non-camp) program conversation the multi-turn contact turn
("მარიამი, 595111222") reaches the engine (via USE_PER_PRODUCT_BOOKING) but the
LLM sometimes only acknowledges the name/phone in text and skips the
save_lead_info tool, so the contact is never persisted (eval RC-CC1: turn2=[],
1/3 runs passed). When USE_DYNAMIC_CONTACT_CAPTURE is ON, the dynamic-programs
prompt suffix nudges the engine to call save_lead_info the moment a name/phone is
given (measured RC-CC1 1/3 -> 3/3, twice). Gated on top of USE_DYNAMIC_PROGRAMS;
OFF => the dynamic suffix is byte-identical.
"""
import dataclasses

from app.agent.llm import parent_llm_engine
from app.config import Settings
from app.services import admin_config_service

_TWO_PROGRAMS = [
    {"id": "summer_camp", "name": "საზაფხულო ბანაკი", "status": "active"},
    {"id": "robotics_club", "name": "რობოტიკის კლუბი", "status": "active"},
]


def _pin(monkeypatch, **flags):
    swapped = dataclasses.replace(parent_llm_engine.settings, **flags)
    monkeypatch.setattr(parent_llm_engine, "settings", swapped)
    monkeypatch.setattr(
        admin_config_service, "get_active_sections", lambda: list(_TWO_PROGRAMS),
    )


# --- flag default ---

def test_flag_defaults_false():
    assert Settings().USE_DYNAMIC_CONTACT_CAPTURE is False


def test_flag_parses_env(monkeypatch):
    monkeypatch.setenv("USE_DYNAMIC_CONTACT_CAPTURE", "true")
    assert Settings.from_env().USE_DYNAMIC_CONTACT_CAPTURE is True


# --- suffix content ---

def test_nudge_absent_when_flag_off(monkeypatch):
    _pin(monkeypatch, USE_DYNAMIC_PROGRAMS=True, USE_DYNAMIC_CONTACT_CAPTURE=False)
    suffix = parent_llm_engine._dynamic_programs_prompt_suffix()
    assert "list_programs" in suffix                 # base suffix present
    assert "save_lead_info" not in suffix            # nudge absent


def test_nudge_present_when_flag_on(monkeypatch):
    _pin(monkeypatch, USE_DYNAMIC_PROGRAMS=True, USE_DYNAMIC_CONTACT_CAPTURE=True)
    suffix = parent_llm_engine._dynamic_programs_prompt_suffix()
    assert "list_programs" in suffix                 # base suffix preserved
    assert "save_lead_info" in suffix                # nudge added
    assert "ტელეფონის ნომერს" in suffix


def test_nudge_extends_base_suffix(monkeypatch):
    """The ON suffix is a strict superset (starts-with) of the OFF suffix — the
    nudge is appended, the base text is not rewritten."""
    _pin(monkeypatch, USE_DYNAMIC_PROGRAMS=True, USE_DYNAMIC_CONTACT_CAPTURE=False)
    base = parent_llm_engine._dynamic_programs_prompt_suffix()
    _pin(monkeypatch, USE_DYNAMIC_PROGRAMS=True, USE_DYNAMIC_CONTACT_CAPTURE=True)
    extended = parent_llm_engine._dynamic_programs_prompt_suffix()
    assert extended.startswith(base)
    assert len(extended) > len(base)


def test_composes_with_isolation(monkeypatch):
    """Both flags on → both clauses present; order is isolation then nudge."""
    _pin(
        monkeypatch,
        USE_DYNAMIC_PROGRAMS=True,
        USE_PROGRAM_ISOLATION=True,
        USE_DYNAMIC_CONTACT_CAPTURE=True,
    )
    suffix = parent_llm_engine._dynamic_programs_prompt_suffix()
    assert "დამოუკიდებელია" in suffix                 # isolation clause
    assert "save_lead_info" in suffix                # contact nudge
    assert suffix.index("დამოუკიდებელია") < suffix.index("save_lead_info")


def test_no_suffix_when_dynamic_off(monkeypatch):
    """USE_DYNAMIC_PROGRAMS off short-circuits to '' — the nudge can never appear
    without the dynamic gate."""
    _pin(monkeypatch, USE_DYNAMIC_PROGRAMS=False, USE_DYNAMIC_CONTACT_CAPTURE=True)
    assert parent_llm_engine._dynamic_programs_prompt_suffix() == ""


# --- deterministic capture (2026-07-25): the hoist runs _maybe_handle_contact_collection
# so a bare phone in a per-product booking is captured without LLM discipline ---

def _contact_conv():
    from app.models.conversation import Conversation
    from app.models.lead import Lead
    c = Conversation(sender_id="x", platform="instagram", segment="PARENT")
    c.lead = Lead(sender_id="x", platform="instagram", segment="PARENT")
    c.pending_booking = {"source": "per_product"}   # satisfies in_contact_ctx
    return c


def test_bare_phone_captured_deterministically():
    from app.flows import parent_flow
    c = _contact_conv()
    resp = parent_flow._maybe_handle_contact_collection(c, "595999733")
    assert resp is not None                    # answered deterministically
    assert c.lead.phone == "595999733"         # captured, no LLM needed


def test_contact_collection_defers_on_question():
    from app.flows import parent_flow
    c = _contact_conv()
    # a question is a discussion turn — never hijacked (defers to engine)
    assert parent_flow._maybe_handle_contact_collection(c, "რა ღირს კონსულტაცია?") is None
