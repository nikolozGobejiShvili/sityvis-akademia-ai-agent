# -*- coding: utf-8 -*-
"""Live-test upload regressions (2026-07-02) — pre-deploy hotfix.

Issue 1 — greeting + remaining-seats must NOT route to the generic menu, and a
          FIRST-TURN greeting earns the „გამარჯობა 💙" opener before the
          remaining-seats manager defer.

Issue 2 — safety + parent-contact multi-question must return the safety answer
          PLUS the FULL parent-communication block (daily program + photo/video +
          the direct-call manager defer) — the direct-call fallback was being
          dropped by the multi-question first-paragraph trim.

Legacy/live mode: engine ON, planner + slim OFF; client 💙 policy ON.
"""
from __future__ import annotations

import dataclasses

import pytest

import app.config as config_module
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import conversation_service, messenger_service

_SEATS_FB = "რაც შეეხება კონკრეტულ ნაკადზე დარჩენილ ადგილებს, ამ დეტალებს მენეჯერი გაგაცნობთ : 558 67 47 33"
_DIRECT_CALL_FB = "რაც შეეხება ბავშვთან პირდაპირი კონტაქტის წესებს, ამ დეტალებს მენეჯერი გაგაცნობთ : 558 67 47 33"
_SAFETY_1 = "დიახ, უსაფრთხოების ნაწილს დიდი ყურადღება ეთმობა. ბანაკის დეტალები დაგეგმილია ევროპული საბანაკე სტანდარტების შესაბამისად."
_PC_1 = "გუნდის წევრები მუდმივ კომუნიკაციაში არიან მონაწილეების მშობლებთან."
_PC_2 = "მშობლებს ყოველდღიურად გაეგზავნებათ დღის პროგრამა და ფოტო-ვიდეო მასალა"
_MENU_MARKERS = ("გვითხარით, რა გაინტერესებთ", "ბავშვების საზაფხულო ბანაკი", "ზრდასრულთა კულტურული საღამოები")


@pytest.fixture(autouse=True)
def _reset():
    conversation_service.conversations.clear()
    parent_flow.invalid_phone_retries.clear()
    parent_flow._sunday_school_notified_senders.clear()
    yield
    conversation_service.conversations.clear()
    parent_flow._sunday_school_notified_senders.clear()


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    swapped = dataclasses.replace(
        config_module.settings, USE_PARENT_LLM_ENGINE=True,
        USE_CONVERSATION_PLANNER=False, CONVERSATION_PLANNER_AUTHORITATIVE=False,
        USE_SLIM_PROMPTS=False)
    monkeypatch.setattr(parent_flow, "settings", swapped)
    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    monkeypatch.setattr(parent_flow, "_CLIENT_EMOJI_ENABLED", True, raising=False)
    monkeypatch.setattr(parent_flow, "_run_llm_engine_safely", lambda c, m: "[ENGINE]")
    yield


def _fresh(sid):
    c = Conversation(sender_id=sid, platform="instagram", segment="PARENT")
    c.state = "START"
    c.lead = Lead(sender_id=sid, platform="instagram", segment="PARENT", child_age="")
    return c


def _mid(sid, child_age="12"):
    c = Conversation(sender_id=sid, platform="instagram", segment="PARENT")
    c.state = "ASK_CHALLENGE"
    c.history.append({"role": "assistant", "content": "რას ელოდებით ბანაკისგან?"})
    c.lead = Lead(sender_id=sid, platform="instagram", segment="PARENT", child_age=child_age)
    return c


def _no_menu(out):
    return all(m not in out for m in _MENU_MARKERS)


# =====================================================================
# Issue 1 — greeting + remaining seats
# =====================================================================
def test_greeting_seats_gets_heart_and_fallback(camp_registration_open):
    out = parent_flow.handle(_fresh("g1"), "გამარჯობა მეორე ნაკადზე ადგილები არის ?")
    assert "გამარჯობა 💙" in out
    assert _SEATS_FB in out
    assert "558 67 47 33" in out
    assert _no_menu(out)
    assert "რამდენი წლის არის თქვენი შვილი" not in out
    assert "კონსულტაციაზე ჩაგწერთ" not in out
    assert "არის ადგილი" not in out and "თავისუფალია" not in out
    assert "💙." not in out and "❤️" not in out
    assert out.startswith("გამარჯობა 💙")


