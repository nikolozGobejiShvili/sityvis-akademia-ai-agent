"""The brand's own vocabulary, in the model's FREE text.

Taken verbatim from the Railway logs of 2026-08-03 21:11-21:17 — the first
conversation on the deploy that already carried the „კონსულტანტი" → „მენეჯერი"
template fix. The templates were right; the model wrote its own word anyway,
three times in six turns.

The sharpest one is „შემომწერეთ": it does not mean „write to me", it means
„subscribe to me". Every conversation was closing with an invitation to
subscribe to the agent.

These are rewrites, not bans — the sentence keeps its meaning and its place.
`FORBIDDEN_PHRASE_REPLACEMENTS` stays at 183.
"""
from __future__ import annotations

import pytest

from app.agent.llm import parent_llm_engine as engine

_brand = engine._normalise_brand_terms


# --- the exact live sentences --------------------------------------------

@pytest.mark.parametrize("live,expected_fragment", [
    ("თუ რამე კითხვა გექნებათ, ნებისმიერ დროს შემომწერეთ.",
     "ნებისმიერ დროს მომწერეთ"),
    ("კონსულტანტი დაგიკავშირდებათ. თუ რამე შეიცვლება, შემატყობინეთ!",
     "მენეჯერი დაგიკავშირდებათ"),
    ("დამატებითი დეტალები კონსულტანტთან დაზუსტება დაგჭირდებათ.",
     "მენეჯერთან დაზუსტება"),
    ("გსურთ კონსულტანტთან შეხვედრა დაჯავშნოთ?",
     "მენეჯერთან შეხვედრა"),
    ("ჩაწერა წარმატებით დასრულდა 💙 დეტალები:",
     "კონსულტაცია ჩაგინიშნეთ"),
    ("კონსულტაციები მიმდინარეობს 10:00-დან 21:00-მდე.",
     "კონსულტაციები ტარდება"),
    ("ნახვამდის და წარმატებულ კონსულტაციას გისურვებთ ხვალ 19:00 საათზე!",
     "შეხვედრამდე ხვალ 19:00"),
    ("გირჩევთ, ჩვენს კონსულტანტს დაუკავშირდეთ.",
     "მენეჯერს დაუკავშირდეთ"),
])
def test_live_sentence_is_corrected(live, expected_fragment):
    assert expected_fragment in _brand(live)


@pytest.mark.parametrize("wrong", ["შემომწერეთ", "კონსულტანტთან", "კონსულტანტს"])
def test_wrong_form_does_not_survive(wrong):
    assert wrong not in _brand("წინადადება %s დაბოლოება" % wrong)


# --- what must NOT change -------------------------------------------------

def test_the_agents_own_manner_is_not_rewritten():
    """„კონსულტანტი" is legitimate for the agent describing ITSELF.

    Blind replacement would produce „მე მენეჯერი ვარ" — the agent claiming to
    be the human the parent is waiting for.
    """
    text = "მე სიტყვის აკადემიის გაყიდვების კონსულტანტი ვარ."
    assert _brand(text) == text


@pytest.mark.parametrize("text", [
    "მენეჯერი დაგიკავშირდებათ მოსახერხებელ დროს.",
    "თუ გსურთ, მენეჯერთან დაგაკავშირებთ.",
    "ნებისმიერ დროს მომწერეთ.",
    "კონსულტაცია ჩაგინიშნეთ 5 აგვისტოს, 19:00 საათზე.",
    "კონსულტაციები ტარდება 10:00-დან 21:00-მდე.",
    "დისნეილენდის ფასია 4 000 ლარი.",
])
def test_already_correct_text_is_untouched(text):
    assert _brand(text) == text


@pytest.mark.parametrize("text", [
    "თუ რამე კითხვა გექნებათ, ნებისმიერ დროს შემომწერეთ.",
    "კონსულტანტი დაგიკავშირდებათ.",
    "ჩაწერა წარმატებით დასრულდა.",
    "მე გაყიდვების კონსულტანტი ვარ.",
])
def test_idempotent(text):
    once = _brand(text)
    assert _brand(once) == once


def test_runs_inside_the_public_sanitiser():
    out = engine.sanitise_response_wording(
        "კონსულტანტი დაგიკავშირდებათ. ნებისმიერ დროს შემომწერეთ.")
    assert "მენეჯერი დაგიკავშირდებათ" in out
    assert "შემომწერეთ" not in out


def test_prohibition_table_did_not_grow():
    assert len(engine.FORBIDDEN_PHRASE_REPLACEMENTS) == 183
