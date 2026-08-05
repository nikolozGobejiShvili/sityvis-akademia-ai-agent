"""Railway live test, 2026-08-05 10:08 — one message carried two questions.

A parent asked the Sunday-School price. The reply answered it and closed by
putting a question to the parent („გაქვთ დამატებითი კითხვები? მაგალითად,
გრაფიკი, ადგილმდებარეობა ან რეგისტრაცია — სიამოვნებით დაგეხმარებით."), and
then `_ensure_camp_age_question` grafted „თქვენი შვილი რამდენი წლისაა?" on top
of it. The log line is the proof it fired:

    [parent_flow] FIX2 appended camp age question (child_age unknown)

FIX 2 exists for a reply that asks NOTHING. When the reply already opens a
thread with the parent, the age arrives from the parent's own next turn — and
on the live conversation it did, on the very next message („ჩემი შვილი 10 წლის
არის").

These tests pin the FACT, not the wording of any reply.
"""

from __future__ import annotations

from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead


def _parent_conv(*, child_age: str = "") -> Conversation:
    conv = Conversation(
        sender_id="live-2026-08-05", platform="messenger", segment="PARENT",
    )
    conv.state = "START"
    lead = Lead(
        sender_id="live-2026-08-05", platform="messenger", segment="PARENT",
    )
    lead.child_age = child_age
    conv.lead = lead
    return conv


# Verbatim shape of the live reply (Railway 2026-08-05 10:08:46, reply_len=341):
# it asks mid-text and closes on a statement, so „ends with ?" would miss it.
LIVE_SUNDAY_SCHOOL_REPLY = (
    "საკვირაო სკოლის ფასი არის 200 ლარი თვეში. პროგრამა განკუთვნილია "
    "6–15 წლის ბავშვებისთვის.\n\n"
    "გაქვთ დამატებითი კითხვები? მაგალითად, გრაფიკი, ადგილმდებარეობა ან "
    "რეგისტრაცია — სიამოვნებით დაგეხმარებით."
)


def test_live_reply_that_already_asks_gets_no_second_question():
    conv = _parent_conv(child_age="")

    out = parent_flow._ensure_camp_age_question(
        conv, "გამარჯობა სკავირაო სკოლის ფასი მაინტერესებს რა ღირს ?",
        LIVE_SUNDAY_SCHOOL_REPLY,
    )

    assert out == LIVE_SUNDAY_SCHOOL_REPLY
    assert "რამდენი წლისაა" not in out
    assert out.count("?") == 1


def test_reply_ending_in_a_question_gets_no_second_question():
    conv = _parent_conv(child_age="")
    reply = "დისნეილენდის ფასი 4 000 ლარია. რომელი დეტალი გაინტერესებთ?"

    out = parent_flow._ensure_camp_age_question(conv, "დისნეილენდი", reply)

    assert out == reply


def test_reply_that_asks_nothing_still_gets_the_age_question():
    """FIX 2's original purpose is untouched — this is the case it exists for."""
    conv = _parent_conv(child_age="")
    reply = "სიტყვის აკადემიის პროგრამა 9-17 წლის ბავშვებისთვისაა."

    out = parent_flow._ensure_camp_age_question(
        conv, "ბავშვების საზაფხულო ბანაკი 9-17", reply,
    )

    assert "თქვენი შვილი რამდენი წლისაა?" in out


def test_a_registration_url_query_string_is_not_a_question():
    """„?" inside a link is followed by a non-space character, so a reply that
    only carries a registration URL still gets the age question."""
    conv = _parent_conv(child_age="")
    reply = "რეგისტრაციის ბმული: https://sityvisakademia.ge/reg?form=1"

    out = parent_flow._ensure_camp_age_question(conv, "რეგისტრაცია", reply)

    assert "თქვენი შვილი რამდენი წლისაა?" in out


def test_known_age_is_still_a_no_op():
    conv = _parent_conv(child_age="10")

    out = parent_flow._ensure_camp_age_question(
        conv, "ფასი?", "დისნეილენდის ფასი 4 000 ლარია.",
    )

    assert out == "დისნეილენდის ფასი 4 000 ლარია."
