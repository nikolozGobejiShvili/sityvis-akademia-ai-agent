"""Config-unification regression — admin_config.sections.yaml is the
source of truth for camp facts surfaced to the user via the P3-C
engine's `get_camp_info` tool.

Catches the live bug where an operator changed `price_text` to "2200"
in the Admin Panel but the agent kept replying with "2150" because
`parent_tool_executor._get_camp_info` was reading `camp_2026.yaml`
directly.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from unittest.mock import MagicMock

import pytest

from app.agent.tools.parent_tool_executor import ParentToolExecutor
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import admin_config_service


def _executor() -> ParentToolExecutor:
    """A throwaway executor — `_get_camp_info` only needs the dataclass shell."""
    return ParentToolExecutor(
        conversation=Conversation(sender_id="t1", platform="messenger"),
        lead=Lead(sender_id="t1", platform="messenger", segment="PARENT"),
        sender_id="t1",
        platform="messenger",
    )


# -- (1) get_camp_facts returns admin price when admin is present --------


def test_get_camp_facts_uses_admin_price_text(monkeypatch):
    """When the operator sets `price_text=2200`, the merged dict's
    user-facing price reflects that — not the canonical 2150."""
    monkeypatch.setattr(
        admin_config_service, "get_section",
        lambda _sid: {
            "id": "summer_camp",
            "name": "საზაფხულო ბანაკი",
            "type": "camp",
            "status": "active",
            "hashtags": ["ბანაკი"],
            "auto_dm_template_id": "summer_camp_comment_dm",
            "price_text": "2200",
            "price_gel": 2150,  # legacy field — admin price_text wins for display
        },
    )
    facts = admin_config_service.get_camp_facts()
    assert facts.get("price_text") == "2200"


def test_get_camp_facts_recovers_price_gel_from_price_text(monkeypatch):
    """When `price_gel` is absent but `price_text` is "2200", the
    integer is recovered so legacy arithmetic callers keep working."""
    monkeypatch.setattr(
        admin_config_service, "get_section",
        lambda _sid: {
            "id": "summer_camp",
            "name": "x", "type": "camp", "status": "active",
            "hashtags": ["ბანაკი"],
            "auto_dm_template_id": "summer_camp_comment_dm",
            "price_text": "2200",
        },
    )
    facts = admin_config_service.get_camp_facts()
    assert facts.get("price_gel") == 2200
    assert facts.get("price_text") == "2200"


# -- (2) Fallback to camp_2026.yaml when admin section is missing -------


def test_get_camp_facts_falls_back_to_canonical_yaml_when_admin_missing(
    monkeypatch,
):
    monkeypatch.setattr(
        admin_config_service, "get_section", lambda _sid: None,
    )
    facts = admin_config_service.get_camp_facts()
    # camp_2026.yaml's canonical value.
    assert facts.get("price_gel") == 2150
    assert facts.get("location") == "ამბასადორი კაჭრეთი"


# -- (3) Malformed admin_config does not crash --------------------------


def test_get_camp_facts_tolerates_admin_load_error(monkeypatch):
    def _boom(_sid):
        raise RuntimeError("yaml exploded")

    monkeypatch.setattr(admin_config_service, "get_section", _boom)
    facts = admin_config_service.get_camp_facts()
    # Must still return camp_2026.yaml values.
    assert facts.get("price_gel") == 2150


# -- (4) _get_camp_info(topic="price") reflects admin override ----------


def test_get_camp_info_price_reflects_admin_override(monkeypatch):
    monkeypatch.setattr(
        admin_config_service, "get_section",
        lambda _sid: {
            "id": "summer_camp",
            "name": "x", "type": "camp", "status": "active",
            "hashtags": ["ბანაკი"],
            "auto_dm_template_id": "summer_camp_comment_dm",
            "price_text": "2200",
            "price_gel": 2150,  # ignored for display because price_text wins
            "payment_terms": "გადახდის გადანაწილება შესაძლებელია 6 თვემდე",
            "discounts": ["10% დედმამიშვილებისთვის"],
        },
    )
    result = _executor()._get_camp_info({"topic": "price"})
    assert result["success"] is True
    assert result["price_text"] == "2200"
    assert result["payment_terms"] == "გადახდის გადანაწილება შესაძლებელია 6 თვემდე"
    # admin's string-list discounts are normalised — no crash.
    assert isinstance(result["discounts"], list)
    assert any("10%" in (d.get("name") or "") for d in result["discounts"])


def test_get_camp_info_price_does_not_leak_stale_2150_when_admin_is_2200(
    monkeypatch,
):
    monkeypatch.setattr(
        admin_config_service, "get_section",
        lambda _sid: {
            "id": "summer_camp",
            "name": "x", "type": "camp", "status": "active",
            "hashtags": ["ბანაკი"],
            "auto_dm_template_id": "summer_camp_comment_dm",
            "price_text": "2200",
        },
    )
    result = _executor()._get_camp_info({"topic": "price"})
    # The tool returns price_gel for arithmetic — derived from price_text.
    assert result["price_gel"] == 2200
    assert result["price_text"] == "2200"


# -- (5) Comment rich DM picks up admin price ---------------------------


def test_comment_rich_dm_uses_admin_price_when_present(monkeypatch):
    from app.services import comment_service

    monkeypatch.setattr(
        admin_config_service, "get_section",
        lambda _sid: {
            "id": "summer_camp",
            "name": "საზაფხულო ბანაკი",
            "type": "camp",
            "status": "active",
            "hashtags": ["ბანაკი"],
            "auto_dm_template_id": "summer_camp_comment_dm",
            "location": "ამბასადორი კაჭრეთი",
            "duration_days": 7,
            "price_gel": 2200,
            "registration_url": "https://example.com/reg",
            "streams": [
                {"name": "I ნაკადი", "dates_text": "23-29 ივნისი"},
            ],
        },
    )
    out = comment_service._build_parent_rich_dm()
    assert "2200" in out, f"expected admin price in DM, got: {out!r}"
    assert "2150" not in out  # stale price must NOT survive


# -- (6) Other camp_info topics still work with admin overrides --------


def test_get_camp_info_dates_uses_admin_streams(monkeypatch):
    monkeypatch.setattr(
        admin_config_service,
        "_now_tbilisi",
        lambda: (
            datetime(2026, 6, 20, 12, 0, tzinfo=ZoneInfo("Asia/Tbilisi")),
            ZoneInfo("Asia/Tbilisi"),
        ),
    )
    monkeypatch.setattr(
        admin_config_service, "get_section",
        lambda _sid: {
            "id": "summer_camp",
            "name": "x", "type": "camp", "status": "active",
            "hashtags": ["ბანაკი"],
            "auto_dm_template_id": "summer_camp_comment_dm",
            "duration_days": 10,
            "streams": [
                {"name": "I ნაკადი", "dates_text": "1-7 ივლისი"},
                {"name": "II ნაკადი", "dates_text": "10-16 ივლისი"},
            ],
        },
    )
    result = _executor()._get_camp_info({"topic": "dates"})
    assert result["success"] is True
    assert result["duration_days"] == 10
    assert len(result["streams"]) == 2
    assert result["streams"][0]["dates_text"] == "1-7 ივლისი"


def test_get_camp_info_location_uses_admin_value(monkeypatch):
    monkeypatch.setattr(
        admin_config_service, "get_section",
        lambda _sid: {
            "id": "summer_camp",
            "name": "x", "type": "camp", "status": "active",
            "hashtags": ["ბანაკი"],
            "auto_dm_template_id": "summer_camp_comment_dm",
            "location": "ახალი ლოკაცია",
        },
    )
    result = _executor()._get_camp_info({"topic": "location"})
    assert result["success"] is True
    assert result["location"] == "ახალი ლოკაცია"
