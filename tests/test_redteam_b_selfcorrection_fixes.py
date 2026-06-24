"""Red-Team B self-correction + M1 spelled-out numerals batch fix (2026-06-13).

Covers the deterministic fixes for the conversation-level red-team findings
(docs/REDTEAM_CONVERSATIONS.md) and the M1 metamorphic divergence:

  FIX 1 (B5) — _maybe_requalify_child must NOT wipe a BOOKED child's age.
  FIX 2 (B2) — _parse_name_phone must strip a leading refusal/correction prefix.
  FIX 3 (B4) — _maybe_capture_adult_target must revert to self on "ჩემთვის".
  FIX 4 (M1) — maybe_capture_child_age_fallback must read spelled-out Georgian
               numerals (9–17) with age context.
  FIX 5 (B1) — explicit age self-correction updates child_age (if deterministic).

All deterministic; no OpenAI / network / Redis / Calendar / Sheets / Meta / email.
"""

from __future__ import annotations

import pytest

from app.models.conversation import Conversation
from app.models.lead import Lead


def _conv(*, child_age="", booked=False, name="", phone="", state="DONE",
          segment="PARENT", booked_iso="", event_id=""):
    conv = Conversation(sender_id="s_b", platform="messenger")
    conv.segment = segment
    conv.state = state
    lead = Lead(sender_id="s_b", platform="messenger", segment=segment)
    lead.child_age = child_age
    lead.name = name
    lead.phone = phone
    lead.calendly_booked = booked
    lead.booked_datetime_iso = booked_iso
    lead.calendar_event_id = event_id
    conv.lead = lead
    return conv, lead


# ===========================================================================
# FIX 1 — B5: booked child's age is never wiped by a second-child mention
# ===========================================================================

from app.flows.parent_flow import _maybe_requalify_child, _BOOKED_SECOND_CHILD_MANAGER


def test_fix1_booked_lead_second_child_does_not_overwrite_age():
    conv, lead = _conv(
        child_age="10", booked=True,
        booked_iso="2026-07-01T10:00:00+04:00", event_id="evt_10yo",
        name="ნინო", phone="595999733",
    )
    out = _maybe_requalify_child(conv, "ჩემი მეორე შვილი 14 წლისაა")
    assert lead.child_age == "10"                       # NOT overwritten
    assert out == _BOOKED_SECOND_CHILD_MANAGER          # manager handoff
    # booked data + name/phone intact (no booking / Sheets / Calendar change)
    assert lead.calendly_booked is True
    assert lead.booked_datetime_iso == "2026-07-01T10:00:00+04:00"
    assert lead.calendar_event_id == "evt_10yo"
    assert lead.name == "ნინო"
    assert lead.phone == "595999733"


def test_fix1_booked_via_iso_only_also_guarded():
    conv, lead = _conv(child_age="12", booked=False,
                       booked_iso="2026-08-01T11:00:00+04:00")
    out = _maybe_requalify_child(conv, "სხვა შვილზე ვწერ")
    assert lead.child_age == "12"
    assert out == _BOOKED_SECOND_CHILD_MANAGER


def test_fix1_non_booked_requalify_still_clears_and_asks():
    conv, lead = _conv(child_age="14", booked=False)
    out = _maybe_requalify_child(conv, "სხვა შვილზე ვწერ")
    assert lead.child_age == ""                         # cleared (unchanged behaviour)
    assert out is not None and "რამდენი წლისაა" in out


def test_fix1_non_booked_requalify_with_new_age_in_same_message():
    conv, lead = _conv(child_age="14", booked=False)
    out = _maybe_requalify_child(conv, "სხვა ბავშვი, 10 წლის")
    assert lead.child_age == "10"                       # re-captured
    assert out is None                                  # continue normal flow


def test_fix1_no_requalify_phrase_is_noop():
    conv, lead = _conv(child_age="10", booked=True)
    out = _maybe_requalify_child(conv, "კარგი, მადლობა")
    assert out is None
    assert lead.child_age == "10"


# ===========================================================================
# FIX 2 — B2: refusal/correction prefix stripped from the name
# ===========================================================================

from app.flows.parent_flow import _parse_name_phone, is_valid_person_name


