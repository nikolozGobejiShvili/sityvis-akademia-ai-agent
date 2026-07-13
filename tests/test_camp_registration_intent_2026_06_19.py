"""Live bug (2026-06-19) — clear camp REGISTRATION intent must skip the menu.

User wrote „ბანაკზე როგორ დავრეგისტრირდე" / „გამარჯობა, ბანაკზე როგორ
დავრეგისტრირდე?" and got the generic two-option menu instead of the camp
registration flow. Root cause: `_has_explicit_georgian_camp_intent` had the
camp keyword („ბანაკ") but NO registration/sign-up marker, so it returned
False and `_maybe_static_welcome` showed the menu.

Fix: registration/sign-up stems (`რეგისტრაცი` / `დარეგისტრ` / `დავრეგისტრ`
/ `ჩავეწერ` / `ფორმა` / `ბმულ` / `ლინკ` / `register`) added to
`_CAMP_INTENT_MARKERS`. The detector still REQUIRES a camp keyword, so a
bare greeting, a bare topic word, and non-camp / adult-event registration
messages are unaffected. The camp registration answer already uses the
Admin/config `Registration URL` via the engine's `get_camp_info("registration")`
tool (admin-first `get_camp_facts()` → `camp_2026.yaml`), with a safe
`registration_url_missing` fallback (no invented link).

Also: `messenger_service.get_user_profile` now masks `access_token` in its
error log.

All offline / mocked — no real OpenAI, Meta, WhatsApp, Calendar, Sheets,
Redis, or network.
"""

from __future__ import annotations

import dataclasses
import logging

import pytest

import app.config as config_module
from app.agent.tools.parent_tool_executor import ParentToolExecutor
from app.agent.tools.parent_tools import TOOL_GET_CAMP_INFO
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import admin_config_service, conversation_service, messenger_service


_MENU = "გვითხარით, რა გაინტერესებთ"
_REG_URL = "https://tinyurl.com/36jcae8z"


@pytest.fixture(autouse=True)
def _reset():
    conversation_service.conversations.clear()
    yield
    conversation_service.conversations.clear()

@pytest.fixture
def camp_registration_open(monkeypatch):
    monkeypatch.setattr(
        admin_config_service, "get_camp_registration_status", lambda: "open",
    )


# =========================================================================
# Detector — TRUE for clear camp + registration/sign-up intent.
# =========================================================================

_CAMP_REGISTRATION_TRUE = [
    "ბანაკზე როგორ დავრეგისტრირდე",
    "გამარჯობა, ბანაკზე როგორ დავრეგისტრირდე",
    "ბანაკზე რეგისტრაცია მინდა",
    "როგორ ჩავწერო ბავშვი ბანაკზე",
    "ბანაკზე ჩაწერა",
    "ბანაკის რეგისტრაციის ლინკი მომწერეთ",
    "რეგისტრაციის ფორმა სად არის ბანაკზე?",
]

# Preserved existing BUG-1 (ISSUE 1) camp-intent cases.
_EXISTING_CAMP_INTENT_TRUE = [
    "საზაფხულო ბანაკი მაინტერესებს",
    "ბანაკით ვარ დაინტერესებული",
]

_CAMP_INTENT_FALSE = [
    "გამარჯობა",                          # bare greeting → menu
    "ბანაკი",                              # bare topic word → menu
    "ღონისძიებაზე როგორ დავრეგისტრირდე",  # adult-event registration, no camp kw
    "რეგისტრაცია მინდა",                   # registration but no camp context
]


@pytest.mark.parametrize("msg", _CAMP_REGISTRATION_TRUE + _EXISTING_CAMP_INTENT_TRUE)
def test_detector_true_for_camp_registration_intent(msg):
    assert parent_flow._has_explicit_georgian_camp_intent(msg) is True


@pytest.mark.parametrize("msg", _CAMP_INTENT_FALSE)
def test_detector_false_for_non_camp_or_bare(msg):
    assert parent_flow._has_explicit_georgian_camp_intent(msg) is False


