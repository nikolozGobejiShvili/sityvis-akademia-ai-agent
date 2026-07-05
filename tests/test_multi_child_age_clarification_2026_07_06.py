"""Multi-child age RECORD-AND-CONTINUE (2026-07-06 client fix, REVISED).

Live Messenger regression: a parent registering two children typed the ages as a
hyphenated range („12-14 წლის"), which collided with the guard that rejects the
advertised camp band („9-17"). The age was silently dropped and the booking kept
re-asking it.

Revised decision: do NOT ask the parent to choose one age. RECORD BOTH ages and
continue — child_age holds the first in-band age (the single-value booking gate);
the full list is stored in the manager-visible `deeper_concern` field (Sheets +
manager handoff show both). The advertised band („9-17") is still never captured.

Handled edge cases (from the adversarial review):
  * eligibility QUESTION („ბანაკი 12-14 წლის ბავშვებისთვისაა?") does NOT hijack;
  * scattered numbers („10 დღიანია? … 14 წლისაა") capture the single age, not two;
  * a bare „12 და 14" right after the age question is recorded;
  * a mixed sibling pair („8-14") captures the eligible age (no re-ask).
The single-age fallback (`maybe_capture_child_age_fallback`) is UNCHANGED.
"""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import pytest

import app.config as config_module
from app.agent.llm.parent_llm_engine import (
    extract_distinct_child_ages,
    maybe_capture_child_age_fallback,
)
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead

_AGE_QUESTION_MARKER = "რამდენი წლის"  # broad marker: covers the _CAMP_AGE_QUESTION re-ask
_AGE_Q_PENDING = "თქვენი შვილი რამდენი წლისაა?"


# -- helpers ---------------------------------------------------------------


def _parent_conv(*, child_age: str = "", challenge: str = "", history=None) -> Conversation:
    conv = Conversation(sender_id="s_mc", platform="messenger")
    conv.segment = "PARENT"
    conv.lead = Lead(sender_id="s_mc", platform="messenger", segment="PARENT")
    conv.lead.child_age = child_age
    conv.lead.challenge = challenge
    for turn in history or []:
        conv.history.append(turn)
    return conv


def _record(conv: Conversation, message: str):
    return parent_flow._maybe_handle_multi_child_age(conv, message)


# -- extractor -------------------------------------------------------------


@pytest.mark.parametrize("message", [
    "12-14 წლის",
    "12 და 14 წლის",
    "12, 14 წლის",
    "12 წლის და 14 წლის",
])
def test_extractor_returns_two_ages_for_compact_multi_child(message):
    assert extract_distinct_child_ages(message, age_min=9, age_max=17) == [12, 14]


def test_extractor_bare_pair_needs_age_question_pending():
    # No age word → nothing without the pending flag…
    assert extract_distinct_child_ages("12 და 14", age_min=9, age_max=17) == []
    # …but right after the age question it IS the two ages.
    assert extract_distinct_child_ages(
        "12 და 14", age_min=9, age_max=17, age_question_pending=True,
    ) == [12, 14]


@pytest.mark.parametrize("message", [
    "9-17",
    "9-17 წლის",
    "9-17 წელი",
    "9-დან 17 წლამდე",
])
def test_extractor_excludes_advertised_band(message):
    assert extract_distinct_child_ages(message, age_min=9, age_max=17) == []


def test_extractor_ignores_eligibility_question():
    # „Is the camp for 12-14 year olds?" — not the parent's own children.
    assert extract_distinct_child_ages(
        "ბანაკი 12-14 წლის ბავშვებისთვისაა?", age_min=9, age_max=17,
    ) == []


def test_extractor_ignores_scattered_numbers():
    # „Is the camp 10 days? My child is 14" — one child, an unrelated count.
    assert extract_distinct_child_ages(
        "ბანაკი 10 დღიანია? ჩემი შვილი 14 წლისაა", age_min=9, age_max=17,
    ) == []


def test_extractor_single_age_is_not_multi():
    assert extract_distinct_child_ages("14 წლის", age_min=9, age_max=17) == []


# -- (1,2,4) record both ages; child_age set; manager-visible -------------


