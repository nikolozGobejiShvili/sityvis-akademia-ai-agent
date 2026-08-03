"""The agent must address a parent with the polite „თქვენ", never „შენ".

Georgian distinguishes a singular „შენ" from a polite „თქვენ", and the brand uses
only the polite form. The model slips into the singular when a parent writes
emotionally — measured on R41-angry-user and T04-conditions (3/3 -> 2/3 on the
41-case eval), and live on 2026-08-02 in „ნიკოლოზ, გესმის შენი უკმაყოფილება".

Why this is not a prompt rule: it WAS one, and was ignored at both prompt sizes —
53k, and the 4.6k v3 where the wrong form is named with a worked example. A rule
the model ignores at every size is a mechanical rewrite, and belongs beside the
„აკადემიაის" -> „აკადემიის" genitive fix in the sanitizer.

„გესმის" is a separate error: not informal but wrong-person. It tells the parent
that THEY understand. The empathic first person is „მესმის" / „გვესმის".
"""
from __future__ import annotations

import pytest

from app.agent.llm import parent_llm_engine as engine

_normalise = engine._normalise_polite_address


# --- the forms measured in real replies ----------------------------------

@pytest.mark.parametrize("broken,expected_fragment", [
    # live 2026-08-02, price objection
    ("ნიკოლოზ, გესმის თქვენი უკმაყოფილება", "გვესმის თქვენი"),
    ("მარიამ, გესმის შენი განცდა", "გვესმის თქვენი"),
    # eval R41 / T04
    ("შენი გრძნობა სრულიად გასაგებია", "თქვენი გრძნობა"),
    ("გარდა ამისა, გაქვს ფასდაკლებები", "გაქვთ ფასდაკლებები"),
    ("თუ წინა ბანაკის მონაწილე ხარ", "მონაწილე ხართ"),
    ("თუ გინდა, ახლავე შემიძლია მოვიძიო", "თუ გსურთ"),
    ("რა გირჩევნია?", "რა გირჩევნიათ?"),
    ("გადახდა შეგიძლია გაანაწილო", "შეგიძლიათ"),
    ("რომ პირდაპირ გვეუბნები", "გვეუბნებით"),
    ("თუ სხვა კითხვა გაქვს, გეტყვი", "გეტყვით"),
])
def test_singular_address_is_rewritten(broken, expected_fragment):
    assert expected_fragment in _normalise(broken)


@pytest.mark.parametrize("bad", ["შენი", "შენს", "შენთვის", " შენ ", "გესმის"])
def test_no_singular_form_survives(bad):
    out = _normalise("წინადადება %s დაბოლოება" % bad)
    assert bad.strip() not in out.split()


# --- must not damage a reply that is already correct ----------------------

CORRECT = [
    "გვესმის თქვენი უკმაყოფილება და გმადლობთ, რომ გვიზიარებთ.",
    "თუ გსურთ, დაგაკავშირებთ მენეჯერთან.",
    "თქვენ უკვე გაქვთ დაჯავშნილი კონსულტაცია 10 აგვისტოს, 12:00 საათზე.",
    "ბანაკის მიმდინარე ნაკადები უკვე დასრულებულია.",
    "მე სიტყვის აკადემიის AI აგენტი ვარ. დაგეხმარებით: საკვირაო სკოლა, დისნეილენდი.",
    "რამდენი წლისაა თქვენი შვილი?",
    "მადლობა თქვენ. კონსულტაცია ჩანიშნულია და მენეჯერი დაგიკავშირდებათ.",
]


@pytest.mark.parametrize("text", CORRECT)
def test_correct_reply_is_untouched(text):
    assert _normalise(text) == text


@pytest.mark.parametrize("text", CORRECT + ["გესმის შენი განცდა, გაქვს დრო?"])
def test_idempotent(text):
    once = _normalise(text)
    assert _normalise(once) == once


# --- word boundaries: a longer word must never be corrupted ---------------

@pytest.mark.parametrize("text", [
    "თქვენ ხართ ჩვენი სტუმარი",      # ხართ must not become ხართთ
    "თქვენი შვილი მიხარია",           # ხარ inside მიხარია
    "იცით თუ არა",                    # იცი inside იცით
    "გაქვთ შესაძლებლობა",             # გაქვს-like tail
])
def test_word_boundaries_protect_longer_words(text):
    assert _normalise(text) == text


def test_runs_inside_the_public_sanitiser():
    """The guarantee is only real if sanitise_response_wording applies it."""
    out = engine.sanitise_response_wording("გესმის შენი განაწყენება.")
    assert "გვესმის" in out
    assert "თქვენი" in out
    assert "შენი" not in out


def test_prohibition_table_did_not_grow():
    """This fix must not be another banned phrase — the table stays at 183."""
    assert len(engine.FORBIDDEN_PHRASE_REPLACEMENTS) == 183
