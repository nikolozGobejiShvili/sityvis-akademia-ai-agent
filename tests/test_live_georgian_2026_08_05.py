"""Three Georgian defects from the Railway session of 2026-08-05 18:31–18:41.

  18:33  „სასიამოვნოა, ხვალ 6 აგვისტოს 17:00 თავისუფალია!"
         A free slot is a fact, not a pleasure. The opener carries no
         information and reads as translated-sounding Georgian.

  18:40  „ჯავშანი გააუქმოთ, თუ გნებავთ?"
         The agent offers to cancel, but conjugates it in the SECOND person —
         „YOU cancel" — so the offer reads as an instruction to the parent. It
         cancels through `manage_consultation_booking` itself.

  18:41  „თუ რამე დაგჭირდებათ,. ნახვამდის!"
         A comma left touching a period.

Each is a REWRITE of the agent's own output, never an input matcher: nothing
here can change which question the agent recognises. „თუ გნებავთ" is left alone
on purpose — it is approved PARENT wording (the prompt and templates use it
throughout); only the ADULT prompt bans it.

Operator decision, same session: fix these three and NOTHING else. Adding more
bans makes the agent answer real questions wrongly.
"""

from __future__ import annotations

from app.agent.llm.parent_llm_engine import (
    FORBIDDEN_PHRASE_REPLACEMENTS,
    sanitise_response_wording,
)


# ── 18:33 — the empty opener ────────────────────────────────────────────────
def test_live_slot_reply_loses_the_empty_opener():
    live = "სასიამოვნოა, ხვალ 6 აგვისტოს 17:00 თავისუფალია!"

    out = sanitise_response_wording(live)

    assert out == "ხვალ 6 აგვისტოს 17:00 თავისუფალია!"


def test_the_opener_is_stripped_only_at_the_start_of_a_line():
    """Mid-sentence the word is ordinary Georgian and must survive."""
    text = "ძალიან სასიამოვნოა, რომ დაინტერესდით."

    assert sanitise_response_wording(text) == text


# ── 18:40 — the cancellation offer in the wrong person ──────────────────────
def test_live_cancellation_offer_is_first_person():
    live = "თუ გადაიფიქრებთ, მოხარული ვიქნებით. ჯავშანი გააუქმოთ, თუ გნებავთ?"

    out = sanitise_response_wording(live)

    assert "გსურთ, ჯავშანი გავაუქმო?" in out
    assert "გააუქმოთ" not in out


def test_bare_cancellation_question_is_first_person_too():
    out = sanitise_response_wording("ჯავშანი გააუქმოთ?")

    assert out == "გსურთ, ჯავშანი გავაუქმო?"


def test_tu_gnebavt_is_not_touched_elsewhere():
    """Approved PARENT wording — the prompt and templates use it throughout."""
    text = "თუ გნებავთ, კონსულტაციაზე ჩაგწერთ."

    assert sanitise_response_wording(text) == text


# ── 18:41 — the punctuation ─────────────────────────────────────────────────
def test_live_farewell_loses_the_stray_comma():
    live = "გასაგებია, მარიამ! თუ რამე დაგჭირდებათ,. ნახვამდის!"

    out = sanitise_response_wording(live)

    assert ",." not in out
    assert "თუ რამე დაგჭირდებათ. ნახვამდის!" in out


def test_an_ordinary_comma_survives():
    text = "გასაგებია, მარიამ. კონსულტაცია ჩაგინიშნეთ."

    assert sanitise_response_wording(text) == text


# ── scope of the change ─────────────────────────────────────────────────────
def test_all_three_are_idempotent():
    live = (
        "სასიამოვნოა, ხვალ 17:00 თავისუფალია!\n"
        "ჯავშანი გააუქმოთ?\n"
        "თუ რამე დაგჭირდებათ,. ნახვამდის!"
    )

    once = sanitise_response_wording(live)

    assert sanitise_response_wording(once) == once


def test_the_forbidden_phrase_table_did_not_grow():
    """These are rewrites of the agent's own wording, not new prohibitions.
    The ban list stays where it was."""
    assert len(FORBIDDEN_PHRASE_REPLACEMENTS) == 183