_SEATS_VARIANTS = [
    "გამარჯობა მეორე ნაკადზე ადგილები არის ?",
    "გამარჯობა, მეორე ნაკადზე ადგილები გაქვთ?",
    "მეორე ნაკადზე ადგილები არის?",
    "მე-2 ნაკადზე ადგილები გაქვთ?",
    "2 ნაკადზე დარჩა ადგილი?",
    "მაინტერესებს ბანაკის მეორე ნაკადზე ადგილები არის?",
]


@pytest.mark.parametrize("msg", _SEATS_VARIANTS, ids=[f"s{i}" for i in range(len(_SEATS_VARIANTS))])
def test_seats_variants_return_fallback_not_menu(msg, camp_registration_open):
    out = parent_flow.handle(_fresh(f"sv-{abs(hash(msg)) % 9999}"), msg)
    assert _SEATS_FB in out, f"{msg!r} -> {out!r}"
    assert _no_menu(out)
    assert "რამდენი წლის არის თქვენი შვილი" not in out
    assert "თავისუფალია" not in out and "არის ადგილი" not in out
    # First-turn greeting variants carry „გამარჯობა 💙"; non-greeting variants do not.
    greeted = msg.strip().lower().startswith("გამარჯობა")
    assert ("გამარჯობა 💙" in out) == greeted


def test_seats_no_greeting_no_heart_midflow(camp_registration_open):
    # A mid-conversation seats question (no greeting) → plain fallback, no heart.
    out = parent_flow.handle(_mid("m-seats"), "მე-2 ნაკადზე ადგილები გაქვთ?")
    assert _SEATS_FB in out
    assert "💙" not in out


# =====================================================================
# Issue 2 — safety + parent-contact multi-question
# =====================================================================
def test_safety_contact_full_block():
    out = parent_flow.handle(_mid("sc1"), "უსაფრთხოება როგორ არის და ბავშვთან კონტაქტი მექნება?")
    assert _SAFETY_1 in out                       # safety answer
    assert _PC_1 in out                           # parent-comm: team communication
    assert _PC_2 in out                           # parent-comm: daily program + photo/video
    assert _DIRECT_CALL_FB in out                 # direct-call manager defer (was dropped)
    assert "558 67 47 33" in out
    assert "აგიხსნით" not in out
    assert "რამდენი წლის არის თქვენი შვილი" not in out
    assert "კონსულტაციაზე ჩაგწერთ" not in out
    assert "9-ნიშნა" not in out


_SAFETY_CONTACT_VARIANTS = [
    "უსაფრთხოება როგორ არის და ბავშვთან კონტაქტი მექნება?",
    "უსაფრთხოება და დარეკვა როგორ იქნება?",
    "უსაფრთხოება როგორ არის და დღეში რამდენჯერ შევძლებ დარეკვას?",
    "ბავშვი დაცულად იქნება და კონტაქტი მექნება?",
    "უსაფრთხოება როგორ არის? ბავშვთან დარეკვას შევძლებ?",
]


@pytest.mark.parametrize(
    "msg", _SAFETY_CONTACT_VARIANTS,
    ids=[f"sc{i}" for i in range(len(_SAFETY_CONTACT_VARIANTS))])
def test_safety_contact_variants(msg, camp_registration_open):
    out = parent_flow.handle(_mid(f"scv-{abs(hash(msg)) % 9999}"), msg)
    assert "უსაფრთხოებ" in out                     # safety part present
    assert _DIRECT_CALL_FB in out                  # direct-call/parent-contact fallback present
    assert "558 67 47 33" in out
    assert "აგიხსნით" not in out
    assert "რამდენი წლის არის თქვენი შვილი" not in out
    assert "კონსულტაციაზე ჩაგწერთ" not in out


def test_direct_call_fallback_helper():
    from app.reasoning import camp_topic_facts as ctf
    assert ctf.direct_call_fallback() == _DIRECT_CALL_FB
