"""Price-objection vs decline + phone/name correction fixes (2026-06-22).

Three confirmed live bugs (narrow scope):

  #1 — a price objection that contains „არ მინდა" („…არ მინდა, მაგრამ ბავშვი
       ძალიან მინდა") was cold-closed as a decline, killing the lead.
  #2 — correcting the phone after it was saved („ნომერი შევცდი, სწორია 595…")
       was ignored — the stale number stayed.
  #3 — correcting the name after it was saved („ნინო კი არა, მარიამი") was
       ignored — the agent kept the old name.

Fixes are deterministic + narrow: a price-objection guard in
`_maybe_handle_decline_engine`, and a new `_maybe_handle_contact_correction`
interceptor that overwrites lead.phone / lead.name on an explicit correction.
NO Calendar / Sheets / notifications / prompt / YAML touched.

Driven through the REAL parent flow with the engine ON and a mocked OpenAI.
"""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import pytest

import app.config as config_module
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import conversation_service, messenger_service, openai_service

_COLD_CLOSE = "თუ რამე შეიცვლება"  # the decline cold-close fragment


@pytest.fixture(autouse=True)
def _reset():
    conversation_service.conversations.clear()
    parent_flow.invalid_phone_retries.clear()
    yield
    conversation_service.conversations.clear()


@pytest.fixture
def engine_on(monkeypatch):
    swapped = dataclasses.replace(config_module.settings, USE_PARENT_LLM_ENGINE=True)
    monkeypatch.setattr(parent_flow, "settings", swapped)
    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})