@pytest.mark.parametrize("msg", _CAMP_REGISTRATION_TRUE)
def test_static_welcome_yields_for_camp_registration(msg):
    conv = Conversation(sender_id="reg-yield", platform="instagram")
    conv.segment = "PARENT"
    assert parent_flow._maybe_static_welcome(conv, msg) is None


def test_static_welcome_still_fires_for_bare_greeting():
    conv = Conversation(sender_id="reg-greet", platform="instagram")
    conv.segment = "PARENT"
    assert parent_flow._maybe_static_welcome(conv, "გამარჯობა") == parent_flow.PARENT_WELCOME.strip()


# =========================================================================
# Full-path (engine ON, stubbed) — no generic menu, camp flow continues.
# =========================================================================


@pytest.fixture
def parent_engine_on(monkeypatch):
    swapped = dataclasses.replace(config_module.settings, USE_PARENT_LLM_ENGINE=True)
    monkeypatch.setattr(parent_flow, "settings", swapped)
    monkeypatch.setattr(
        "app.agent.llm.parent_llm_engine.run_parent_llm_turn",
        lambda **k: "CAMP_ENGINE_REPLY",
    )
    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})


_FULLPATH_CAMP_REG = [
    "ბანაკზე როგორ დავრეგისტრირდე",
    "გამარჯობა, ბანაკზე როგორ დავრეგისტრირდე",
    "ბანაკზე რეგისტრაცია მინდა",
    "როგორ ჩავწერო ბავშვი ბანაკზე",
]


@pytest.mark.parametrize("msg", _FULLPATH_CAMP_REG)
def test_fullpath_camp_registration_skips_menu(parent_engine_on, camp_registration_open, msg):
    conversation_service.conversations.clear()  # fresh / flushed state
    out = conversation_service.process_message("reg-fp", msg, "instagram")
    assert _MENU not in out, f"menu wrongly shown for: {msg!r}"
    # Live mismatch fix (2026-06-19): a registration request now returns the
    # configured Admin link DETERMINISTICALLY (pre-engine). The engine must
    # NOT be consulted (its stubbed sentinel must be absent) and the link
    # must be present — this is the behaviour the old assertion missed.
    assert "CAMP_ENGINE_REPLY" not in out, f"engine wrongly consulted for: {msg!r}"
    assert _REG_URL in out, f"registration link missing for: {msg!r}"
    assert conversation_service.conversations["reg-fp"].segment == "PARENT"


def test_fullpath_fresh_state_does_not_change_routing(parent_engine_on, camp_registration_open):
    """No prior state (Redis flushed in tests) → still skips the menu and
    returns the deterministic Admin registration link (not the engine)."""
    conversation_service.conversations.clear()
    out = conversation_service.process_message(
        "reg-fresh", "ბანაკზე როგორ დავრეგისტრირდე", "instagram",
    )
    assert _MENU not in out
    assert "CAMP_ENGINE_REPLY" not in out
    assert _REG_URL in out


def test_fullpath_bare_greeting_still_shows_menu(parent_engine_on):
    conversation_service.conversations.clear()
    out = conversation_service.process_message("reg-greet-fp", "გამარჯობა", "instagram")
    assert _MENU in out


# =========================================================================
# Registration URL — uses Admin/config value, safe fallback when missing.
# =========================================================================


def _camp_info_executor(sender_id="reg-url"):
    conv = Conversation(sender_id=sender_id, platform="instagram", segment="PARENT")
    lead = Lead(sender_id=sender_id, platform="instagram", segment="PARENT")
    conv.lead = lead
    return ParentToolExecutor(
        conversation=conv, lead=lead, sender_id=sender_id, platform="instagram",
    )


def test_registration_answer_uses_configured_admin_url(monkeypatch, camp_registration_open):
    monkeypatch.setattr(
        admin_config_service, "get_camp_facts",
        lambda: {"name": "ბანაკი", "registration_url": _REG_URL, "phone": "558674733"},
    )
    ex = _camp_info_executor()
    result = ex.execute(TOOL_GET_CAMP_INFO, {"topic": "registration"})
    assert result["success"] is True
    assert result["registration_url"] == _REG_URL  # exactly the Admin value


