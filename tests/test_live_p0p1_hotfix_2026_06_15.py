"""Live P0/P1 Hotfix (2026-06-15) regression tests — BUG A / B / C.

NO real notifications / messages are sent: every dispatch path is mocked,
and conftest's autouse `_block_real_smtp` is an additional hard safety net.

BUG A — under-age manager handoff MUST actually notify the operator
        (message-only; no Sheets/Calendar) and only claim success on a real
        dispatch.
BUG B — a PAST or NON-EXISTENT named adult event is resolved deterministically
        (already-took-place / not-found + active list) BEFORE any self/child
        target question.
BUG C — „მოგიწოდებთ" is rewritten to „გთხოვთ"; handoff / ineligible answers
        are paragraph-broken (not one dense block).
"""
from __future__ import annotations

import pytest

from app.agent.llm import adult_llm_engine
from app.agent.llm import parent_llm_engine
from app.agent.tools import parent_tool_executor
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import admin_config_service as acs
from app.services import calendar_service, notification_service, sheets_service


_INELIGIBLE_OFFER = (
    "ბანაკში მონაწილეობა შესაძლებელია 9–17 წლის ბავშვებისთვის. "
    "თუ გსურთ, მენეჯერთან დაგაკავშირებთ."
)


def _underage_conv(sender_id="ua-1", *, child_age="8", name="", phone="",
                   last_bot=_INELIGIBLE_OFFER):
    conv = Conversation(sender_id=sender_id, platform="instagram", segment="PARENT")
    conv.lead = Lead(sender_id=sender_id, platform="instagram", segment="PARENT")
    conv.lead.child_age = child_age
    if name:
        conv.lead.name = name
    if phone:
        conv.lead.phone = phone
    conv.history.append({"role": "user", "content": f"{child_age} წლის"})
    conv.history.append({"role": "assistant", "content": last_bot})
    return conv


@pytest.fixture(autouse=True)
def _reset_executor_state():
    parent_tool_executor.reset_state()
    yield
    parent_tool_executor.reset_state()


# ===========================================================================
# BUG A — under-age manager handoff actually dispatches
# ===========================================================================


def test_buga_underage_handoff_dispatches_once_no_sheets_calendar(monkeypatch):
    calls = []
    monkeypatch.setattr(
        notification_service, "notify_manager_handoff",
        lambda lead, reason: calls.append((lead.name, lead.phone, reason)) or True,
    )
    sheets_hits = []
    for fn in ("create_lead", "save_lead", "update_lead"):
        monkeypatch.setattr(
            sheets_service, fn,
            lambda *a, _fn=fn, **k: sheets_hits.append(_fn) or True, raising=False,
        )
    cal_hits = []
    for fn in ("book_slot", "create_event"):
        monkeypatch.setattr(
            calendar_service, fn,
            lambda *a, _fn=fn, **k: cal_hits.append(_fn) or True, raising=False,
        )

    conv = _underage_conv()
    out = parent_flow._maybe_handle_underage_manager_handoff(
        conv, "ნიკოლოზი 595999733",
    )

    assert len(calls) == 1, "operator must be notified exactly once"
    name, phone, reason = calls[0]
    assert "ნიკოლოზ" in (name or "")
    assert "595999733" in (phone or "")
    assert "8" in reason and "ასაკ" in reason  # reason = under-age
    assert sheets_hits == [], "must NOT write Sheets (message-only handoff)"
    assert cal_hits == [], "must NOT write Calendar (message-only handoff)"
    assert out is not None and "გადავეცი" in out  # success only on dispatch


def test_buga_success_message_paragraphed(monkeypatch):
    monkeypatch.setattr(notification_service, "notify_manager_handoff", lambda l, r: True)
    conv = _underage_conv()
    out = parent_flow._maybe_handle_underage_manager_handoff(conv, "ნიკოლოზი 595999733")
    assert "მენეჯერს გადავეცი" in out
    assert "\n\n" in out  # BUG C readability


def test_buga_dispatch_failure_no_false_success_with_contact(monkeypatch):
    monkeypatch.setattr(notification_service, "notify_manager_handoff", lambda l, r: False)
    monkeypatch.setattr(parent_flow, "_manager_contact_for_fallback", lambda: "558 67 47 33")
    conv = _underage_conv()
    out = parent_flow._maybe_handle_underage_manager_handoff(conv, "ნიკოლოზი 595999733")
    # NEVER falsely claim the manager was notified / will call back
    assert "დაგიკავშირდებათ" not in out
    assert "ჩავიწერე" not in out
    # honest fallback with the manager's direct contact
    assert "ვერ გადავეცი" in out
    assert "558 67 47 33" in out


def test_buga_dispatch_failure_no_contact_configured(monkeypatch):
    monkeypatch.setattr(notification_service, "notify_manager_handoff", lambda l, r: False)
    monkeypatch.setattr(parent_flow, "_manager_contact_for_fallback", lambda: "")
    conv = _underage_conv()
    out = parent_flow._maybe_handle_underage_manager_handoff(conv, "ნიკოლოზი 595999733")
    assert "დაგიკავშირდებათ" not in out
    assert "ვერ გადავეცი" in out
    assert "მოგვიანებით" in out


