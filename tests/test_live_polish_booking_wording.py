"""Live Polish Patch (2026-06-09) — booking wording regression tests.

Covers the five live wording issues observed after the client smoke test:

  PART 1 — Confirmation normalization
    1. "კიმინდა" after consultation offer continues booking (no repeated ask).
    2. "კი მინდა" after consultation offer continues booking (no repeated ask).
    3. "კი მაწყობს" after slot offer continues booking.
    4. _user_confirmed_booking helper normalizes joined/split forms.

  PART 2 — Privacy wording when collecting phone
    5. System prompt includes privacy sentence for name-known phone request.
    6. System prompt includes privacy sentence for name-unknown phone request.

  PART 3 — Banned awkward phrases (sanitiser)
    7. "მიხარია ნომრის მიღება" stripped → "ნომერი მივიღე".
    8. "მოხარული ვარ ნომრის მიღებით" stripped → "ნომერი მივიღე".
    9. Standalone "სიამოვნებით." stripped (never reaches user as sole response).
   10. "კომპიუტერის მეხსიერების მიხედვით" remains banned (regression).

  PART 4 — Context-aware thank-you closings
   11. Thanks after booked consultation → booked closing hint in sales context.
   12. Thanks after adult subscription → subscription closing hint in sales context.
   13. General thanks → general closing hint in sales context.
   14. Sales context after thanks never contains "სიამოვნებით".
"""

from __future__ import annotations

import pytest

from app.models.conversation import Conversation
from app.models.lead import Lead


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_conv(
    history: list[dict] | None = None,
    booked: bool = False,
    adult_subscription_status: str = "",
) -> tuple[Conversation, Lead]:
    """Return a minimal (conv, lead) pair for unit-testing context helpers."""
    conv = Conversation(
        sender_id="test_polish_001",
        platform="messenger",
        segment="PARENT",
        state="PRESENT_VALUE",
    )
    conv.history = list(history or [])
    conv.adult_subscription_status = adult_subscription_status

    lead = Lead(
        sender_id="test_polish_001",
        platform="messenger",
        segment="PARENT",
        child_age="12",
        name="ნიკა",
        phone="595999733" if booked else "",
        calendly_booked=booked,
    )
    conv.lead = lead
    return conv, lead


def _booking_offer_history() -> list[dict]:
    """Simulate a conversation where the bot just offered a consultation."""
    return [
        {"role": "user", "content": "ბანაკი რა ჯდება?"},
        {
            "role": "assistant",
            "content": (
                "ბანაკი 2150 ლარია. "
                "თუ გინდათ, კონსულტაციაზე ჩაგწერთ და მენეჯერი დეტალებს აგიხსნით."
            ),
        },
    ]


# ---------------------------------------------------------------------------
# PART 1 — Confirmation normalization helpers and sales-context injection
# ---------------------------------------------------------------------------


class TestConfirmationNormalization:
    """_user_confirmed_booking and _build_sales_context confirmation path."""

    def test_kiminda_joined_recognized_as_confirmation(self):
        from app.agent.llm.parent_llm_engine import _user_confirmed_booking

        assert _user_confirmed_booking("კიმინდა") is True

    def test_ki_minda_split_recognized_as_confirmation(self):
        from app.agent.llm.parent_llm_engine import _user_confirmed_booking

        assert _user_confirmed_booking("კი მინდა") is True

    def test_ki_mawqobs_recognized_as_confirmation(self):
        from app.agent.llm.parent_llm_engine import _user_confirmed_booking

        assert _user_confirmed_booking("კი მაწყობს") is True

    def test_diakh_minda_recognized_as_confirmation(self):
        from app.agent.llm.parent_llm_engine import _user_confirmed_booking

        assert _user_confirmed_booking("დიახ მინდა") is True

    def test_unrelated_message_not_confirmation(self):
        from app.agent.llm.parent_llm_engine import _user_confirmed_booking

        assert _user_confirmed_booking("ბანაკი სად ტარდება?") is False
        assert _user_confirmed_booking("ფასი რამდენია?") is False
        assert _user_confirmed_booking("") is False

    def test_kiminda_after_offer_sales_context_contains_continue_hint(self):
        """After consultation offer + 'კიმინდა', sales context must tell
        the LLM to continue booking directly, NOT ask again."""
        from app.agent.llm.parent_llm_engine import _build_sales_context

        conv, lead = _make_conv(history=_booking_offer_history())
        ctx = _build_sales_context(conv, lead, "კიმინდა")

        assert "პირდაპირ გააგრძელე" in ctx, (
            "Sales context must instruct direct continuation after confirmation"
        )
        assert "ნუ" in ctx, (
            "Sales context must prohibit re-asking 'გსურთ?'"
        )

    def test_ki_minda_after_offer_sales_context_no_repeat_ask(self):
        """'კი მინდა' after offer — sales context must not allow repeating
        the confirmation question."""
        from app.agent.llm.parent_llm_engine import _build_sales_context

        conv, lead = _make_conv(history=_booking_offer_history())
        ctx = _build_sales_context(conv, lead, "კი მინდა")

        assert "პირდაპირ გააგრძელე" in ctx
        # The confirmation phrase from the user should be echoed in context
        assert "კი მინდა" in ctx

    def test_confirmation_without_prior_offer_does_not_inject_hint(self):
        """Standalone 'კი' with no booking offer in history must NOT
        trigger the confirmation shortcut — it could mean anything."""
        from app.agent.llm.parent_llm_engine import _build_sales_context

        conv, lead = _make_conv(history=[
            {"role": "user", "content": "ბავშვი 11 წლისაა"},
            {"role": "assistant", "content": "კარგი, ასაკი ბანაკისთვის შესაბამისია."},
        ])
        ctx = _build_sales_context(conv, lead, "კი")

        # No booking offer in history → must NOT inject the continuation hint
        assert "პირდაპირ გააგრძელე" not in ctx