def test_registration_answer_does_not_invent_link_when_missing(monkeypatch, camp_registration_open):
    # Non-empty camp facts WITHOUT a registration_url → must NOT fall back to
    # camp_2026.yaml's URL and must NOT invent one.
    monkeypatch.setattr(
        admin_config_service, "get_camp_facts",
        lambda: {"name": "ბანაკი", "registration_url": "", "phone": "558674733"},
    )
    ex = _camp_info_executor()
    result = ex.execute(TOOL_GET_CAMP_INFO, {"topic": "registration"})
    assert result["success"] is False
    assert result["reason"] == "registration_url_missing"
    assert result.get("phone") == "558674733"  # safe fallback to contact
    assert "registration_url" not in result    # no invented link


# =========================================================================
# Security — get_user_profile masks access_token; failure is non-blocking.
# =========================================================================


def test_get_user_profile_masks_access_token_in_log(monkeypatch, caplog):
    secret = "EAA_SECRET_TOKEN_VALUE_xyz"
    swapped = dataclasses.replace(
        messenger_service.settings, MESSENGER_PAGE_ACCESS_TOKEN=secret,
    )
    monkeypatch.setattr(messenger_service, "settings", swapped)

    def _boom(*a, **k):
        raise RuntimeError(
            "Client error '400 Bad Request' for url "
            f"'https://graph.facebook.com/v19.0/123?fields=name&access_token={secret}'"
        )

    monkeypatch.setattr(messenger_service.httpx, "get", _boom)

    with caplog.at_level(logging.WARNING):
        result = messenger_service.get_user_profile("sender123", "instagram")

    assert result == {}  # failure does not block — returns empty profile
    logs = "\n".join(r.getMessage() for r in caplog.records)
    assert secret not in logs, "access_token leaked into logs"
    assert "access_token=***masked***" in logs


def test_get_user_profile_failure_does_not_block(monkeypatch):
    swapped = dataclasses.replace(
        messenger_service.settings, MESSENGER_PAGE_ACCESS_TOKEN="EAA_TOKEN",
    )
    monkeypatch.setattr(messenger_service, "settings", swapped)

    def _boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(messenger_service.httpx, "get", _boom)
    assert messenger_service.get_user_profile("s", "instagram") == {}


def test_mask_access_token_helper():
    masked = messenger_service._mask_access_token(
        "url?fields=name&access_token=SUPERSECRET123&x=1",
    )
    assert "SUPERSECRET123" not in masked
    assert "access_token=***masked***" in masked


# =========================================================================
# Regression guards — adult routing + scheduling + Sheets unaffected.
# =========================================================================


def test_adult_event_registration_not_treated_as_camp():
    # An adult-event registration message (no camp keyword) must NOT match
    # the camp detector — it routes to the adult flow as before.
    assert parent_flow._has_explicit_georgian_camp_intent(
        "ღონისძიებაზე რეგისტრაცია მინდა",
    ) is False


def test_saturday_sunday_scheduling_unchanged():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from app.services import calendar_service
    tz = ZoneInfo("Asia/Tbilisi")
    ok_sat, r_sat = calendar_service.is_within_business_hours(
        datetime(2030, 6, 8, 12, 0, tzinfo=tz),
    )
    assert ok_sat is True and r_sat == ""
    ok_sun, r_sun = calendar_service.is_within_business_hours(
        datetime(2030, 6, 9, 12, 0, tzinfo=tz),
    )
    assert ok_sun is False and r_sun == "weekend"


def test_sheets_aq_schema_unchanged():
    from app.services import sheets_service
    assert sheets_service.HEADERS[:7] == [
        "ID", "Sender ID", "Platform", "Segment", "Name", "Phone", "Child Age",
    ]
    assert len(sheets_service.HEADERS) == 17
