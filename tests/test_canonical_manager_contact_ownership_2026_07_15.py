from __future__ import annotations

import inspect

import pytest

from app.flows import parent_flow
from app.agent.tools import parent_tool_executor
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import admin_config_service, conversation_service

WRONG_USER_PHONE = "+995595999733"
WRONG_USER_PHONE_DIGITS = "995595999733"
CANONICAL_MANAGER_SENTINEL = "MANAGER_CONTACT_SENTINEL"
CALLBACK_SENTINEL = "595111222"
LEAD_SENTINEL = "595333444"
USER_A_PHONE = "595101101"
USER_B_PHONE = "595202202"


def _conv(sender_id: str, *, phone: str = "") -> Conversation:
    lead = Lead(sender_id=sender_id, platform="facebook", segment="PARENT", phone=phone)
    return Conversation(
        sender_id=sender_id,
        platform="facebook",
        page_id="page-canonical-manager-contact",
        session_key=f"facebook:page-canonical-manager-contact:{sender_id}",
        segment="PARENT",
        lead=lead,
        history=[
            {"role": "user", "content": "ბანაკი მაინტერესებს"},
            {"role": "assistant", "content": "ბანაკის შესახებ გისმენთ."},
        ],
    )


@pytest.fixture(autouse=True)
def _clear_conversations():
    conversation_service.conversations.clear()
    yield
    conversation_service.conversations.clear()


@pytest.fixture
def canonical_manager(monkeypatch):
    monkeypatch.setattr(admin_config_service, "get_manager_phone", lambda: CANONICAL_MANAGER_SENTINEL)
    return CANONICAL_MANAGER_SENTINEL


def test_exact_manager_number_path_rejects_wrong_user_phone(canonical_manager):
    conv = _conv("manager-path")

    out = parent_flow._maybe_handle_explicit_manager_request(conv, "მენეჯერის ნომერი მომწერეთ")

    assert out.count("მენეჯერის ნომერია:") == 1
    assert canonical_manager in out
    assert WRONG_USER_PHONE not in out
    assert WRONG_USER_PHONE_DIGITS not in out
    assert "შეგიძლიათ პირდაპირ დაუკავშირდეთ" in out


def test_user_callback_phone_is_not_rendered_as_manager_phone(canonical_manager):
    conv = _conv("callback-separation")
    lead = parent_flow._ensure_lead(conv)
    lead.phone = CALLBACK_SENTINEL

    out = parent_flow._maybe_handle_explicit_manager_request(conv, "მენეჯერის ნომერი მომწერეთ")

    assert lead.phone == CALLBACK_SENTINEL
    assert canonical_manager in out
    assert CALLBACK_SENTINEL not in out
    assert "დატოვეთ თქვენი ნომერი" not in out


def test_lead_phone_is_not_manager_phone(canonical_manager):
    lead = Lead(sender_id="lead-separation", platform="facebook", segment="PARENT", phone=LEAD_SENTINEL)

    out = parent_flow._render_manager_number_answer(lead)

    assert lead.phone == LEAD_SENTINEL
    assert canonical_manager in out
    assert LEAD_SENTINEL not in out
    assert "მენეჯერის ნომერია:" in out


def test_two_users_keep_callback_phones_isolated_from_manager_contact(canonical_manager):
    conv_a = _conv("user-a", phone=USER_A_PHONE)
    conv_b = _conv("user-b", phone=USER_B_PHONE)

    out_a = parent_flow._maybe_handle_explicit_manager_request(conv_a, "მენეჯერის ნომერი მომწერეთ")
    out_b = parent_flow._maybe_handle_explicit_manager_request(conv_b, "მენეჯერის ნომერი მომწერეთ")

    assert conv_a.session_key != conv_b.session_key
    assert conv_a.lead.phone == USER_A_PHONE
    assert conv_b.lead.phone == USER_B_PHONE
    assert canonical_manager in out_a and canonical_manager in out_b
    assert USER_A_PHONE not in out_a and USER_A_PHONE not in out_b
    assert USER_B_PHONE not in out_a and USER_B_PHONE not in out_b