def test_buga_notify_handoff_any_channel_logic(monkeypatch):
    lead = Lead(sender_id="x", platform="instagram", segment="PARENT")
    lead.name = "ნიკა"
    lead.phone = "595999733"
    captured = {}
    monkeypatch.setattr(
        notification_service, "_send_email",
        lambda subject, body: captured.update(subject=subject, body=body) or True,
    )
    monkeypatch.setattr(notification_service, "_send_manager_whatsapp", lambda text: False)
    # email succeeds + whatsapp unconfigured → a REAL dispatch happened
    assert notification_service.notify_manager_handoff(lead, "8 წლის ბავშვი") is True
    assert "ნიკა" in captured["body"]
    assert "595999733" in captured["body"]
    assert "8 წლის ბავშვი" in captured["body"]
    # both channels fail → no dispatch → caller must NOT claim success
    monkeypatch.setattr(notification_service, "_send_email", lambda subject, body: False)
    assert notification_service.notify_manager_handoff(lead, "8 წლის ბავშვი") is False


def test_buga_eligible_lead_not_affected(monkeypatch):
    spy = []
    monkeypatch.setattr(
        notification_service, "notify_manager_handoff",
        lambda l, r: spy.append(1) or True,
    )
    conv = _underage_conv(child_age="14")  # eligible — not a handoff path
    out = parent_flow._maybe_handle_underage_manager_handoff(conv, "ნიკოლოზი 595999733")
    assert out is None
    assert spy == []


def test_buga_over_age_not_affected(monkeypatch):
    spy = []
    monkeypatch.setattr(
        notification_service, "notify_manager_handoff",
        lambda l, r: spy.append(1) or True,
    )
    conv = _underage_conv(child_age="18")  # over-age → adult-switch path, not here
    out = parent_flow._maybe_handle_underage_manager_handoff(conv, "ნიკოლოზი 595999733")
    assert out is None
    assert spy == []


def test_buga_no_phone_defers(monkeypatch):
    spy = []
    monkeypatch.setattr(
        notification_service, "notify_manager_handoff",
        lambda l, r: spy.append(1) or True,
    )
    # P1 polish (2026-06-15): an affirmative with NO contact must ASK for
    # name+phone together (when name unknown) — not dispatch, not defer.
    conv = _underage_conv()
    out = parent_flow._maybe_handle_underage_manager_handoff(conv, "კი, მინდა")
    assert out is not None
    assert "სახელი" in out and "ნომერ" in out      # asks both together
    assert spy == [], "must NOT dispatch before contact is collected"
    # A genuine topic-change question on the offer turn is NOT hijacked.
    conv2 = _underage_conv(sender_id="ua-topic")
    assert parent_flow._maybe_handle_underage_manager_handoff(conv2, "რა ღირს ბანაკი?") is None


def test_buga_idempotent_single_dispatch(monkeypatch):
    n = []
    monkeypatch.setattr(
        notification_service, "notify_manager_handoff",
        lambda l, r: n.append(1) or True,
    )
    conv = _underage_conv()
    parent_flow._maybe_handle_underage_manager_handoff(conv, "ნიკოლოზი 595999733")
    out2 = parent_flow._maybe_handle_underage_manager_handoff(conv, "595999733")
    assert len(n) == 1                  # dispatched only once
    assert out2 is not None and "უკვე" in out2  # already-handed-off reassurance


def test_buga_end_to_end_via_handle(monkeypatch, camp_registration_open):
    # The deterministic pre-handlers run on the engine-ON path (live default).
    # Enable the engine; our handler returns BEFORE the LLM, so no OpenAI call.
    import dataclasses
    monkeypatch.setattr(
        parent_flow, "settings",
        dataclasses.replace(parent_flow.settings, USE_PARENT_LLM_ENGINE=True),
    )
    # Guard: if the engine were ever reached, fail loudly instead of calling OpenAI.
    from app.services import openai_service
    monkeypatch.setattr(
        openai_service, "chat_with_tools",
        lambda **k: (_ for _ in ()).throw(AssertionError("engine must not be reached")),
    )
    calls = []
    monkeypatch.setattr(
        notification_service, "notify_manager_handoff",
        lambda lead, reason: calls.append(reason) or True,
    )
    conv = _underage_conv(sender_id="ua-e2e")
    conv.state = "ASK_CHALLENGE"
    out = parent_flow.handle(conv, "ნიკოლოზი 595999733")
    assert len(calls) == 1
    assert "გადავეცი" in out


# ===========================================================================
# BUG B — past / not-found named events resolved before target/age
# ===========================================================================

_PAST_EV = {"title": "შეხვედრა გია მურღულიასთან", "date_text": "14 ივნისი 20:00"}
_ACTIVE_EV = {
    "title": "fromula 1", "date_text": "28 აგვისტო 19:00",
    "location": "monaco", "price_text": "5000",
    "reservation_url": "https://wordacademy.ge/cart",
}


