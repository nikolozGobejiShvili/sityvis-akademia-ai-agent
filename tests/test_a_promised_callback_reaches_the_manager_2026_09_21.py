"""Live regression, client Page 2026-09-21 19:42 — the agent promised a
callback, the parent left her number, and the manager was never told.

The same conversation as `test_a_number_is_not_a_goodbye_2026_09_21`, one layer
deeper. Even with the trailing thanks removed — so the contact IS captured — no
mail reached the manager. Measured, both shapes:

    „593535551 nana madloba"  -> warm goodbye, nothing stored, no mail
    „593535551 nana"          -> name and phone stored, still no mail

What the agent had said one turn earlier was its own fixed message:

    „the manager's number is 599 00 11 20. You can contact them directly.
     If you prefer, leave your number and the manager will contact you."

That is a promise. The parent kept her side of it within twenty seconds.

The hand-off that actually mails the manager arms on
`_bot_in_sunday_school_collection`, which requires the flow's previous message
to BOTH name the programme AND ask for a contact. The manager-number answer
asks for a contact and names no programme, so it armed nothing, and the number
fell through to the consultation-booking path — which stores the contact and
asks which day suits, a question this parent had not asked and no manager ever
sees.

Compare, same day 13:31, where the mail did go out:

    out  „write your name and number and the manager will contact you"   <- armed
    in   „599558844 sopo"
    out  „thank you, I passed it to the manager"                          <- mailed

The only difference is which of the flow's two contact invitations was used.
One is wired to the hand-off, the other is not. This wires the second one, and
takes the invitation text from the message the flow sends rather than writing it
out again, so re-wording the message carries the detector with it.

Deliberately narrow, because this arming is the most regression-prone check in
the flow (see `_bot_in_sunday_school_collection`, 2026-09-12): it fires only on
the flow's OWN callback invitation as the most recent assistant turn, only when
no booking is in progress, and only for a turn that actually carries a number.
A model-written sentence never arms it, whatever it promises.
"""
from __future__ import annotations

import dataclasses

import pytest

from app import config as config_module
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.services import admin_config_service
from app.services import notification_service as ns
from app.services import sheets_service

SCHOOL = {"id": "sunday_school", "name": "საკვირაო სკოლა", "type": "kids_program",
          "status": "active", "age_min": 7, "age_max": 17,
          "price_text": "595 ლარი", "manager_contact": "599 00 11 20"}
CAMP_OFF = {"id": "summer_camp", "name": "საზაფხულო ბანაკი", "type": "camp",
            "status": "ended"}


@pytest.fixture
def live(monkeypatch):
    """The panel as the client runs it, with every outbound channel captured."""
    monkeypatch.setattr(
        admin_config_service, "get_active_sections", lambda *a, **k: [dict(SCHOOL)])
    monkeypatch.setattr(
        admin_config_service, "load_sections",
        lambda *a, **k: [dict(CAMP_OFF), dict(SCHOOL)])
    monkeypatch.setattr(
        admin_config_service, "get_section",
        lambda pid, *a, **k: (
            dict(SCHOOL) if pid == "sunday_school" else dict(CAMP_OFF)))
    monkeypatch.setattr(
        admin_config_service, "is_camp_registration_open", lambda *a, **k: False)
    monkeypatch.setattr(
        admin_config_service, "get_camp_status", lambda *a, **k: "ended")
    monkeypatch.setattr(
        admin_config_service, "get_manager_phone", lambda *a, **k: "599 00 11 20")
    settings = dataclasses.replace(
        config_module.settings,
        USE_DYNAMIC_PROGRAMS=True, USE_PROGRAM_ISOLATION=True,
        USE_PARENT_LLM_ENGINE=True, USE_DYNAMIC_WELCOME=True,
        USE_RESERVED_PROGRAMS_DYNAMIC=True, USE_PER_PRODUCT_BOOKING=True,
        USE_CONSULTATION_PROGRAM_NAME=True,
    )
    monkeypatch.setattr(parent_flow, "settings", settings)
    monkeypatch.setattr(ns, "settings", settings)
    monkeypatch.setattr(
        parent_flow, "_run_llm_engine_safely", lambda c, m: "[ENGINE]")

    sent: list[dict] = []
    monkeypatch.setattr(
        ns, "_send_email",
        lambda subject, body, **k: (
            sent.append({"subject": subject, "body": body}) or True))
    monkeypatch.setattr(ns, "_send_manager_whatsapp", lambda *a, **k: False)
    monkeypatch.setattr(
        sheets_service, "log_sunday_school_lead", lambda *a, **k: True)
    # The hand-off is idempotent per sender for the life of the process.
    parent_flow._sunday_school_notified_senders.clear()
    return sent


def _conversation(invitation: str, sender: str = "nana") -> Conversation:
    conv = Conversation(sender_id=sender, platform="messenger")
    conv.segment = "PARENT"
    conv.state = "DONE"
    conv.history = [
        {"role": "user",
         "content": "მე დავუკავშირდები. მადლობა. 12 წლის რომ დავარეგისტრირო"},
        {"role": "assistant", "content": invitation},
    ]
    return conv


