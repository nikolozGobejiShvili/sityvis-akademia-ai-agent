"""Which of a programme's two descriptions leads the answer (2026-09-05).

Both `description_short` and `description_full` travel with the turn, and
nothing ranked them, so the model merged the two: the opening answer began with
the operator's newly-written `description_short` and then continued into
`description_full`'s detail. The operator's intention is that the short one IS
the opening answer and the long one is held back for follow-up questions.

The fix states the ROLE of each field, not the text of either — no wording is
fixed, no answer is approved, and the model still writes the reply. It is keyed
on the field names, so it holds for any programme the operator adds. These tests
use a non-reserved id for exactly that reason: nothing here is specific to
Sunday School.
"""
from app.agent.llm import parent_llm_engine as eng
from app.models.conversation import Conversation
from app.models.lead import Lead

_PRIORITY_KEY = "program_facts_priority="
_NAME = "რობოტიკის სტუდია"


def _section(**over):
    base = {
        "id": "robotics_club",
        "name": _NAME,
        "type": "kids_program",
        "status": "active",
        "price_text": "450 ლარი",
        "description_short": "მოკლე აღწერა პროგრამის შესახებ.",
        "description_full": "ვრცელი აღწერა დეტალებით და ჯგუფებით.",
    }
    base.update(over)
    return base


def _context(monkeypatch, section, message=f"{_NAME} მაინტერესებს"):
    monkeypatch.setattr("app.services.admin_config_service.load_sections",
                        lambda: [section])
    monkeypatch.setattr("app.services.admin_config_service.get_active_sections",
                        lambda: [section])
    conv = Conversation(sender_id="s", platform="messenger", segment="PARENT")
    lead = Lead(sender_id="s", platform="messenger", segment="PARENT")
    return eng._build_context_message(conv, lead, message)


def test_both_descriptions_travel_and_the_short_one_is_marked_as_opening(monkeypatch):
    out = _context(monkeypatch, _section())
    assert f"active_program={_NAME}" in out
    assert "მოკლე აღწერა" in out          # description_short is available
    assert "ვრცელი აღწერა" in out         # so is description_full
    assert _PRIORITY_KEY in out
    assert "description_short is the opening" in out


def test_no_priority_line_when_only_one_description_exists(monkeypatch):
    """With one description there is nothing to rank — the hint would be noise."""
    only_short = _context(monkeypatch, _section(description_full=""))
    assert "მოკლე აღწერა" in only_short
    assert _PRIORITY_KEY not in only_short

    only_full = _context(monkeypatch, _section(description_short=""))
    assert "ვრცელი აღწერა" in only_full
    assert _PRIORITY_KEY not in only_full


def test_no_text_is_hardcoded(monkeypatch):
    """The hint names the FIELDS, never their contents — changing the operator's
    wording must change the facts and leave the hint identical."""
    a = _context(monkeypatch, _section())
    b = _context(monkeypatch, _section(
        description_short="სულ სხვა მოკლე ტექსტი.",
        description_full="სულ სხვა ვრცელი ტექსტი.",
    ))
    hint = lambda s: [c for c in s.split("; ") if c.startswith(_PRIORITY_KEY)]
    assert hint(a) == hint(b) != []
    assert "სულ სხვა მოკლე ტექსტი." in b
    assert "მოკლე აღწერა" not in b


def test_switched_off_program_sends_neither_description_nor_hint(monkeypatch):
    """A programme the operator disables stops travelling, hint included."""
    off = _section(status="coming_soon")
    monkeypatch.setattr("app.services.admin_config_service.load_sections", lambda: [off])
    monkeypatch.setattr("app.services.admin_config_service.get_active_sections", lambda: [])
    conv = Conversation(sender_id="s", platform="messenger", segment="PARENT")
    lead = Lead(sender_id="s", platform="messenger", segment="PARENT")
    out = eng._build_context_message(conv, lead, f"{_NAME} მაინტერესებს")
    assert "მოკლე აღწერა" not in out
    assert _PRIORITY_KEY not in out
