"""Sunday School manager handoff + false-success fix (2026-06-22).

Sunday School is planned for July and NOT fully available. A user who asks
about it must not get invented price/dates/program; if they want details /
a manager callback the agent collects name + phone and dispatches an
EMAIL-ONLY manager handoff — NO Calendar consultation, NO WhatsApp — and
only confirms „გადავეცი" on a REAL email send.

Also fixes the false-success bug: `_request_manager_callback` previously
returned success=True even when the manager email never dispatched.

All offline / mocked — no real OpenAI / Meta / Calendar / Sheets / email /
network. The conftest nets block real SMTP / Meta too.
"""
from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import pytest

import app.config as config_module
from app.agent.tools import parent_tool_executor
from app.agent.tools.parent_tool_executor import ParentToolExecutor
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import (
    calendar_service,
    messenger_service,
    notification_service,
    openai_service,
    sheets_service,
)

TOOL_REQUEST_MANAGER_CALLBACK = "request_manager_callback"


@pytest.fixture(autouse=True)
def _reset_state():
    from app.services import conversation_service
    parent_tool_executor.reset_state()
    parent_flow._sunday_school_notified_senders.clear()
    parent_flow.invalid_phone_retries.clear()
    conversation_service.conversations.clear()
    yield
    parent_tool_executor.reset_state()
    parent_flow._sunday_school_notified_senders.clear()
    conversation_service.conversations.clear()


@pytest.fixture
def engine_on(monkeypatch):
    swapped = dataclasses.replace(config_module.settings, USE_PARENT_LLM_ENGINE=True)
    monkeypatch.setattr(parent_flow, "settings", swapped)
    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})


def _conv(sender_id="ss-u"):
    conv = Conversation(sender_id=sender_id, platform="instagram", segment="PARENT")
    conv.lead = Lead(sender_id=sender_id, platform="instagram", segment="PARENT")
    return conv


def _step(conv, msg):
    """Call the Sunday-school interceptor and mirror the turn into history so
    the next turn is recognised as continued collection (like the live flow)."""
    conv.history.append({"role": "user", "content": msg})
    out = parent_flow._maybe_handle_sunday_school(conv, msg)
    if out is not None:
        conv.history.append({"role": "assistant", "content": out})
    return out


def _boom(**kw):
    raise AssertionError("engine must NOT be consulted on the deterministic SS path")


# ===========================================================================
# notification_service.notify_sunday_school_handoff — EMAIL ONLY (#6)
# ===========================================================================


def test_sunday_school_email_only_no_whatsapp(monkeypatch):
    email = SimpleNamespace(called=0)
    wa = SimpleNamespace(called=0)
    monkeypatch.setattr(notification_service, "_send_email",
                        lambda **k: (setattr(email, "called", email.called + 1) or True))
    monkeypatch.setattr(notification_service, "_send_manager_whatsapp",
                        lambda text: (setattr(wa, "called", wa.called + 1) or True))
    lead = Lead(sender_id="x", platform="instagram", segment="PARENT",
                name="ნიკოლოზი", phone="595999733")
    ok = notification_service.notify_sunday_school_handoff(lead)
    assert ok is True
    assert email.called == 1            # email sent
    assert wa.called == 0               # WhatsApp NEVER attempted


def test_sunday_school_email_failure_returns_false(monkeypatch):
    monkeypatch.setattr(notification_service, "_send_email", lambda **k: False)
    lead = Lead(sender_id="x", platform="instagram", segment="PARENT",
                name="ნიკოლოზი", phone="595999733")
    assert notification_service.notify_sunday_school_handoff(lead) is False


# ===========================================================================
# send_manager_notification is now EMAIL-GATED (#11)
# ===========================================================================


def test_send_manager_notification_email_only_success_when_whatsapp_off(monkeypatch):
    """Email succeeds, WhatsApp fails (unconfigured in prod) → still True."""
    monkeypatch.setattr(notification_service, "_send_email", lambda **k: True)
    monkeypatch.setattr(notification_service, "_send_manager_whatsapp", lambda text: False)
    lead = Lead(sender_id="x", platform="instagram", segment="PARENT",
                name="ნიკო", phone="595999733")
    assert notification_service.send_manager_notification(lead, "s") is True