@pytest.mark.parametrize("message", [
    "12-14 წლის",
    "12 და 14 წლის",
    "12, 14 წლის",
])
def test_two_child_input_records_both_and_continues(message):
    conv = _parent_conv()
    out = _record(conv, message)
    assert out is not None
    # (2) child_age not empty — first in-band gate value.
    assert conv.lead.child_age == "12"
    # (1) both ages stored in a manager-visible field.
    assert "12 და 14" in conv.lead.deeper_concern
    # acknowledges + continues, does NOT ask to choose or re-ask the age.
    assert "ჩავიწერე" in out
    assert "რომელი ასაკი მივუთითო" not in out
    assert _AGE_QUESTION_MARKER not in out.replace("რას ელოდებით", "")


def test_acknowledgement_exact_wording_plus_goal():
    conv = _parent_conv()
    out = _record(conv, "12-14 წლის")
    assert out == (
        "ორი ბავშვის ასაკი მივიღე — 12 და 14 წელი. ორივე ასაკი ჩავიწერე. "
        "ბანაკი ორივე ასაკისთვის შესაბამისია. რას ელოდებით ბანაკისგან?"
    )


def test_goal_not_reasked_when_challenge_known():
    conv = _parent_conv(challenge="ეკრანთან დროის შემცირება")
    out = _record(conv, "12-14 წლის")
    assert out is not None
    assert "რას ელოდებით" not in out  # challenge already known → no goal question
    assert conv.lead.child_age == "12"


def test_sheets_payload_includes_both_ages():
    conv = _parent_conv()
    _record(conv, "12-14 წლის")
    row = conv.lead.to_sheet_row("reply")
    assert any("12 და 14" in str(cell) for cell in row)


def test_bare_pair_after_age_question_records_both():
    conv = _parent_conv(history=[{"role": "assistant", "content": _AGE_Q_PENDING}])
    out = _record(conv, "12 და 14")
    assert out is not None
    assert conv.lead.child_age == "12"
    assert "12 და 14" in conv.lead.deeper_concern


# -- (3) booking does not re-ask age --------------------------------------


def test_no_age_reask_once_recorded():
    conv = _parent_conv(child_age="12")
    engine_reply = "კარგი, კონსულტაციაზე ჩასაწერად რომელი დღე გირჩევნიათ?"
    out = parent_flow._ensure_camp_age_question(conv, "რაიმე", engine_reply)
    assert out == engine_reply
    assert _AGE_QUESTION_MARKER not in out


# -- (5) advertised band still not captured -------------------------------


def test_band_9_17_not_recorded_or_captured():
    conv = _parent_conv()
    assert _record(conv, "9-17 წლის") is None
    assert conv.lead.child_age == ""
    lead = Lead(sender_id="s", platform="messenger", segment="PARENT")
    maybe_capture_child_age_fallback(lead, "9-17 წლის", age_question_pending=True)
    assert lead.child_age == ""


# -- (6) single age still works normally ----------------------------------


def test_single_age_defers_and_captures():
    conv = _parent_conv()
    assert _record(conv, "14 წლის") is None
    lead = Lead(sender_id="s", platform="messenger", segment="PARENT")
    maybe_capture_child_age_fallback(lead, "14 წლის")
    assert lead.child_age == "14"


def test_scattered_number_defers_single_captured():
    conv = _parent_conv()
    assert _record(conv, "ბანაკი 10 დღიანია? ჩემი შვილი 14 წლისაა") is None
    lead = Lead(sender_id="s", platform="messenger", segment="PARENT")
    maybe_capture_child_age_fallback(lead, "ჩემი შვილი 14 წლისაა")
    assert lead.child_age == "14"


# -- mixed sibling pair (one out of band) — no re-ask ---------------------


def test_mixed_pair_captures_eligible_age_no_reask():
    conv = _parent_conv()
    out = _record(conv, "8-14 წლის")
    # Only the in-band 14 becomes the gate value; both ages noted for the manager.
    assert conv.lead.child_age == "14"
    assert "8 და 14" in conv.lead.deeper_concern
    # No re-ask: child_age is set, so _ensure_camp_age_question is a no-op.
    assert parent_flow._ensure_camp_age_question(
        conv, "x", "კარგი.",
    ) == "კარგი."
    # No „both suitable" claim for a mixed pair → interceptor returns None.
    assert out is None


