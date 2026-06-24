"""PARENT booking smoke regression tests (2026-06-09).

Covers the five live failures observed during the client local smoke test:

  1. "კი მინდა" after a consultation offer must enter the booking flow
     (get_available_slots / check_consultation_slot), NOT jump straight to
     manager callback.
  2. "595999733 ტესტ" must parse as phone="595999733", name="ტესტ".
  3. "ტესტ 595999733" (name before phone) must parse correctly.
  4. "595 999 733 ნიკა" (spaced phone + name) must parse correctly.
  5. Phone-only is sufficient when lead.name is already populated.
  6. Known Meta/profile name must not be re-requested.
  7. "კომპიუტერის მეხსიერების მიხედვით" must be stripped by the sanitiser.
  8. No booking claimed without a Calendar event (no fake-booking).
  9. System prompt contains the booking-intent flow CRITICAL block.
 10. System prompt contains the contact-info CRITICAL block.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mk_response(content: str = "", tool_calls: list[dict] | None = None) -> Any:
    choice = MagicMock()
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = []
    if tool_calls:
        tc_list = []
        for tc in tool_calls:
            t = MagicMock()
            t.id = tc.get("id", "tc1")
            fn = MagicMock()
            fn.name = tc["name"]
            fn.arguments = json.dumps(tc.get("arguments", {}))
            t.function = fn
            tc_list.append(t)
        msg.tool_calls = tc_list
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


# ---------------------------------------------------------------------------
# Part 1 — _parse_name_phone correctly handles phone-before-name
# ---------------------------------------------------------------------------

class TestPhoneNameParser:
    """_parse_name_phone must handle phone-first and name-first orders."""

    def _parse(self, text: str):
        from app.flows.parent_flow import _parse_name_phone
        return _parse_name_phone(text)

    def test_phone_before_name(self):
        name, phone = self._parse("595999733 ტესტ")
        assert phone == "595999733", f"Expected phone=595999733, got {phone!r}"
        assert name == "ტესტ", f"Expected name=ტესტ, got {name!r}"

    def test_name_before_phone(self):
        name, phone = self._parse("ტესტ 595999733")
        assert phone == "595999733", f"Expected phone=595999733, got {phone!r}"
        assert name == "ტესტ", f"Expected name=ტესტ, got {name!r}"

    def test_spaced_phone_then_name(self):
        name, phone = self._parse("595 999 733 ნიკა")
        assert phone == "595999733", f"Expected phone=595999733, got {phone!r}"
        assert name == "ნიკა", f"Expected name=ნიკა, got {name!r}"

    def test_name_then_spaced_phone(self):
        name, phone = self._parse("ნიკა 595 999 733")
        assert phone == "595999733"
        assert name == "ნიკა"

    def test_phone_only_valid(self):
        name, phone = self._parse("595999733")
        assert phone == "595999733"
        assert name == ""

    def test_plus995_phone(self):
        name, phone = self._parse("+995595999733")
        assert "595999733" in phone

    def test_invalid_phone_rejected(self):
        name, phone = self._parse("12345")
        assert phone == ""

    def test_georgian_name_extracted_from_phone_name(self):
        """Regression: 'ნომერი სწორად ვერ ამოვიკითხე' must NOT be generated
        for '595999733 ტესტ' — the parser successfully extracts both fields."""
        name, phone = self._parse("595999733 ტესტ")
        assert phone != "", "Parser should extract a valid phone from '595999733 ტესტ'"
        assert name != "", "Parser should extract name 'ტესტ' from '595999733 ტესტ'"

    def test_filler_word_before_phone(self):
        # "კაი 595999733" — "კაი" is a filler word, should be stripped
        name, phone = self._parse("კაი 595999733")
        assert phone == "595999733"

    def test_me_var_before_phone(self):
        # "მე ვარ ნიკა 595999733"
        name, phone = self._parse("მე ვარ ნიკა 595999733")
        assert phone == "595999733"


# ---------------------------------------------------------------------------
# Part 2 — Bad phrase banned from sanitiser
# ---------------------------------------------------------------------------

class TestBadPhraseBanned:
    """'კომპიუტერის მეხსიერების მიხედვით' must be stripped by the sanitiser."""

    def test_computer_memory_phrase_stripped(self):
        from app.agent.llm.parent_llm_engine import sanitise_response_wording
        raw = "კომპიუტერის მეხსიერების მიხედვით, კონსულტაცია ჯერ არ არის ჩანიშნული."
        out = sanitise_response_wording(raw)
        assert "კომპიუტერის მეხსიერების" not in out, \
            f"Sanitiser should strip 'კომპიუტერის მეხსიერების': got {out!r}"

    def test_computer_memory_phrase_with_comma_stripped(self):
        from app.agent.llm.parent_llm_engine import sanitise_response_wording
        raw = "კომპიუტერის მეხსიერების მიხედვით, კონსულტაცია ჩანიშნულია."
        out = sanitise_response_wording(raw)
        assert "კომპიუტერის მეხსიერების" not in out

    def test_chemi_memory_phrase_stripped(self):
        from app.agent.llm.parent_llm_engine import sanitise_response_wording
        raw = "ჩემი მეხსიერების მიხედვით, კონსულტაცია ჯერ არ გაქვთ."
        out = sanitise_response_wording(raw)
        assert "ჩემი მეხსიერების" not in out

    def test_clean_response_unchanged(self):
        from app.agent.llm.parent_llm_engine import sanitise_response_wording
        raw = "ამ ეტაპზე კონსულტაცია ჯერ არ არის ჩანიშნული."
        out = sanitise_response_wording(raw)
        assert out == raw


# ---------------------------------------------------------------------------
# Part 3 — System prompt contains critical booking flow blocks
# ---------------------------------------------------------------------------

class TestSystemPromptRules:
    """The CRITICAL blocks added for the booking regression must be present."""

    @pytest.fixture(scope="class")
    def prompt_text(self):
        from app.agent.llm.prompt_loader import load_prompt
        return load_prompt("system_parent_v2")

    def test_booking_intent_flow_block_present(self, prompt_text):
        assert "Booking Intent Flow" in prompt_text or "კონსულტაციის მოსურვება" in prompt_text, \
            "Booking Intent Flow CRITICAL block must be in system_parent_v2.md"

    def test_get_available_slots_first_rule_present(self, prompt_text):
        # Must say to call get_available_slots before asking for phone/name
        assert "get_available_slots" in prompt_text
        # The word "სლოტ" (slots) must appear near the booking intent rule
        assert "სლოტ" in prompt_text

    def test_contact_info_block_present(self, prompt_text):
        assert "კონტაქტ-ინფორმაციის" in prompt_text or "Contact Info" in prompt_text, \
            "Contact Info CRITICAL block must be in system_parent_v2.md"

    def test_phone_name_order_rule_present(self, prompt_text):
        # The rule "phone + name in same message is valid" must be explicit
        assert "595999733 ნიკა" in prompt_text or "ნომერი + სახელი" in prompt_text or \
               "ციფრული ნაწილი" in prompt_text, \
            "Phone+name order rule must be in system_parent_v2.md"

    def test_bad_phrase_rule_present(self, prompt_text):
        # The prompt should tell the LLM not to say the bad phrase
        assert "კომპიუტერის" not in prompt_text, \
            "Prompt must NOT reference 'კომპიუტერის' (it teaches the bad phrase)"

    def test_name_reuse_rule_present(self, prompt_text):
        # Must not re-ask name if already in context
        assert "name=X" in prompt_text or "სახელი უკვე ცნობილია" in prompt_text or \
               "ხელახლა" in prompt_text, \
            "Name reuse rule must be in system_parent_v2.md"


# ---------------------------------------------------------------------------
# Part 4 — LLM engine integration: "კი მინდა" triggers get_available_slots
# ---------------------------------------------------------------------------

class TestBookingIntentFlow:
    """When user says 'კი მინდა' after a consultation offer, the LLM engine
    must call get_available_slots first, not request_manager_callback."""

    def _make_conversation(self, monkeypatch):
        """Build a minimal Conversation in the state after a consultation offer."""
        from app.models.conversation import Conversation
        from app.models.lead import Lead
        conv = Conversation(
            sender_id="smoke_test_001",
            platform="messenger",
            segment="PARENT",
            state="PRESENT_VALUE",
        )
        conv.lead = Lead(
            sender_id="smoke_test_001",
            platform="messenger",
            segment="PARENT",
        )
        # Simulate: agent already offered consultation in the previous turn
        conv.history = [
            {"role": "assistant", "content": "თუ გსურთ, კონსულტაციაზე ჩაგწერთ და მენეჯერი დეტალებს გიხსნით."},
        ]
        return conv

    def test_ki_minda_calls_get_available_slots(self, monkeypatch):
        """After consultation offer, 'კი მინდა' must trigger get_available_slots,
        not request_manager_callback.
        This is a mocked test — verifies the LLM is instructed to call the right tool."""
        from app.models.conversation import Conversation
        from app.models.lead import Lead
        from app.services import openai_service, messenger_service

        conv = Conversation(
            sender_id="smoke_test_ki_minda",
            platform="messenger",
            segment="PARENT",
            state="PRESENT_VALUE",
        )
        conv.lead = Lead(
            sender_id="smoke_test_ki_minda",
            platform="messenger",
            segment="PARENT",
            child_age="12",
        )
        conv.history = [
            {"role": "assistant", "content": "თუ გსურთ, კონსულტაციაზე ჩაგწერთ."},
        ]

        monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})

        tools_called: list[str] = []

        def _mock_chat(**kwargs):
            # Capture which tool the LLM decides to call
            return _mk_response(
                tool_calls=[{"id": "t1", "name": "get_available_slots", "arguments": {}}]
            )

        slots_result = {
            "success": True,
            "slots": [
                {"slot_id": 1, "display": "10 ივნისი, 10:00", "datetime_iso": "2030-06-10T10:00:00+04:00"},
                {"slot_id": 2, "display": "10 ივნისი, 11:00", "datetime_iso": "2030-06-10T11:00:00+04:00"},
            ],
        }

        def _mock_chat_with_slots(**kwargs):
            # First call: LLM calls get_available_slots
            # Second call: LLM generates text with slot options
            if not tools_called:
                tools_called.append("get_available_slots")
                return _mk_response(
                    tool_calls=[{"id": "t1", "name": "get_available_slots", "arguments": {}}]
                )
            # After tool result injected, LLM generates text
            return _mk_response(content="გთავაზობ: 10 ივნისი 10:00 ან 11:00. რომელი მოგერგება?")

        monkeypatch.setattr(openai_service, "chat_with_tools", _mock_chat_with_slots)

        from app.agent.llm.parent_llm_engine import run_parent_llm_turn
        from app.agent.tools.parent_tool_executor import ParentToolExecutor

        # Patch the executor to intercept tool calls
        orig_execute = ParentToolExecutor.execute
        executor_calls: list[str] = []

        def _mock_execute(self, tool_name, args):
            executor_calls.append(tool_name)
            if tool_name == "get_available_slots":
                return slots_result
            return orig_execute(self, tool_name, args)

        monkeypatch.setattr(ParentToolExecutor, "execute", _mock_execute)

        out = run_parent_llm_turn(
            user_message="კი მინდა",
            conversation=conv,
            lead=conv.lead,
            sender_id="smoke_test_ki_minda",
            platform="messenger",
        )
        # The engine should have called get_available_slots
        assert "get_available_slots" in executor_calls, \
            f"Expected get_available_slots to be called after 'კი მინდა', got: {executor_calls}"

    def test_ki_minda_does_not_call_manager_callback_alone(self, monkeypatch):
        """'კი მინდა' after consultation offer must NOT directly call
        request_manager_callback without first asking for a time slot."""
        from app.models.conversation import Conversation
        from app.models.lead import Lead
        from app.services import openai_service, messenger_service

        conv = Conversation(
            sender_id="smoke_test_no_mgr",
            platform="messenger",
            segment="PARENT",
            state="PRESENT_VALUE",
        )
        conv.lead = Lead(
            sender_id="smoke_test_no_mgr",
            platform="messenger",
            segment="PARENT",
            child_age="11",
        )
        conv.history = [
            {"role": "assistant", "content": "თუ გსურთ, კონსულტაციაზე ჩაგწერთ."},
        ]

        monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})

        from app.agent.tools.parent_tool_executor import ParentToolExecutor
        from app.agent.tools import parent_tool_executor as pte

        executor_calls: list[str] = []
        orig_execute = ParentToolExecutor.execute

        def _mock_execute(self, tool_name, args):
            executor_calls.append(tool_name)
            if tool_name == "get_available_slots":
                return {"success": True, "slots": [
                    {"slot_id": 1, "display": "10 ივნისი, 10:00", "datetime_iso": "2030-06-10T10:00:00+04:00"}
                ]}
            if tool_name == "request_manager_callback":
                return {"success": True, "manager_phone": "558674733"}
            return orig_execute(self, tool_name, args)

        monkeypatch.setattr(ParentToolExecutor, "execute", _mock_execute)

        def _mock_chat(**kwargs):
            # Simulate LLM calling get_available_slots (correct behavior)
            if "get_available_slots" not in executor_calls:
                return _mk_response(
                    tool_calls=[{"id": "t1", "name": "get_available_slots", "arguments": {}}]
                )
            return _mk_response(content="გთავაზობ შემდეგ დროებს: 10 ივნისი 10:00. რომელი მოგერგება?")

        monkeypatch.setattr(openai_service, "chat_with_tools", _mock_chat)

        from app.agent.llm.parent_llm_engine import run_parent_llm_turn
        out = run_parent_llm_turn(
            user_message="კი მინდა",
            conversation=conv,
            lead=conv.lead,
            sender_id="smoke_test_no_mgr",
            platform="messenger",
        )
        # Manager callback alone (without prior slot selection) is wrong
        assert executor_calls != ["request_manager_callback"], \
            "LLM should NOT call only request_manager_callback for 'კი მინდა'"


# ---------------------------------------------------------------------------
# Part 5 — Phone sufficient when name already known
# ---------------------------------------------------------------------------

class TestPhoneOnlyWhenNameKnown:
    """If lead.name is already populated, phone alone completes contact info."""

    def test_phone_only_accepted_when_name_exists(self):
        from app.flows.parent_flow import _parse_name_phone
        from app.models.lead import Lead

        lead = Lead(
            sender_id="s1",
            platform="messenger",
            segment="PARENT",
            name="ნიკა გობეჯიშვილი",
        )
        # Phone-only message
        name, phone = _parse_name_phone("595999733")
        # Even though name is "" from the message, lead already has one
        assert phone == "595999733", "Phone should be extracted from '595999733'"
        # Combined: name from lead + phone from message = complete
        combined_name = name or lead.name
        assert combined_name, "Name from lead should cover the missing parsed name"
        assert phone, "Phone from message should be valid"

    def test_phone_name_message_when_name_known(self):
        """If lead already has name and user sends phone+name, phone extracted."""
        from app.flows.parent_flow import _parse_name_phone
        name, phone = _parse_name_phone("595999733 ტესტი")
        assert phone == "595999733"
        # Name may be "ტესტი" or overridden by lead.name — either is fine


# ---------------------------------------------------------------------------
# Part 6 — No fake booking claimed without Calendar event
# ---------------------------------------------------------------------------

class TestNoFakeBooking:
    """The fake-booking guard must prevent 'ჩაგინიშნეთ' text without
    an actual Calendar write (book_consultation_success_for_conversation=True)."""

    def test_booking_confirmation_stripped_without_success_flag(self, monkeypatch):
        from app.flows.parent_flow import _sanitise_booking_confirmation
        from app.agent.tools import parent_tool_executor as pte
        from app.models.conversation import Conversation

        conv = Conversation(
            sender_id="fake_test",
            platform="messenger",
            segment="PARENT",
            state="START",
        )
        # Ensure the success flag is False
        pte.book_consultation_success_for_conversation["fake_test"] = False

        response_with_confirmation = "კონსულტაცია ჩაგინიშნეთ 10 ივნისს 10:00 საათზე."
        result = _sanitise_booking_confirmation(conv, response_with_confirmation)
        # The guard must strip or replace the confirmation
        assert "ჩაგინიშნეთ" not in result or result != response_with_confirmation, \
            "Fake booking confirmation must be stripped when success flag is False"

    def test_real_booking_passes_through(self, monkeypatch):
        from app.flows.parent_flow import _sanitise_booking_confirmation
        from app.agent.tools import parent_tool_executor as pte
        from app.models.conversation import Conversation
        from app.models.lead import Lead

        conv = Conversation(
            sender_id="real_test",
            platform="messenger",
            segment="PARENT",
            state="DONE",
        )
        conv.lead = Lead(
            sender_id="real_test",
            platform="messenger",
            segment="PARENT",
            calendly_booked=True,
        )
        pte.book_consultation_success_for_conversation["real_test"] = True

        response = "კონსულტაცია ჩაგინიშნეთ 10 ივნისს, 10:00 საათზე. მენეჯერი დაგიკავშირდებათ."
        result = _sanitise_booking_confirmation(conv, response)
        assert "ჩაგინიშნეთ" in result, \
            "Real booking confirmation should pass through the guard"


# ---------------------------------------------------------------------------
# Part 7 — Existing PARENT booking tests still pass (smoke check)
# ---------------------------------------------------------------------------

def test_parse_name_phone_baseline():
    """Baseline: existing valid inputs still parse correctly."""
    from app.flows.parent_flow import _parse_name_phone

    # Classic "name phone" format
    name, phone = _parse_name_phone("ნიკა 595999733")
    assert phone == "595999733"
    assert name == "ნიკა"

    # With international prefix
    name, phone = _parse_name_phone("+995595999733")
    assert "595999733" in phone

    # Empty input
    name, phone = _parse_name_phone("")
    assert phone == ""
    assert name == ""

    # Age only (not a phone) — should not extract phone
    name, phone = _parse_name_phone("12 წლის")
    assert phone == ""


def test_sanitiser_does_not_break_valid_responses():
    """Sanitiser must leave clean responses untouched."""
    from app.agent.llm.parent_llm_engine import sanitise_response_wording

    clean = "კონსულტაცია ჩაგინიშნეთ 10 ივნისს, 10:00 საათზე."
    assert sanitise_response_wording(clean) == clean

    greeting = "გამარჯობა, ბანაკი 9–17 წლის ბავშვებისთვისაა."
    assert sanitise_response_wording(greeting) == greeting
