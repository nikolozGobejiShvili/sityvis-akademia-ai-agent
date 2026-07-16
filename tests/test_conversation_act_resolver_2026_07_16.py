from __future__ import annotations

import ast
import inspect
import subprocess
import sys
from dataclasses import FrozenInstanceError, fields
from pathlib import Path

import pytest

from app.domain.decision import (
    ConversationAct,
    ConversationActDecision,
    ConversationActReason,
    NormalizedMessage,
    ProgramId,
    normalize_message,
    resolve_conversation_act,
)


ROOT = Path(__file__).resolve().parents[1]
DOMAIN_DIR = ROOT / "app" / "domain" / "decision"


def _decision(text: str) -> ConversationActDecision:
    return resolve_conversation_act(normalize_message(text))


def test_conversation_act_enum_is_exactly_the_closed_twelve_values():
    assert tuple(ConversationAct) == (
        ConversationAct.PROGRAM_QUESTION,
        ConversationAct.CLARIFICATION,
        ConversationAct.CORRECTION,
        ConversationAct.COMPLAINT,
        ConversationAct.NEGATIVE_FEEDBACK,
        ConversationAct.INSULT,
        ConversationAct.GREETING,
        ConversationAct.THANKS,
        ConversationAct.HUMAN_HANDOFF,
        ConversationAct.CALLBACK_REQUEST,
        ConversationAct.UNRELATED,
        ConversationAct.UNKNOWN,
    )
    assert tuple(item.value for item in ConversationAct) == (
        "program_question",
        "clarification",
        "correction",
        "complaint",
        "negative_feedback",
        "insult",
        "greeting",
        "thanks",
        "human_handoff",
        "callback_request",
        "unrelated",
        "unknown",
    )


def test_decision_and_nested_metadata_are_immutable():
    decision = _decision("დებილი ხარ, მენეჯერს დამაკავშირეთ")
    assert decision.candidate_acts == (
        ConversationAct.INSULT,
        ConversationAct.HUMAN_HANDOFF,
    )
    with pytest.raises(FrozenInstanceError):
        decision.act = ConversationAct.UNKNOWN  # type: ignore[misc]
    with pytest.raises(AttributeError):
        decision.evidence.append("changed")  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        decision.candidate_acts.append(  # type: ignore[attr-defined]
            ConversationAct.UNKNOWN
        )


def test_decision_validation_rejects_invalid_confidence_and_metadata():
    with pytest.raises(ValueError, match="confidence"):
        ConversationActDecision(
            act=ConversationAct.UNKNOWN,
            confidence=1.1,
            primary_reason=ConversationActReason.INSUFFICIENT_EVIDENCE,
            evidence=("unknown.test",),
            candidate_acts=(ConversationAct.UNKNOWN,),
        )
    with pytest.raises(ValueError, match="first candidate"):
        ConversationActDecision(
            act=ConversationAct.UNKNOWN,
            confidence=0.0,
            primary_reason=ConversationActReason.INSUFFICIENT_EVIDENCE,
            evidence=("unknown.test",),
            candidate_acts=(ConversationAct.GREETING,),
        )


def test_resolver_accepts_only_normalized_message_and_has_no_context_argument():
    signature = inspect.signature(resolve_conversation_act)
    assert tuple(signature.parameters) == ("message",)
    message = normalize_message("მადლობა")
    assert resolve_conversation_act(message).act is ConversationAct.THANKS
    with pytest.raises(TypeError, match="NormalizedMessage"):
        resolve_conversation_act("მადლობა")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "text",
    [
        "არასწორ ინფორმაციას მწერ",
        "ეს პასუხი არასწორია",
        "სწორად არ მითხარი",
        "ინფორმაცია შეგეშალა",
    ],
)
def test_required_correction_cases(text: str):
    assert _decision(text).act is ConversationAct.CORRECTION


@pytest.mark.parametrize(
    "text",
    [
        "საერთოდ არ მეხმარებით",
        "რატომ მაწვალებთ?",
        "რამდენჯერ უნდა გკითხოთ?",
        "ცუდი მომსახურებაა",
    ],
)
def test_required_complaint_cases(text: str):
    assert _decision(text).act is ConversationAct.COMPLAINT


@pytest.mark.parametrize(
    "text",
    ["ვერ ხარ", "არ მომწონს", "ცუდია", "გააფრინე?"],
)
def test_required_negative_feedback_cases(text: str):
    assert _decision(text).act is ConversationAct.NEGATIVE_FEEDBACK


def test_required_insult_case():
    assert _decision("დებილი ხარ").act is ConversationAct.INSULT


@pytest.mark.parametrize("text", ["გამარჯობა", "საღამო მშვიდობისა"])
def test_required_greeting_cases(text: str):
    assert _decision(text).act is ConversationAct.GREETING


