"""Planner-first stabilization patch (Phase 3 Stage 2, 2026-06-24).

Covers Classes 1–6 of the live-transcript stabilization:

  1. planner-first / pending-state protection (manager phone overrides Sunday
     School; known contact never re-asked);
  2. topic-routing authority (active_topic controls the route; adult-event turns
     never get a camp answer);
  3. selected-state contract (adult-self sees adult_age only; camp sees
     child_age only; recall sees both, separately);
  4. slim prompts (USE_SLIM_PROMPTS → core prompts, not the giant ones);
  5. planner state writebacks (adult-age self-correction; bare registration);
  6. expanded final validator.

Everything is deterministic / offline: the LLM engines are mocked, Calendar /
Sheets / WhatsApp / email are never reached. The planner flags are enabled
explicitly per the LIFO monkeypatch convention (conftest pins them OFF).
"""
from __future__ import annotations

import dataclasses

import pytest

import app.config as config_module
from app.agent.llm import adult_llm_engine, parent_llm_engine
from app.flows import adult_flow, parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.reasoning import conversation_planner as cp
from app.reasoning import conversation_trace as trace
from app.reasoning import selected_state as ss
from app.services import conversation_service, notification_service, sheets_service

_FLAGS = dict(
    USE_CONVERSATION_PLANNER=True,
    CONVERSATION_PLANNER_AUTHORITATIVE=True,
    USE_PARENT_LLM_ENGINE=True,
    USE_ADULT_LLM_ENGINE=True,
)

_PARENT_CANNED = "ბანაკის შესახებ დაგეხმარებით."
_ADULT_CANNED = "ზრდასრულთა აქტიური ღონისძიებები: დეტალებს გაგიზიარებთ."


def _fake_parent_engine(conversation, message):
    """Mimic the real engine's deterministic fact capture (child_age / phone)
    WITHOUT calling OpenAI, then return canned camp text."""
    lead = conversation.lead
    try:
        pending = parent_llm_engine._bot_recently_asked_child_age(conversation)
        parent_llm_engine.maybe_capture_child_age_fallback(
            lead, message, age_question_pending=pending,
        )
    except Exception:
        pass
    try:
        parent_llm_engine.maybe_capture_phone_fallback(lead, message)
    except Exception:
        pass
    return _PARENT_CANNED


@pytest.fixture
def live(monkeypatch):
    for mod in (
        conversation_service, parent_flow, adult_flow,
        parent_llm_engine, adult_llm_engine, config_module,
    ):
        monkeypatch.setattr(
            mod, "settings", dataclasses.replace(mod.settings, **_FLAGS),
        )
    monkeypatch.setattr(parent_flow, "_run_llm_engine_safely", _fake_parent_engine)
    monkeypatch.setattr(adult_flow, "_run_adult_engine_safely", lambda c, l, m: _ADULT_CANNED)
    monkeypatch.setattr(
        notification_service, "notify_sunday_school_handoff", lambda lead: True,
    )
    monkeypatch.setattr(sheets_service, "log_sunday_school_lead", lambda *a, **k: True)
    parent_flow._sunday_school_notified_senders.clear()
    conversation_service.conversations.clear()
    yield


def _conv(sender, segment="PARENT", state="IN_PROGRESS", history=None, **lk):
    lead = Lead(sender_id=sender, platform="messenger", segment=segment)
    for k, v in lk.items():
        setattr(lead, k, v)
    conv = Conversation(
        sender_id=sender, platform="messenger", segment=segment, state=state,
        lead=lead, history=history or [{"role": "assistant", "content": "prev"}],
    )
    conversation_service.conversations[sender] = conv
    return conv


def _send(sender, text, platform="messenger"):
    return conversation_service.process_message(sender, text, platform)


def _manager_phone() -> str:
    from app.services import admin_config_service
    return (admin_config_service.get_manager_phone() or "558 67 47 33").strip()


# ───────────────────────── Class 3: selected-state contract (unit) ────────────

def test_selected_state_adult_self_excludes_child_age():
    """Class 3 — adult_event_for_self sees adult_age only; child_age excluded."""
    lead = Lead(sender_id="s", platform="messenger", segment="ADULT", child_age="7", adult_age="29")
    conv = Conversation(sender_id="s", platform="messenger", segment="ADULT", lead=lead)
    plan = cp.plan_turn("ჩემთვის მინდა", conv)
    sel = ss.build_selected_state(plan, lead, conv)
    assert sel.get(cp.S_CHILD_AGE) is None        # child age EXCLUDED
    assert "child_age" not in ss.format_selected_state(sel)


