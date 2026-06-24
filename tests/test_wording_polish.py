"""Georgian wording polish patch — sanitiser regression tests.

Covers the post-Redis live-QA wording bugs:

  * "გეთანხმებით ამ დროით" / "გეთანხმებით" must never reach the user.
  * "დაჭვება" / "დაეჭვება" are typos — must be rewritten to "კითხვა".
  * Double-conditional closings ("თუ რამე დაგჭირდებათ, თუ კიდევ რამე…")
    must collapse to a single natural phrase.
  * Robotic "ყოველთვის მზად ვარ" / "აქ ვარ თქვენთვის" must be stripped.

These tests bypass the LLM entirely and assert directly against
``sanitise_response_wording`` — that's the choke point every engine
response passes through before reaching the user.
"""

from __future__ import annotations

import pytest

from app.agent.llm.parent_llm_engine import sanitise_response_wording


# Phrases that must never survive the sanitiser, regardless of context.
FORBIDDEN_FRAGMENTS: tuple[str, ...] = (
    "გეთანხმებით ამ დროით",
    "დაეჭვება",
    "დაჭვება",
    "თუ რამე დაგჭირდებათ, თუ კიდევ",
    "თუ რამე დაგჭირდება, თუ კიდევ",
    "ყოველთვის მზად ვარ",
    "აქ ვარ თქვენთვის",
)


# -- (1) Slot-confirmation rewrite ----------------------------------------


def test_slot_confirmation_geethanxmebit_at_dro_rewritten():
    bad = (
        "29 მაისს, 15:00 თავისუფალია. კონსულტაციის ჩასანიშნად "
        "დამიდასტურეთ, გეთანხმებით ამ დროით."
    )
    out = sanitise_response_wording(bad)

    assert "გეთანხმებით" not in out
    # Final output should still contain the date/time + the natural
    # user-side confirmation phrase.
    assert "29 მაისს, 15:00 თავისუფალია" in out
    assert ("დამიდასტურეთ" in out) or ("თუ ეს დრო გაწყობთ" in out)
    assert "კონსულტაცია" in out


def test_standalone_geethanxmebit_dropped():
    out = sanitise_response_wording("გასაგებია. გეთანხმებით.")
    assert "გეთანხმებით" not in out
    # The sanitiser collapses leftover punctuation, so the line should
    # still be a clean Georgian sentence — not "გასაგებია . ."
    assert "გასაგებია" in out
    assert ". ." not in out
    assert ".." not in out


# -- (2) Typo / misspelling fix -------------------------------------------


def test_dachveba_rewritten_to_kitkhva():
    out = sanitise_response_wording(
        "თუ რამე დაჭვება, თუ კიდევ რამე დაგჭირდება, მომწერეთ"
    )
    assert "დაჭვება" not in out
    assert "დაეჭვება" not in out
    # The collapsed closing should mention either "კითხვა" directly or
    # "გაგიჩნდებათ" (the natural Georgian form for "have a question").
    assert ("კითხვა" in out) or ("გაგიჩნდებათ" in out)


def test_daecheba_rewritten_to_kitkhva():
    out = sanitise_response_wording(
        "თუ კიდევ რაიმე დაეჭვება გაგიჩნდებათ, შემეხმიანეთ"
    )
    assert "დაეჭვება" not in out
    assert "კითხვა" in out


# -- (3) Duplicated "თუ … თუ …" collapser ---------------------------------


def test_duplicated_tu_clause_collapsed():
    bad = (
        "თუ მომავალში რაიმე კითხვა გაგიჩნდებათ, თუ კიდევ რაიმე "
        "გაგიჩნდებათ, შემეხმიანეთ."
    )
    out = sanitise_response_wording(bad)
    # Only ONE "თუ ... გაგიჩნდებათ" clause should remain after the
    # collapser. The double form must be gone.
    assert out.count("გაგიჩნდებათ,") <= 1
    assert "გაგიჩნდებათ, თუ" not in out


# -- (4) Robotic "always available" closers -------------------------------


def test_always_ready_phrase_stripped():
    out = sanitise_response_wording(
        "მადლობა. ყოველთვის მზად ვარ."
    )
    assert "ყოველთვის მზად ვარ" not in out


def test_robotic_aq_var_stripped():
    out = sanitise_response_wording(
        "მადლობა თქვენ. მე აქ ვარ თქვენთვის."
    )
    assert "აქ ვარ თქვენთვის" not in out


# -- (5) Catch-all: no forbidden fragment survives sanitisation -----------


@pytest.mark.parametrize(
    "input_text",
    [
        "29 მაისს 15:00 თავისუფალია. გეთანხმებით ამ დროით.",
        "თუ რამე დაჭვება გაგიჩნდებათ, შემეხმიანეთ.",
        "თუ რამე დაგჭირდებათ, თუ კიდევ რამე გჭირდებათ, მომწერეთ.",
        "მადლობა. ყოველთვის მზად ვარ.",
        "კი, აქ ვარ თქვენთვის ნებისმიერ დროს.",
        "ხელახლა მოგვწერეთ თუ რამე დაეჭვება გაგიჩნდებათ.",
    ],
)
def test_no_forbidden_fragment_survives(input_text):
    out = sanitise_response_wording(input_text)
    for fragment in FORBIDDEN_FRAGMENTS:
        assert fragment not in out, (
            f"sanitiser left forbidden fragment {fragment!r} in "
            f"output {out!r} (input was {input_text!r})"
        )


# -- (6) Idempotence — running twice does not damage clean text -----------


def test_sanitiser_idempotent_on_clean_text():
    clean = (
        "29 მაისს, 15:00 თავისუფალია. თუ ეს დრო გაწყობთ, "
        "დამიდასტურეთ და კონსულტაციას ჩავნიშნავ."
    )
    once = sanitise_response_wording(clean)
    twice = sanitise_response_wording(once)
    assert once == twice
    assert "გეთანხმებით" not in once
    assert "თუ ეს დრო გაწყობთ" in once


def test_sanitiser_strips_leaf_emoji_from_short_thanks():
    """Agent Wording Cleanup Patch (2026-06-03): production replies
    are emoji-free. The sanitiser strips 🌿 cleanly without breaking
    the surrounding wording."""
    out = sanitise_response_wording("მადლობა თქვენ 🌿")
    assert "🌿" not in out
    assert out == "მადლობა თქვენ"


def test_sanitiser_strips_leaf_emoji_from_decline_closing():
    """Same — embedded 🌿 is removed, the Georgian closing stays."""
    text = "გასაგებია 🌿 თუ დამატებითი კითხვა გაგიჩნდებათ, მოგვწერეთ."
    out = sanitise_response_wording(text)
    assert "🌿" not in out
    # Order of words preserved, single-space cleanup applied.
    assert out == "გასაგებია თუ დამატებითი კითხვა გაგიჩნდებათ, მოგვწერეთ."
