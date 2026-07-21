"""Phase 3 pilot — objection domain (USE_OBJECTION_ENGINE_ROUTING).

The flag adds ONE term to the decline/objection override in
`_maybe_handle_decline_engine`: a HESITATION phrase co-occurring with an
objection marker defers to the engine (like a decline+objection already does).
Flag OFF ⇒ byte-identical. Every other decline guardrail is untouched — proven
here by asserting flag-ON == flag-OFF for every non-(hesitation+objection)
message.
"""
import dataclasses

import pytest

from app import config
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead


def _conv(pending=False):
    c = Conversation(sender_id="op-u", platform="instagram")
    c.history.append({"role": "assistant", "content": "_prior"})
    c.lead = Lead(sender_id="op-u", platform="instagram", segment="PARENT",
                  child_age="14")
    if pending:
        c.pending_booking = {"datetime_iso": "2030-01-01T10:00:00"}
    return c


def _handle(monkeypatch, message, *, flag, pending=False):
    swapped = dataclasses.replace(config.settings, USE_OBJECTION_ENGINE_ROUTING=flag)
    monkeypatch.setattr(parent_flow, "settings", swapped)
    return parent_flow._maybe_handle_decline_engine(_conv(pending=pending), message)


# -- the pilot behavior: hesitation + objection --------------------------------

def test_hesitation_objection_defers_to_engine_when_flag_on(monkeypatch):
    assert _handle(monkeypatch, "მოვიფიქრებ, ძვირია", flag=True) is None


def test_hesitation_objection_still_canned_when_flag_off(monkeypatch):
    out = _handle(monkeypatch, "მოვიფიქრებ, ძვირია", flag=False)
    assert out is not None and "დაფიქრდით" in out   # today's canned will-think reply


# -- guardrails: flag ONLY changes hesitation+objection; everything else
#    must be byte-identical ON vs OFF (my change adds only the is_will_think term)

@pytest.mark.parametrize("message", [
    "არა მადლობა",                              # plain decline → still declines
    "არ მინდა, მაგრამ ბავშვი ძალიან მინდა",     # decline+objection → already defers
    "არ მინდა, მენეჯერის ნომერი მომწერეთ",      # manager-contact inside decline
    "არ მინდა?",                                # decline + question
    "ძვირია",                                   # bare objection (defers before the gate)
    "მადლობა, კარგია",                          # neither decline nor hesitation
])
def test_guardrail_messages_identical_on_vs_off(monkeypatch, message):
    off = _handle(monkeypatch, message, flag=False)
    on = _handle(monkeypatch, message, flag=True)
    assert on == off, f"flag changed a non-(hesitation+objection) turn: {message!r}"


def test_hard_decline_still_clears_pending_booking_both_flags(monkeypatch):
    for flag in (False, True):
        swapped = dataclasses.replace(config.settings, USE_OBJECTION_ENGINE_ROUTING=flag)
        monkeypatch.setattr(parent_flow, "settings", swapped)
        conv = _conv(pending=True)
        out = parent_flow._maybe_handle_decline_engine(conv, "არ მინდა")
        assert out is not None                      # canned decline close
        assert conv.pending_booking is None         # hard decline cleared it


# -- Task 2: objection eval coverage (>=6 cases incl. the hesitation gap) -----

def test_objection_domain_has_at_least_six_cases_incl_ob3():
    from evals import cases
    obj = [c for c in cases.CASES if getattr(c, "domain", "") == "objection"]
    ids = {c.id for c in obj}
    assert len(obj) >= 6, f"objection coverage too thin: {sorted(ids)}"
    assert "OB3" in ids, "the hesitation-routing gap case OB3 is missing"
