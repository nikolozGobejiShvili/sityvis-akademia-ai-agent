"""Three live production bugs (2026-07-08):

BUG D — duplicate DM reply. Meta redelivers the same messaging event; without a
        `mid` idempotency guard the bot replies twice. Fixed by reading the mid
        and deduping (in-process LRU + Redis), modelled on the comment dedup.
BUG E — a camp parent's call/visit question routed to adult events. The neutral
        welcome menu (which lists an adult LINE) locked the conversation into
        adult context forever; a saved in-band child age now wins, the menu no
        longer counts as adult context, and a call/visit question gets a camp
        answer.
BUG C — child age asked twice during booking. A „name / phone / age" intake
        message dropped the age (name+phone parse only), so the slot confirmation
        re-asked it. Fixed by capturing an in-band age at the intake site.

Deterministic; the LLM engine is mocked where a handle()-level check is needed.
"""
from __future__ import annotations

import asyncio
import dataclasses

import pytest

import app.config as config_module
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.routes import webhook
from app.services import admin_config_service, messenger_service

_MANAGER = "558 67 47 33"
_MENU = (
    "გვითხარით, რა გაინტერესებთ:\n— ბავშვების საზაფხულო ბანაკი (9-17 წელი)\n"
    "— ზრდასრულთა კულტურული საღამოები"
)
_ADULT_STEER = (
    "გასაგებია, ზრდასრულთა ღონისძიებებზე დაგეხმარებით. "
    "ღონისძიების შერჩევა თქვენთვის გსურთ თუ თქვენი შვილისთვის?"
)


def _conv(sid="x", *, seg="PARENT", state="", history=None, age="", pending=None) -> Conversation:
    c = Conversation(sender_id=sid, platform="instagram", segment=seg)
    if state:
        c.state = state
    c.lead = Lead(sender_id=sid, platform="instagram", segment=seg, child_age=age)
    for t in history or []:
        c.history.append(t)
    if pending:
        c.pending_booking = pending
    return c


# ════════════════════════════════════════════════════════════════════════════
# BUG D — DM idempotency
# ════════════════════════════════════════════════════════════════════════════
def _dm_payload(mid, *, text="გამარჯობა", sender="U1", page="P1"):
    return {"object": "page", "entry": [
        {"id": page, "messaging": [
            {"sender": {"id": sender}, "message": {"mid": mid, "text": text}},
        ]},
    ]}


@pytest.fixture
def dm_buffer(monkeypatch):
    """LRU-only dedup (Redis off) + a buffer_message spy that records each call."""
    webhook._processed_dms_lru.clear()
    monkeypatch.setattr(webhook.redis_state_service, "is_enabled", lambda: False)
    calls: list[dict[str, str]] = []

    async def _fake_buffer(*, sender_id, message, platform, page_id, on_ready):
        calls.append({
            "sender_id": sender_id,
            "message": message,
            "platform": platform,
            "page_id": page_id,
        })

    monkeypatch.setattr(webhook.message_buffer, "buffer_message", _fake_buffer)
    return calls


def test_d_same_mid_twice_processed_once(dm_buffer):
    p = _dm_payload("m1")
    asyncio.run(webhook._process_payload(p))
    asyncio.run(webhook._process_payload(p))   # Meta redelivery
    assert len(dm_buffer) == 1


def test_d_same_text_different_mid_processed_twice(dm_buffer):
    asyncio.run(webhook._process_payload(_dm_payload("m1", text="კი")))
    asyncio.run(webhook._process_payload(_dm_payload("m2", text="კი")))  # legit repeat
    assert [call["message"] for call in dm_buffer] == ["კი", "კი"]


def test_d_missing_mid_never_deduped(dm_buffer):
    asyncio.run(webhook._process_payload(_dm_payload("", text="გამარჯობა")))
    asyncio.run(webhook._process_payload(_dm_payload("", text="გამარჯობა")))
    assert len(dm_buffer) == 2   # no mid → never collapse distinct deliveries


def test_d_dedup_key_shape():
    assert webhook._dm_dedup_key("messenger", "P1", "U1", "") == ""
    assert webhook._dm_dedup_key("messenger", "P1", "U1", "m9") == "processed_dm:messenger:P1:U1:m9"


def test_d_extract_reads_mid_and_page():
    msgs = webhook._extract_meta_messages(
        {"object": "page"}, _dm_payload("mZ", sender="S", page="PG")["entry"][0],
    )
    assert msgs and msgs[0]["mid"] == "mZ" and msgs[0]["page_id"] == "PG"