def test_send_manager_notification_false_when_email_fails(monkeypatch):
    monkeypatch.setattr(notification_service, "_send_email", lambda **k: False)
    monkeypatch.setattr(notification_service, "_send_manager_whatsapp", lambda text: True)
    lead = Lead(sender_id="x", platform="instagram", segment="PARENT",
                name="ნიკო", phone="595999733")
    assert notification_service.send_manager_notification(lead, "s") is False


# ===========================================================================
# _request_manager_callback false-success fix (#10)
# ===========================================================================


def _callback_executor(monkeypatch):
    monkeypatch.setattr(sheets_service, "create_lead", lambda lead: True)
    monkeypatch.setattr(openai_service, "generate_summary", lambda h: "x")
    conv = _conv("cb-u")
    conv.lead.name, conv.lead.phone = "ნიკოლოზი", "599999733"
    return ParentToolExecutor(conversation=conv, lead=conv.lead,
                              sender_id="cb-u", platform="instagram")


def test_request_manager_callback_no_false_success_on_dispatch_failure(monkeypatch):
    monkeypatch.setattr(notification_service, "send_manager_notification",
                        lambda lead, summary: False)         # email failed
    ex = _callback_executor(monkeypatch)
    res = ex.execute(TOOL_REQUEST_MANAGER_CALLBACK, {})
    assert res.get("success") is not True
    assert res.get("manager_notified") is not True


def test_request_manager_callback_success_on_real_dispatch(monkeypatch):
    monkeypatch.setattr(notification_service, "send_manager_notification",
                        lambda lead, summary: True)
    ex = _callback_executor(monkeypatch)
    res = ex.execute(TOOL_REQUEST_MANAGER_CALLBACK, {})
    assert res["success"] is True
    assert res["manager_notified"] is True


# ===========================================================================
# Sunday-school flow — parent_flow._maybe_handle_sunday_school
# ===========================================================================


def test_interest_coming_soon_no_details_offers_manager(monkeypatch):   # (#1, updated 2026-06-27)
    # Coming-soon contract: NO launch detail revealed, NO name/phone demand —
    # just say details are being finalised and OFFER a manager connection.
    _set_ss_config(monkeypatch, status="coming_soon",
                   availability_text="საკვირაო სკოლა ივლისში დაემატება.",
                   details_text="დეტალები ზუსტდება", handoff_enabled=True)
    conv = _conv()
    out = _step(conv, "საკვირაო სკოლა მაინტერესებს")
    assert out is not None
    assert "ივლის" not in out              # launch month NOT revealed
    assert "მენეჯერ" in out                # offers a manager connection
    # must NOT invent camp facts
    assert "2150" not in out
    assert "ამბასადორ" not in out
    assert "9–17" not in out and "9-17" not in out
    assert (conv.lead.name or "") == ""    # topic words not captured as a name


def test_phone_then_name_triggers_email_handoff(monkeypatch):        # (#2,#3)
    calls = []
    monkeypatch.setattr(notification_service, "notify_sunday_school_handoff",
                        lambda lead: calls.append((lead.name, lead.phone)) or True)
    monkeypatch.setattr(sheets_service, "log_sunday_school_lead",
                        lambda *a, **k: True)
    conv = _conv()
    _step(conv, "საკვირაო სკოლა მაინტერესებს")
    out_phone = _step(conv, "595999733")
    assert "სახელი" in out_phone and calls == []         # asks name, no dispatch yet
    out_name = _step(conv, "ნიკოლოზი")
    assert calls == [("ნიკოლოზი", "595999733")]          # dispatched ONCE
    assert out_name == parent_flow._SUNDAY_SCHOOL_SUCCESS
    assert "გადავეცი" in out_name


def test_email_failure_no_false_success(monkeypatch):               # (#4)
    monkeypatch.setattr(notification_service, "notify_sunday_school_handoff",
                        lambda lead: False)
    monkeypatch.setattr(sheets_service, "log_sunday_school_lead", lambda *a, **k: True)
    conv = _conv()
    _step(conv, "საკვირაო სკოლა მაინტერესებს")
    _step(conv, "595999733")
    out = _step(conv, "ნიკოლოზი")
    assert out == parent_flow._SUNDAY_SCHOOL_FAIL
    assert "გადავეცი" not in out
    assert conv.sender_id not in parent_flow._sunday_school_notified_senders