def test_selected_state_camp_excludes_adult_age():
    """Class 3 — camp context sees child_age only; adult_age excluded."""
    lead = Lead(sender_id="s", platform="messenger", segment="PARENT", child_age="13", adult_age="40")
    conv = Conversation(sender_id="s", platform="messenger", segment="PARENT", lead=lead)
    plan = cp.plan_turn("ბანაკზე უსაფრთხოება დაცულია?", conv)
    sel = ss.build_selected_state(plan, lead, conv)
    assert sel.get(cp.S_CHILD_AGE) == "13"
    assert sel.get(cp.S_ADULT_AGE) is None


def test_selected_state_recall_includes_both_ages_separately():
    """Class 3 / test #7 — state_recall sees BOTH child_age and adult_age,
    under distinct keys."""
    lead = Lead(
        sender_id="s", platform="messenger", segment="ADULT", child_age="7",
        adult_age="29", name="ჯონი", phone="595999733",
    )
    conv = Conversation(sender_id="s", platform="messenger", segment="ADULT", lead=lead)
    plan = cp.plan_turn("ჩემზე რა ინფრომაცია გაქვს?", conv)
    sel = ss.build_selected_state(plan, lead, conv)
    assert sel.get(cp.S_CHILD_AGE) == "7"
    assert sel.get(cp.S_ADULT_AGE) == "29"
    assert sel.get(cp.S_NAME) == "ჯონი"
    assert sel.get(cp.S_PHONE) == "595***733"      # masked, not the full number


# ───────────────────────── Class 1: planner-first protection ──────────────────

def test_manager_phone_overrides_sunday_school_pending(live):
    """Class 1 / test #3 — a manager-phone request while a Sunday-School
    collection is pending returns the manager number immediately, NOT the
    Sunday-School success."""
    conv = _conv(
        "u_mgr", child_age="7", name="ჯონი", phone="595999733",
        history=[{"role": "assistant", "content": "საკვირაო სკოლის თაობაზე მომწერეთ თქვენი სახელი"}],
    )
    resp = _send("u_mgr", "მენეჯერის ნომერი მომწერეთ და მეთვითონ დავურეკავ")
    assert _manager_phone() in resp
    assert "გადავეცი მენეჯერს" not in resp          # not the Sunday-School success


def test_sunday_school_known_contact_not_reasked(live):
    """Class 1 / Stage-3 #5 — a Sunday-School inquiry with a KNOWN contact does
    not re-ask name/phone, and OFFERS consent (no auto-handoff)."""
    _conv("u_ss", child_age="7", name="ჯონი", phone="595999733")
    resp = _send("u_ss", "მადლობა და კიდევ მაინტერესებს საკვირაო სკოლა როდის ემატება?")
    assert "მომწერეთ თქვენი სახელი" not in resp
    assert "9-ნიშნა ნომერი" not in resp
    # consent-first (#5): offer to pass the contact, do NOT auto-dispatch
    assert "გადავეცი მენეჯერს" not in resp
    assert ("მენეჯერს გადავცემ" in resp) or ("დაგიკავშირდებათ" in resp)


# ───────────────────────── Class 2: topic-routing authority ───────────────────

def test_adult_discovery_routes_to_adult_flow_not_camp(live, monkeypatch):
    """Class 2 / test #4 — an adult-event discovery turn is answered by the
    ADULT flow, never the parent camp engine."""
    # fail loudly if the parent camp engine is consulted for this turn
    def _boom(*a, **k):
        raise AssertionError("adult-event turn must NOT reach the parent camp engine")
    monkeypatch.setattr(parent_flow, "_run_llm_engine_safely", _boom)
    conv = _conv("u_adult", child_age="7", name="ჯონი", phone="595999733")
    resp = _send("u_adult", "ამ ეტაპზე რა ღონისძიებები გაქვთ?")
    assert resp == _ADULT_CANNED
    assert conv.segment == "ADULT"                  # sticky topic switch


def test_adult_self_does_not_use_child_age_as_adult_age(live):
    """Class 2/3 / test #5 — „ჩემთვის მინდა" with child_age=7 routes to the adult
    flow; the answer never presents the user as 7."""
    conv = _conv(
        "u_self", segment="ADULT", child_age="7", name="ჯონი", phone="595999733",
        history=[{"role": "assistant", "content": "ზრდასრულთა ღონისძიებები"}],
    )
    resp = _send("u_self", "ჩემთვის მინდა")
    assert "7" not in resp
    assert conv.lead.child_age == "7"               # child age preserved
    # the planner selected-state for this turn excludes child_age
    plan = conv._turn_plan
    sel = ss.build_selected_state(plan, conv.lead, conv)
    assert sel.get(cp.S_CHILD_AGE) is None


# ───────────────────────── Class 5: state writebacks ──────────────────────────

