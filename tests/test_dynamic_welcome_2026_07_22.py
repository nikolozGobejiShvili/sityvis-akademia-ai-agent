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
    # #8 status governance: an ended section is not in get_active_sections → it
    # cannot reach the greeting. The camp is ended, so it is absent from the
    # seed and must be absent from the reply.
    #
    # With a single active program the greeting no longer lists it (client
    # decision 2026-09-03 — see `test_single_active_program_greets_without_a_menu`),
    # so what this test now pins is the half that still matters: the ENDED
    # program does not appear.
    _on(monkeypatch)
    _seed(monkeypatch, [{"name": "დისნეილენდის ტური", "status": "active"}])  # camp ended → absent
    out = parent_flow._maybe_static_welcome(_fresh(), "გამარჯობა")
    assert "ბანაკი" not in out
    assert "რით შემიძლია დაგეხმაროთ" in out


def test_single_active_program_greets_without_a_menu(monkeypatch):
    """One program on sale ⇒ no „choose one of:" list.

    Client feedback 2026-09-03: with a single active program the menu offered a
    choice of one („გვითხარით, რა გაინტერესებთ: — საკვირაო სკოლა"), which reads
    oddly. The opener becomes a plain question instead. Nothing is hardcoded to
    a program — this is driven purely by how many sections are active.
    """
    _on(monkeypatch)
    _seed(monkeypatch, [{"name": "საკვირაო სკოლა", "status": "active"}])
    out = parent_flow._maybe_static_welcome(_fresh(), "გამარჯობა")
    assert "რით შემიძლია დაგეხმაროთ" in out
    assert "გვითხარით, რა გაინტერესებთ" not in out
    assert "—" not in out  # no bullet list at all
    # The program is not named: with one on sale there is nothing to choose.
    assert "საკვირაო სკოლა" not in out


def test_second_active_program_brings_the_menu_back(monkeypatch):
    """The moment a second program goes active in the panel, the list returns.

    The one-program greeting must not become a permanent state that an operator
    has to undo in code.
    """
    _on(monkeypatch)
    _seed(monkeypatch, _TWO)
    out = parent_flow._maybe_static_welcome(_fresh(), "გამარჯობა")
    assert "გვითხარით, რა გაინტერესებთ" in out
    assert "რით შემიძლია დაგეხმაროთ" not in out
    for entry in _TWO:
        assert entry["name"] in out


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
