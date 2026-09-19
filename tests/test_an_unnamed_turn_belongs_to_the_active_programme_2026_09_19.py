"""Live regression, client Page 2026-09-18/19 — eight screenshots, one shape.

Every leaking turn named NO programme:

    11:20  address?            -> the camp's last stream has started, registration closed
    09:39  where is the centre -> camp registration is closed
    09:40  is registration open-> the camp's last stream has started
    09:40  which day is it on  -> the camp's last stream has started
    09:41  when is the next    -> the camp's last stream has started
    09:44  price               -> the camp's last stream has started
    09:49  the 11-12 group     -> you are on the right STREAM (a camp word, model prose)

None of them says camp. Address, price, schedule and registration are questions
ANY programme is asked.

The cause is one design decision repeated everywhere: each isolation guard asks
"is ANOTHER programme named?" and stands down only then. Nothing asks "is this
turn attributed at all?" — so an unattributed turn has one owner by default, and
that owner is the camp. `_active_program_section` returns None for it, the camp
tool answers it, and a system prompt in which 43 of 519 lines name the camp
supplies the rest.

The rule the operator specified, and the one these tests pin:

  * a turn that names nothing, with exactly ONE programme on sale, belongs to
    THAT programme — whichever it is;
  * with two or more on sale, it belongs to none of them and the agent asks;
  * a turn that names a programme is unaffected.
"""
from __future__ import annotations

import dataclasses

import pytest

from app import config as config_module
from app.agent.llm import parent_llm_engine as engine
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import admin_config_service

SCHOOL = {
    "id": "sunday_school",
    "name": "საკვირაო სკოლა",
    "type": "sunday_school",
    "status": "active",
    "description_short": "სამთვიანი პროგრამა ლიტერატურასა და ფსიქოლოგიაში.",
    "price_text": "595 ლარი",
}
CAMP_OFF = {
    "id": "summer_camp",
    "name": "საზაფხულო ბანაკი",
    "type": "summer_camp",
    "status": "ended",
}
CAMP_ON = dict(CAMP_OFF, status="active")
SECOND = {
    "id": "winter_lab",
    "name": "ზამთრის ლაბორატორია",
    "type": "sunday_school",
    "status": "active",
    "description_short": "ზამთრის მოკლე კურსი.",
}

# The parent's own words, from the screenshots. Not one names a programme.
UNNAMED_TURNS = (
    "თქვენი მისამართი რომ მითხრათ",
    "გამარჯობა ტერიტორიულად სად ხართ?",
    "ტერიტორიულად სად არის ცენტრი",
    "ფასი",
    "რომელ დღეს ტარდება",
    "შეხვედრებს როდიდან ანახლებთ?",
)


def _panel(monkeypatch, sections: list[dict]) -> None:
    active = [s for s in sections if (s.get("status") or "") == "active"]
    monkeypatch.setattr(
        admin_config_service, "load_sections", lambda *a, **k: list(sections))
    monkeypatch.setattr(
        admin_config_service, "get_active_sections", lambda *a, **k: list(active))
    monkeypatch.setattr(
        admin_config_service, "get_camp_status", lambda *a, **k: "ended")


def _flags(monkeypatch, module) -> None:
    monkeypatch.setattr(
        module, "settings",
        dataclasses.replace(
            config_module.settings,
            USE_DYNAMIC_PROGRAMS=True,
            USE_PROGRAM_ISOLATION=True,
        ),
    )


def _lead() -> Lead:
    return Lead(sender_id="unnamed-turn", platform="messenger", segment="PARENT")


def _fresh() -> Conversation:
    conv = Conversation(sender_id="unnamed-turn", platform="messenger")
    conv.segment = "PARENT"
    conv.lead = _lead()
    return conv


# --------------------------------------------------------------------------
# 1. The rule itself.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("message", UNNAMED_TURNS)
def test_an_unnamed_turn_belongs_to_the_sole_programme_on_sale(
    monkeypatch, message,
):
    _panel(monkeypatch, [CAMP_OFF, SCHOOL])
    _flags(monkeypatch, engine)
    section = engine._active_program_section(_fresh(), message, _lead())
    assert section is not None, (
        "the turn names nothing and one programme is on sale — it is that "
        "programme's; leaving it unattributed is what hands it to the camp"
    )
    assert section.get("id") == "sunday_school"


def test_the_sole_programme_may_be_the_camp_itself(monkeypatch):
    """Camp alone in the panel ⇒ the camp owns an unattributed turn, exactly as
    it always has. The rule is about the SOLE programme, not about demoting the
    camp."""
    _panel(monkeypatch, [CAMP_ON])
    _flags(monkeypatch, engine)
    section = engine._active_program_section(_fresh(), "ფასი", _lead())
    assert (section or {}).get("id") == "summer_camp"