def test_adult_age_self_correction_writeback(live):
    """Class 5 / test #6 — „ჩემი ასაკი 29 წელია, ეგ ჩემი შვილის ასაკია" writes
    adult_age=29 and preserves child_age=7."""
    conv = _conv(
        "u_corr", segment="ADULT", child_age="7", name="ჯონი", phone="595999733",
        history=[{"role": "assistant", "content": "ზრდასრულთა ღონისძიებები, რამდენი წლის ბრძანდებით?"}],
    )
    _send("u_corr", "ჩემი ასაკი 29 წელია, ეგ ჩემი შვილის ასაკია")
    assert conv.lead.adult_age == "29"
    assert conv.lead.child_age == "7"               # NOT overwritten


def test_bare_registration_returns_link_no_age_question(live):
    """Class 5 / test #8 — „რეგისტრაცია მინდა" in an active camp context returns
    the registration link and does NOT append an age question."""
    conv = _conv(
        "u_reg", segment="PARENT", child_age="7",
        history=[{"role": "assistant", "content": "ბანაკზე რეგისტრაცია ხდება ამ ბმულზე"}],
    )
    resp = _send("u_reg", "რეგისტრაცია მინდა")
    assert ("რეგისტრაცი" in resp) or ("ბმულ" in resp) or ("http" in resp.lower())
    assert "რამდენი წლისაა" not in resp and "რა ასაკის" not in resp


# ───────────────────────── Class 4: slim prompts ──────────────────────────────

def test_slim_prompts_skip_giant_prompts(monkeypatch):
    """Class 4 / test #9 — USE_SLIM_PROMPTS=true loads parent_core/adult_core and
    NEVER system_parent_v2 / system_adult_v1."""
    from app.agent.llm import prompt_loader

    calls: list[str] = []
    orig = prompt_loader.load_prompt

    def _spy(name):
        calls.append(name)
        return orig(name)

    monkeypatch.setattr(prompt_loader, "load_prompt", _spy)
    monkeypatch.setattr(parent_llm_engine, "load_prompt", _spy)
    monkeypatch.setattr(adult_llm_engine, "load_prompt", _spy)
    monkeypatch.setattr(
        parent_llm_engine, "settings",
        dataclasses.replace(parent_llm_engine.settings, USE_SLIM_PROMPTS=True),
    )
    monkeypatch.setattr(
        adult_llm_engine, "settings",
        dataclasses.replace(adult_llm_engine.settings, USE_SLIM_PROMPTS=True),
    )

    parent_llm_engine._build_system_prompt()
    adult_llm_engine._build_system_prompt()

    assert "parent_core" in calls and "adult_core" in calls
    assert "system_parent_v2" not in calls
    assert "system_adult_v1" not in calls


def test_giant_prompts_loaded_when_slim_off(monkeypatch):
    """Regression — with USE_SLIM_PROMPTS off the giant prompts load as before."""
    from app.agent.llm import prompt_loader

    calls: list[str] = []
    orig = prompt_loader.load_prompt

    def _spy(name):
        calls.append(name)
        return orig(name)

    monkeypatch.setattr(parent_llm_engine, "load_prompt", _spy)
    monkeypatch.setattr(adult_llm_engine, "load_prompt", _spy)
    parent_llm_engine._build_system_prompt()
    adult_llm_engine._build_system_prompt()
    assert "system_parent_v2" in calls and "system_adult_v1" in calls


# ───────────────────────── Class 6: final validator (unit) ────────────────────

def test_validator_forces_manager_phone():
    """Class 6 — a manager-phone request whose answer lacks the number is
    repaired to include it."""
    lead = Lead(sender_id="s", platform="messenger", segment="PARENT")
    conv = Conversation(sender_id="s", platform="messenger", segment="PARENT", lead=lead)
    plan = cp.plan_turn("მენეჯერის ნომერი მომწერეთ", conv)
    out = parent_flow.planner_final_validate(conv, plan, "ვერ დაგეხმარებით ამ საკითხში.")
    assert _manager_phone() in out


def test_validator_strips_robotic_decline_phrase():
    """Class 6 — the robotic „სიამოვნებით." opener is stripped from a decline."""
    lead = Lead(sender_id="s", platform="messenger", segment="PARENT")
    conv = Conversation(sender_id="s", platform="messenger", segment="PARENT", lead=lead)
    plan = cp.plan_turn("არ მინდა მადლობა", conv)
    out = parent_flow.planner_final_validate(
        conv, plan, "სიამოვნებით. გისურვებთ ნებისმიერ დროს დაგვიკავშირდეთ.",
    )
    assert "სიამოვნებით." not in out


