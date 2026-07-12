from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from app.flows import parent_flow, parent_turn_router
from app.models.conversation import Conversation
from app.reasoning import camp_topic_facts
from app.services import admin_config_service, approved_copy_service


REPO_ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_FLAT_KEYS = {"camp_price_block", "CAMP_PRICE_BLOCK", "PRICE_BLOCK"}


@pytest.fixture(autouse=True)
def _reset_approved_copy_cache():
    approved_copy_service.reset_cache()
    yield
    approved_copy_service.reset_cache()


def _read_yaml() -> dict[str, Any]:
    return yaml.safe_load(
        approved_copy_service.APPROVED_COPY_PATH.read_text(encoding="utf-8")
    )


def _all_mapping_keys(node: Any) -> set[str]:
    if not isinstance(node, dict):
        return set()
    keys = {str(key) for key in node}
    for value in node.values():
        keys.update(_all_mapping_keys(value))
    return keys


def _price_context() -> dict[str, Any]:
    banks_phrase = " და ".join(
        parent_flow._bank_genitive(bank) for bank in parent_flow._camp_price_banks()
    ) or "ბანკის"
    return {
        "price": parent_flow._camp_price_value(),
        "installments_months": parent_flow._camp_installments_months(),
        "banks_phrase": banks_phrase,
    }


def _manager_phone() -> str:
    return admin_config_service.get_manager_phone()


def _registration_url() -> str:
    return parent_flow._camp_registration_url()


def _reservation_conversation() -> Conversation:
    return Conversation(
        sender_id="approved-copy-reservation",
        platform="instagram",
        segment="PARENT",
    )


def _render(key_path: str, **context: Any) -> str:
    return approved_copy_service.get_approved_copy("camp", key_path, **context)


def test_programs_yaml_is_program_scoped():
    data = _read_yaml()

    assert set(data) == {"programs"}
    assert set(data["programs"]) == {"camp"}
    assert "price" in data["programs"]["camp"]
    assert "registration" in data["programs"]["camp"]
    assert not (FORBIDDEN_FLAT_KEYS & _all_mapping_keys(data))


def test_loader_supports_dotted_and_two_argument_lookup():
    context = _price_context()

    assert approved_copy_service.get_approved_copy(
        "camp.price.full_block",
        context=context,
    ) == approved_copy_service.get_approved_copy(
        "camp",
        "price.full_block",
        context=context,
    )


def test_loader_fails_closed_for_missing_program_key_and_placeholder():
    with pytest.raises(approved_copy_service.ApprovedCopyNotFound):
        approved_copy_service.get_approved_copy("sunday_school.price.full_block")

    with pytest.raises(approved_copy_service.ApprovedCopyNotFound):
        approved_copy_service.get_approved_copy("camp.price.missing")

    with pytest.raises(approved_copy_service.ApprovedCopyFormatError):
        approved_copy_service.get_approved_copy("camp.price.full_block")