def test_two_programmes_on_sale_leave_an_unnamed_turn_unattributed(monkeypatch):
    """With a real choice to make, guessing is the bug. The turn stays
    unattributed so the agent asks which programme the parent means."""
    _panel(monkeypatch, [CAMP_OFF, SCHOOL, SECOND])
    _flags(monkeypatch, engine)
    assert engine._active_program_section(
        _fresh(), "ფასი", _lead()) is None


def test_a_named_programme_still_wins_over_the_sole_programme_rule(monkeypatch):
    _panel(monkeypatch, [CAMP_OFF, SCHOOL, SECOND])
    _flags(monkeypatch, engine)
    section = engine._active_program_section(
        _fresh(), "ზამთრის ლაბორატორია მაინტერესებს", _lead())
    assert (section or {}).get("id") == "winter_lab"


# --------------------------------------------------------------------------
# 2. The three places the camp actually reached the parent.
# --------------------------------------------------------------------------

def test_the_prompt_does_not_hardcode_the_camp_as_ended(monkeypatch):
    """`_OFFTOPIC_PROGRAM_AGNOSTIC_DIRECTIVE` was written to STOP the camp being
    offered, and states as a fact, on every single turn, that the summer camp is
    over. With nothing else attributed that is the most salient thing the model
    holds, so it volunteers it — measured 11:20 and 09:49, both with no camp
    tool call at all. The camp's status is panel data; it does not belong in a
    hardcoded prompt line."""
    monkeypatch.setattr(
        engine, "settings",
        dataclasses.replace(
            config_module.settings, USE_OFFTOPIC_INTELLIGENCE=True),
    )
    prompt = engine._build_system_prompt(message="ფასი", segment="PARENT")
    assert "საზაფხულო ბანაკი ამჟამად დასრულებულია" not in prompt, (
        "a hardcoded camp fact rides along on every turn"
    )


def test_a_closed_camp_refusal_does_not_hand_its_sentence_to_the_model(
    monkeypatch,
):
    """`_camp_public_info_limited_tool_result` put
    `_camp_registration_closed_answer()` into the refusal's `message` field, so
    the gate that blocked 2150 handed over the camp sentence instead. The model
    relayed it — screenshots 27, 30, 31, 32."""
    from app.agent.tools import parent_tool_executor as executor

    _panel(monkeypatch, [CAMP_OFF, SCHOOL])
    _flags(monkeypatch, parent_flow)

    # The turn the parents actually sent: nothing names the camp, and another
    # programme is on sale.
    assert executor._turn_belongs_to_the_camp(_fresh(), "ფასი") is False
    bare = executor._camp_public_info_limited_tool_result(
        "price", turn_is_camps=False)
    assert bare.get("success") is False
    assert "ბანაკ" not in str(bare.get("message") or ""), (
        "the refusal carries the camp sentence into the reply"
    )

    # A parent who NAMES the camp still gets the honest closed answer.
    assert executor._turn_belongs_to_the_camp(_fresh(), "ბანაკის ფასი") is True
    named = executor._camp_public_info_limited_tool_result(
        "price", turn_is_camps=True)
    assert "ბანაკ" in str(named.get("message") or "")


def test_the_camp_alone_in_the_panel_still_owns_its_refusal(monkeypatch):
    """Nothing about this rule demotes a camp that is the only programme."""
    from app.agent.tools import parent_tool_executor as executor

    _panel(monkeypatch, [CAMP_ON])
    _flags(monkeypatch, parent_flow)
    assert executor._turn_belongs_to_the_camp(_fresh(), "ფასი") is True


@pytest.mark.parametrize("message", (
    "რეგისტრაცია შევსებულიაა",
    "როდის იწყება მეორე რეგისტრაცია",
))
def test_a_generic_registration_request_is_not_the_camps(monkeypatch, message):
    """`_maybe_handle_camp_registration_link` is the one camp handler with no
    isolation guard at all. Live 09:40 and 09:41 it answered a Sunday-School
    parent with the camp's closed-registration sentence — deterministically, no
    model involved."""
    _panel(monkeypatch, [CAMP_OFF, SCHOOL])
    _flags(monkeypatch, parent_flow)
    assert parent_flow._maybe_handle_camp_registration_link(
        _fresh(), message) is None, (
        "a registration request that names nothing belongs to the programme on sale"
    )