def test_no_calendar_booking(monkeypatch):                          # (#5)
    monkeypatch.setattr(notification_service, "notify_sunday_school_handoff", lambda lead: True)
    monkeypatch.setattr(sheets_service, "log_sunday_school_lead", lambda *a, **k: True)
    for name in ("book_slot", "check_slot_available", "get_free_slots"):
        if hasattr(calendar_service, name):
            monkeypatch.setattr(calendar_service, name,
                                lambda *a, **k: pytest.fail(f"calendar.{name} must not run"))
    conv = _conv()
    _step(conv, "საკვირაო სკოლა მაინტერესებს")
    _step(conv, "595999733")
    assert _step(conv, "ნიკოლოზი") == parent_flow._SUNDAY_SCHOOL_SUCCESS


def test_does_not_write_booking_aq_sheet(monkeypatch):              # (#7)
    monkeypatch.setattr(notification_service, "notify_sunday_school_handoff", lambda lead: True)
    monkeypatch.setattr(sheets_service, "log_sunday_school_lead", lambda *a, **k: True)
    for name in ("save_lead", "create_lead", "append_lead", "_worksheet"):
        monkeypatch.setattr(sheets_service, name,
                            lambda *a, **k: pytest.fail(f"booking sheet {name} must not run"))
    conv = _conv()
    _step(conv, "საკვირაო სკოლა მაინტერესებს")
    _step(conv, "595999733")
    assert _step(conv, "ნიკოლოზი") == parent_flow._SUNDAY_SCHOOL_SUCCESS


def test_sunday_school_sheet_logged_independently(monkeypatch):     # (#8)
    logged = []
    monkeypatch.setattr(notification_service, "notify_sunday_school_handoff", lambda lead: True)
    monkeypatch.setattr(sheets_service, "log_sunday_school_lead",
                        lambda lead, **k: logged.append(k.get("notification_status")) or True)
    conv = _conv()
    _step(conv, "საკვირაო სკოლა მაინტერესებს")
    _step(conv, "595999733")
    _step(conv, "ნიკოლოზი")
    assert logged == ["sent"]


def test_sheet_failure_does_not_block_email_success(monkeypatch):   # (#9)
    monkeypatch.setattr(notification_service, "notify_sunday_school_handoff", lambda lead: True)
    def _raise(*a, **k):
        raise RuntimeError("sheets down")
    monkeypatch.setattr(sheets_service, "log_sunday_school_lead", _raise)
    conv = _conv()
    _step(conv, "საკვირაო სკოლა მაინტერესებს")
    _step(conv, "595999733")
    out = _step(conv, "ნიკოლოზი")
    assert out == parent_flow._SUNDAY_SCHOOL_SUCCESS    # email success not blocked


def test_idempotent_no_second_email(monkeypatch):
    calls = []
    monkeypatch.setattr(notification_service, "notify_sunday_school_handoff",
                        lambda lead: calls.append(1) or True)
    monkeypatch.setattr(sheets_service, "log_sunday_school_lead", lambda *a, **k: True)
    conv = _conv()
    _step(conv, "საკვირაო სკოლა მაინტერესებს")
    _step(conv, "595999733")
    _step(conv, "ნიკოლოზი")
    out_again = _step(conv, "კიდევ საკვირაო სკოლა მაინტერესებს")
    assert len(calls) == 1
    assert out_again == parent_flow._SUNDAY_SCHOOL_ALREADY


def test_name_and_phone_in_one_message(monkeypatch):
    calls = []
    monkeypatch.setattr(notification_service, "notify_sunday_school_handoff",
                        lambda lead: calls.append((lead.name, lead.phone)) or True)
    monkeypatch.setattr(sheets_service, "log_sunday_school_lead", lambda *a, **k: True)
    conv = _conv()
    out = _step(conv, "საკვირაო სკოლა მინდა, ნიკოლოზი 595999733")
    assert calls == [("ნიკოლოზი", "595999733")]
    assert out == parent_flow._SUNDAY_SCHOOL_SUCCESS


