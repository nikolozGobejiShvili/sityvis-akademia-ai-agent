"""Adult events switched off in the panel never surface (operator, 2026-10-07).

„ადმინ პანელში ended წერია ზრდასრულთა ღონისძიებაზე" — and on the deployed
848ddc7, with the production flags and that panel:

* a first message with a word the keyword list files under adult events
  („საღამოს რა ღონისძიებაა?", „ბილეთი როგორ ვიყიდო?", „კულტურული საღამოები
  გაქვთ?") put the chat in the adult flow, and it stayed there;
* a Sunday-School parent's „დასკვნითი ღონისძიება იქნება?" and a Paris
  parent's „კონცერტზეც წაიყვანთ?" were answered „ამ ეტაპზე აქტიური ღონისძიება
  სიაში არ მაქვს";
* a camp + adult turn got „…ზრდასრულთა ღონისძიებებს — რომელი გაინტერესებთ?";
* the agent was offered `switch_to_adult_flow`;
* a comment under an #event post got the adult „no events" DM.

The switch is the one `get_active_adult_events` already honoured
(USE_SECTION_STATUS_GATE on, the adult_events section not active). Every
`off` test below was RED on 848ddc7; each `on sale` twin pins that nothing
changes while adult events are being sold.
"""
from __future__ import annotations

import asyncio
import dataclasses
import sys
from pathlib import Path

import pytest
import yaml

import app.config as config_module
from app.agent.llm import parent_llm_engine
from app.flows import parent_flow
from app.services import admin_config_service as acs
from app.services import anthropic_service, comment_service
from app.services import conversation_service as cs
from tests import test_programme_attribution_and_booking_2026_10_05 as h
from tests.test_programme_attribution_and_booking_2026_10_05 import (  # noqa: F401 — fixtures
    _no_network,
    world,
)

# Production flags the shared harness does not set (.env.prodlike, Railway).
_PROD_EXTRA = dict(
    USE_MIXED_INTENT_CAMP_ADULT=True, USE_VAGUE_CAMP_INTENT=True,
    USE_SELF_OVERAGE_ADULT_REDIRECT=True, USE_OFFTOPIC_INTELLIGENCE=True,
)
# „ended" is what the operator's panel says; „hidden" is the other off value.
_OFF = ("ended", "hidden")
_EVENT = {"id": "poetry", "title": "პოეზიის საღამო", "status": "active",
          "min_age": 13, "price_text": "30"}
_NONE_ACTIVE = parent_flow._EVENT_NONE_ACTIVE_REPLY
_POINTER = parent_flow._CAMP_OFF_ADULT_POINTER


def _settings(mp, **flags) -> None:
    for mod in list(sys.modules.values()):
        name = getattr(mod, "__name__", "") or ""
        current = getattr(mod, "settings", None)
        if (name == "app.config" or name.startswith("app.")) and isinstance(
            current, config_module.Settings,
        ):
            mp.setattr(mod, "settings", dataclasses.replace(current, **flags))


def _panel(mp, tmp_path, base: str, adult: str) -> None:
    """The shared synthetic panel with the adult section's status set; an
    active section carries one event so there is something on sale."""
    sections = h._sections(base)
    for section in sections:
        if section["id"] == "adult_events":
            section["status"] = adult
            section["events"] = [dict(_EVENT)] if adult == "active" else []
    path = tmp_path / f"sections_{base}_{adult}.yaml"
    path.write_text(yaml.safe_dump({"sections": sections}, allow_unicode=True,
                                   sort_keys=False), encoding="utf-8")
    mp.setattr(acs, "SECTIONS_PATH", Path(path))


@pytest.fixture
def prod(world, monkeypatch):
    _settings(monkeypatch, **_PROD_EXTRA)
    return world


@pytest.fixture
def unit(monkeypatch):
    """Production flags for the tests that need no conversation."""
    _settings(monkeypatch, **h._PROD, **_PROD_EXTRA)
    return monkeypatch


# ═══ routing — no chat is put in, or kept in, a switched-off flow ══════════

