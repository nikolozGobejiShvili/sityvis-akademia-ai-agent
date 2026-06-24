"""Batch Fix (2026-06-12) — name-capture root-cause regression guards.

Covers ROOT 1 (reject-list gaps: function words + booking stems), ROOT 2
(`_looks_like_contact_disclosure` phone bypass + multi-phone clarification),
and ROOT 3 (`_parse_name_phone` length cap). ROOT 4 (multi-child age) was
DEFERRED — see the report. All deterministic / offline.
"""

from __future__ import annotations

import pytest

from app.flows.parent_flow import (
    _distinct_valid_phones,
    _maybe_handle_contact_collection,
    _parse_name_phone,
    is_valid_person_name,
)
from app.models.conversation import Conversation
from app.models.lead import Lead

PHONE = "595999733"
_CONTACT_ASK_TURN = {
    "role": "assistant",
    "content": "მომწერეთ თქვენი სახელი და 9-ნიშნა საკონტაქტო ნომერი, "
               "რომ კონსულტაცია ჩავნიშნოთ.",
}


def _conv(**lk):
    conv = Conversation(sender_id="batch", platform="instagram")
    conv.segment = "PARENT"
    conv.state = "ASK_NAME"
    conv.history = [_CONTACT_ASK_TURN]
    lead = Lead(sender_id="batch", platform="instagram", segment="PARENT")
    for k, v in lk.items():
        setattr(lead, k, v)
    conv.lead = lead
    return conv, lead


def _name(msg: str) -> str:
    return _parse_name_phone(msg)[0]


# ===========================================================================
# ROOT 1 — function words + booking stems never saved as a name
# ===========================================================================
@pytest.mark.parametrize("word", ["ჩემი", "ან", "და", "გამარჯობა", "არის", "გთხოვთ"])
def test_root1_function_word_not_saved_as_name(word):
    assert word not in _name(f"{word} {PHONE}").split()
    assert word not in _name(f"{PHONE} {word}").split()
    assert is_valid_person_name(word) is False


@pytest.mark.parametrize("word", ["ჯავშანი", "გადანიშვნა"])
def test_root1_booking_word_not_saved_as_name(word):
    assert word not in _name(f"{word} {PHONE}").split()
    assert word not in _name(word).split()
    assert is_valid_person_name(word) is False


@pytest.mark.parametrize("name", ["ჯონი", "ლიზი", "ნინო", "გიორგი"])
def test_root1_legitimate_names_still_accepted(name):
    assert is_valid_person_name(name) is True
    assert _parse_name_phone(f"{name} {PHONE}") == (name, PHONE)


def test_root1_currently_rejected_words_stay_rejected():
    for w in ["მე", "ვარ", "ნომერი", "ნომერია", "სახელია", "მინდა", "კი"]:
        assert w not in _name(f"{w} {PHONE}").split()


def test_root1_refusal_word_still_blanked():
    # „არა" must stay blanked as a refusal (not saved as a name).
    assert _parse_name_phone(f"არა {PHONE}")[0] == ""


# ===========================================================================
# ROOT 2 — disclosure bypass fix + multi-phone clarification
# ===========================================================================
def test_root2_chemi_nomeria_not_saved_as_name():
    conv, lead = _conv()
    reply = _maybe_handle_contact_collection(conv, "ჩემი ნომერია 595999733")
    assert lead.phone == "595999733"
    assert lead.name != "ჩემი"
    assert (lead.name or "") == ""         # garbage not saved; asks for name
    assert reply is not None


def test_root2_two_phones_asks_which_no_garbage_name():
    conv, lead = _conv()
    reply = _maybe_handle_contact_collection(conv, "595999733 ან 595999734")
    assert reply is not None
    assert "ორი ნომერი" in reply           # clarification asked
    assert lead.name != "ან"
    assert (lead.name or "") == ""
    # Detector sees two distinct numbers; one phone sees one.
    assert _distinct_valid_phones("595999733 ან 595999734") == ["595999733", "595999734"]
    assert _distinct_valid_phones("595 999 733") == ["595999733"]


def test_root2_single_phone_happy_path_lizi():
    conv, lead = _conv()
    _maybe_handle_contact_collection(conv, "ლიზი 595999733")
    assert lead.name == "ლიზი"
    assert lead.phone == "595999733"


def test_root2_single_phone_happy_path_joni():
    conv, lead = _conv()
    _maybe_handle_contact_collection(conv, "ჯონი 595999733")
    assert lead.name == "ჯონი"
    assert lead.phone == "595999733"


def test_root2_my_name_is_lizi_extracts_lizi():
    # „ჩემი სახელია ლიზი ნომერი 595999733" → name=ლიზი (filler stripped),
    # NOT the whole sentence, NOT „ჩემი".
    conv, lead = _conv()
    _maybe_handle_contact_collection(conv, "ჩემი სახელია ლიზი ნომერი 595999733")
    assert lead.name == "ლიზი"
    assert lead.phone == "595999733"


# ===========================================================================
# ROOT 3 — saved name length is capped
# ===========================================================================
def test_root3_rambling_paragraph_not_saved_as_name():
    words = " ".join(["ლა", "მო", "ნი", "რე", "ბუ"])  # 5 valid tokens
    name, phone = _parse_name_phone(f"{PHONE} {words}")
    assert phone == PHONE
    assert name == ""                      # > 4 tokens dropped


def test_root3_long_real_message_phone_extracted_name_dropped():
    msg = (
        "გამარჯობა ძალიან მაინტერესებს თქვენი ბანაკი ჩემი შვილისთვის "
        "დამირეკეთ 595999733"
    )
    name, phone = _parse_name_phone(msg)
    assert phone == "595999733"
    assert len(name.split()) <= 4          # never the whole paragraph


def test_root3_short_name_still_saved():
    assert _parse_name_phone(f"ლიზი {PHONE}") == ("ლიზი", PHONE)
    assert _parse_name_phone(f"{PHONE} ნინო") == ("ნინო", PHONE)