@pytest.mark.parametrize(
    "text", ["მადლობა", "დიდი მადლობა", "კარგი, მადლობა"]
)
def test_required_thanks_cases(text: str):
    assert _decision(text).act is ConversationAct.THANKS


@pytest.mark.parametrize(
    "text",
    [
        "ადამიანთან დამაკავშირეთ",
        "მენეჯერს დამაკავშირეთ",
        "ოპერატორს მინდა დაველაპარაკო",
        "კონსულტანტს გადამაერთეთ",
    ],
)
def test_required_human_handoff_cases(text: str):
    assert _decision(text).act is ConversationAct.HUMAN_HANDOFF


@pytest.mark.parametrize(
    "text",
    [
        "დამირეკეთ",
        "გადმომირეკეთ",
        "შეგიძლიათ დამიკავშირდეთ?",
        "ჩემი ნომერი დაგიტოვოთ და დამირეკავთ?",
    ],
)
def test_required_callback_cases(text: str):
    assert _decision(text).act is ConversationAct.CALLBACK_REQUEST


@pytest.mark.parametrize(
    "text",
    [
        "რას გულისხმობ?",
        "ვერ გავიგე",
        "შეგიძლიათ დამიზუსტოთ?",
        "კიდევ ერთხელ ამიხსენით",
    ],
)
def test_required_clarification_cases(text: str):
    assert _decision(text).act is ConversationAct.CLARIFICATION


@pytest.mark.parametrize(
    "text",
    [
        "ბანაკი რა ღირს?",
        "რა ჯდება ბავშვის ბანაკში მონაწილეობა?",
        "წელს კიდევ გექნებათ ბანაკი?",
        "ბანაკის გარდა ახლა რა პროგრამა გაქვთ?",
        "მენეჯერის ნომერი მომწერეთ",
        "სად ტარდება?",
        "რამდენი დღეა?",
        "ბანაკი არ მინდა, სხვა პროგრამა გაქვთ?",
    ],
)
def test_required_generic_program_question_cases(text: str):
    decision = _decision(text)
    assert decision.act is ConversationAct.PROGRAM_QUESTION
    assert decision.primary_reason is ConversationActReason.GENERIC_PROGRAM_QUESTION


@pytest.mark.parametrize("text", ["14 წლის", "14", "რომელი?", "ჰმ", "...", "", "   "])
def test_required_unknown_and_bare_age_cases(text: str):
    assert _decision(text).act is ConversationAct.UNKNOWN


def test_unknown_reason_distinguishes_empty_punctuation_and_context_fragments():
    assert _decision("").primary_reason is ConversationActReason.EMPTY_INPUT
    assert _decision("...").primary_reason is ConversationActReason.PUNCTUATION_ONLY
    for text in ("14", "14 წლის", "რომელი?"):
        assert (
            _decision(text).primary_reason
            is ConversationActReason.CONTEXT_DEPENDENT_FRAGMENT
        )


@pytest.mark.parametrize(
    "text", ["დღეს ამინდი როგორია?", "ფეხბურთის ანგარიში მითხარი"]
)
def test_unrelated_is_limited_to_clear_off_domain_cases(text: str):
    decision = _decision(text)
    assert decision.act is ConversationAct.UNRELATED
    assert decision.primary_reason is ConversationActReason.CLEAR_OFF_DOMAIN


@pytest.mark.parametrize(
    ("text", "expected", "candidates"),
    [
        (
            "გამარჯობა, ბანაკი რა ღირს?",
            ConversationAct.PROGRAM_QUESTION,
            (ConversationAct.PROGRAM_QUESTION,),
        ),
        (
            "მადლობა, ბანაკი რა ღირს?",
            ConversationAct.PROGRAM_QUESTION,
            (ConversationAct.PROGRAM_QUESTION,),
        ),
        (
            "რამდენჯერ უნდა გკითხოთ, ბანაკი რა ღირს?",
            ConversationAct.COMPLAINT,
            (ConversationAct.COMPLAINT, ConversationAct.PROGRAM_QUESTION),
        ),
        (
            "დებილი ხარ, მენეჯერს დამაკავშირეთ",
            ConversationAct.INSULT,
            (ConversationAct.INSULT, ConversationAct.HUMAN_HANDOFF),
        ),
        (
            "არასწორად რატომ მწერ?",
            ConversationAct.CORRECTION,
            (ConversationAct.CORRECTION,),
        ),
        (
            "რას გულისხმობ?",
            ConversationAct.CLARIFICATION,
            (ConversationAct.CLARIFICATION,),
        ),
    ],
)
def test_explicit_stronger_act_and_wrapper_precedence(
    text: str,
    expected: ConversationAct,
    candidates: tuple[ConversationAct, ...],
):
    decision = _decision(text)
    assert decision.act is expected
    assert decision.candidate_acts == candidates