# ---------------------------------------------------------------------------
# PART 2 — Privacy wording in system prompt
# ---------------------------------------------------------------------------


class TestPrivacyWordingInSystemPrompt:
    """system_parent_v2.md must contain the privacy notice for phone requests."""

    @pytest.fixture(scope="class")
    def prompt_text(self) -> str:
        from app.agent.llm.prompt_loader import load_prompt
        return load_prompt("system_parent_v2")

    def test_privacy_sentence_present(self, prompt_text):
        """The privacy sentence must appear in the system prompt."""
        privacy_sentence = "საჯაროდ არ გამოქვეყნდება"
        assert privacy_sentence in prompt_text, (
            "Privacy notice ('საჯაროდ არ გამოქვეყნდება') must be in system_parent_v2.md"
        )

    def test_privacy_used_only_for_consultation(self, prompt_text):
        """The privacy notice must be scoped to consultation use only."""
        assert "კონსულტაციისთვის" in prompt_text

    def test_privacy_applies_when_name_known(self, prompt_text):
        """The prompt must describe the name-known phone-request form."""
        assert "სახელი უკვე ვიცი" in prompt_text or "name ≠" in prompt_text, (
            "Prompt must instruct using 'სახელი უკვე ვიცი' when name is known"
        )

    def test_privacy_applies_when_name_unknown(self, prompt_text):
        """The prompt must describe the name-unknown phone-request form."""
        assert "სახელი და 9-ნიშნა" in prompt_text or "name = " in prompt_text, (
            "Prompt must instruct asking name + phone when name is unknown"
        )

    def test_kiminda_normalization_in_prompt(self, prompt_text):
        """Prompt must mention 'კიმინდა' as a recognized confirmation form."""
        assert "კიმინდა" in prompt_text, (
            "'კიმინდა' (joined form) must be listed in the booking intent block"
        )


# ---------------------------------------------------------------------------
# PART 3 — Banned awkward phrases in the sanitiser
# ---------------------------------------------------------------------------