def test_bugb_past_named_event_says_already_took_place(monkeypatch):
    monkeypatch.setattr(acs, "find_active_events_by_reference", lambda m, **k: [])
    monkeypatch.setattr(acs, "find_events_by_reference", lambda m, **k: [_PAST_EV])
    monkeypatch.setattr(acs, "is_adult_event_past", lambda e, **k: True)
    monkeypatch.setattr(acs, "get_active_adult_events", lambda **k: [_ACTIVE_EV])
    out = adult_llm_engine._maybe_handle_named_adult_event(
        "გია მურღულიას ღონისძიება როდის არის?",
    )
    assert out is not None
    assert "უკვე გაიმართა" in out
    assert "მურღულია" in out
    assert "14 ივნის" in out            # its date stated
    assert "fromula 1" in out            # active list offered after
    assert "თქვენთვის თუ" not in out     # NO self/child target question
    assert "რამდენი წლის" not in out


def test_bugb_unknown_named_event_not_found_plus_list(monkeypatch):
    monkeypatch.setattr(acs, "find_active_events_by_reference", lambda m, **k: [])
    monkeypatch.setattr(acs, "find_events_by_reference", lambda m, **k: [])
    monkeypatch.setattr(acs, "get_active_adult_events", lambda **k: [_ACTIVE_EV])
    out = adult_llm_engine._maybe_handle_named_adult_event("გალაკტიონის საღამო გაქვთ?")
    assert out is not None
    assert "ვერ მოვძებნე" in out
    assert "fromula 1" in out            # active list
    assert "მენეჯერ" in out              # manager-verify
    assert "თქვენთვის თუ" not in out


def test_bugb_active_named_event_direct_answer_unchanged(monkeypatch):
    monkeypatch.setattr(acs, "find_active_events_by_reference", lambda m, **k: [_ACTIVE_EV])
    out = adult_llm_engine._maybe_handle_named_adult_event("fromula 1 ღონისძიება გაქვთ?")
    assert out is not None
    assert "fromula 1" in out
    assert "თარიღი" in out
    assert "თქვენთვის თუ" not in out


def test_bugb_generic_query_still_defers_to_llm():
    assert adult_llm_engine._maybe_handle_named_adult_event("ღონისძიება მაინტერესებს") is None
    assert adult_llm_engine._maybe_handle_named_adult_event("რომელი ღონისძიება გაქვთ?") is None


def test_bugb_fix3_adult_self_revert_still_holds():
    lead = Lead(sender_id="z", platform="instagram", segment="ADULT")
    lead.adult_target_relation = "შვილი"
    lead.adult_target_age = "14"
    adult_llm_engine._maybe_capture_adult_target("ჩემთვის მინდა", lead)
    assert (lead.adult_target_relation or "") == ""
    assert (lead.adult_target_age or "") == ""


def test_bugb_find_events_by_reference_include_past(monkeypatch):
    """The new past-inclusive search delegates to the wider pool; the
    active-only wrapper preserves its contract."""
    pool_active = [_ACTIVE_EV]
    pool_all = [_ACTIVE_EV, _PAST_EV]

    def fake_get_active(*, now=None, include_past=False):
        return pool_all if include_past else pool_active

    monkeypatch.setattr(acs, "get_active_adult_events", fake_get_active)
    # active-only wrapper finds the active event by its name
    assert acs.find_active_events_by_reference("fromula") == [_ACTIVE_EV]
    # include_past surfaces the past event by its guest name
    past = acs.find_events_by_reference("გია მურღულია", include_past=True)
    assert _PAST_EV in past


# ===========================================================================
# BUG C — wording + paragraphs
# ===========================================================================


def test_bugc_parent_sanitizer_rewrites_mogiwodebt():
    out = parent_llm_engine.sanitise_response_wording("მოგიწოდებთ, მომწერეთ ნომერი.")
    assert "მოგიწოდებთ" not in out
    assert "გთხოვთ" in out


def test_bugc_adult_sanitizer_rewrites_mogiwodebt():
    out = adult_llm_engine.sanitise_adult_response("მოგიწოდებთ, მომწერეთ ნომერი.")
    assert "მოგიწოდებთ" not in out
    assert "გთხოვთ" in out


def test_bugc_ineligible_message_is_paragraphed():
    conv = _underage_conv()
    out = parent_flow._ensure_ineligible_young_age_message(
        conv, "8 წლის", "ბუნდოვანი პასუხი ასაკზე.",
    )
    assert "\n\n" in out                       # not one dense block
    assert ("9" in out) or ("ასაკი" in out)    # SC-06 invariant preserved
    assert "მენეჯერ" in out                    # SC-06 invariant preserved
    assert "ჩავნიშნ" not in out


def test_bugc_format_handoff_paragraphs_helper():
    assert parent_flow._format_handoff_paragraphs("ერთი. ორი. სამი.") == (
        "ერთი.\n\nორი.\n\nსამი."
    )
    # single sentence / already-paragraphed → unchanged
    assert parent_flow._format_handoff_paragraphs("ერთი წინადადება.") == "ერთი წინადადება."
    assert parent_flow._format_handoff_paragraphs("ა.\n\nბ.") == "ა.\n\nბ."