def test_thanks_with_only_an_unresolved_new_question_does_not_stop_at_thanks():
    decision = _decision("მადლობა, კიდევ ერთი კითხვა მაქვს")
    assert decision.act is ConversationAct.UNKNOWN


def test_manager_handoff_callback_and_contact_information_are_distinct():
    assert _decision("მენეჯერს დამაკავშირეთ").act is ConversationAct.HUMAN_HANDOFF
    assert _decision("დამირეკეთ").act is ConversationAct.CALLBACK_REQUEST
    assert _decision("მენეჯერის ნომერი მომწერეთ").act is ConversationAct.PROGRAM_QUESTION
    assert _decision("მენეჯერი ვინ არის?").act is ConversationAct.PROGRAM_QUESTION
    assert _decision("მენეჯერის სამუშაო საათები რა არის?").act is ConversationAct.PROGRAM_QUESTION


@pytest.mark.parametrize(
    "text",
    ["არ დამირეკოთ", "ნუ დამირეკავთ", "არასწორი არ არის"],
)
def test_negation_does_not_trigger_callback_or_correction(text: str):
    decision = _decision(text)
    assert decision.act not in {
        ConversationAct.CALLBACK_REQUEST,
        ConversationAct.CORRECTION,
    }


@pytest.mark.parametrize(
    "text",
    [
        "საგამარჯობაო",
        "მადლობიანი",
        "დამირეკეთის",
        "დებილიხარ",
        "მენეჯერსდამაკავშირეთ",
    ],
)
def test_act_signals_do_not_match_inside_longer_tokens(text: str):
    assert _decision(text).act is ConversationAct.UNKNOWN


def test_curated_act_typo_is_narrow_and_does_not_mutate_message():
    message = normalize_message("მადლბა")
    before = message
    decision = resolve_conversation_act(message)
    assert decision.act is ConversationAct.THANKS
    assert decision.primary_reason is ConversationActReason.CURATED_TYPO
    assert decision.confidence == 0.84
    assert message == before
    assert _decision("სრულიად").act is ConversationAct.UNKNOWN


def test_confidence_is_bounded_deterministic_rule_strength_metadata():
    texts = (
        "დებილი ხარ",
        "არასწორ ინფორმაციას მწერ",
        "ბანაკი რა ღირს?",
        "მადლბა",
        "რომელი?",
        "უცნობი ტექსტი",
    )
    for text in texts:
        first = _decision(text)
        second = _decision(text)
        assert 0.0 <= first.confidence <= 1.0
        assert first == second


def test_evidence_is_static_redacted_and_contains_no_response_or_reasoning():
    sentinel = "555 123 456"
    decision = _decision(f"დამირეკეთ {sentinel}")
    serialized = repr(decision.evidence)
    assert decision.act is ConversationAct.CALLBACK_REQUEST
    assert sentinel not in serialized
    assert "555" not in serialized
    assert all(item.count(".") == 1 for item in decision.evidence)
    assert not any("response" in item or "because" in item for item in decision.evidence)


def test_decision_contract_contains_no_program_topic_lifecycle_or_action_fields():
    assert {field.name for field in fields(ConversationActDecision)} == {
        "act",
        "confidence",
        "primary_reason",
        "evidence",
        "candidate_acts",
    }
    forbidden = {
        "program_id",
        "topic",
        "price",
        "future_program",
        "lifecycle",
        "response",
        "copy",
        "pending_workflow",
        "route",
    }
    assert not ({field.name for field in fields(ConversationActDecision)} & forbidden)
    decision = _decision("ბანაკი რა ღირს?")
    assert not any(isinstance(value, ProgramId) for value in decision.candidate_acts)


def test_phase2_boundary_remains_lexical_and_caller_supplied():
    source = (DOMAIN_DIR / "input_normalizer.py").read_text(encoding="utf-8")
    assert "ConversationAct" not in source
    assert "ProgramId" not in source
    signature = inspect.signature(resolve_conversation_act)
    assert "context" not in signature.parameters
    assert "state" not in signature.parameters
    assert "history" not in signature.parameters


def test_phase3_module_has_only_local_domain_imports():
    path = DOMAIN_DIR / "conversation_act.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    assert set(imported) <= {"__future__", "input_normalizer", "models"}


def test_decision_package_import_remains_side_effect_free_without_environment():
    command = (
        "import sys; "
        "import app.domain.decision as decision; "
        "message = decision.normalize_message('hello'); "
        "assert decision.resolve_conversation_act(message).act; "
        "assert not any(name.startswith(('app.services', 'app.flows')) "
        "for name in sys.modules)"
    )
    system_root = str(Path(Path(sys.executable).anchor) / "Windows")
    result = subprocess.run(
        [sys.executable, "-c", command],
        cwd=ROOT,
        env={
            "PYTHONDONTWRITEBYTECODE": "1",
            "SYSTEMROOT": system_root,
            "WINDIR": system_root,
        },
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