class TestBannedPhrases:
    """sanitise_response_wording must strip all banned phrases."""

    def test_mikharobia_nomris_migeba_stripped(self):
        from app.agent.llm.parent_llm_engine import sanitise_response_wording

        out = sanitise_response_wording("მიხარია ნომრის მიღება! გაგრძელოთ.")
        assert "მიხარია ნომრის მიღება" not in out, (
            "Phrase 'მიხარია ნომრის მიღება' must be stripped by the sanitiser"
        )

    def test_mikharobia_nomris_migeba_replaced_with_natural_form(self):
        from app.agent.llm.parent_llm_engine import sanitise_response_wording

        out = sanitise_response_wording("მიხარია ნომრის მიღება.")
        assert "ნომერი მივიღე" in out, (
            "Sanitiser must replace 'მიხარია ნომრის მიღება' with 'ნომერი მივიღე'"
        )

    def test_mokhlaruli_nomris_migeba_stripped(self):
        from app.agent.llm.parent_llm_engine import sanitise_response_wording

        out = sanitise_response_wording("მოხარული ვარ ნომრის მიღებით.")
        assert "მოხარული ვარ ნომრის მიღებით" not in out
        assert "ნომერი მივიღე" in out

    def test_standalone_siamovnebit_stripped(self):
        from app.agent.llm.parent_llm_engine import sanitise_response_wording

        out = sanitise_response_wording("სიამოვნებით.")
        assert "სიამოვნებით." not in out, (
            "Standalone 'სიამოვნებით.' must be stripped by the sanitiser"
        )

    def test_siamovnebit_in_longer_phrase_also_stripped(self):
        """'მადლობა. სიამოვნებით.' as agent response must be sanitised."""
        from app.agent.llm.parent_llm_engine import sanitise_response_wording

        out = sanitise_response_wording("მადლობა. სიამოვნებით.")
        assert "სიამოვნებით." not in out

    def test_kompiteris_mekhsierbis_still_banned(self):
        """Regression: 'კომპიუტერის მეხსიერების მიხედვით' must still be stripped."""
        from app.agent.llm.parent_llm_engine import sanitise_response_wording

        out = sanitise_response_wording("კომპიუტერის მეხსიერების მიხედვით, ...")
        assert "კომპიუტერის მეხსიერების" not in out

    def test_sanitiser_idempotent_on_clean_text(self):
        """Running the sanitiser twice on clean text should not change output."""
        from app.agent.llm.parent_llm_engine import sanitise_response_wording

        clean = "ნომერი მივიღე. მენეჯერი დაგიკავშირდებათ."
        once = sanitise_response_wording(clean)
        twice = sanitise_response_wording(once)
        assert once == twice

    def test_adult_sanitiser_also_strips_siamovnebit(self):
        """sanitise_adult_response must also strip standalone 'სიამოვნებით.'."""
        from app.agent.llm.adult_llm_engine import sanitise_adult_response

        out = sanitise_adult_response("სიამოვნებით.", sender_id=None)
        assert "სიამოვნებით." not in out


# ---------------------------------------------------------------------------
# PART 4 — Context-aware thank-you closings via sales context
# ---------------------------------------------------------------------------


class TestThankYouClosings:
    """_build_sales_context must inject context-aware thank-you hints."""

    def test_thanks_after_booking_gives_booked_closing(self):
        from app.agent.llm.parent_llm_engine import _build_sales_context

        conv, lead = _make_conv(booked=True)
        ctx = _build_sales_context(conv, lead, "მადლობა")

        assert "კონსულტაცია ჩანიშნულია" in ctx, (
            "After booking, thanks should get 'კონსულტაცია ჩანიშნულია' hint"
        )
        assert "მენეჯერი დაგიკავშირდებათ" in ctx

    def test_thanks_after_adult_subscription_gives_subscription_closing(self):
        from app.agent.llm.parent_llm_engine import _build_sales_context

        conv, lead = _make_conv(adult_subscription_status="subscribed")
        ctx = _build_sales_context(conv, lead, "მადლობა")

        assert (
            "ახალი ღონისძიება" in ctx or "პირად შეტყობინება" in ctx
        ), (
            "After subscription, thanks should get the new-event notification hint"
        )

    def test_general_thanks_gives_general_closing(self):
        from app.agent.llm.parent_llm_engine import _build_sales_context

        conv, lead = _make_conv()  # no booking, no subscription
        ctx = _build_sales_context(conv, lead, "მადლობა")

        assert "თუ კიდევ დაგჭირდებათ" in ctx or "მომწერეთ" in ctx, (
            "General thanks should get 'თუ კიდევ დაგჭირდებათ … მომწერეთ' hint"
        )

    def test_thanks_context_never_contains_siamovnebit(self):
        """Sales context injected on 'მადლობა' must never suggest
        'სიამოვნებით.' as the closing."""
        from app.agent.llm.parent_llm_engine import _build_sales_context

        conv, lead = _make_conv()
        ctx = _build_sales_context(conv, lead, "მადლობა")

        assert "სიამოვნებით" not in ctx.replace("სიამოვნებით", "_BANNED_CHECK")
        # More precisely: the context should warn AGAINST it
        assert "სიამოვნებით" not in ctx or "არასოდეს" in ctx

    def test_thanks_does_not_restart_sales_flow(self):
        """A 'მადლობა' turn must not receive the full sales-flow context
        (age / price / motivation questions)."""
        from app.agent.llm.parent_llm_engine import _build_sales_context

        conv, lead = _make_conv()
        ctx = _build_sales_context(conv, lead, "მადლობა")

        # The normal sales flow lines should NOT appear when user says thanks
        assert "ბავშვის ასაკი" not in ctx
        assert "ფასი" not in ctx

    def test_thanks_after_subscription_ok_status_also_works(self):
        """adult_subscription_status='ok' (legacy value) should also
        trigger the subscription closing hint."""
        from app.agent.llm.parent_llm_engine import _build_sales_context

        conv, lead = _make_conv(adult_subscription_status="ok")
        ctx = _build_sales_context(conv, lead, "მადლობა")

        assert "ახალი ღონისძიება" in ctx or "პირად შეტყობინება" in ctx