def test_loader_allows_new_program_without_service_code_change(tmp_path, monkeypatch):
    program_yaml = tmp_path / "programs.yaml"
    program_yaml.write_text(
        "programs:\n"
        "  sunday_school:\n"
        "    greeting: \"გამარჯობა, {name}\"\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(approved_copy_service, "APPROVED_COPY_PATH", program_yaml)
    approved_copy_service.reset_cache()

    assert approved_copy_service.get_approved_copy(
        "sunday_school.greeting",
        name="მარიამ",
    ) == "გამარჯობა, მარიამ"


def test_camp_price_copy_matches_current_runtime_functions():
    assert _render("price.full_block", **_price_context()) == (
        parent_flow._camp_price_full_block()
    )
    assert _render("price.payment_process") == (
        parent_flow._camp_payment_process_answer()
    )
    assert _render(
        "price.reservation_exact_amount_deferral",
        manager_phone=_manager_phone(),
    ) == parent_flow._maybe_handle_reservation_fee_question(
        _reservation_conversation(),
        "ჯავშნის საფასური რამდენია?",
    )
    assert _render(
        "price.exact_amount_manager_deferral_line",
        manager_phone=_manager_phone(),
    ) == parent_flow._camp_price_manager_deferral_line()


def test_camp_manager_unknown_detail_copy_matches_current_runtime_functions():
    rendered = _render("manager.unknown_detail_ending", manager_phone=_manager_phone())

    assert rendered == parent_flow._UNKNOWN_DETAIL_ENDING
    assert rendered == camp_topic_facts._unknown_ending()


def test_camp_transport_copy_matches_current_runtime_functions():
    included = _render("logistics.transport.included")
    details = _render("logistics.transport.details_defer", manager_phone=_manager_phone())
    pickup = _render("logistics.transport.pickup_defer", manager_phone=_manager_phone())
    city = _render(
        "logistics.transport.city_details_defer",
        manager_phone=_manager_phone(),
        city_ablative="თელავიდან",
    )

    assert f"{included} {details}" == parent_flow._transport_answer("", pickup=False)
    assert f"{included} {pickup}" == parent_flow._transport_answer("", pickup=True)
    assert f"{included} {city}" == parent_flow._transport_answer(
        "თელავიდან",
        pickup=False,
    )


def test_parent_flow_transport_paths_route_through_approved_copy_service(monkeypatch):
    original = parent_flow._approved_camp_copy
    calls: list[tuple[str, dict[str, Any]]] = []

    def spy(key_path: str, **context: Any) -> str | None:
        calls.append((key_path, dict(context)))
        return original(key_path, **context)

    monkeypatch.setattr(parent_flow, "_approved_camp_copy", spy)
    city_ablative = "\u10d7\u10d4\u10da\u10d0\u10d5\u10d8\u10d3\u10d0\u10dc"

    assert parent_flow._transport_answer("", pickup=False)
    assert parent_flow._transport_answer("", pickup=True)
    assert parent_flow._transport_answer(city_ablative, pickup=False)

    key_paths = [key_path for key_path, _ in calls]
    contexts = {key_path: context for key_path, context in calls}

    assert key_paths.count("logistics.transport.included") == 3
    assert "logistics.transport.details_defer" in key_paths
    assert "logistics.transport.pickup_defer" in key_paths
    assert "logistics.transport.city_details_defer" in key_paths
    assert contexts["logistics.transport.details_defer"]["manager_phone"] == _manager_phone()
    assert contexts["logistics.transport.pickup_defer"]["manager_phone"] == _manager_phone()
    assert contexts["logistics.transport.city_details_defer"]["manager_phone"] == _manager_phone()
    assert contexts["logistics.transport.city_details_defer"]["city_ablative"] == city_ablative


def test_parent_flow_transport_approved_copy_failure_keeps_runtime_output(monkeypatch):
    city_ablative = "\u10d7\u10d4\u10da\u10d0\u10d5\u10d8\u10d3\u10d0\u10dc"
    expected_generic = parent_flow._transport_answer("", pickup=False)
    expected_pickup = parent_flow._transport_answer("", pickup=True)
    expected_city = parent_flow._transport_answer(city_ablative, pickup=False)

    def missing_copy(key_path: str, **context: Any) -> None:
        return None

    monkeypatch.setattr(parent_flow, "_approved_camp_copy", missing_copy)

    assert parent_flow._transport_answer("", pickup=False) == expected_generic
    assert parent_flow._transport_answer("", pickup=True) == expected_pickup
    assert parent_flow._transport_answer(city_ablative, pickup=False) == expected_city


def test_parent_flow_registration_url_first_routes_through_approved_copy_service(monkeypatch):
    expected_url = _registration_url()
    approved_response = "approved registration url-first response"
    calls: list[tuple[str, dict[str, Any]]] = []

    def spy(key_path: str, **context: Any) -> str:
        calls.append((key_path, dict(context)))
        return approved_response

    monkeypatch.setattr(parent_flow, "_approved_camp_copy", spy)

    assert parent_flow._render_camp_registration_answer() == approved_response
    assert calls == [("registration.url_first", {"registration_url": expected_url})]


def test_parent_flow_registration_url_first_approved_copy_failure_keeps_runtime_output(monkeypatch):
    expected_response = parent_flow._render_camp_registration_answer()
    expected_url = _registration_url()
    calls: list[tuple[str, dict[str, Any]]] = []

    def missing_copy(key_path: str, **context: Any) -> None:
        calls.append((key_path, dict(context)))
        return None

    monkeypatch.setattr(parent_flow, "_approved_camp_copy", missing_copy)

    assert parent_flow._render_camp_registration_answer() == expected_response
    assert calls == [("registration.url_first", {"registration_url": expected_url})]


def test_camp_registration_copy_preserves_both_active_variants():
    assert _render(
        "registration.url_first",
        registration_url=_registration_url(),
    ) == parent_flow._render_camp_registration_answer()
    assert _render(
        "registration.consultation_first",
        registration_url=_registration_url(),
    ) == parent_turn_router._build_premium_registration_answer()


def test_parent_flow_price_paths_route_through_approved_copy_service(monkeypatch):
    original = approved_copy_service.get_approved_copy
    calls: list[tuple[str, str | None]] = []

    def spy(program: str, key_path: str | None = None, **kwargs: Any) -> str:
        calls.append((program, key_path))
        return original(program, key_path, **kwargs)

    monkeypatch.setattr(parent_flow.approved_copy_service, "get_approved_copy", spy)
    reservation_question = (
        "\u10ef\u10d0\u10d5\u10e8\u10dc\u10d8\u10e1 "
        "\u10e1\u10d0\u10e4\u10d0\u10e1\u10e3\u10e0\u10d8 "
        "\u10e0\u10d0\u10db\u10d3\u10d4\u10dc\u10d8\u10d0?"
    )

    assert parent_flow._camp_price_full_block()
    assert parent_flow._camp_payment_process_answer()
    assert parent_flow._camp_price_manager_deferral_line()
    assert parent_flow._maybe_handle_reservation_fee_question(
        _reservation_conversation(),
        reservation_question,
    )

    assert {
        ("camp", "price.full_block"),
        ("camp", "price.payment_process"),
        ("camp", "price.exact_amount_manager_deferral_line"),
        ("camp", "price.reservation_exact_amount_deferral"),
    } <= set(calls)


def test_st3c_parent_router_still_does_not_use_approved_copy_service():
    parent_flow_source = (REPO_ROOT / "app/flows/parent_flow.py").read_text(
        encoding="utf-8",
    )
    router_source = (REPO_ROOT / "app/flows/parent_turn_router.py").read_text(
        encoding="utf-8",
    )

    assert "approved_copy_service" in parent_flow_source
    assert "price.full_block" in parent_flow_source
    assert "price.payment_process" in parent_flow_source
    assert "price.reservation_exact_amount_deferral" in parent_flow_source
    assert "price.exact_amount_manager_deferral_line" in parent_flow_source
    assert "approved_copy_service" not in router_source
    assert "get_approved_copy" not in router_source