def test_camp_message_not_hijacked():
    """A camp message has no Sunday-school marker → interceptor defers."""
    conv = _conv()
    assert parent_flow._maybe_handle_sunday_school(conv, "ბანაკი მაინტერესებს") is None
    assert parent_flow._maybe_handle_sunday_school(conv, "გამარჯობა") is None


# ===========================================================================
# End-to-end through parent_flow.handle (engine ON) — replays the transcript
# ===========================================================================


def test_transcript_end_to_end(engine_on, monkeypatch):             # (#2,#3 e2e)
    monkeypatch.setattr(openai_service, "chat_with_tools", _boom)
    monkeypatch.setattr(notification_service, "_send_email", lambda **k: True)
    wa = SimpleNamespace(called=0)
    monkeypatch.setattr(notification_service, "_send_manager_whatsapp",
                        lambda text: setattr(wa, "called", wa.called + 1) or True)
    monkeypatch.setattr(sheets_service, "log_sunday_school_lead", lambda *a, **k: True)
    # Booking sheet + Calendar must never be touched by this flow.
    monkeypatch.setattr(sheets_service, "save_lead",
                        lambda *a, **k: pytest.fail("booking sheet must not run"))

    conv = _conv("ss-e2e")

    def _turn(msg):
        # Mirror conversation_service.process_message history accumulation so
        # the multi-turn Sunday-school collection context is recognised.
        conv.history.append({"role": "user", "content": msg})
        reply = parent_flow.handle(conv, msg)
        conv.history.append({"role": "assistant", "content": reply})
        return reply

    out1 = _turn("საკვირაო სკოლა მაინტერესებს")
    # Coming-soon contract (2026-06-27): no launch detail, offers manager.
    assert "ივლის" not in out1 and "მენეჯერ" in out1
    assert "2150" not in out1

    out2 = _turn("595999733")
    assert "სახელი" in out2

    out3 = _turn("ნიკოლოზი")
    assert out3 == parent_flow._SUNDAY_SCHOOL_SUCCESS
    assert "გადავეცი" in out3
    assert wa.called == 0                  # EMAIL ONLY — no WhatsApp


# ===========================================================================
# Preserved behaviour (regression smoke) — (#12,#13,#20)
# ===========================================================================


def test_underage_handoff_still_dispatches(monkeypatch):            # (#12)
    calls = []
    monkeypatch.setattr(notification_service, "notify_manager_handoff",
                        lambda lead, reason: calls.append((lead.name, lead.phone)) or True)
    conv = Conversation(sender_id="ua", platform="instagram", segment="PARENT")
    conv.lead = Lead(sender_id="ua", platform="instagram", segment="PARENT", child_age="8")
    conv.history.append({"role": "assistant",
                         "content": "თუ გსურთ, მენეჯერთან დაგაკავშირებთ."})
    out = parent_flow._maybe_handle_underage_manager_handoff(conv, "ნიკოლოზი 595999733")
    assert len(calls) == 1
    assert "გადავეცი" in out


def test_manager_phone_direct_request_unchanged(engine_on, monkeypatch):  # (#13)
    monkeypatch.setattr(openai_service, "chat_with_tools", _boom)
    conv = Conversation(sender_id="mn", platform="instagram", segment="PARENT")
    conv.history.append({"role": "assistant", "content": "_prior"})
    conv.lead = Lead(sender_id="mn", platform="instagram", segment="PARENT", child_age="14")
    out = parent_flow.handle(conv, "მენეჯერის ნომერი მომწერეთ")
    assert "558 67 47 33" in out


# ===========================================================================
# Review hardening (adversarial review, 2026-06-22)
# ===========================================================================


@pytest.mark.parametrize("msg", [
    "საკვირაო სკოლა მაინტერესებს",
    "საკვირაო სკოლა როდის დაემატება?",
    "sunday school",
    "საკვირაოსკოლა მინდა",
])
def test_intent_true_for_real_sunday_school(msg):
    assert parent_flow._is_sunday_school_intent(msg) is True


