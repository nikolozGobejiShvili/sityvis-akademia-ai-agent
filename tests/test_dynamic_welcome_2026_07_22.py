"""R2 — data-driven welcome menu (USE_DYNAMIC_WELCOME). Flag OFF ⇒ the static
PARENT_WELCOME byte-for-byte; flag ON ⇒ the greeting lists the ACTIVE admin
programs by name; ended/hidden drop (via get_active_sections); fail-safe to the
static menu when there are no active sections."""
import dataclasses

import app.config as config_module
from app.flows import parent_flow
from app.models.conversation import Conversation
from data.prompts import PARENT_WELCOME

_TWO = [{"name": "ბავშვების საზაფხულო ბანაკი", "status": "active"},
        {"name": "დისნეილენდის ტური", "status": "active"}]


def _fresh():
    c = Conversation(sender_id="w", platform="messenger", segment="PARENT")
    c.state = "START"
    return c


def _on(monkeypatch):
    monkeypatch.setattr(parent_flow, "settings",
                        dataclasses.replace(config_module.settings, USE_DYNAMIC_WELCOME=True))


def _seed(monkeypatch, sections):
    import app.services.admin_config_service as acs
    monkeypatch.setattr(acs, "get_active_sections", lambda: [dict(s) for s in sections])


# -- builder ---------------------------------------------------------------
def test_builder_lists_active_program_names(monkeypatch):
    _seed(monkeypatch, _TWO)
    out = parent_flow._build_active_programs_welcome()
    assert out.startswith("გამარჯობა.")
    assert "— ბავშვების საზაფხულო ბანაკი" in out
    assert "— დისნეილენდის ტური" in out
    assert out.index("ბანაკი") < out.index("დისნეილენდის")  # section order


def test_builder_none_when_no_active_sections(monkeypatch):
    _seed(monkeypatch, [])
    assert parent_flow._build_active_programs_welcome() is None


# -- flag OFF byte-identity (the critical guarantee) -----------------------
def test_flag_off_returns_static_menu_byte_identical(monkeypatch):
    _seed(monkeypatch, _TWO)  # even with seeded sections, OFF must ignore them
    out = parent_flow._maybe_static_welcome(_fresh(), "გამარჯობა")
    assert out == PARENT_WELCOME.strip()


# -- flag ON ---------------------------------------------------------------
def test_flag_on_returns_dynamic_menu(monkeypatch):
    _on(monkeypatch)
    _seed(monkeypatch, _TWO)
    out = parent_flow._maybe_static_welcome(_fresh(), "გამარჯობა")
    assert "დისნეილენდის ტური" in out
    assert "ზრდასრულთა კულტურული საღამოები" not in out  # not the hardcoded line


def test_flag_on_excludes_ended_program(monkeypatch):
    # #8 status governance: an ended section is not in get_active_sections → not in the menu.
    _on(monkeypatch)
    _seed(monkeypatch, [{"name": "დისნეილენდის ტური", "status": "active"}])  # camp ended → absent
    out = parent_flow._maybe_static_welcome(_fresh(), "გამარჯობა")
    assert "დისნეილენდის ტური" in out
    assert "ბანაკი" not in out


def test_flag_on_failsafe_to_static_when_empty(monkeypatch):
    _on(monkeypatch)
    _seed(monkeypatch, [])
    out = parent_flow._maybe_static_welcome(_fresh(), "გამარჯობა")
    assert out == PARENT_WELCOME.strip()  # never empty


def test_explicit_camp_intent_still_yields_both_flag_states(monkeypatch):
    _seed(monkeypatch, _TWO)
    assert parent_flow._maybe_static_welcome(_fresh(), "საზაფხულო ბანაკი მაინტერესებს") is None
    _on(monkeypatch)
    assert parent_flow._maybe_static_welcome(_fresh(), "საზაფხულო ბანაკი მაინტერესებს") is None


# -- the UNCLEAR_ROUTING greeting path (the one a bare „გამარჯობა" actually hits) --
def test_conversation_service_unclear_gate_flag_off_byte_identical():
    import app.services.conversation_service as cs
    from data.prompts import UNCLEAR_ROUTING
    fb = UNCLEAR_ROUTING.format(company_name=config_module.settings.COMPANY_NAME).strip()
    assert cs._maybe_dynamic_welcome(fb) == fb  # flag off (conftest) ⇒ unchanged


def test_conversation_service_unclear_gate_flag_on_dynamic(monkeypatch):
    import app.services.conversation_service as cs
    from data.prompts import UNCLEAR_ROUTING
    monkeypatch.setattr(cs, "settings",
                        dataclasses.replace(config_module.settings, USE_DYNAMIC_WELCOME=True))
    _seed(monkeypatch, _TWO)
    fb = UNCLEAR_ROUTING.format(company_name=config_module.settings.COMPANY_NAME).strip()
    out = cs._maybe_dynamic_welcome(fb)
    assert "დისნეილენდის ტური" in out and out != fb
