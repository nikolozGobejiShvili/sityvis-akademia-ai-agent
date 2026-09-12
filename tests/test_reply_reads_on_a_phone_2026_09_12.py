"""Replies arrived as one wall of text (live 2026-09-12).

On a phone the answers about invited guests and about the teachers came through
as a single block — four and five sentences with no break — while the locations
answer, which the model happened to structure itself, read fine. The formatting
a parent gets depended on the model's mood.

Two formatters already existed and neither could help:

  * `_format_multipoint_paragraphs` fired only on price/value wording, which a
    guest or teacher answer has none of;
  * both returned early on the FIRST blank line in the reply, so the teachers
    answer — a one-line heading followed by a five-sentence wall — counted as
    „already paragraphed" and was left alone.

`_format_reply_paragraphs` looks at every block on its own and is tied to no
topic. Whitespace only: a block that already carries single newlines is a list
and is never touched, and the wording must come out identical.
"""
from __future__ import annotations

from app.flows import parent_flow

# Screenshot_8 — one block, four sentences.
_GUESTS = (
    "კონკრეტული მოწვეული სტუმრების სახელები ჯერ არ არის გამოცხადებული. "
    "პროგრამის ფარგლებში ბავშვებს შეხვედრა ექნებათ რეალურ პროფესიონალებთან, "
    "რომლებიც გაუზიარებენ პრაქტიკულ გამოცდილებასა და რჩევებს. "
    "კონკრეტული სტუმრების შესახებ დეტალური ინფორმაციისთვის "
    "დაგვიკავშირდით: 558 67 47 33"
)

# Screenshot_10 — a heading, then a five-sentence wall under it.
_TEACHERS = (
    "პედაგოგების შესახებ შეგვიძლია გითხრათ, რომ:\n\n"
    "აკადემიის გუნდი დაკომპლექტებულია გამოცდილი ფსიქოლოგებითა და "
    "ლიტერატორებით, რომლებსაც ბავშვებთან მუშაობის მრავალწლიანი პრაქტიკა აქვთ. "
    "თითოეულ ჯგუფს, ასაკობრივი კატეგორიის შესაბამისად, ჰყავს საკუთარი "
    "ფსიქოლოგიისა და ლიტერატურის პედაგოგი. კონკრეტული პედაგოგების სახელების "
    "შესახებ უფრო სრულ ინფორმაციას მოგაწვდით ჩვენი მენეჯერი. "
    "დაგვიკავშირდით: 558 67 47 33"
)

# Screenshot_11 — the one that already read well. It must survive untouched.
_LOCATIONS = (
    "საკვირაო სკოლის შეხვედრები იმართება შემდეგ ლოკაციებზე:\n\n"
    "თბილისი:\nშაბათი — Holiday Inn Tbilisi და Hilton Garden Inn Tbilisi "
    "Chavchavadze\nკვირა — Paragraph Freedom Square\n\n"
    "ბათუმი:\nშაბათი — Le Méridien Batumi"
)

_SHORT = "თითოეული შეხვედრის ხანგრძლივობა 1 საათი და 30 წუთია."


def _blocks(text: str) -> int:
    return len([b for b in text.split("\n\n") if b.strip()])


def _words(text: str) -> str:
    return "".join(text.split())


# ── the walls are broken up ────────────────────────────────────────────────

def test_a_single_block_answer_becomes_paragraphs():
    out = parent_flow._format_reply_paragraphs(_GUESTS)
    assert _blocks(out) == 3
    assert _words(out) == _words(_GUESTS)


def test_a_wall_under_a_heading_is_formatted_too():
    """The case both existing formatters walked past."""
    out = parent_flow._format_reply_paragraphs(_TEACHERS)
    assert _blocks(out) == 5
    assert _words(out) == _words(_TEACHERS)


def test_it_is_not_tied_to_price_or_to_any_topic():
    """The old formatter needed two price/value signals to fire."""
    neutral = (
        "პროგრამა მოიცავს თორმეტ შეხვედრას სასწავლო წლის განმავლობაში. "
        "შეხვედრები იმართება შაბათს ან კვირას, ჯგუფის განრიგის მიხედვით. "
        "თითოეულ ჯგუფს ჰყავს საკუთარი პედაგოგი და ფსიქოლოგი."
    )
    assert _blocks(parent_flow._format_reply_paragraphs(neutral)) == 3


# ── and nothing else is disturbed ──────────────────────────────────────────

def test_a_list_is_left_exactly_as_written():
    assert parent_flow._format_reply_paragraphs(_LOCATIONS) == _LOCATIONS


def test_a_short_answer_is_untouched():
    assert parent_flow._format_reply_paragraphs(_SHORT) == _SHORT


def test_two_sentences_are_not_split():
    two = (
        "საკვირაო სკოლა სამთვიანი პროგრამაა და მოიცავს თორმეტ შეხვედრას "
        "ლიტერატურასა და ფსიქოლოგიაში. შეხვედრები შაბათს ან კვირას იმართება."
    )
    assert parent_flow._format_reply_paragraphs(two) == two


def test_it_never_changes_the_wording():
    for text in (_GUESTS, _TEACHERS, _LOCATIONS, _SHORT):
        assert _words(parent_flow._format_reply_paragraphs(text)) == _words(text)


def test_it_is_idempotent():
    once = parent_flow._format_reply_paragraphs(_GUESTS)
    assert parent_flow._format_reply_paragraphs(once) == once


def test_empty_and_none_safe():
    assert parent_flow._format_reply_paragraphs("") == ""
    assert parent_flow._format_reply_paragraphs(None) is None
