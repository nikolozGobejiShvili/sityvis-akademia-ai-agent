"""Live wording/state bugfix — 3 scoped bugs (2026-07-06).

BUG 1 — Name confirmation after phone. After the phone is captured and the bot
        has asked for the NAME, a name-only reply („მარიამი") must NOT re-emit the
        phone acknowledgement („ნომერი მივიღე…"); it must thank by name and move to
        day/time selection.

BUG 2 — Georgian animate-possession grammar. Children take „გყავთ" (animate),
        never „გაქვთ". The plural-children age question is LLM free-generation, so
        the sanitiser rewrites „შვილები გაქვთ" → „შვილები გყავთ".

BUG 3 — The empathy phrase „ეს გასაგები მოთხოვნაა" is banned in user-facing
        replies. The sanitiser strips it (and its variants) to „გასაგებია", the
        „აზრი აქვს" rewrites no longer INJECT it, and system_parent_v2.md no longer
        prescribes it as approved wording.

Regression — c98a5d9 multi-child behaviour is preserved (both ages recorded,
        „9-17" not captured, booking never re-asks the age).

Deterministic — exercises the pre-engine contact helper + the module-scope
sanitiser directly; no LLM / externals touched.
"""
from __future__ import annotations

import re
from pathlib import Path

from app.agent.llm.parent_llm_engine import sanitise_response_wording
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead

_BOT_ASK_CONTACT = (
    "გთხოვთ, მომწერეთ თქვენი სახელი და საკონტაქტო ნომერი, "
    "რომ კონსულტაცია ჩავნიშნოთ."
)


def _conv(sender_id: str = "u-2026-07-06") -> Conversation:
    conv = Conversation(sender_id=sender_id, platform="messenger")
    conv.segment = "PARENT"
    conv.state = "ASK_CONTACT"
    conv.lead = Lead(sender_id=sender_id, platform="messenger", segment="PARENT")
    conv.history = [
        {"role": "user", "content": "კონსულტაცია მინდა"},
        {"role": "assistant", "content": _BOT_ASK_CONTACT},
    ]
    return conv


# ── BUG 1 — phone then name ───────────────────────────────────────────────────
def test_bug1_name_after_phone_does_not_repeat_number_ack():
    """The live two-turn flow: phone → name. The name turn must NOT say
    „ნომერი მივიღე" and must continue to day/time selection."""
    conv = _conv()

    # Turn 1 — user gives the phone; agent acks the number + asks for the name.
    reply1 = parent_flow._maybe_handle_contact_collection(conv, "595999733")
    assert reply1 is not None
    assert conv.lead.phone == "595999733"
    assert "ნომერი მივიღე" in reply1        # a NUMBER was given → correct ack
    assert "სახელ" in reply1                # asks for the name
    conv.history.append({"role": "assistant", "content": reply1})

    # Turn 2 — user gives ONLY the name.
    reply2 = parent_flow._maybe_handle_contact_collection(conv, "მარიამი")
    assert reply2 is not None
    assert conv.lead.name == "მარიამი"
    # BUG 1: a name-only reply must NEVER re-acknowledge the phone.
    assert "ნომერი მივიღე" not in reply2
    # …it thanks (by name) and continues to day/time selection.
    assert "მადლობა" in reply2
    assert "რომელი დღე და დრო" in reply2


def test_bug1_name_only_helper_returns_thanks_by_name():
    """Direct helper check: phone already known, bot asked for the name,
    user sends a bare name → thanks-by-name, not the number ack."""
    conv = _conv()
    conv.lead.phone = "595999733"
    conv.history = [
        {"role": "user", "content": "595999733"},
        {"role": "assistant", "content":
            "ნომერი მივიღე. მომწერეთ თქვენი სახელი, რომ კონსულტაცია ჩავნიშნოთ."},
    ]
    out = parent_flow._maybe_handle_contact_collection(conv, "მარიამი")
    assert out is not None
    assert out == parent_flow._CONTACT_THANKS_NAME_ASK_TIME.format(name="მარიამი")
    assert "ნომერი მივიღე" not in out