@pytest.mark.parametrize("msg", [
    "საკვირაო ბანაკი გაქვთ?",            # bare „საკვირაო" + camp → NOT Sunday school
    "საკვირაო დღეებში ტარდება ბანაკი?",
    "ბანაკი მაინტერესებს",
    "გამარჯობა",
])
def test_intent_false_for_bare_sakvirao_or_camp(msg):
    assert parent_flow._is_sunday_school_intent(msg) is False


def test_camp_question_with_bare_sakvirao_not_hijacked():
    """„საკვირაო ბანაკი გაქვთ?" must defer (None) so the camp flow answers."""
    conv = _conv()
    assert parent_flow._maybe_handle_sunday_school(conv, "საკვირაო ბანაკი გაქვთ?") is None


def test_mid_collection_camp_pivot_defers_and_does_not_capture_name():
    """Mid-collection pivot to camp must defer to the engine AND never store a
    topic word („ბანაკი") as the lead name."""
    conv = _conv()
    conv.history.append({"role": "assistant", "content": parent_flow._render_sunday_school_answer()})
    out = parent_flow._maybe_handle_sunday_school(conv, "ბანაკი მაინტერესებს, 14 წლისაა")
    assert out is None                                  # defers — not trapped
    assert (conv.lead.name or "") == ""                 # „ბანაკი" NOT captured


def test_mid_collection_question_defers():
    conv = _conv()
    conv.history.append({"role": "assistant", "content": parent_flow._SUNDAY_SCHOOL_ASK_NAME})
    assert parent_flow._maybe_handle_sunday_school(conv, "ფასი რა არის?") is None


def test_fail_message_carries_collection_marker():
    assert parent_flow._SUNDAY_SCHOOL_COLLECTION_MARKER in parent_flow._SUNDAY_SCHOOL_FAIL


def test_email_failure_then_retry_dispatches_again(monkeypatch):
    """After an email FAIL, a follow-up turn re-attempts the dispatch (the FAIL
    message keeps the conversation in Sunday-school collection)."""
    state = {"n": 0}
    def _dispatch(lead):
        state["n"] += 1
        return state["n"] >= 2          # first attempt fails, second succeeds
    monkeypatch.setattr(notification_service, "notify_sunday_school_handoff", _dispatch)
    monkeypatch.setattr(sheets_service, "log_sunday_school_lead", lambda *a, **k: True)

    conv = _conv()
    _step(conv, "საკვირაო სკოლა მაინტერესებს")
    _step(conv, "595999733")
    out_fail = _step(conv, "ნიკოლოზი")
    assert out_fail == parent_flow._SUNDAY_SCHOOL_FAIL
    out_retry = _step(conv, "კი, სცადე ისევ")
    assert out_retry == parent_flow._SUNDAY_SCHOOL_SUCCESS
    assert state["n"] == 2              # really re-dispatched


def test_callback_no_lead_write_on_dispatch_failure(monkeypatch):   # (#3 dup-row)
    monkeypatch.setattr(notification_service, "send_manager_notification",
                        lambda lead, summary: False)
    monkeypatch.setattr(openai_service, "generate_summary", lambda h: "x")
    created = []
    monkeypatch.setattr(sheets_service, "create_lead",
                        lambda lead: created.append(1) or True)
    conv = _conv("cb-fail")
    conv.lead.name, conv.lead.phone = "ნიკოლოზი", "599999733"
    ex = ParentToolExecutor(conversation=conv, lead=conv.lead,
                            sender_id="cb-fail", platform="instagram")
    res = ex.execute(TOOL_REQUEST_MANAGER_CALLBACK, {})
    assert res.get("success") is not True
    assert created == []               # no CRM row written on failed dispatch


def test_callback_writes_lead_once_on_success(monkeypatch):
    monkeypatch.setattr(notification_service, "send_manager_notification",
                        lambda lead, summary: True)
    monkeypatch.setattr(openai_service, "generate_summary", lambda h: "x")
    created = []
    monkeypatch.setattr(sheets_service, "create_lead",
                        lambda lead: created.append(1) or True)
    conv = _conv("cb-ok")
    conv.lead.name, conv.lead.phone = "ნიკოლოზი", "599999733"
    ex = ParentToolExecutor(conversation=conv, lead=conv.lead,
                            sender_id="cb-ok", platform="instagram")
    res = ex.execute(TOOL_REQUEST_MANAGER_CALLBACK, {})
    assert res["success"] is True
    assert created == [1]              # exactly one CRM row on success


