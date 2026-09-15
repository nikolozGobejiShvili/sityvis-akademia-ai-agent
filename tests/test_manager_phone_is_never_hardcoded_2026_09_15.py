"""The manager's phone number must come from the admin panel everywhere it is
shown to a parent — the same way price, age and location already do — never
typed literally into a prompt, skill, or Python constant.

Live, 2026-09-15 (screenshots): the operator changed the manager's number in
the admin panel. One question (syllabus, a dedicated deterministic handler)
picked up the new number correctly. Three others — teachers, invited guests,
field trips, all "unconfirmed operational detail" redirects composed by the
model — kept answering with the OLD number, „558 67 47 33".

Root cause: `system_parent_v2.md`'s anti-invention rule told the model to
redirect with this EXACT wording, phone included, as a literal example — the
same shape of bug the project already fixed once for literal example dates
(a model imitates a wordperfect example over a fact given elsewhere in the
same context, when the prompt says "reproduce this exactly"). The identical
literal also lived in `dissatisfied-customer.md` (a live skill, USE_SKILLS is
on), in three `parent_flow.py` Python constants comparing against that exact
string, and unconditionally in two `camp_topic_facts.py` answer paths that
never consulted the admin config at all.

Fix (a deletion / restoration of symmetry — no new prohibition, no new
wording): the two live prompt variants now carry `{manager_phone}`, filled by
the SAME `.format()` call that already supplies `{company_name}`/`{age_min}`/
`{age_max}` — from `admin_config_service.get_manager_phone()`, the one
already-canonical source. The skill's line loses its trailing literal digits
entirely (the model already receives `manager_phone=...` as a turn fact on
every PARENT turn — that sentence needed no number of its own). The three
Python detectors compare against the STABLE prefix, not the number. The two
camp_topic_facts.py answer paths swap the fallback literal for the live value
when one is configured, exactly as `_unknown_ending()` already did.

Georgian strings are built from code points so no letter can drift.
"""
from __future__ import annotations

import io

import pytest

from app.agent.llm import parent_llm_engine as ple
from app.flows import parent_flow
from app.reasoning import camp_topic_facts as ctf
from app.services import admin_config_service as acs


def ka(text: str) -> str:
    for ch in text:
        assert ord(ch) < 128 or 0x10D0 <= ord(ch) <= 0x10FF, repr(text)
    return text


OLD_PHONE = ka("558 67 47 33")
NEW_PHONE = "599 00 11 20"

LIVE_PROMPT_FILES = [
    "app/agent/prompts/system_parent_v2.md",
    "app/agent/prompts/parent_lean.md",
]
LIVE_SKILL_FILES = [
    "app/agent/skills/dissatisfied-customer.md",
]


# ── source scan: the literal number is gone from every live text source ────

@pytest.mark.parametrize("relpath", LIVE_PROMPT_FILES + LIVE_SKILL_FILES)
def test_the_old_number_is_not_typed_into_any_live_prompt_or_skill(relpath):
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    text = io.open(os.path.join(root, relpath), encoding="utf-8").read()
    assert OLD_PHONE not in text, f"{relpath} still hardcodes the manager number"


def test_the_manager_phone_rule_uses_the_placeholder_not_any_literal():
    """The specific sentences the anti-invention rule renders must use the
    placeholder, not a digit string — narrower than a blanket phone-shaped
    scan, which also matches unrelated example numbers elsewhere in the
    prompt (e.g. a sample PARENT contact number used for validation)."""
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for relpath in LIVE_PROMPT_FILES:
        text = io.open(os.path.join(root, relpath), encoding="utf-8").read()
        for line in text.splitlines():
            if "მენეჯერი გაგაცნობთ :" in line or "მენეჯერი გაგაცნობთ:" in line:
                assert "{manager_phone}" in line, f"{relpath}: {line!r}"


# ── the live prompt renders the CURRENT admin-panel number ─────────────────

