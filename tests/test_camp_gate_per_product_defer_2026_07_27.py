"""Live test #6 (2026-07-27): a follow-up money/payment question in an active NON-camp
program conversation was answered with the CAMP-off message.

„წინასწარი გადასახადი არის თუ ერთიანად უნდა გადავიხადო?" during a Disneyland chat →
„ბანაკის მიმდინარე ნაკადები დასრულებულია…". Root: `გადასახად` is a camp price marker, the
message doesn't re-name a program, so the camp-status gate claimed it. The gate now defers to
the engine when the lead is tagged to an active non-camp program (per-product context) AND the
message does NOT explicitly name camp. Gated by USE_PROGRAM_ISOLATION (+ USE_PER_PRODUCT_BOOKING
inside `_is_active_per_product_booking`) ⇒ OFF is byte-identical.
"""
import dataclasses
from unittest.mock import patch

from app import config
from app.flows import parent_flow as pf
from app.services import admin_config_service as acs
from app.models.conversation import Conversation
from app.models.lead import Lead

_PAY = "წინასწარი გადასახადი არის თუ ერთიანად უნდა გადავიხადო?"
_RESERVED = {"summer_camp", "sunday_school", "adult_events"}


def _conv(program_id=""):
    c = Conversation(sender_id="s", platform="facebook")
    c.lead = Lead(sender_id="s", platform="facebook", segment="PARENT")
    c.lead.program_id = program_id
    return c


def _run(message, program_id, *, isolation):
    sw = dataclasses.replace(
        config.settings, USE_PROGRAM_ISOLATION=isolation, USE_PER_PRODUCT_BOOKING=True)
    with patch.object(pf, "settings", sw), \
            patch.object(acs, "get_camp_status", return_value="ended"), \
            patch.object(pf, "reserved_program_ids", return_value=_RESERVED):
        return pf._maybe_handle_camp_status(_conv(program_id), message)


def test_off_is_byte_identical():
    # ISOLATION off ⇒ payment still hits the camp-off gate (unchanged)
    assert _run(_PAY, "disneyland_tour", isolation=False) is not None


def test_payment_in_dynamic_context_defers_to_engine():
    # the live bug: payment question during a tagged Disneyland conversation → defer
    assert _run(_PAY, "disneyland_tour", isolation=True) is None


def test_payment_without_context_still_camp_off():
    # no per-product tag ⇒ a bare money question is genuinely camp → camp-off answer
    assert _run(_PAY, "", isolation=True) is not None


def test_explicit_camp_word_still_answered_even_when_tagged():
    # naming camp explicitly must still get the camp status, even mid-Disneyland chat
    assert _run("ბანაკის გადასახადი რა არის?", "disneyland_tour", isolation=True) is not None


def test_reserved_program_tag_does_not_defer():
    # a reserved (camp/SS/adult) program_id is not a per-product context → no defer
    assert _run(_PAY, "summer_camp", isolation=True) is not None