def _mk(content):
    msg = SimpleNamespace(content=content or None, tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def _conv(name="", phone="", child_age="14", booked=False):
    c = Conversation(sender_id="oc-u", platform="instagram")
    c.history.append({"role": "assistant", "content": "_prior"})
    lead = Lead(
        sender_id="oc-u", platform="instagram", segment="PARENT",
        child_age=child_age, name=name, phone=phone,
    )
    if booked:
        lead.calendly_booked = True
    c.lead = lead
    return c


# ==========================================================================
# #1 — price objection must NOT be treated as a decline
# ==========================================================================


@pytest.mark.parametrize("message", [
    "ამდენის გადახდა არ მინდა მაგრამ ბავშვი ძალიან მინდა",
    "არ მინდა ამდენი გადავიხადო, მაგრამ მაინტერესებს",
    "მინდა, მაგრამ ძვირია",
    "ფასი მაღალია, მაგრამ მაინტერესებს",
    "გადახდა მიჭირს",
])
def test_price_objection_not_declined(message):
    # None == "not a decline" → the flow falls through to the engine/objection.
    assert parent_flow._maybe_handle_decline_engine(_conv(), message) is None


@pytest.mark.parametrize("message", [
    "არ მინდა",
    "არა მადლობა",
    "უარს ვამბობ",
    "არ არის საჭირო",
])
def test_plain_decline_still_declines(message):
    out = parent_flow._maybe_handle_decline_engine(_conv(), message)
    assert out is not None
    assert _COLD_CLOSE in out


def test_price_objection_uses_deterministic_price_not_cold_close(engine_on, monkeypatch):
    """A price objection containing a decline phrase is still handled as price,
    not as a cold-close or free LLM objection path."""
    seen = {"called": False}

    def _chat(**kw):
        seen["called"] = True
        return _mk("ENGINE_REPLY")

    monkeypatch.setattr(openai_service, "chat_with_tools", _chat)
    conv = _conv()
    out = parent_flow.handle(conv, "ამდენის გადახდა არ მინდა მაგრამ ბავშვი ძალიან მინდა")
    assert seen["called"] is False
    assert _COLD_CLOSE not in out          # lead NOT killed
    assert "2150" not in out
    assert "TBC" in out
    assert "6 თვემდე" in out

# ==========================================================================
# #2 — phone correction
# ==========================================================================


@pytest.mark.parametrize("message, expected", [
    ("ნომერი შევცდი, სწორია 595222222", "595222222"),
    ("ეს არა, სწორი ნომერია 595 33 33 33", "595333333"),
    ("სხვა ნომერი ჩავწეროთ 595444444", "595444444"),
])
def test_phone_correction_updates_before_commit(message, expected):
    conv = _conv(phone="595111111")
    out = parent_flow._maybe_handle_contact_correction(conv, message)
    assert out is not None
    assert conv.lead.phone == expected            # overwritten
    assert "მენეჯერს გადავცემ" not in out         # not-committed wording


def test_phone_correction_after_commit_acks_manager_no_schema_touch(monkeypatch):
    """When a booking is already committed, still acknowledge the corrected
    number for the manager — WITHOUT touching Calendar / Sheets / notifications."""
    from app.services import calendar_service, sheets_service, notification_service

    def _boom(*a, **k):
        raise AssertionError("correction must NOT touch Calendar/Sheets/notification")
    for mod, fn in [
        (calendar_service, "book_slot"), (calendar_service, "create_event"),
        (sheets_service, "create_lead"), (sheets_service, "save_lead"),
        (notification_service, "send_manager_notification"),
    ]:
        if hasattr(mod, fn):
            monkeypatch.setattr(mod, fn, _boom, raising=False)

    conv = _conv(phone="595111111", booked=True)
    out = parent_flow._maybe_handle_contact_correction(conv, "ნომერი შევცდი, სწორია 595222222")
    assert conv.lead.phone == "595222222"
    assert "მენეჯერს გადავცემ" in out


def test_normal_phone_provision_is_not_a_correction():
    """A plain phone with no correction marker must NOT be hijacked here."""
    conv = _conv(phone="595111111")
    assert parent_flow._maybe_handle_contact_correction(conv, "ჩემი ნომერია 595999733") is None
    assert conv.lead.phone == "595111111"  # untouched by this interceptor


# ==========================================================================
# #3 — name correction
# ==========================================================================


@pytest.mark.parametrize("message, expected", [
    ("ნინო კი არა, მარიამი ვარ", "მარიამი"),
    ("სახელი შევცდი, მარიამი", "მარიამი"),
    ("არა, მარიამი", "მარიამი"),
])
def test_name_correction_updates_before_commit(message, expected):
    conv = _conv(name="ნინო")
    out = parent_flow._maybe_handle_contact_correction(conv, message)
    assert out is not None
    assert conv.lead.name == expected


def test_normal_name_provision_is_not_a_correction():
    conv = _conv()
    assert parent_flow._maybe_handle_contact_correction(conv, "მე ვარ ნინო") is None


# ==========================================================================
# End-to-end through handle() (engine ON)
# ==========================================================================


def test_phone_correction_end_to_end(engine_on, monkeypatch):
    def _boom(**kw):
        raise AssertionError("engine must not be consulted for a contact correction")
    monkeypatch.setattr(openai_service, "chat_with_tools", _boom)
    conv = _conv(name="გიორგი", phone="595111111")
    out = parent_flow.handle(conv, "ნომერი შევცდი, სწორია 595222222")
    assert conv.lead.phone == "595222222"
    assert "595 22 22 22" in out


def test_name_correction_end_to_end(engine_on, monkeypatch):
    def _boom(**kw):
        raise AssertionError("engine must not be consulted for a contact correction")
    monkeypatch.setattr(openai_service, "chat_with_tools", _boom)
    conv = _conv(name="ნინო", phone="595999733")
    out = parent_flow.handle(conv, "ნინო კი არა, მარიამი ვარ")
    assert conv.lead.name == "მარიამი"
    assert "მარიამი" in out


def test_consultation_memory_unchanged(engine_on, monkeypatch):
    """Regression guard: the age+phone same-message capture still works."""
    monkeypatch.setattr(openai_service, "chat_with_tools", lambda **kw: _mk("გასაგებია."))
    conv = _conv(name="", phone="", child_age="")
    parent_flow.handle(conv, "14 წლის არის 595999733")
    assert conv.lead.child_age == "14"
    assert conv.lead.phone == "595999733"