# -- eligibility question is not hijacked ---------------------------------


def test_eligibility_question_not_hijacked():
    conv = _parent_conv()
    assert _record(conv, "ბანაკი 12-14 წლის ბავშვებისთვისაა?") is None
    assert conv.lead.child_age == ""


# -- gating ----------------------------------------------------------------


def test_no_record_when_age_already_known():
    conv = _parent_conv(child_age="13")
    assert _record(conv, "12-14 წლის") is None
    assert conv.lead.child_age == "13"  # unchanged


def test_no_record_outside_parent_segment():
    conv = _parent_conv()
    conv.segment = "ADULT"
    assert _record(conv, "12-14 წლის") is None


# -- (7) no schema change -------------------------------------------------


def test_no_new_lead_schema_fields():
    names = {f.name for f in dataclasses.fields(Lead)}
    # The fix reuses EXISTING fields only.
    assert "child_age" in names
    assert "deeper_concern" in names
    assert not any("multi" in n or "children" in n for n in names)


# -- (8) recorded state survives write/read roundtrip ---------------------


def test_recorded_state_survives_roundtrip():
    conv = _parent_conv()
    _record(conv, "12-14 წლის")  # exercise the fix (sets child_age + deeper_concern)
    assert conv.lead.child_age == "12"
    assert "12 და 14" in conv.lead.deeper_concern
    restored = Conversation.from_dict(conv.to_dict())
    assert restored.lead.child_age == "12"
    assert "12 და 14" in restored.lead.deeper_concern


# -- end-to-end through parent_flow.handle --------------------------------


def test_handle_records_and_acks_without_engine(monkeypatch):
    """The two-age turn records + acknowledges BEFORE the engine — no LLM."""
    from app.services import openai_service

    def _boom(*a, **k):
        raise AssertionError("chat_with_tools must not be called")

    monkeypatch.setattr(openai_service, "chat_with_tools", _boom)
    swapped = dataclasses.replace(config_module.settings, USE_PARENT_LLM_ENGINE=True)
    monkeypatch.setattr(parent_flow, "settings", swapped)

    conv = _parent_conv(history=[{"role": "assistant", "content": "_prior_camp_turn"}])
    out = parent_flow.handle(conv, "12-14 წლის")
    assert "ჩავიწერე" in out
    assert conv.lead.child_age == "12"
    assert "12 და 14" in conv.lead.deeper_concern
    assert _AGE_QUESTION_MARKER not in out.replace("რას ელოდებით", "")


def test_handle_continues_after_record_no_age_reask(monkeypatch):
    """After recording, the parent's goal answer flows into the engine and the
    age is NOT re-asked (child_age is already set)."""
    from app.services import openai_service, messenger_service

    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})

    def _chat(**kwargs):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content="მშვენიერია. კონსულტაციაზე ჩასაწერად რომელი დღე გირჩევნიათ?",
            tool_calls=None,
        ))])

    monkeypatch.setattr(openai_service, "chat_with_tools", _chat)
    swapped = dataclasses.replace(config_module.settings, USE_PARENT_LLM_ENGINE=True)
    monkeypatch.setattr(parent_flow, "settings", swapped)

    conv = _parent_conv(
        child_age="12",
        history=[
            {"role": "assistant", "content": "_prior_camp_turn"},
            {"role": "user", "content": "12-14 წლის"},
            {"role": "assistant", "content": parent_flow._build_multi_child_ack([12, 14])
                + " " + parent_flow._CAMP_GOAL_QUESTION_CONTINUE},
        ],
    )
    conv.lead.deeper_concern = "ორი შვილი: 12 და 14 წლის"
    out = parent_flow.handle(conv, "მინდა რომ სოციალურად განვითარდნენ")
    assert conv.lead.child_age == "12", f"age lost; reply={out!r}"
    assert _AGE_QUESTION_MARKER not in out
