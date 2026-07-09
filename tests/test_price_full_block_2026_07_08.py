"""Camp price/payment intent split (2026-07-09).

price_amount returns the full approved camp price block. Pure payment_process
returns the approved payment-process wording without 2150. Reservation exact
amount returns manager deferral only, without inventing an amount.
"""
from __future__ import annotations

import dataclasses

import pytest

import app.config as config_module
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import conversation_service, messenger_service

_FULL_BLOCK_ELEMENTS = ("2150", "ტრანსპორტირება", "გადანაწილება", "TBC", "საქართველოს ბანკ", "10%")
_AS_ABOVE = ("როგორც ზემოთ მოგწერეთ", "როგორც უკვე გითხარით", "ზემოთ მოგწერეთ")
_PAYMENT_PROCESS_ANSWER = (
    "ბანაკის ჯავშნის საფასურის გადახდა ხდება წინასწარ, ხოლო სრული თანხის — "
    "ხელშეკრულებით გათვალისწინებულ დროში. გადახდის გადანაწილება შესაძლებელია "
    "6 თვემდე TBC-ისა და საქართველოს ბანკის საშუალებით"
)
_RESERVATION_DEFER = "რაც შეეხება ჯავშნის საფასურს, ამ დეტალებს მენეჯერი გაგაცნობთ: 558 67 47 33"


def _assert_full_block(out: str) -> None:
    for expected in _FULL_BLOCK_ELEMENTS:
        assert expected in out, expected
    for bad in _AS_ABOVE:
        assert bad not in out


def _assert_payment_process(out: str) -> None:
    assert _PAYMENT_PROCESS_ANSWER in out
    assert "2150" not in out
    assert "ბანაკის ფასი" not in out


@pytest.fixture(autouse=True)
def _reset():
    conversation_service.conversations.clear()
    yield
    conversation_service.conversations.clear()


@pytest.fixture
def engine_on(monkeypatch):
    swapped = dataclasses.replace(
        config_module.settings,
        USE_PARENT_LLM_ENGINE=True,
        USE_CONVERSATION_PLANNER=False,
        CONVERSATION_PLANNER_AUTHORITATIVE=False,
        USE_SLIM_PROMPTS=False,
    )
    monkeypatch.setattr(parent_flow, "settings", swapped)
    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    monkeypatch.setattr(
        parent_flow,
        "_run_llm_engine_safely",
        lambda c, m: parent_flow._camp_price_full_block(),
    )
    return swapped


def _price_conv(sid="pr", child_age="10"):
    c = Conversation(sender_id=sid, platform="instagram", segment="PARENT")
    c.state = "ASK_CHALLENGE"
    c.history.append({"role": "assistant", "content": "რას ელოდებით ბანაკისგან?"})
    c.lead = Lead(sender_id=sid, platform="instagram", segment="PARENT", child_age=child_age)
    return c


def _direct_conv(sid="direct", child_age="12", user_msgs=()):
    c = Conversation(sender_id=sid, platform="instagram", segment="PARENT")
    c.lead = Lead(sender_id=sid, platform="instagram", segment="PARENT", child_age=child_age)
    c.history = [{"role": "user", "content": m} for m in user_msgs]
    return c


def _turn(conv, msg):
    conv.history.append({"role": "user", "content": msg})
    out = parent_flow.handle(conv, msg)
    conv.history.append({"role": "assistant", "content": out})
    return out


def test_full_block_builder_contains_approved_elements():
    _assert_full_block(parent_flow._camp_price_full_block())


@pytest.mark.parametrize("msg", [
    "ბანაკი რა ღირს?",
    "ბანაკის ფასი რა არის?",
    "ბანაკის ღირებულება მითხარით",
])
def test_price_amount_returns_full_block_without_llm(engine_on, monkeypatch, msg):
    monkeypatch.setattr(
        parent_flow,
        "_run_llm_engine_safely",
        lambda c, m: pytest.fail("LLM must not run for camp price amount"),
    )
    out = _turn(_price_conv("price"), msg)
    _assert_full_block(out)


