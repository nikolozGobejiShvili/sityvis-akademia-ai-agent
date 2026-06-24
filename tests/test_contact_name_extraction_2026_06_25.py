"""Contact / name extraction — Georgian relationship & context words are NEVER
a name (live bug 2026-06-25, legacy/giant-prompt path).

Transcript:
  bot: „… მომწერეთ თქვენი სახელი და 9-ნიშნა საკონტაქტო ნომერი … რამდენი წლისაა?"
  user: „10 წლის არის ჩემი შვილი\n\nნიკოლოზი 595999733"
  bug: agent stored name=„შვილი" and replied „მადლობა, შვილი".

After the fix:  child_age=10 · name=ნიკოლოზი · phone=595999733.

No planner / slim flags involved — this exercises the deterministic
pre-engine contact-collection helper directly. Externals never touched.
"""
from __future__ import annotations

from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead

_BOT_ASK = (
    "გთხოვთ, ჯერ მომწერეთ თქვენი სახელი და 9-ნიშნა საკონტაქტო ნომერი, "
    "რომ კონსულტაცია ჩავნიშნოთ. თქვენი შვილი რამდენი წლისაა?"
)
TRANSCRIPT = "10 წლის არის ჩემი შვილი\n\nნიკოლოზი 595999733"


def _conv(sender_id: str = "u-2026-06-25") -> Conversation:
    conv = Conversation(sender_id=sender_id, platform="instagram")
    conv.segment = "PARENT"
    conv.state = "ASK_CONTACT"
    conv.lead = Lead(sender_id=sender_id, platform="instagram", segment="PARENT")
    conv.history = [
        {"role": "user", "content": "ჩამწერეთ კონსულტაციაზე"},
        {"role": "assistant", "content": _BOT_ASK},
    ]
    return conv


# ── Test 1 — the live transcript ──────────────────────────────────────────────
def test_transcript_parse_name_phone():
    name, phone = parent_flow._parse_name_phone(TRANSCRIPT)
    assert name == "ნიკოლოზი"
    assert phone == "595999733"
    assert name != "შვილი"


def test_transcript_full_capture():
    conv = _conv()
    out = parent_flow._maybe_handle_contact_collection(conv, TRANSCRIPT)
    assert out is not None
    assert conv.lead.child_age == "10"
    assert conv.lead.name == "ნიკოლოზი"
    assert conv.lead.phone == "595999733"
    assert conv.lead.name != "შვილი"
    assert "შვილი" not in (conv.lead.name or "")


# ── Test 2 — age first, name+phone after a comma ──────────────────────────────
def test_age_first_then_name_phone():
    conv = _conv()
    out = parent_flow._maybe_handle_contact_collection(
        conv, "ჩემი შვილი 10 წლისაა, ნიკოლოზი 595999733",
    )
    assert out is not None
    assert conv.lead.child_age == "10"
    assert conv.lead.name == "ნიკოლოზი"
    assert conv.lead.phone == "595999733"


# ── Test 3 — no real name → save phone + ask only for the name ────────────────
def test_no_valid_name_asks_for_name_only():
    conv = _conv()
    out = parent_flow._maybe_handle_contact_collection(
        conv, "შვილი 10 წლისაა 595999733",
    )
    assert out is not None
    assert conv.lead.phone == "595999733"
    assert conv.lead.child_age == "10"
    # „შვილი" must NOT be saved as the name; nothing invalid is stored.
    assert (conv.lead.name or "") == ""
    # The agent acknowledges the number and asks (only) for the name.
    assert "ნომერი მივიღე" in out
    assert "სახელ" in out


# ── Test 4 — „მე ვარ <name> <phone>" ─────────────────────────────────────────
def test_me_var_name_phone():
    conv = _conv()
    out = parent_flow._maybe_handle_contact_collection(
        conv, "მე ვარ ნიკოლოზი 595999733",
    )
    assert out is not None
    assert conv.lead.name == "ნიკოლოზი"
    assert conv.lead.phone == "595999733"


# ── Requirement #2 — name immediately before the phone, punctuation variants ───
def test_name_before_phone_punctuation_variants():
    for msg in (
        "ნიკოლოზი 595999733",
        "ნიკოლოზი, 595999733",
        "ნიკოლოზი - 595999733",
    ):
        name, phone = parent_flow._parse_name_phone(msg)
        assert name == "ნიკოლოზი", msg
        assert phone == "595999733", msg


# ── Requirement #1 — relationship / context words rejected as names ───────────
def test_relationship_context_words_rejected_as_names():
    for bad in (
        "შვილი", "ბავშვი", "ბიჭი", "გოგო", "დედა", "მამა", "მშობელი",
        "მეუღლე", "მე", "ჩემი", "ჩემია", "თქვენი", "არის", "წლის",
        "წელია", "ასაკი", "ნომერი", "ტელეფონი", "საკონტაქტო",
        "კონსულტაცია", "ბანაკი",
        # common Georgian case forms of the relationship words
        "შვილის", "შვილს", "ბავშვის", "მამის", "დედის", "ბიჭის",
    ):
        assert not parent_flow._name_token_is_valid(bad), bad


def test_real_georgian_names_still_valid():
    # Names that could collide with a relationship stem MUST stay valid
    # (მამუკა vs მამა; გოგა/გოგი vs გოგო; ბარბარა contains „არა").
    for good in (
        "ნიკოლოზი", "ნინო", "გიორგი", "მარიამი", "ანა", "დავითი",
        "ლიზი", "ჯონი", "ბარბარა", "მამუკა", "გოგა", "გოგი",
    ):
        assert parent_flow._name_token_is_valid(good), good


# ── Regression guards — existing behaviour preserved ──────────────────────────
def test_reversed_name_after_phone_still_parsed():
    # Name placed AFTER the phone must still parse (the near-phone preference
    # falls through to the full scan here).
    name, phone = parent_flow._parse_name_phone("595999733 ლიზი")
    assert name == "ლიზი"
    assert phone == "595999733"


def test_filler_before_real_name_unchanged():
    # „კაი ფრიდონი 595999733" → ფრიდონი (filler dropped, name next to phone).
    name, phone = parent_flow._parse_name_phone("კაი ფრიდონი 595999733")
    assert name == "ფრიდონი"
    assert phone == "595999733"


def test_capture_creates_no_booking_side_effects():
    conv = _conv()
    parent_flow._maybe_handle_contact_collection(conv, TRANSCRIPT)
    assert conv.lead.calendly_booked is False
    assert (conv.lead.booked_datetime_iso or "") == ""
    assert not conv.pending_booking