@pytest.mark.parametrize("status", _OFF)
@pytest.mark.parametrize("opener", [
    "ღონისძიებები გაქვთ?",
    "საღამოს რა ღონისძიებაა?",
    "ბილეთი როგორ ვიყიდო?",
    "კულტურული საღამოები გაქვთ?",
    "ზრდასრულთა ღონისძიებები მაინტერესებს",
])
def test_an_adult_word_does_not_put_the_chat_in_a_switched_off_flow(
    prod, monkeypatch, tmp_path, status, opener,
):
    _panel(monkeypatch, tmp_path, "SS", status)
    reply = prod.say(opener)
    assert prod.conversation.segment != "ADULT", reply
    assert _NONE_ACTIVE not in reply, reply
    assert "ზრდასრულ" not in reply, reply


def test_while_adult_events_are_on_sale_the_same_word_still_reaches_them(
    prod, monkeypatch, tmp_path,
):
    _panel(monkeypatch, tmp_path, "SS", "active")
    prod.say("საღამოს რა ღონისძიებაა?")
    assert prod.conversation.segment == "ADULT"


def test_a_chat_already_in_adult_events_leaves_them_once_they_are_switched_off(
    prod, monkeypatch, tmp_path,
):
    """A conversation saved in Redis before the operator switched the
    programme off: the segment never got re-read, so it stayed adult."""
    _panel(monkeypatch, tmp_path, "SS", "active")
    prod.say("კულტურული საღამოები გაქვთ?")
    assert prod.conversation.segment == "ADULT"
    _panel(monkeypatch, tmp_path, "SS", "ended")
    reply = prod.say("ფასი რა არის?")
    assert prod.conversation.segment == "PARENT", reply
    assert _NONE_ACTIVE not in reply, reply


# ═══ a programme's own question is that programme's ═══════════════════════

@pytest.mark.parametrize("panel,turns", [
    ("SS", ["საკვირაო სკოლა მაინტერესებს", "დასკვნითი ღონისძიება იქნება?"]),
    ("SS", ["საკვირაო სკოლა მაინტერესებს", "საღამოს შეხვედრა როდისაა?"]),
    ("SS_PARIS", ["პარიზის ბანაკი მაინტერესებს", "კონცერტზეც წაიყვანთ?"]),
    ("SS", ["კონცერტი მაინტერესებს"]),
])
def test_an_event_word_is_not_answered_from_a_switched_off_adult_list(
    prod, monkeypatch, tmp_path, panel, turns,
):
    _panel(monkeypatch, tmp_path, panel, "ended")
    for turn in turns:
        reply = prod.say(turn)
    assert _NONE_ACTIVE not in reply, reply
    assert prod.conversation.segment != "ADULT", reply


@pytest.mark.parametrize("message", [
    "ბანაკი და ზრდასრულთა ღონისძიებები მაინტერესებს",
    "ბანაკი და კულტურული საღამოები მაინტერესებს",
])
def test_camp_and_adult_in_one_turn_gets_no_pointer_to_switched_off_events(
    prod, monkeypatch, tmp_path, message,
):
    _panel(monkeypatch, tmp_path, "SS", "ended")
    reply = prod.say(message)
    assert reply, "no reply"
    assert _POINTER not in reply, reply
    assert "ზრდასრულ" not in reply, reply


@pytest.mark.parametrize("status,pointed", [("ended", False), ("active", True)])
def test_the_closed_camps_status_reply_points_at_adult_events_only_while_on_sale(
    unit, tmp_path, status, pointed,
):
    """The gate itself, on a turn that names no programme by name. (On sale,
    „ზრდასრულთა ღონისძიებები" names the adult section and the turn is
    routed there before this gate, so the twin uses „კულტურული".)"""
    _panel(unit, tmp_path, "SS", status)
    message = "ბანაკი და კულტურული საღამოები მაინტერესებს"
    conv = h._conversation([("user", message)])
    conv.segment = "PARENT"
    out = parent_flow._maybe_handle_camp_status(conv, message)
    assert out, "the closed camp's gate did not answer"
    assert (_POINTER in out) is pointed, out


# ═══ the agent is not handed a way into them ══════════════════════════════