def test_d_webhook_passes_page_id_to_buffer(dm_buffer):
    asyncio.run(webhook._process_payload(_dm_payload("m-page", sender="S", page="PAGE-A")))
    assert dm_buffer[0]["sender_id"] == "S"
    assert dm_buffer[0]["platform"] == "messenger"
    assert dm_buffer[0]["page_id"] == "PAGE-A"


def test_d_comment_dedup_not_regressed():
    webhook._processed_comments_lru.clear()
    assert webhook._is_comment_processed_local("c1") is False
    webhook._mark_comment_processed_local("c1")
    assert webhook._is_comment_processed_local("c1") is True
    # DM and comment LRUs are independent.
    assert webhook._is_dm_processed_local("c1") is False


# ════════════════════════════════════════════════════════════════════════════
# BUG E — camp context wins over the adult misroute
# ════════════════════════════════════════════════════════════════════════════
def test_e_menu_only_not_adult_context():
    assert parent_flow._bot_recently_in_adult_context(
        _conv(history=[{"role": "assistant", "content": _MENU}]),
    ) is False


def test_e_actual_adult_steering_is_adult_context():
    assert parent_flow._bot_recently_in_adult_context(
        _conv(history=[{"role": "assistant", "content": _ADULT_STEER}]),
    ) is True


def test_e_saved_in_band_age_stays_camp():
    # child_age=12 saved → relative message stays camp (returns None).
    c = _conv(history=[{"role": "assistant", "content": _MENU}], age="12")
    assert parent_flow._maybe_handle_adult_context_relative(c, "ჩემი შვილისთვის") is None


def test_e_parent_contact_visit_answer():
    c = _conv(history=[{"role": "assistant", "content": _MENU}], age="12")
    out = parent_flow._maybe_handle_parent_contact_visit(
        c, "შემიძლია ბავშვს დავურეკო ან ჩამოვიდე და ვნახო?",
    )
    assert out is not None
    assert ("ყოველდღიურ" in out or "ფოტო-ვიდეო" in out)     # daily updates
    assert _MANAGER in out                                   # manager phone
    assert "ზრდასრულთა ღონისძიებ" not in out
    assert "მონაწილე" not in out                             # no adult phrasing


def test_e_visit_handler_defers_without_camp_context():
    # No saved age / no camp flow → not our turn.
    assert parent_flow._maybe_handle_parent_contact_visit(
        _conv(history=[{"role": "assistant", "content": _MENU}]),
        "შემიძლია ბავშვს ჩამოვიდე და ვნახო?",
    ) is None


def test_e_lets_see_dates_not_hijacked():
    # „ვნახოთ თარიღები" is a booking phrase, NOT a visit request.
    c = _conv(history=[{"role": "assistant", "content": _MENU}], age="12")
    assert parent_flow._maybe_handle_parent_contact_visit(c, "კი ვნახოთ თარიღები") is None


# ── COUNTER-TEST: genuine adult-events context must STILL win ─────────────────
_ADULT_OFFER = {
    "role": "assistant",
    "content": "ზრდასრულთა კულტურული საღამოები. ღონისძიების შერჩევა თქვენთვის თუ შვილისთვის?",
}


def test_e_counter_adult_participant_stays_adult():
    hist = [
        {"role": "user", "content": "80 წლის არია"},
        _ADULT_OFFER,
    ]
    c = _conv(history=hist)   # NO camp child_age
    # The visit handler does not fire (no call/visit trigger, no camp context).
    assert parent_flow._maybe_handle_parent_contact_visit(c, "ჩემი შვილისთვის") is None
    # The adult-context handler STILL keeps adult events (known adult participant).
    out = parent_flow._maybe_handle_adult_context_relative(c, "ჩემი შვილისთვის")
    assert out == parent_flow._ADULT_CTX_ADULT_PARTICIPANT


def test_e_counter_menu_then_camp_topic_not_adult():
    # Menu shown, then a later camp-topic assistant turn → still not adult ctx.
    hist = [
        {"role": "assistant", "content": _MENU},
        {"role": "user", "content": "უსაფრთხოება?"},
        {"role": "assistant", "content": "დიახ, უსაფრთხოებას დიდი ყურადღება ეთმობა."},
    ]
    assert parent_flow._bot_recently_in_adult_context(_conv(history=hist)) is False


