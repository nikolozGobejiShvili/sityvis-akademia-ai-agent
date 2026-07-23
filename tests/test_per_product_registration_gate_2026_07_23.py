"""Per-product registration gate for consultation booking (2026-07-23).

Live bug: once the camp ended, EVERY consultation booking was blocked with
„registration closed" — even for a dynamic product (Disneyland) — because the
slot-check / slot-listing / reschedule paths hard-coded `_is_camp_registration_open()`
instead of the booked product's own registration status. `_book_consultation`
already resolved per-product; the other three paths did not.

New helper `_registration_open_for_booking()` mirrors `_book_consultation`: resolve
the booking product and check ITS registration; fall back to camp when there is no
per-product context (USE_PER_PRODUCT_BOOKING off / camp booking) — byte-identical.
"""
from app.agent.tools import parent_tool_executor as pte
from app.agent.tools.parent_tool_executor import ParentToolExecutor
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import admin_config_service


def _executor():
    conv = Conversation(sender_id="x", platform="instagram", segment="PARENT")
    lead = Lead(sender_id="x", platform="instagram", segment="PARENT")
    return ParentToolExecutor(conv, lead, "x", "instagram", user_message="")


def test_no_per_product_falls_back_to_camp(monkeypatch):
    """No dynamic product resolved → camp registration (byte-identical)."""
    ex = _executor()
    monkeypatch.setattr(ex, "_resolve_booking_program_id", lambda: "")
    monkeypatch.setattr(pte, "_is_camp_registration_open", lambda: False)
    assert ex._registration_open_for_booking() is False
    monkeypatch.setattr(pte, "_is_camp_registration_open", lambda: True)
    assert ex._registration_open_for_booking() is True


def test_dynamic_program_uses_its_own_registration(monkeypatch):
    """THE FIX: a dynamic product's OPEN registration allows booking even when the
    camp registration is closed; its CLOSED registration blocks."""
    ex = _executor()
    monkeypatch.setattr(ex, "_resolve_booking_program_id", lambda: "disneyland")
    monkeypatch.setattr(pte, "_is_camp_registration_open", lambda: False)  # camp CLOSED

    monkeypatch.setattr(admin_config_service, "is_program_registration_open", lambda pid: True)
    assert ex._registration_open_for_booking() is True   # not blocked by camp

    monkeypatch.setattr(admin_config_service, "is_program_registration_open", lambda pid: False)
    assert ex._registration_open_for_booking() is False


def test_fail_open_to_camp_on_error(monkeypatch):
    """Any resolution error → camp registration (never a fault-driven block/allow)."""
    ex = _executor()

    def _boom():
        raise RuntimeError("resolve failed")

    monkeypatch.setattr(ex, "_resolve_booking_program_id", _boom)
    monkeypatch.setattr(pte, "_is_camp_registration_open", lambda: True)
    assert ex._registration_open_for_booking() is True