def test_the_agent_is_not_offered_the_adult_switch_while_it_is_off(
    prod, monkeypatch, tmp_path,
):
    _panel(monkeypatch, tmp_path, "SS", "ended")
    offered: list = []
    scripted = prod.post

    def _post(**kw):
        offered.extend(((t or {}).get("function") or {}).get("name")
                       for t in (kw.get("tools") or []))
        return scripted(**kw)
    monkeypatch.setattr(anthropic_service, "_post", _post)
    prod.say("ფასი რა არის?")
    assert "book_consultation" in offered, "the engine was never asked"
    assert "switch_to_adult_flow" not in offered


@pytest.mark.parametrize("status,offered", [
    ("ended", False), ("hidden", False), ("active", True),
])
def test_the_tool_list_follows_the_panel(unit, tmp_path, status, offered):
    _panel(unit, tmp_path, "SS", status)
    names = [t["function"]["name"] for t in parent_llm_engine.build_active_tools(
        True, False, True)]
    assert ("switch_to_adult_flow" in names) is offered


@pytest.mark.parametrize("status,moved", [("ended", False), ("active", True)])
def test_a_switch_call_that_arrives_anyway_moves_nobody(unit, tmp_path, status, moved):
    _panel(unit, tmp_path, "SS", status)
    conv = h._conversation([("user", "ფასი რა არის?")])
    conv.segment = "PARENT"
    result = h._executor(conv, "ღონისძიება მაინტერესებს").execute(
        "switch_to_adult_flow", {})
    assert bool(result.get("success")) is moved, result
    assert conv.segment == ("ADULT" if moved else "PARENT")


# ═══ no reply points at them ══════════════════════════════════════════════

_BARE_SWITCH = "გასაგებია, ზრდასრულთა ღონისძიებებზე დაგეხმარებით."
_ADULT_TURN = ("ზრდასრულთა ღონისძიებებზე დაგეხმარებით. "
               "ღონისძიების შერჩევა თქვენთვის გსურთ თუ თქვენი შვილისთვის?")


@pytest.mark.parametrize("status,appended", [("ended", False), ("active", True)])
def test_the_adult_follow_up_question_is_only_asked_while_they_are_on_sale(
    unit, tmp_path, status, appended,
):
    _panel(unit, tmp_path, "SS", status)
    conv = h._conversation([("user", "ფასი რა არის?")])
    out = parent_flow._ensure_adult_intro_followup_for_parent_flow(conv, _BARE_SWITCH)
    assert (parent_flow._PARENT_ADULT_INTRO_FOLLOWUP_QUESTION in out) is appended, out


@pytest.mark.parametrize("status,kept", [("ended", False), ("active", True)])
def test_an_old_adult_turn_keeps_nobody_in_adult_events(unit, tmp_path, status, kept):
    _panel(unit, tmp_path, "SS", status)
    conv = h._conversation([("user", "ღონისძიებები გაქვთ?"), ("assistant", _ADULT_TURN)])
    out = parent_flow._maybe_handle_adult_context_relative(conv, "ჩემი შვილისთვის")
    assert (out is not None) is kept, out


@pytest.mark.parametrize("status", ["ended", "active"])
@pytest.mark.parametrize("message,on_sale_reply,off_reply", [
    # An adult asking about the camp for themselves: with nothing to point at,
    # the child intro (which asks for their child's age) would be the R7
    # mistake, so the turn is left to the engine.
    ("ჩემთვის მინდა ბანაკი, 25 წლის ვარ",
     parent_flow._CAMP_OVERAGE_ADULT_REDIRECT, None),
    ("ბავშვისთვის ბანაკი მაინტერესებს და ჩემთვის რამე ღონისძიება",
     parent_flow._CAMP_INTRO_TEXT + "\n\n" + _POINTER, parent_flow._CAMP_INTRO_TEXT),
])
def test_the_camp_intro_points_at_adult_events_only_while_they_are_on_sale(
    unit, tmp_path, status, message, on_sale_reply, off_reply,
):
    _panel(unit, tmp_path, "CAMP_ONLY", status)
    conv = h._conversation([("user", message)])
    conv.segment = "PARENT"
    out = parent_flow._maybe_handle_camp_intro(conv, message)
    assert out == (on_sale_reply if status == "active" else off_reply), out