@pytest.mark.parametrize("msg", [
    "გადახდა როგორ ხდება?",
    "როგორ ხდება გადახდა?",
    "როგორ უნდა გადავიხადო?",
])
def test_payment_process_answer_has_no_price_without_llm(engine_on, monkeypatch, msg):
    monkeypatch.setattr(
        parent_flow,
        "_run_llm_engine_safely",
        lambda c, m: pytest.fail("LLM must not run for payment process"),
    )
    out = _turn(_price_conv("payment"), msg)
    _assert_payment_process(out)


@pytest.mark.parametrize("msg", [
    "წინასწარი საფასური რამდენია?",
    "ჯავშნის ღირებულება რამდენია?",
    "ჯავშნის საფასური რამდენია?",
    "წინასწარ რამდენს ვიხდი?",
    "ჯავშანი რამდენია?",
])
def test_reservation_exact_amount_manager_defer_only(engine_on, monkeypatch, msg):
    monkeypatch.setattr(
        parent_flow,
        "_run_llm_engine_safely",
        lambda c, m: pytest.fail("LLM must not run for reservation exact amount"),
    )
    out = _turn(_price_conv("reservation"), msg)
    assert out == _RESERVATION_DEFER
    assert "2150" not in out


def test_combined_price_and_payment_may_return_full_block_without_llm(engine_on, monkeypatch):
    monkeypatch.setattr(
        parent_flow,
        "_run_llm_engine_safely",
        lambda c, m: pytest.fail("LLM must not run for combined price/payment"),
    )
    out = _turn(_price_conv("combined"), "ბანაკი რა ღირს და გადახდა როგორ ხდება?")
    _assert_full_block(out)


def test_repeat_price_returns_full_block_no_as_above(engine_on):
    conv = _price_conv("repeat")
    _assert_full_block(_turn(conv, "ბანაკი რა ღირს?"))
    _assert_full_block(_turn(conv, "ფასი კიდევ ერთხელ მითხარით"))


def test_repeat_handler_direct_price_payment_split():
    price = parent_flow._maybe_handle_repeat_camp_price(
        _direct_conv("dp", user_msgs=("ბანაკი რა ღირს?",)),
        "ბანაკი რა ღირს?",
    )
    payment = parent_flow._maybe_handle_repeat_camp_price(
        _direct_conv("pay", user_msgs=("გადახდა როგორ ხდება?",)),
        "გადახდა როგორ ხდება?",
    )
    reservation = parent_flow._maybe_handle_repeat_camp_price(
        _direct_conv("res", user_msgs=("ჯავშნის ღირებულება რამდენია?",)),
        "ჯავშნის ღირებულება რამდენია?",
    )
    assert price is not None
    _assert_full_block(price)
    assert payment is not None
    _assert_payment_process(payment)
    assert reservation == _RESERVATION_DEFER


def test_sanitizer_preserves_approved_payment_process_answer():
    kept = parent_flow._strip_payment_terms_from_simple_price(
        "გადახდა როგორ ხდება?",
        parent_flow._camp_payment_process_answer(),
    )
    assert kept == _PAYMENT_PROCESS_ANSWER
    assert "2150" not in kept


def test_no_price_handler_emits_as_above():
    outputs = [
        parent_flow._camp_price_full_block(),
        parent_flow._camp_price_direct_answer(),
        parent_flow._camp_price_answer("ბანაკი რა ღირს?"),
        parent_flow._camp_payment_process_answer(),
        parent_flow._maybe_handle_reservation_fee_question(
            _direct_conv("rf"),
            "ჯავშნის საფასური რამდენია?",
        ),
    ]
    for out in outputs:
        assert out is not None
        for bad in _AS_ABOVE:
            assert bad not in out