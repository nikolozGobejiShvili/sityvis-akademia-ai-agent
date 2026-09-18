"""Live regression, client Page 2026-09-18 12:22 — two children's ages were
answered with the camp.

  „მაინტერესებს 16 და 13 წლის მოზარდების ჯგუფში თუ გაქვთ ადგილი ?
   ადგილმდებარეობა : თბილისი"
  → „ორი ბავშვის ასაკი მივიღე — 16 და 13 წელი. ორივე ასაკი ჩავიწერე.
     ბანაკი ორივე ასაკისთვის შესაბამისია. რას ელოდებით ბანაკისგან?"

The camp was ended and Sunday School was the only programme on sale. The
handler's existing deferral only fires when the message or the conversation
NAMES another programme; this parent had named nothing, so the camp claimed the
turn and made a suitability claim on its own age band.

Same three conditions as the camp-status gate and the out-of-range-age handler:
the camp stands down when it is closed, the conversation is not the camp's, and
another child programme is active.
"""
from __future__ import annotations

import dataclasses

import pytest

from app import config as config_module
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import admin_config_service

SCHOOL_ONLY = [
    {"id": "sunday_school", "name": "საკვირაო სკოლა",
     "type": "sunday_school", "status": "active"},
]
TWO_AGES = (
    "მაინტერესებს 16 და 13 წლის მოზარდების ჯგუფში თუ გაქვთ ადგილი ? "
    "ადგილმდებარეობა : თბილისი"
)


def _conv() -> Conversation:
    conv = Conversation(sender_id="two-ages", platform="messenger")
    conv.segment = "PARENT"
    conv.lead = Lead(sender_id="two-ages", platform="messenger", segment="PARENT")
    return conv


@pytest.fixture
def camp_ended_school_on_sale(monkeypatch):
    monkeypatch.setattr(
        admin_config_service, "get_camp_status", lambda *a, **k: "ended")
    monkeypatch.setattr(
        admin_config_service, "get_active_sections", lambda *a, **k: list(SCHOOL_ONLY))
    monkeypatch.setattr(
        parent_flow, "settings",
        dataclasses.replace(
            config_module.settings,
            USE_PROGRAM_ISOLATION=True, USE_DYNAMIC_PROGRAMS=True,
        ),
    )


def test_two_ages_are_not_answered_with_the_camps_age_band(camp_ended_school_on_sale):
    answer = parent_flow._maybe_handle_multi_child_age(_conv(), TWO_AGES)
    assert answer is None, "the closed camp judged another programme's ages: " + str(answer)


def test_the_camp_still_answers_when_it_is_the_only_programme(monkeypatch):
    monkeypatch.setattr(
        admin_config_service, "get_camp_status", lambda *a, **k: "ended")
    monkeypatch.setattr(
        admin_config_service, "get_active_sections", lambda *a, **k: [])
    monkeypatch.setattr(
        parent_flow, "settings",
        dataclasses.replace(
            config_module.settings,
            USE_PROGRAM_ISOLATION=True, USE_DYNAMIC_PROGRAMS=True,
        ),
    )
    answer = parent_flow._maybe_handle_multi_child_age(_conv(), TWO_AGES)
    assert answer, "with nothing else on sale the camp's own answer is unchanged"