@pytest.mark.parametrize("status,described", [
    ("ended", False), ("hidden", False), ("active", True),
])
def test_the_prompt_describes_the_adult_switch_only_while_it_is_offered(
    unit, tmp_path, status, described,
):
    """The tool's rules told the model to answer „გასაგებია, ზრდასრულთა
    ღონისძიებებზე დაგეხმარებით." — a promise nothing could keep once the tool
    and the adult flow were gone."""
    _panel(unit, tmp_path, "SS", status)
    prompt = parent_llm_engine._build_system_prompt("ფასი რა არის?", "PARENT")
    assert ("switch_to_adult_flow" in prompt) is described
    assert ("ზრდასრულთა ღონისძიებებზე დაგეხმარებით" in prompt) is described
    assert ("ზრდასრულთა ღონისძიების წესი:" in prompt) is described
    # Only the switch's own lines go; the rules around them stay.
    assert "მენეჯერის წესი:" in prompt and "უარის წესი:" in prompt
    assert "request_manager_callback" in prompt


def test_dropping_a_tool_leaves_every_other_rule_in_place():
    text = ("ა წესი:\n- ერთი `tool_a`\n\nბ წესი:\n- ორი `tool_a`\n- სამი\n\n"
            "გ წესი:\n\n- ოთხი")
    assert parent_llm_engine._without_tool_lines(text, "tool_a") == (
        "\nბ წესი:\n- სამი\n\nგ წესი:\n\n- ოთხი")


# ═══ an opt-out from the adult-event list is still honoured ══════════════

_UNSUBSCRIBED = "კარგი, მომავალ ღონისძიებებზე შეტყობინებებს აღარ გამოგიგზავნით."


def _record_unsubscribe(mp) -> list:
    from app.services import adult_subscription_service
    calls: list = []

    def _unsubscribe(platform, sender_id):
        calls.append(sender_id)
        return {"success": True, "status": "unsubscribed"}
    mp.setattr(adult_subscription_service, "unsubscribe", _unsubscribe)
    return calls


def test_a_subscriber_in_the_adult_flow_can_still_unsubscribe_once_it_is_off(
    prod, monkeypatch, tmp_path,
):
    """The subscription tells them to write „აღარ გამომიგზავნოთ"; with the flow
    switched off the turn went to Sunday School and the row stayed subscribed."""
    _panel(monkeypatch, tmp_path, "SS", "active")
    prod.say("კულტურული საღამოები გაქვთ?")
    assert prod.conversation.segment == "ADULT"
    _panel(monkeypatch, tmp_path, "SS", "ended")
    calls = _record_unsubscribe(monkeypatch)
    assert prod.say("აღარ გამომიგზავნოთ") == _UNSUBSCRIBED
    assert calls == [prod.sender]
    reply = prod.say("ფასი რა არის?")
    assert prod.conversation.segment == "PARENT", reply


def test_a_subscriber_already_moved_to_a_programme_can_still_unsubscribe(
    prod, monkeypatch, tmp_path,
):
    _panel(monkeypatch, tmp_path, "SS", "ended")
    prod.say("ფასი რა არის?")
    prod.conversation.adult_subscription_status = "subscribed"
    calls = _record_unsubscribe(monkeypatch)
    assert prod.say("აღარ გამომიგზავნოთ") == _UNSUBSCRIBED
    assert calls == [prod.sender]


def test_a_parent_who_never_subscribed_is_not_sent_to_the_adult_flow(
    prod, monkeypatch, tmp_path,
):
    _panel(monkeypatch, tmp_path, "SS", "ended")
    prod.say("ფასი რა არის?")
    calls = _record_unsubscribe(monkeypatch)
    reply = prod.say("აღარ მინდა შეტყობინებები")
    assert calls == [], reply
    assert prod.conversation.segment != "ADULT", reply