def test_validator_strips_camp_eligibility_from_adult_answer():
    """Class 6 — camp eligibility framing is stripped from an adult-event answer."""
    lead = Lead(sender_id="s", platform="messenger", segment="ADULT", adult_age="29")
    conv = Conversation(sender_id="s", platform="messenger", segment="ADULT", lead=lead)
    plan = cp.plan_turn("ჩემთვის მინდა ღონისძიება", conv)
    polluted = (
        "ზრდასრულთა ღონისძიება გაქვთ. ბანაკში მონაწილეობა შესაძლებელია 9–17 წლის ბავშვებისთვის."
    )
    out = parent_flow.planner_final_validate(conv, plan, polluted)
    assert "9–17" not in out and "ბანაკში მონაწილეობა" not in out


# ───────────────────────── test #10: trace fields ─────────────────────────────

def test_trace_includes_route_handler_prompt_selected_validator(monkeypatch, live):
    """Test #10 — the per-turn trace block includes route / handler / planner /
    selected_state / validator / final answer."""
    monkeypatch.setattr(
        config_module, "settings",
        dataclasses.replace(config_module.settings, CONVERSATION_TRACE_DEBUG=True, **_FLAGS),
    )
    trace.reset_history()
    _conv("u_trace", child_age="7", name="ჯონი", phone="595999733")
    _send("u_trace", "მენეჯერის ნომერი მომწერეთ და მეთვითონ დავურეკავ")
    blocks = trace.history()
    assert blocks, "trace should record a block when CONVERSATION_TRACE_DEBUG is on"
    blk = blocks[-1]
    assert "route" in blk
    assert blk.get("planner_intent") == "manager_phone_request"
    assert "selected_state" in blk
    assert "final_validator_ran" in blk
    assert "final_answer" in blk


# ───────────────────────── test #1: full A–N replay ───────────────────────────

def test_full_transcript_replay(live):
    """Test #1 — replay the exact controlled smoke transcript and assert the
    critical per-turn pass criteria."""
    s = "u_replay"
    _conv(s, segment="UNCLEAR", state="START", history=[])

    # 1–4: camp info → child age 7 → connect → contact. (Setup turns; the
    # engine fact-capture lands child_age; contact is established below.)
    _send(s, "გამარჯობა ბანაკზე ინფრომაცია მაინტერესებს")
    _send(s, "7 წლის არის")
    conv = conversation_service.conversations[s]
    assert conv.lead.child_age == "7"
    _send(s, "კი დამაკავშირეთ")
    _send(s, "ჯონი 595999733")
    # ensure the established contact (turns 3–4 exercise the underage handoff;
    # seed defensively so the stabilization turns below are isolated from it)
    conv.lead.name = conv.lead.name or "ჯონი"
    conv.lead.phone = conv.lead.phone or "595999733"
    assert conv.lead.child_age == "7"

    # 5: Sunday School with known contact → must NOT re-ask name/phone
    r5 = _send(s, "მადლობა და კიდევ მაინტერესებს საკვირაო სკოლა როდის ემატება?")
    assert "მომწერეთ თქვენი სახელი" not in r5 and "9-ნიშნა ნომერი" not in r5

    # 6: manager phone → returns the number immediately (overrides pending SS)
    r6 = _send(s, "მენეჯერის ნომერი მომწერეთ და მეთვითონ დავურეკავ")
    assert _manager_phone() in r6

    # 7–9: adult event discovery / self → ADULT flow, never camp
    r7 = _send(s, "ამ ეტაპზე რა ღონისძიებები გაქვთ?")
    assert r7 == _ADULT_CANNED
    r8 = _send(s, "ზრდასრულთა ღონისძიებებს ვგულისხმობ")
    assert r8 == _ADULT_CANNED
    r9 = _send(s, "ჩემთვის მინდა")
    assert "7" not in r9                            # never treats the user as 7
    assert conv.segment == "ADULT"

    # 10: adult age self-correction → adult_age=29, child_age stays 7
    _send(s, "ჩემი ასაკი 29 წელია, ეგ ჩემი შვილის ასაკია")
    assert conv.lead.adult_age == "29"
    assert conv.lead.child_age == "7"

    # 11: state recall → name + masked phone + child_age + adult_age (separate)
    r11 = _send(s, "ჩემზე რა ინფრომაცია გაქვს?")
    assert "ჯონი" in r11
    assert "595***733" in r11 and "595999733" not in r11
    assert "7" in r11 and "29" in r11

    # 12: decline → no robotic „სიამოვნებით."
    r12 = _send(s, "არ მინდა მადლობა")
    assert "სიამოვნებით." not in r12

    # 13: camp registration → link, no age question
    r13 = _send(s, "გამარჯობა ბანაკზე როგორ დავრეგისტრირდე?")
    assert "რამდენი წლისაა" not in r13

    # 14: bare registration in camp context → link, no age question
    r14 = _send(s, "რეგისტრაცია მინდა")
    assert "რამდენი წლისაა" not in r14
    assert ("რეგისტრაცი" in r14) or ("ბმულ" in r14) or ("http" in r14.lower())