def test_admin_config_source_of_truth_wins_over_env_company_and_test_fixture(monkeypatch):
    monkeypatch.setattr(admin_config_service, "load_manager_contacts_mirror", lambda: {})
    monkeypatch.setattr(
        admin_config_service,
        "get_section",
        lambda section_id: {
            "id": "summer_camp",
            "manager_contact": CANONICAL_MANAGER_SENTINEL,
        } if section_id == "summer_camp" else {
            "id": "adult_events",
            "manager_contact": "ADULT_MANAGER_SHOULD_NOT_WIN",
        } if section_id == "adult_events" else None,
    )

    assert admin_config_service.get_manager_phone() == CANONICAL_MANAGER_SENTINEL
    out = parent_flow._render_manager_number_answer(Lead(sender_id="x", platform="facebook", segment="PARENT"))
    assert CANONICAL_MANAGER_SENTINEL in out
    assert "ADULT_MANAGER_SHOULD_NOT_WIN" not in out
    assert WRONG_USER_PHONE not in out
    assert WRONG_USER_PHONE_DIGITS not in out


def test_missing_manager_contact_never_falls_back_to_user_or_lead_phone(monkeypatch):
    monkeypatch.setattr(admin_config_service, "get_manager_phone", lambda: "")
    lead = Lead(sender_id="missing-contact", platform="facebook", segment="PARENT", phone=WRONG_USER_PHONE_DIGITS)

    out = parent_flow._render_manager_number_answer(lead)

    assert WRONG_USER_PHONE not in out
    assert WRONG_USER_PHONE_DIGITS not in out
    assert "მენეჯერის ნომერია:" not in out
    assert out == "მენეჯერი თავად დაგიკავშირდებათ."


def test_entry_points_use_same_canonical_manager_contact(canonical_manager, monkeypatch):
    conv_direct = _conv("entry-direct")
    direct = parent_flow._maybe_handle_explicit_manager_request(conv_direct, "მენეჯერის ნომერი მომწერეთ")

    conv_planner = _conv("entry-planner")
    plan = type("Plan", (), {"user_current_intent": "manager_phone_request"})()
    planner = parent_flow._planner_protect_manager_phone(conv_planner, "მენეჯერის ნომერი მომწერეთ", plan)

    conv_underage = _conv("entry-underage")
    conv_underage.lead.child_age = "8"
    conv_underage.history.append({"role": "assistant", "content": "თუ გსურთ, მენეჯერთან დაგაკავშირებთ."})
    monkeypatch.setattr(parent_flow.notification_service, "notify_manager_handoff", lambda *a, **k: False)
    underage = parent_flow._maybe_handle_underage_manager_handoff(conv_underage, "მენეჯერის ნომერი მომწერე")

    for out in (direct, planner, underage):
        assert out is not None
        assert canonical_manager in out
        assert WRONG_USER_PHONE not in out
        assert WRONG_USER_PHONE_DIGITS not in out



def test_parent_tool_camp_info_uses_canonical_manager_contact(canonical_manager, monkeypatch):
    monkeypatch.setattr(parent_tool_executor, "_is_camp_registration_open", lambda: True)
    conv = _conv("tool-entry")
    executor = parent_tool_executor.ParentToolExecutor(
        conversation=conv,
        lead=conv.lead,
        sender_id=conv.sender_id,
        platform=conv.platform,
        user_message="რეგისტრაციის ინფორმაცია მინდა",
    )

    registration = executor._get_camp_info({"topic": "registration"})
    all_info = executor._get_camp_info({"topic": "all"})

    assert registration.get("phone") == canonical_manager
    assert all_info.get("phone") == canonical_manager
    assert WRONG_USER_PHONE_DIGITS not in str(registration)
    assert WRONG_USER_PHONE_DIGITS not in str(all_info)

def test_one_manager_phone_request_produces_one_response(canonical_manager):
    conv = _conv("single-response")

    out = parent_flow._maybe_handle_explicit_manager_request(conv, "მენეჯერის ნომერი მომწერეთ")

    assert out.count("მენეჯერის ნომერია:") == 1
    assert out.count(canonical_manager) == 1
    assert out.count("მენეჯერის ნომერია:") == 1


def test_manager_contact_source_guard_has_no_noncanonical_runtime_fallbacks():
    manager_src = inspect.getsource(admin_config_service.get_manager_phone)
    render_src = inspect.getsource(parent_flow._render_manager_number_answer)

    assert "summer_camp" in manager_src
    assert "load_knowledge" not in manager_src
    assert "company" not in manager_src
    assert "lead.phone" not in render_src.split("manager_phone =", 1)[-1]
    assert WRONG_USER_PHONE not in render_src
    assert WRONG_USER_PHONE_DIGITS not in render_src
    assert "_approved_camp_copy" in render_src