@pytest.mark.parametrize("status,mentioned", [("ended", False), ("active", True)])
def test_a_thank_you_after_an_old_subscription_gets_the_ordinary_closing(
    unit, tmp_path, status, mentioned,
):
    _panel(unit, tmp_path, "SS", status)
    conv = h._conversation([("user", "საკვირაო სკოლა მაინტერესებს"),
                            ("assistant", "საკვირაო სკოლის ფასი 595 ლარია.")])
    conv.adult_subscription_status = "subscribed"
    text = parent_llm_engine._build_sales_context(conv, conv.lead, "მადლობა")
    assert ("სუბსქრიფციის" in text) is mentioned, text


# ═══ comments — a hashtag routes nowhere a switched-off programme lives ════

def _comment(mp, tmp_path, adult: str, caption: str) -> tuple[str, str | None]:
    """The DM a comment gets, and the segment its conversation is left in."""
    _panel(mp, tmp_path, "SS", adult)

    async def _caption(post_id, platform):
        return caption
    mp.setattr(comment_service, "fetch_post_content", _caption)
    # The env lists as an older deploy carried them (config.ADULT_HASHTAGS).
    mp.setattr(comment_service, "settings", dataclasses.replace(
        comment_service.settings, PARENT_HASHTAGS=["camp", "ბანაკი"],
        ADULT_HASHTAGS=["event", "ღონისძიება"]))
    box: dict = {}

    def _reply(comment_id, text):
        box["text"] = text
        return True
    mp.setattr(comment_service.messenger_service, "send_private_reply", _reply)
    sender = "r5-comment-" + adult
    asyncio.run(comment_service.send_dm_from_comment(
        sender, "facebook", "post-1", None, comment_id="c-1", comment_text="ფასი?"))
    segment = None
    for key, conv in list(cs.conversations.items()):
        if getattr(conv, "sender_id", "") == sender:
            segment = conv.segment
            cs.conversations.pop(key, None)
    return box.get("text", ""), segment


@pytest.mark.parametrize("status", _OFF)
def test_a_comment_under_an_event_post_gets_the_greeting_not_the_adult_dm(
    unit, tmp_path, status,
):
    """„hidden" matched the section's own hashtags; „ended" fell through to the
    env list's #event — both sent the adult DM and left the chat adult."""
    text, segment = _comment(unit, tmp_path, status, "საღამო #event #ღონისძიება")
    assert text, "no DM at all"
    assert comment_service.ADULT_NO_EVENTS_DM not in text, text
    assert "ღონისძიებ" not in text, text
    assert "რით შემიძლია დაგეხმაროთ" in text, text
    assert segment != "ADULT"


def test_a_comment_under_an_event_post_still_lists_events_on_sale(unit, tmp_path):
    text, segment = _comment(unit, tmp_path, "active", "საღამო #event #ღონისძიება")
    assert _EVENT["title"] in text, text
    assert segment == "ADULT"


@pytest.mark.parametrize("status,section", [
    ("ended", "paris_camp"), ("hidden", "paris_camp"), ("active", "adult_events"),
])
def test_a_post_tagged_for_two_programmes_goes_to_the_one_on_sale(
    unit, tmp_path, status, section,
):
    """The first matching section wins, and the adult section is listed before
    Paris. Switched off (any off status), it is skipped like an ended one."""
    _panel(unit, tmp_path, "SS_PARIS", status)

    async def _caption(post_id, platform):
        return "პარიზის საღამო #event #პარიზი"
    unit.setattr(comment_service, "fetch_post_content", _caption)
    found = asyncio.run(comment_service.resolve_section_from_post("post-1", "facebook"))
    assert (found or {}).get("id") == section


@pytest.mark.parametrize("status,segment", [
    ("ended", "UNCLEAR"), ("hidden", "UNCLEAR"), ("active", "ADULT"),
])
def test_the_post_segment_follows_the_panel(unit, tmp_path, status, segment):
    _panel(unit, tmp_path, "SS", status)

    async def _caption(post_id, platform):
        return "#event"
    unit.setattr(comment_service, "fetch_post_content", _caption)
    unit.setattr(comment_service, "settings", dataclasses.replace(
        comment_service.settings, ADULT_HASHTAGS=["event"]))
    assert asyncio.run(comment_service.determine_segment_from_post(
        "post-1", "facebook")) == segment