def _callback_invitation() -> str:
    """Exactly what the flow sends — rendered, never retyped."""
    return parent_flow._render_manager_number_answer(None)


# --------------------------------------------------------------------------
# The live fault.
# --------------------------------------------------------------------------

def test_the_promised_callback_mails_the_manager(live):
    conv = _conversation(_callback_invitation())
    parent_flow.handle(conv, "593535551 ნანა")
    assert live, "the parent left her number and no mail reached the manager"


def test_the_mail_carries_the_name_and_the_number(live):
    conv = _conversation(_callback_invitation())
    parent_flow.handle(conv, "593535551 ნანა")
    body = live[0]["body"]
    assert "593535551" in body
    assert "ნანა" in body


def test_the_mail_names_the_programme_not_the_closed_camp(live):
    """Together with the 2026-09-21 mail fix: one programme on sale, so that is
    what the manager is told — never the camp that is switched off."""
    conv = _conversation(_callback_invitation())
    parent_flow.handle(conv, "593535551 ნანა")
    assert "ბანაკ" not in live[0]["body"]


def test_the_parent_is_told_it_was_passed_on(live):
    conv = _conversation(_callback_invitation())
    reply = str(parent_flow.handle(conv, "593535551 ნანა"))
    assert "მენეჯერ" in reply
    assert "რომელი დღე და დრო" not in reply


def test_the_merged_live_turn_works_too(live):
    """The turn as the buffer actually delivered it, thanks and all."""
    conv = _conversation(_callback_invitation())
    parent_flow.handle(conv, "593535551 ნანა მადლობა💚")
    assert live


# --------------------------------------------------------------------------
# What must not move.
# --------------------------------------------------------------------------

def test_a_number_with_no_invitation_is_left_where_it_was(live):
    """No promise was made, so nothing is owed. An informational answer that
    names the programme but asks for nothing must not start mailing the
    manager — that is the 2026-09-12 rule, restated for this arming."""
    conv = _conversation("საკვირაო სკოლა 3-თვიანი პროგრამაა, 12 შეხვედრა.")
    reply = str(parent_flow.handle(conv, "593535551 ნანა"))
    assert not live
    assert "გადავეცი" not in reply


def test_a_self_call_answer_promises_nothing_and_arms_nothing(live):
    """„I will call them myself" — the flow gives the number and asks for
    none, so a number arriving later is not an answer to an invitation."""
    invitation = parent_flow._render_manager_number_answer(None, self_call=True)
    assert "დატოვეთ თქვენი ნომერი" not in invitation
    conv = _conversation(invitation, sender="selfcall")
    parent_flow.handle(conv, "593535551 ნანა")
    assert not live


def test_a_confirmed_slot_waiting_on_a_contact_is_never_intercepted(live):
    """The contact completes the booking — it is not a callback request."""
    conv = _conversation(_callback_invitation(), sender="booking")
    conv.pending_booking = {"requested_datetime_iso": "2030-01-01T10:00:00",
                            "user_confirmed_datetime": True}
    parent_flow.handle(conv, "593535551 ნანა")
    assert not live


def test_a_half_built_booking_is_never_intercepted(live):
    """Not yet confirmed, so the confirmed-slot defer does not cover it — the
    booking is still mid-build and owns the contact turn."""
    conv = _conversation(_callback_invitation(), sender="halfbooking")
    conv.pending_booking = {"requested_datetime_iso": "2030-01-01T10:00:00"}
    parent_flow.handle(conv, "593535551 ნანა")
    assert not live


def test_the_two_fragments_arriving_apart_still_reach_the_manager(live):
    """The debounce usually merges them, but it does not have to."""
    conv = _conversation(_callback_invitation(), sender="split")
    first = str(parent_flow.handle(conv, "593535551"))
    assert not live, "one half is not a hand-off"
    conv.history.append({"role": "user", "content": "593535551"})
    conv.history.append({"role": "assistant", "content": first})
    parent_flow.handle(conv, "ნანა")
    assert live


def test_a_model_written_promise_never_arms_the_handoff(live):
    """The 2026-09-12 rule: only the flow's OWN fixed messages arm a contact
    collection. A sentence the model wrote — however it phrases a callback —
    must not."""
    conv = _conversation(
        "რა თქმა უნდა! დატოვეთ ნომერი და ჩვენი მენეჯერი აუცილებლად "
        "დაგირეკავთ უახლოეს დროში 💙", sender="model")
    parent_flow.handle(conv, "593535551 ნანა")
    assert not live


def test_the_sunday_school_handoff_is_unchanged(live):
    """The invitation that already worked still works — the programme answer
    WITH its offer tail, which is what the flow actually sends."""
    conv = _conversation(parent_flow._render_sunday_school_answer(), sender="ss")
    reply = str(parent_flow.handle(conv, "599558844 სოფო"))
    assert live
    assert "მენეჯერ" in reply