# ===========================================================================
# TASK 2 — Sunday-School status comes from Admin Config (not hardcoded July)
# ===========================================================================


def _set_ss_config(monkeypatch, **fields):
    """Override the Admin-Config Sunday-School status the handler reads."""
    from app.services import admin_config_service
    monkeypatch.setattr(admin_config_service, "get_sunday_school_status", lambda: dict(fields))


def test_answer_uses_config_availability_text_not_hardcoded(monkeypatch):   # (#1,#2)
    _set_ss_config(monkeypatch, availability_text="საკვირაო სკოლა სექტემბერში დაიწყება.",
                   details_text="", handoff_enabled=True)
    out = parent_flow._render_sunday_school_answer()
    assert "სექტემბერ" in out          # config text drives the answer
    assert "ივლის" not in out          # no hardcoded July
    assert "სახელი" in out and "ნომერ" in out


def test_answer_says_july_when_config_says_july(monkeypatch):               # (#3)
    _set_ss_config(monkeypatch, availability_text="საკვირაო სკოლა ივლისში დაემატება.",
                   details_text="დეტალები ზუსტდება", handoff_enabled=True)
    out = parent_flow._render_sunday_school_answer()
    assert "ივლის" in out and "დეტალები ზუსტდება" in out and "მენეჯერს გადავცე" in out


def test_answer_reflects_changed_status(monkeypatch):                       # (#4)
    _set_ss_config(monkeypatch, availability_text="საკვირაო სკოლა უკვე აქტიურია.",
                   details_text="", handoff_enabled=True)
    out = parent_flow._render_sunday_school_answer()
    assert "აქტიურია" in out and "ივლის" not in out


def test_missing_config_safe_fallback_no_invented_facts(monkeypatch):       # (#5)
    _set_ss_config(monkeypatch)        # empty → all defaults/empty
    out = parent_flow._render_sunday_school_answer()
    assert "დეტალები ზუსტდება" in out  # safe no-date fallback
    assert "ივლის" not in out          # no invented month
    assert "2150" not in out           # no invented price
    assert "სახელი" in out and "ნომერ" in out


def test_handoff_disabled_omits_contact_ask(monkeypatch):
    _set_ss_config(monkeypatch, availability_text="საკვირაო სკოლა ივლისში დაემატება.",
                   details_text="", handoff_enabled=False)
    out = parent_flow._render_sunday_school_answer()
    assert "ივლის" in out
    assert "სახელი" not in out and "მენეჯერს გადავცე" not in out


def test_real_default_config_coming_soon_hides_july_in_render():
    """The shipped sections.yaml HOLDS the July availability text (data), and its
    status is `coming_soon` — so the RENDERED answer hides the month and offers
    the manager instead (coming_soon contract, 2026-06-27)."""
    from app.services import admin_config_service
    st = admin_config_service.get_sunday_school_status()
    assert "ივლის" in st["availability_text"]            # data still present
    assert st["status"] == "coming_soon"
    assert st["handoff_enabled"] is True and st["lead_type"] == "sunday_school"
    out = parent_flow._render_sunday_school_answer()
    assert "ივლის" not in out                            # coming_soon hides the month
    assert "მენეჯერ" in out                               # offers the manager


def test_no_hardcoded_july_in_parent_flow_source():
    """Guard: the live handler module must not hardcode the launch month —
    it must come from config. (Catches a future re-introduction.)"""
    import inspect
    from app.flows import parent_flow as pf
    src = inspect.getsource(pf)
    # The only place „ივლის" may legitimately appear is a comment/example, not a
    # user-facing Sunday-School answer constant. Assert the old hardcoded answer
    # constant is gone and no SS answer constant carries a month literal.
    assert not hasattr(pf, "_SUNDAY_SCHOOL_ANSWER"), "old hardcoded answer constant must be removed"
    assert "ივლისში დაემატება" not in src, "launch month must live in Admin Config, not parent_flow"