@pytest.mark.parametrize("message", [
    "არა, ნინო მქვია",
    "არა ნინო მქვია",
    "არა, მე ნინო ვარ",
    "ლიზი... არა ნინო",   # mid-string correction: the corrected name wins
])
def test_fix2_refusal_prefix_stripped_to_nino(message):
    name, _ = _parse_name_phone(message)
    assert name == "ნინო", f"{message!r} -> {name!r}"
    assert is_valid_person_name(name)


def test_fix2_bare_refusal_is_not_a_name():
    assert _parse_name_phone("არა") == ("", "")
    assert is_valid_person_name("არა") is False


def test_fix2_correction_with_phone_saves_clean_name():
    assert _parse_name_phone("არა, ნინო მქვია 595999733") == ("ნინო", "595999733")


@pytest.mark.parametrize("message,expected", [
    ("ლიზი 595999733", ("ლიზი", "595999733")),
    ("595999733 ლიზი", ("ლიზი", "595999733")),
    ("მე ვარ ნინო, 595999733", ("ნინო", "595999733")),
])
def test_fix2_existing_happy_paths_unchanged(message, expected):
    assert _parse_name_phone(message) == expected


@pytest.mark.parametrize("real_name", ["ბარბარა", "ანა", "დავითი", "მართა"])
def test_fix2_real_names_with_ara_substring_not_corrupted(real_name):
    # "ბარბარა" CONTAINS "არა" as a substring but is one token → never cut.
    name, phone = _parse_name_phone(f"{real_name} 595999733")
    assert name == real_name
    assert phone == "595999733"


# ===========================================================================
# FIX 3 — B4: adult target reverts to self on explicit self-reference
# ===========================================================================

from app.agent.llm.adult_llm_engine import _maybe_capture_adult_target


def _adult_lead(*, rel="", age="", child_age=""):
    lead = Lead(sender_id="s_a", platform="messenger", segment="ADULT")
    lead.adult_target_relation = rel
    lead.adult_target_age = age
    lead.child_age = child_age
    return lead


def test_fix3_child_then_self_reverts():
    lead = _adult_lead()
    _maybe_capture_adult_target("შვილისთვის", lead)
    assert lead.adult_target_relation == "შვილი"
    _maybe_capture_adult_target("ჩემთვის", lead)
    assert lead.adult_target_relation == ""      # reverted to self
    assert (lead.adult_target_age or "") == ""


@pytest.mark.parametrize("marker", [
    "ჩემთვის", "ჩემთვის მინდა", "მე მინდა", "მე მაინტერესებს", "ჩემთან",
])
def test_fix3_self_markers_clear_target(marker):
    lead = _adult_lead(rel="შვილი", age="12")
    _maybe_capture_adult_target(marker, lead)
    assert lead.adult_target_relation == ""
    assert (lead.adult_target_age or "") == ""


@pytest.mark.parametrize("message,expected_rel", [
    ("ჩემი შვილისთვის", "შვილი"),
    ("ჩემ შვილს", "შვილი"),
    ("ბავშვისთვის", "ბავშვი"),
    ("ბავშვს", "ბავშვი"),
])
def test_fix3_child_relations_still_set_target_m4(message, expected_rel):
    lead = _adult_lead()
    _maybe_capture_adult_target(message, lead)
    assert lead.adult_target_relation == expected_rel


def test_fix3_mixed_child_cue_and_self_marker_keeps_child():
    lead = _adult_lead()
    _maybe_capture_adult_target("მე მინდა შვილს ღონისძიება", lead)
    assert lead.adult_target_relation == "შვილი"   # relative cue wins


def test_fix3_self_revert_never_touches_child_age():
    lead = _adult_lead(rel="შვილი", age="12", child_age="12")
    _maybe_capture_adult_target("ჩემთვის", lead)
    assert lead.child_age == "12"                   # camp child_age intact


def test_fix3_self_reference_on_fresh_lead_is_noop():
    lead = _adult_lead()
    _maybe_capture_adult_target("მე მინდა", lead)
    assert (lead.adult_target_relation or "") == ""
    assert (lead.adult_target_age or "") == ""


# ===========================================================================
# FIX 4 — M1: spelled-out Georgian numerals (9–17) with age context
# ===========================================================================

from app.agent.llm.parent_llm_engine import maybe_capture_child_age_fallback


def _age(message: str, *, age_question_pending: bool = False) -> str:
    lead = Lead(sender_id="s_m", platform="messenger", segment="PARENT")
    maybe_capture_child_age_fallback(
        lead, message, age_question_pending=age_question_pending,
    )
    return lead.child_age