def test_the_agents_own_camp_reply_does_not_make_the_next_turn_the_camps(
    monkeypatch,
):
    """The live shape, 2026-09-19 09:39-09:41, reconstructed.

    `_is_camp_registration_link_request` needs a camp word, so „რეგისტრაცია
    შევსებულიაა" does not match it. The turn reached the handler through the
    second, CONTEXT-AWARE detector (`legacy_actions`) — and the context it read
    was the agent's OWN previous reply, which had just said the camp is closed
    because of a different leak on the turn before.

    That is the circle this guard breaks: the agent talks about the camp, which
    makes the next question a camp question, which makes it talk about the camp
    again. Only the parent's own words decide whose turn it is."""
    _panel(monkeypatch, [CAMP_OFF, SCHOOL])
    conv = _fresh()
    conv.history = [
        {"role": "user", "content": "გამარჯობა ტერიტორიულად სად არის ცენტრი"},
        {"role": "assistant",
         "content": "ბანაკის რეგისტრაცია ამ მომენტისთვის დასრულებულია."},
    ]
    message = "რეგისტრაცია შევსებულიაა"

    # Flag off ⇒ the shipped behaviour, so the defect is visible in the test.
    monkeypatch.setattr(
        parent_flow, "settings",
        dataclasses.replace(
            config_module.settings,
            USE_DYNAMIC_PROGRAMS=True, USE_PROGRAM_ISOLATION=False,
        ),
    )
    before = parent_flow._maybe_handle_camp_registration_link(conv, message)

    _flags(monkeypatch, parent_flow)
    after = parent_flow._maybe_handle_camp_registration_link(conv, message)

    if before is not None:
        # The live path reproduced: the guard must close it.
        assert after is None, (
            "the agent's own camp reply still makes the next turn the camp's"
        )
    else:
        # The detector did not fire in this fixture; the guard must at least
        # never turn a non-answer into a camp answer.
        assert after is None


# --------------------------------------------------------------------------
# 3. A SECOND camp in the panel („პარიზის ბანაკი") — the operator's own check.
# --------------------------------------------------------------------------

PARIS = {
    "id": "paris_camp", "name": "პარიზის ბანაკი", "type": "kids_program",
    "status": "active", "age_min": 10, "age_max": 17,
    "hashtags": ["parisi", "პარიზი"], "price_text": "4500 ლარი",
}

PARIS_TURNS = (
    "პარიზის ბანაკის ფასი რა არის?",
    "პარიზის ბანაკზე როგორ დავრეგისტრირდე",
    "პარიზი მაინტერესებს",
)


@pytest.mark.parametrize("message", PARIS_TURNS)
def test_a_second_camp_is_not_this_camp(monkeypatch, message):
    """The guards added today read the message for the word „ბანაკი". The moment
    the operator opens „პარიზის ბანაკი" that word stops meaning THIS camp, and a
    raw keyword scan hands Paris questions the summer camp's closed answer —
    measured, before `_msg_names_the_camp` existed:

        პარიზის ბანაკზე როგორ დავრეგისტრირდე -> the SUMMER camp's answer
        პარიზის ბანაკის ფასი რა არის?        -> counted as the camp's turn

    So the panel is asked first, exactly as `_conversation_names_camp` already
    asks it for a history turn."""
    from app.agent.tools import parent_tool_executor as executor

    _panel(monkeypatch, [CAMP_OFF, SCHOOL, PARIS])
    _flags(monkeypatch, parent_flow)

    assert parent_flow._msg_names_the_camp(message) is False
    assert executor._turn_belongs_to_the_camp(_fresh(), message) is False
    assert parent_flow._maybe_handle_camp_registration_link(
        _fresh(), message) is None, "Paris got the summer camp's answer"


def test_the_camp_still_owns_its_own_turn_when_it_is_the_only_camp(monkeypatch):
    """Without a second camp, „ბანაკი" means this one — unchanged."""
    _panel(monkeypatch, [CAMP_OFF, SCHOOL])
    _flags(monkeypatch, parent_flow)
    assert parent_flow._msg_names_the_camp("ბანაკის ფასი") is True


def test_a_named_camp_registration_request_still_answers(monkeypatch):
    """The camp keeps every turn that names it — including the honest closed
    answer. Only the default changes."""
    _panel(monkeypatch, [CAMP_OFF, SCHOOL])
    _flags(monkeypatch, parent_flow)
    answer = parent_flow._maybe_handle_camp_registration_link(
        _fresh(), "ბანაკზე როგორ დავრეგისტრირდე")
    assert answer and "ბანაკ" in answer
