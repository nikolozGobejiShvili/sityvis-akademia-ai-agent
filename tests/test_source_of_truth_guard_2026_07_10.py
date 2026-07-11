"""Source-of-truth guard tests (ST-1, 2026-07-10).

These tests document current canonical runtime owners and known duplicated
copy/fact debt before cleanup patches start. They intentionally do not fix or
move any copy.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
import yaml

import app.config as config_module
from app.agent.llm import adult_llm_engine
from app.flows import adult_flow, parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import admin_config_service, comment_service


REPO_ROOT = Path(__file__).resolve().parents[1]

EXPECTED_CAMP_PRICE_BLOCK = (
    "ბანაკის ფასი არის 2150 ლარი.\n\n"
    "ამ თანხაში შედის ტრანსპორტირება, განთავსება, კვება და სრული პროგრამა.\n\n"
    "გადახდის გადანაწილება შესაძლებელია 6 თვემდე TBC-ის და საქართველოს "
    "ბანკის საშუალებით.\n\n"
    "10%-იანი ფასდაკლება მოქმედებს დედმამიშვილებისთვის და წინა ბანაკის "
    "მონაწილეებისთვის.\n\n"
    "თუ გსურთ, კონსულტაციაზე ჩაგწერთ, სადაც დეტალებს მენეჯერი გაგაცნობთ."
)

EXPECTED_PAYMENT_PROCESS = (
    "ბანაკის ჯავშნის საფასურის გადახდა ხდება წინასწარ, ხოლო სრული თანხის — "
    "ხელშეკრულებით გათვალისწინებულ დროში. გადახდის გადანაწილება შესაძლებელია "
    "6 თვემდე TBC-ისა და საქართველოს ბანკის საშუალებით"
)

EXPECTED_RESERVATION_DEFER = (
    "რაც შეეხება ჯავშნის საფასურს, ამ დეტალებს მენეჯერი გაგაცნობთ: "
    "558 67 47 33"
)

EXPECTED_ADULT_NO_ACTIVE = (
    "ამ ეტაპზე აქტიური ღონისძიება სიაში არ მაქვს. თუ გსურთ, "
    "მენეჯერთან დაგაკავშირებთ."
)

STALE_ADULT_NO_ACTIVE_VARIANTS = (
    "ამ ეტაპზე ღონისძიებების განრიგი ზუსტდება",
    "როგორც კი დადასტურდება, სიამოვნებით გაგიზიარებთ თარიღებსა და თემებს",
)

AUDIT_SCAN_FILES = (
    "app/flows/parent_flow.py",
    "app/agent/templates/parent/price.yaml",
    "app/agent/prompts/system_parent_v2.md",
    "app/agent/prompts/system_parent.md",
    "app/services/admin_config_service.py",
    "app/flows/adult_flow.py",
    "app/services/comment_service.py",
    "app/agent/templates/adult/welcome.yaml",
    "app/agent/prompts/system_adult.md",
)

KNOWN_DEBT_ALLOWLIST = {
    "2150": {
        "app/flows/parent_flow.py",
        "app/agent/templates/parent/price.yaml",
        "app/agent/prompts/system_parent_v2.md",
        "app/agent/prompts/system_parent.md",
        "app/services/admin_config_service.py",
    },
    "TBC-ისა და": {
        "app/flows/parent_flow.py",
        "app/agent/templates/parent/price.yaml",
        "app/agent/prompts/system_parent_v2.md",
    },
    "TBC-ის და": set(),
    "TBC-ით ან": set(),
    "TBC ან": set(),
    "ჯავშნის საფასურს": {
        "app/flows/parent_flow.py",
        "app/agent/prompts/system_parent_v2.md",
    },
    "558 67 47 33": {
        "app/flows/parent_flow.py",
        "app/agent/prompts/system_parent_v2.md",
        "app/agent/prompts/system_parent.md",
    },
    "გაგაცნობთ :": {
        "app/flows/parent_flow.py",
        "app/agent/prompts/system_parent_v2.md",
    },
    "გაგაცნობთ:": {
        "app/flows/parent_flow.py",
        "app/agent/prompts/system_parent_v2.md",
    },
    "ამ ეტაპზე აქტიური ღონისძიება": {
        "app/services/admin_config_service.py",
        "app/flows/parent_flow.py",
        "app/agent/templates/adult/welcome.yaml",
        "app/agent/prompts/system_adult.md",
    },
    "ამ ეტაპზე ღონისძიებების განრიგი ზუსტდება": set(),
    "პოლიტიკურ თემებზე": {
        "app/agent/prompts/system_parent_v2.md",
    },
    "ონლაინ-კონსულტანტი": {
        "app/flows/parent_flow.py",
        "app/agent/prompts/system_parent_v2.md",
    },
    "tinyurl": {
        "app/agent/templates/parent/price.yaml",
        "app/agent/prompts/system_parent.md",
    },
}

PROMPT_VOLATILE_FACT_ALLOWLIST = {
    "2150": {
        "app/agent/prompts/system_parent.md",
        "app/agent/prompts/system_parent_v2.md",
    },
    "558 67 47 33": {
        "app/agent/prompts/system_parent.md",
        "app/agent/prompts/system_parent_v2.md",
    },
    "tinyurl": {
        "app/agent/prompts/system_parent.md",
    },
    EXPECTED_ADULT_NO_ACTIVE: {
        "app/agent/prompts/system_adult.md",
    },
    "ამ ეტაპზე ღონისძიებების განრიგი ზუსტდება": set(),
}


def _read_repo_text(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def _paths_containing(fragment: str, relative_paths: tuple[str, ...]) -> set[str]:
    return {
        path
        for path in relative_paths
        if fragment in _read_repo_text(path)
    }


def _adult_conversation(sender_id: str = "st1-adult") -> Conversation:
    conversation = Conversation(
        sender_id=sender_id,
        platform="instagram",
        segment="ADULT",
    )
    conversation.state = "START"
    conversation.lead = Lead(
        sender_id=sender_id,
        platform="instagram",
        segment="ADULT",
    )
    return conversation


def _parent_conversation(sender_id: str = "st1-parent") -> Conversation:
    conversation = Conversation(
        sender_id=sender_id,
        platform="instagram",
        segment="PARENT",
    )
    conversation.lead = Lead(
        sender_id=sender_id,
        platform="instagram",
        segment="PARENT",
        child_age="12",
    )
    return conversation


def test_canonical_camp_runtime_facts_are_exposed_by_admin_accessors():
    camp = admin_config_service.get_camp_facts()

    assert camp["price_gel"] == 2150
    assert str(camp["price_text"]) == "2150"
    assert admin_config_service.get_camp_age_bounds() == (9, 17)
    assert admin_config_service.get_manager_phone() == "558 67 47 33"
    assert camp["registration_url"] == "https://tinyurl.com/36jcae8z"
    assert camp["location"] == "ამბასადორი კაჭრეთი"

    streams = camp.get("streams") or []
    stream_dates = {stream.get("dates_text") for stream in streams}
    assert {"23-29 ივნისი", "5-11 ივლისი", "14-20 ივლისი"} <= stream_dates


def test_canonical_adult_events_owner_handles_empty_and_active_admin_events(
    monkeypatch,
):
    monkeypatch.setattr(
        admin_config_service,
        "get_section",
        lambda section_id: {"id": "adult_events", "events": []},
    )
    assert admin_config_service.get_adult_events() == []
    assert admin_config_service.get_active_adult_events() == []
    assert admin_config_service.ADULT_NO_ACTIVE_EVENTS_REPLY == EXPECTED_ADULT_NO_ACTIVE

    active_event = {
        "id": "st1_active",
        "title": "ST1 აქტიური საღამო",
        "status": "active",
        "date_text": "1 ივნისი 2031",
        "min_age": 13,
        "active": True,
    }
    inactive_event = {
        "id": "st1_inactive",
        "title": "ST1 დამალული საღამო",
        "status": "inactive",
        "date_text": "1 ივნისი 2031",
        "min_age": 13,
        "active": False,
    }
    monkeypatch.setattr(
        admin_config_service,
        "get_adult_events",
        lambda: [active_event, inactive_event],
    )

    assert admin_config_service.get_active_adult_events(include_past=True) == [
        active_event,
    ]


def test_adult_flow_maps_active_event_data_from_admin_service(monkeypatch):
    admin_event = {
        "id": "st1_flow_event",
        "title": "ადმინიდან მოსული საღამო",
        "date_text": "1 ივნისი 2031",
        "theme": "თემა",
        "guest": "სტუმარი",
        "location": "დარბაზი",
        "price_text": "120 ლარი",
        "reservation_url": "https://example.com/st1",
        "min_age": 13,
    }
    monkeypatch.setattr(
        admin_config_service,
        "get_active_adult_events",
        lambda: [admin_event],
    )

    events = adult_flow._load_events()

    assert events == [
        {
            "id": "st1_flow_event",
            "name": "ადმინიდან მოსული საღამო",
            "date": "1 ივნისი 2031",
            "time": "",
            "theme": "თემა",
            "guest": "სტუმარი",
            "location": "დარბაზი",
            "price": "120 ლარი",
            "booking_link": "https://example.com/st1",
            "description": "",
            "atmosphere": adult_flow.ADULT_DEFAULT_ATMOSPHERE,
        },
    ]


def test_adult_runtime_no_active_paths_do_not_use_legacy_events_parser(
    monkeypatch,
):
    monkeypatch.setattr(
        comment_service,
        "_parse_events_blocks",
        lambda: pytest.fail("legacy settings.EVENTS parser must not run"),
    )
    monkeypatch.setattr(
        admin_config_service,
        "get_active_adult_events",
        lambda *args, **kwargs: [],
    )
    patched_settings = dataclasses.replace(
        config_module.settings,
        USE_ADULT_LLM_ENGINE=False,
        EVENTS="=== EVENT 1 ===\nსახელი: legacy event\nთარიღი: 30 დეკემბერი 2030\n",
    )
    monkeypatch.setattr(adult_flow, "settings", patched_settings)
    monkeypatch.setattr(comment_service, "settings", patched_settings)
    adult_flow.selected_events.clear()

    assert adult_flow.handle(
        _adult_conversation("st1-empty"),
        "ღონისძიებები მაინტერესებს",
    ) == EXPECTED_ADULT_NO_ACTIVE
    assert adult_llm_engine._render_active_events_list() == EXPECTED_ADULT_NO_ACTIVE
    assert comment_service._build_adult_rich_dm() == EXPECTED_ADULT_NO_ACTIVE


def test_known_source_of_truth_debt_is_allowlisted():
    for fragment, allowed_paths in KNOWN_DEBT_ALLOWLIST.items():
        found = _paths_containing(fragment, AUDIT_SCAN_FILES)
        unexpected = found - allowed_paths
        assert not unexpected, (
            f"Unexpected source-of-truth debt for {fragment!r}: "
            f"{sorted(unexpected)}"
        )

    assert EXPECTED_ADULT_NO_ACTIVE in _read_repo_text(
        "app/services/admin_config_service.py",
    )
    assert EXPECTED_PAYMENT_PROCESS in parent_flow._camp_payment_process_answer()


def test_prompt_volatile_fact_debt_is_allowlisted():
    prompt_paths = tuple(
        path.relative_to(REPO_ROOT).as_posix()
        for path in (REPO_ROOT / "app" / "agent" / "prompts").glob("*.md")
    )

    for fragment, allowed_paths in PROMPT_VOLATILE_FACT_ALLOWLIST.items():
        found = _paths_containing(fragment, prompt_paths)
        unexpected = found - allowed_paths
        assert not unexpected, (
            f"New prompt volatile-fact debt for {fragment!r}: "
            f"{sorted(unexpected)}"
        )

def test_adult_no_active_prompt_and_template_copy_is_canonical():
    aligned_paths = (
        "app/agent/templates/adult/welcome.yaml",
        "app/agent/prompts/system_adult.md",
    )

    for path in aligned_paths:
        text = _read_repo_text(path)
        assert EXPECTED_ADULT_NO_ACTIVE in text
        for stale_copy in STALE_ADULT_NO_ACTIVE_VARIANTS:
            assert stale_copy not in text


def test_approved_copy_yaml_is_program_scoped_for_camp():
    path = REPO_ROOT / "app/agent/templates/approved_copy/programs.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))

    assert set(data) == {"programs"}
    assert set(data["programs"]) == {"camp"}
    assert "price" in data["programs"]["camp"]
    assert "registration" in data["programs"]["camp"]

    forbidden_flat_keys = {"camp_price_block", "CAMP_PRICE_BLOCK", "PRICE_BLOCK"}
    stack = [data]
    seen_keys = set()
    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            continue
        seen_keys.update(str(key) for key in node)
        stack.extend(node.values())

    assert not (forbidden_flat_keys & seen_keys)

def test_approved_copy_behavior_is_currently_frozen():
    assert parent_flow._camp_price_direct_answer() == EXPECTED_CAMP_PRICE_BLOCK
    assert parent_flow._camp_payment_process_answer() == EXPECTED_PAYMENT_PROCESS
    assert adult_flow._no_active_events_reply() == EXPECTED_ADULT_NO_ACTIVE

    reservation = parent_flow._maybe_handle_reservation_fee_question(
        _parent_conversation("st1-reservation"),
        "ჯავშნის საფასური რამდენია?",
    )
    assert reservation == EXPECTED_RESERVATION_DEFER


def test_parent_identity_helper_current_copy_is_frozen():
    response = parent_flow._maybe_handle_identity(
        _parent_conversation("st1-identity"),
        "ვინ ხარ?",
    )

    assert response == parent_flow._IDENTITY_ANSWER
    assert "ონლაინ-კონსულტანტი" in response