@pytest.mark.parametrize("message,expected", [
    ("ცხრა წლის", "9"),
    ("ათი წლის", "10"),
    ("თერთმეტი წლის", "11"),
    ("თორმეტი წლის", "12"),
    ("ცამეტი წლის", "13"),
    ("თოთხმეტი წლის", "14"),
    ("თხუთმეტი წლის", "15"),
    ("თექვსმეტი წლის", "16"),
    ("ჩვიდმეტი წლის", "17"),
    ("ჩემი შვილი ცამეტი წლისაა", "13"),
])
def test_fix4_spelled_out_numerals_capture(message, expected):
    assert _age(message) == expected


def test_fix4_m1_metamorphic_variants_now_agree():
    # The exact M1 metamorphic relation: all four phrasings → 13.
    assert _age("13 წლის") == "13"
    assert _age("ცამეტი წლის") == "13"
    assert _age("13 წლისაა") == "13"
    assert _age("ჩემი შვილი 13 წლის") == "13"


@pytest.mark.parametrize("message", [
    "13 წლის", "9 წლის", "ჩემი შვილი 12 წლისაა",
])
def test_fix4_digit_parsing_unchanged(message):
    assert _age(message) != ""


@pytest.mark.parametrize("message", [
    "ცამეტი",                    # no age context
    "მინდა ცამეტი ბილეთი",       # "thirteen tickets" — no age context
    "9-17",                       # advertised band / range
    "9 - 17",
    "9-17 წლის",                  # range even with context
    "ცხრაასი ლარი",               # "ცხრა" is only a substring of one token
])
def test_fix4_does_not_misfire(message):
    assert _age(message) == ""


# ===========================================================================
# FIX 5 — B1: explicit age self-correction updates child_age
# ===========================================================================

def _set_age(child_age: str, message: str) -> str:
    """Start with an already-set child_age, then apply the fallback."""
    lead = Lead(sender_id="s_b1", platform="messenger", segment="PARENT")
    lead.child_age = child_age
    maybe_capture_child_age_fallback(lead, message)
    return lead.child_age


def test_fix5_b1_correction_sequence():
    # 13 → "არა, 15" → "აბა 9 წლის"
    assert _set_age("13", "არა, 15") == "15"
    assert _set_age("15", "აბა 9 წლის") == "9"


@pytest.mark.parametrize("existing,message,expected", [
    ("13", "არა, 15", "15"),                 # bare number, strong marker
    ("13", "შევცვალე, 10 წლის", "10"),
    ("13", "უფრო სწორად 12", "12"),
    ("13", "ვგულისხმობდი 16 წლის", "16"),
    ("15", "აბა 9 წლის", "9"),               # "აბა" + age word
])
def test_fix5_explicit_correction_updates(existing, message, expected):
    assert _set_age(existing, message) == expected


@pytest.mark.parametrize("existing,message", [
    ("10", "10 და 14 წლის"),                 # multi-child, no correction
    ("10", "ჩემი მეორე შვილი 14 წლისაა"),    # SECOND child is not a correction
    ("10", "სხვა შვილი 14 წლის"),
    ("13", "კარგი, მადლობა"),                # no marker, no number
    ("13", "აბა 15"),                        # bare „აბა"+number → NOT relaxed
    ("13", "არა, 9-17"),                     # range stays excluded
])
def test_fix5_keeps_existing_without_clear_correction(existing, message):
    assert _set_age(existing, message) == existing


def test_fix5_fresh_lead_multi_child_keeps_first_unchanged():
    # Regression: the documented „keep the FIRST valid age" behaviour on a
    # FRESH lead must be untouched (no correction marker, no existing age).
    lead = Lead(sender_id="s_b1", platform="messenger", segment="PARENT")
    maybe_capture_child_age_fallback(lead, "ორი ბავშვი მყავს 11 და 14 წლის")
    assert lead.child_age == "11"


def test_fix5_fresh_lead_correction_marker_still_first():
    # Even if a correction marker appears, a FRESH lead just captures the
    # first valid age (there is nothing to correct).
    lead = Lead(sender_id="s_b1", platform="messenger", segment="PARENT")
    maybe_capture_child_age_fallback(lead, "არა, 12 წლის")
    assert lead.child_age == "12"