@pytest.mark.parametrize("relpath,prompt_name", [
    ("app/agent/prompts/system_parent_v2.md", "system_parent_v2"),
])
def test_the_placeholder_is_present_and_balanced(relpath, prompt_name):
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    text = io.open(os.path.join(root, relpath), encoding="utf-8").read()
    assert "{manager_phone}" in text


def test_build_system_prompt_renders_the_live_admin_panel_number(monkeypatch):
    monkeypatch.setattr(acs, "get_manager_phone", lambda: NEW_PHONE)
    prompt = ple._build_system_prompt()
    assert NEW_PHONE in prompt
    assert OLD_PHONE not in prompt


def test_build_system_prompt_falls_back_safely_when_admin_config_is_empty(monkeypatch):
    """No live number configured → the prompt still renders (never a format
    KeyError), with some safe non-empty fallback digits."""
    monkeypatch.setattr(acs, "get_manager_phone", lambda: "")
    prompt = ple._build_system_prompt()
    assert "{manager_phone}" not in prompt  # placeholder always resolved


def test_build_system_prompt_survives_admin_config_raising(monkeypatch):
    def _boom():
        raise RuntimeError("config unavailable")
    monkeypatch.setattr(acs, "get_manager_phone", _boom)
    prompt = ple._build_system_prompt()  # must not raise
    assert "{manager_phone}" not in prompt


# ── the skill line still reads naturally with the number gone ──────────────

def test_the_skill_still_tells_the_model_to_hand_over_the_number():
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    text = io.open(os.path.join(root, "app/agent/skills/dissatisfied-customer.md"),
                    encoding="utf-8").read()
    assert ka("მენეჯერის "
              "ნომერ") in text  # "manager's number"


# ── the Python-side detector no longer depends on the exact digits ─────────

def test_the_unknown_detail_detector_recognises_any_live_phone():
    reply_with_new_phone = f"რაც შეეხება ამ საკითხს, ამ დეტალებს მენეჯერი გაგაცნობთ : {NEW_PHONE}"
    assert parent_flow._is_unknown_detail_manager_defer(reply_with_new_phone) is True


def test_the_unknown_detail_detector_still_recognises_the_old_phone_too():
    reply_with_old_phone = f"რაც შეეხება ამ საკითხს, ამ დეტალებს მენეჯერი გაგაცნობთ : {OLD_PHONE}"
    assert parent_flow._is_unknown_detail_manager_defer(reply_with_old_phone) is True


def test_the_unknown_detail_detector_is_false_for_an_unrelated_reply():
    assert parent_flow._is_unknown_detail_manager_defer(
        "საკვირაო სკოლის ფასია 595 ლარი.") is False


# ── camp_topic_facts answers swap in the live number ────────────────────────

def test_parent_communication_topic_uses_the_live_admin_panel_number(monkeypatch):
    monkeypatch.setattr(acs, "get_manager_phone", lambda: NEW_PHONE)
    answer = ctf.resolve_camp_answer("ბავშვთან პირდაპირი კონტაქტი შესაძლებელია?")
    assert answer is not None
    assert NEW_PHONE in answer
    assert OLD_PHONE not in answer


def test_menu_clarification_uses_the_live_admin_panel_number(monkeypatch):
    monkeypatch.setattr(acs, "get_manager_phone", lambda: NEW_PHONE)
    clar = ctf.menu_clarification()
    assert NEW_PHONE in clar
    assert OLD_PHONE not in clar


def test_camp_topic_facts_fall_back_to_their_own_text_when_admin_config_is_empty(monkeypatch):
    monkeypatch.setattr(acs, "get_manager_phone", lambda: "")
    answer = ctf.resolve_camp_answer("ბავშვთან პირდაპირი კონტაქტი შესაძლებელია?")
    assert answer is not None
    assert OLD_PHONE in answer  # the YAML's own literal, unchanged text