def test_bug1_name_before_phone_known_still_asks_phone():
    """Regression guard — when the phone is NOT yet known a name-only reply
    still asks for the phone (unchanged behaviour)."""
    conv = _conv()
    conv.history = [
        {"role": "user", "content": "ჩამწერეთ"},
        {"role": "assistant", "content":
            "მომწერეთ თქვენი სახელი და საკონტაქტო ნომერი."},
    ]
    out = parent_flow._maybe_handle_contact_collection(conv, "მარიამი")
    assert out is not None
    assert conv.lead.name == "მარიამი"
    assert out == parent_flow._BOOKING_ASK_PHONE_ONLY


# ── BUG 2 — animate-possession grammar ────────────────────────────────────────
def test_bug2_children_question_uses_gyavt_not_gaqvt():
    out = sanitise_response_wording("რა ასაკის შვილები გაქვთ?")
    assert "შვილები გაქვთ" not in out
    assert "შვილები გყავთ" in out


def test_bug2_bavshvebi_variant_also_fixed():
    out = sanitise_response_wording("რამდენი ბავშვები გაქვთ?")
    assert "ბავშვები გაქვთ" not in out
    assert "ბავშვები გყავთ" in out


def test_bug2_approved_alternative_passes_through():
    out = sanitise_response_wording("რამდენი წლის არიან თქვენი შვილები?")
    assert "რამდენი წლის არიან თქვენი შვილები" in out
    assert "შვილები გაქვთ" not in out


# ── BUG 3 — banned empathy phrase ─────────────────────────────────────────────
def test_bug3_forbidden_phrase_stripped_from_output():
    out = sanitise_response_wording("მესმის, ეს გასაგები მოთხოვნაა. ბანაკი ეხმარება.")
    assert "ეს გასაგები მოთხოვნაა" not in out
    assert "გასაგები მოთხოვნაა" not in out
    assert "გასაგებია" in out


def test_bug3_azri_aqvs_rewrites_never_inject_forbidden_phrase():
    for src in (
        "ეს ძალიან აზრი აქვს",
        "მესმის, ამას აზრი აქვს.",
        "აზრი აქვს, რომ იკითხოთ.",
    ):
        rewritten = sanitise_response_wording(src)
        assert "აზრი აქვს" not in rewritten, src
        assert "გასაგები მოთხოვნაა" not in rewritten, src


def test_bug3_prompt_no_longer_prescribes_forbidden_phrase():
    # Derive the app package dir from a module with a real __file__
    # (app is a namespace package, so app.__file__ can be None).
    app_dir = Path(parent_flow.__file__).resolve().parents[1]
    prompt = (
        app_dir / "agent" / "prompts" / "system_parent_v2.md"
    ).read_text(encoding="utf-8")
    # The phrase may still appear, but ONLY inside an explicit prohibition
    # („არასოდეს …" / „არ გამოიყენო …") — never offered as approved wording.
    for m in re.finditer("ეს გასაგები მოთხოვნაა", prompt):
        # Strip markdown emphasis („*არ*" / „*არასოდეს*") before matching.
        window = prompt[max(0, m.start() - 60): m.start()].replace("*", "")
        assert ("არასოდეს" in window) or ("არ გამოიყენო" in window), (
            "system_parent_v2.md must only mention the banned phrase in a "
            "prohibition, never as an approved empathy option"
        )


# ── Regression — c98a5d9 multi-child behaviour preserved ──────────────────────
def _parent_conv(*, child_age: str = "") -> Conversation:
    conv = Conversation(sender_id="s_mc_0706", platform="messenger")
    conv.segment = "PARENT"
    conv.lead = Lead(sender_id="s_mc_0706", platform="messenger", segment="PARENT")
    conv.lead.child_age = child_age
    return conv


def test_regression_multi_child_records_both_ages():
    conv = _parent_conv()
    out = parent_flow._maybe_handle_multi_child_age(conv, "12-14 წლის")
    assert out is not None
    assert conv.lead.child_age == "12"                 # first in-band gate value
    assert "12 და 14" in conv.lead.deeper_concern      # manager-visible context


def test_regression_band_9_17_not_captured():
    conv = _parent_conv()
    assert parent_flow._maybe_handle_multi_child_age(conv, "9-17 წლის") is None
    assert conv.lead.child_age == ""


def test_regression_booking_does_not_reask_age_once_known():
    conv = _parent_conv(child_age="12")
    reply = "კარგი, კონსულტაციაზე ჩასაწერად რომელი დღე გირჩევნიათ?"
    out = parent_flow._ensure_camp_age_question(conv, "რაიმე", reply)
    assert out == reply
    assert "რამდენი წლის" not in out