# ── E2E: the live message must NOT get the adult participant-age question ─────
@pytest.fixture
def engine(monkeypatch):
    swapped = dataclasses.replace(
        config_module.settings, USE_PARENT_LLM_ENGINE=True,
        USE_CONVERSATION_PLANNER=False, CONVERSATION_PLANNER_AUTHORITATIVE=False,
        USE_SLIM_PROMPTS=False,
    )
    monkeypatch.setattr(parent_flow, "settings", swapped)
    monkeypatch.setattr(messenger_service, "get_user_profile", lambda s, p: {})
    monkeypatch.setattr(admin_config_service, "get_camp_status", lambda: "active")
    monkeypatch.setattr(parent_flow, "_run_llm_engine_safely", lambda c, m: "SENTINEL_ENGINE")
    return monkeypatch


def test_e_e2e_live_message_not_adult_age_question(engine):
    c = _conv("live", state="ASK_CHALLENGE", age="12",
              history=[{"role": "assistant", "content": _MENU},
                       {"role": "assistant", "content": "რას ელოდებით ბანაკისგან?"}])
    out = parent_flow.handle(c, "შემიძლია ბავშვს დავურეკო ან ჩამოვიდე და ვნახო?")
    assert parent_flow._ADULT_CTX_ASK_AGE not in out
    assert "რამდენი წლის არის მონაწილე" not in out
    assert "ზრდასრულთა ღონისძიებ" not in out
    assert _MANAGER in out                     # a camp manager-defer answer
    assert "SENTINEL_ENGINE" not in out


def test_e_e2e_visit_only_gets_camp_answer(engine):
    c = _conv("live2", state="ASK_CHALLENGE", age="12",
              history=[{"role": "assistant", "content": _MENU}])
    out = parent_flow.handle(c, "შემიძლია ბავშვს ჩამოვიდე და ვნახო?")
    assert parent_flow._ADULT_CTX_ASK_AGE not in out
    assert ("ყოველდღიურ" in out or "ფოტო-ვიდეო" in out)
    assert _MANAGER in out


# ════════════════════════════════════════════════════════════════════════════
# BUG C — capture child age from contact intake
# ════════════════════════════════════════════════════════════════════════════
def _lead():
    return Lead(sender_id="s", platform="instagram", segment="PARENT")


def test_c_captures_age_from_name_phone_age():
    l = _lead()
    parent_flow._capture_child_age_from_contact(l, "მარიამი\n558070088\n12 წლის")
    assert l.child_age == "12"


def test_c_no_age_leaves_empty():
    l = _lead()
    parent_flow._capture_child_age_from_contact(l, "მარიამი\n558070088")
    assert l.child_age == ""


def test_c_phone_never_read_as_age():
    l = _lead()
    parent_flow._capture_child_age_from_contact(l, "558070088")
    assert l.child_age == ""


def test_c_age_band_never_captured():
    l = _lead()
    parent_flow._capture_child_age_from_contact(l, "ბანაკი 9-17 წლის ბავშვებისთვისაა?")
    assert l.child_age == ""


def test_c_never_overwrites_existing():
    l = _lead()
    l.child_age = "14"
    parent_flow._capture_child_age_from_contact(l, "მარიამი 558070088 12 წლის")
    assert l.child_age == "14"


def test_c_multi_child_records_both():
    l = _lead()
    parent_flow._capture_child_age_from_contact(l, "ნინო 558070088 12 და 14 წლის")
    assert l.child_age == "12"
    assert "12 და 14" in (l.deeper_concern or "")


def test_c_ask_name_intake_captures_age(monkeypatch):
    # Drive the legacy ASK_NAME booking-intake site directly.
    monkeypatch.setattr(parent_flow, "_present_value_response", lambda conv: "VALUE")
    c = _conv("ci", state="ASK_NAME")
    parent_flow._handle_ask_name(c, c.lead, "მარიამი\n558070088\n12 წლის")
    assert c.lead.child_age == "12"


def test_c_no_reask_when_age_known():
    # After capture, the slot-confirmation guard does NOT append the age question.
    c = _conv("k", age="12")
    out = parent_flow._ensure_camp_age_question(c, "კი", "შესანიშნავია, მალე დაგირეკავთ.")
    assert "წლისაა" not in out


def test_c_counter_still_asks_when_age_unknown():
    # No age captured → the legitimate age question IS still asked.
    c = _conv("u", age="")
    out = parent_flow._ensure_camp_age_question(c, "მარიამი 558070088", "კარგი.")
    assert "წლისაა" in out
