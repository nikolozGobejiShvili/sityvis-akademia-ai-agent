from __future__ import annotations

import ast
import inspect
import subprocess
import sys
from dataclasses import FrozenInstanceError, fields
from pathlib import Path

import pytest

from app.domain.decision import (
    DEFAULT_CONTEXT_ARBITRATION_POLICY,
    ContextArbitrationDecision,
    ContextArbitrationError,
    ContextArbitrationPolicy,
    ContextArbitrationReason,
    ContextSource,
    ContextUse,
    ConversationAct,
    ConversationActDecision,
    ConversationActReason,
    ProgramContextCandidate,
    ProgramId,
    arbitrate_context,
    normalize_message,
    resolve_conversation_act,
)


ROOT = Path(__file__).resolve().parents[1]
DOMAIN_DIR = ROOT / "app" / "domain" / "decision"


def _candidate(
    program_id: ProgramId = ProgramId.SUMMER_CAMP,
    source: ContextSource = ContextSource.USER_CONFIRMED_PROGRAM,
    turn_distance: int = 0,
) -> ProgramContextCandidate:
    return ProgramContextCandidate(program_id, source, turn_distance)


def _program_act() -> ConversationActDecision:
    return ConversationActDecision(
        act=ConversationAct.PROGRAM_QUESTION,
        confidence=0.9,
        primary_reason=ConversationActReason.GENERIC_PROGRAM_QUESTION,
        evidence=("program.generic_information_request",),
        candidate_acts=(ConversationAct.PROGRAM_QUESTION,),
    )


def _arbitrate(
    text: str,
    candidates: tuple[ProgramContextCandidate, ...] = (),
    *,
    act: ConversationActDecision | None = None,
    policy: ContextArbitrationPolicy = DEFAULT_CONTEXT_ARBITRATION_POLICY,
) -> ContextArbitrationDecision:
    message = normalize_message(text)
    return arbitrate_context(
        message,
        act or resolve_conversation_act(message),
        candidates,
        policy,
    )


def test_context_enums_are_exactly_closed():
    assert tuple(item.value for item in ContextSource) == (
        "user_explicit_program",
        "user_confirmed_program",
        "assistant_referenced_program",
        "legacy_sticky_state",
        "legacy_segment_inference",
    )
    assert tuple(item.value for item in ContextUse) == (
        "blocked",
        "current_message_authoritative",
        "prior_context_selected",
        "prior_context_fallback_only",
        "ambiguous",
        "no_relevant_context",
    )
    assert tuple(item.value for item in ContextArbitrationReason) == (
        "act_blocks_context",
        "clarification_does_not_select_context",
        "current_message_substantive",
        "context_reset_or_exclusion",
        "single_fresh_strong_context",
        "single_fresh_assistant_context",
        "assistant_context_fallback_only",
        "conflicting_fresh_contexts",
        "no_context_candidates",
        "stale_context_only",
        "legacy_context_non_authoritative",
        "no_eligible_context",
    )


def test_candidate_policy_and_decision_are_deeply_immutable():
    candidate = _candidate()
    policy = ContextArbitrationPolicy()
    decision = _arbitrate("ფასი?", (candidate,), act=_program_act())

    with pytest.raises(FrozenInstanceError):
        candidate.turn_distance = 2  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        policy.strong_context_max_turn_distance = 9  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        decision.context_use = ContextUse.BLOCKED  # type: ignore[misc]
    with pytest.raises(AttributeError):
        decision.eligible_candidates.append(candidate)  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        decision.rejected_candidates.append(candidate)  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        decision.evidence.append("changed")  # type: ignore[attr-defined]


def test_public_api_has_only_current_message_act_candidates_and_policy():
    signature = inspect.signature(arbitrate_context)
    assert tuple(signature.parameters) == (
        "message",
        "conversation_act",
        "context_candidates",
        "policy",
    )
    assert not ({"history", "state", "conversation", "pending"} & set(signature.parameters))


@pytest.mark.parametrize(
    ("text", "expected_act"),
    [
        ("არასწორ ინფორმაციას მწერ", ConversationAct.CORRECTION),
        ("საერთოდ არ მეხმარებით", ConversationAct.COMPLAINT),
        ("ვერ ხარ", ConversationAct.NEGATIVE_FEEDBACK),
        ("დებილი ხარ", ConversationAct.INSULT),
        ("გამარჯობა", ConversationAct.GREETING),
        ("მადლობა", ConversationAct.THANKS),
        ("მენეჯერს დამაკავშირეთ", ConversationAct.HUMAN_HANDOFF),
        ("დამირეკეთ", ConversationAct.CALLBACK_REQUEST),
        ("დღეს ამინდი როგორია?", ConversationAct.UNRELATED),
        ("14 წლის", ConversationAct.UNKNOWN),
    ],
)
def test_every_non_program_act_blocks_fresh_camp_context(
    text: str,
    expected_act: ConversationAct,
):
    message = normalize_message(text)
    act = resolve_conversation_act(message)
    decision = arbitrate_context(message, act, (_candidate(),))
    assert act.act is expected_act
    assert decision.context_use is ContextUse.BLOCKED
    assert decision.selected_program_id is None
    assert decision.eligible_program_ids == ()
    assert decision.primary_reason is ContextArbitrationReason.ACT_BLOCKS_CONTEXT


@pytest.mark.parametrize(
    "text",
    [
        "არასწორ ინფორმაციას მწერ",
        "ეს პასუხი არასწორია",
        "სწორად არ მითხარი",
        "ინფორმაცია შეგეშალა",
    ],
)
def test_same_conversation_act_always_uses_same_top_level_context_gate(text: str):
    decision = _arbitrate(text, (_candidate(),))
    assert decision.context_use is ContextUse.BLOCKED
    assert decision.primary_reason is ContextArbitrationReason.ACT_BLOCKS_CONTEXT
    assert decision.evidence == ("act.blocked.correction",)


@pytest.mark.parametrize("text", ["რას გულისხმობ?", "ვერ გავიგე"])
def test_clarification_never_selects_a_program(text: str):
    decision = _arbitrate(text, (_candidate(),))
    assert decision.context_use is ContextUse.BLOCKED
    assert decision.selected_program_id is None
    assert (
        decision.primary_reason
        is ContextArbitrationReason.CLARIFICATION_DOES_NOT_SELECT_CONTEXT
    )


@pytest.mark.parametrize(
    "text",
    ["ფასი?", "და როდის?", "სად ტარდება?", "რამდენი დღეა?"],
)
@pytest.mark.parametrize("program_id", tuple(ProgramId))
def test_one_fresh_strong_context_is_selected_for_elliptical_questions(
    text: str,
    program_id: ProgramId,
):
    candidate = _candidate(program_id)
    decision = _arbitrate(text, (candidate,), act=_program_act())
    assert decision.context_use is ContextUse.PRIOR_CONTEXT_SELECTED
    assert decision.selected_program_id is program_id
    assert decision.eligible_program_ids == (program_id,)
    assert decision.eligible_candidates == (candidate,)
    assert decision.primary_reason is ContextArbitrationReason.SINGLE_FRESH_STRONG_CONTEXT


def test_elliptical_question_without_candidates_fails_closed():
    decision = _arbitrate("ფასი?", act=_program_act())
    assert decision.context_use is ContextUse.NO_RELEVANT_CONTEXT
    assert decision.selected_program_id is None
    assert decision.primary_reason is ContextArbitrationReason.NO_CONTEXT_CANDIDATES
    assert decision.confidence == 0.0


@pytest.mark.parametrize(
    "text",
    [
        "წელს კიდევ გექნებათ ბანაკი?",
        "მენეჯერის ნომერი მომწერეთ",
        "ბანაკის გარდა ახლა რა პროგრამა გაქვთ?",
        "ბანაკი არ მინდა, სხვა პროგრამა გაქვთ?",
    ],
)
def test_substantive_current_program_questions_never_inherit_prior_program(text: str):
    decision = _arbitrate(text, (_candidate(),))
    assert decision.context_use is ContextUse.CURRENT_MESSAGE_AUTHORITATIVE
    assert decision.selected_program_id is None


@pytest.mark.parametrize(
    "text",
    [
        "ამის გარდა სხვა რა გაქვთ?",
        "ამის ნაცვლად რას მთავაზობთ?",
        "სხვა პროგრამა მაინტერესებს",
    ],
)
def test_reset_and_exclusion_markers_prevent_prior_selection(text: str):
    decision = _arbitrate(text, (_candidate(),), act=_program_act())
    assert decision.context_use is ContextUse.CURRENT_MESSAGE_AUTHORITATIVE
    assert decision.selected_program_id is None
    assert decision.primary_reason is ContextArbitrationReason.CONTEXT_RESET_OR_EXCLUSION


def test_strong_context_freshness_boundary_and_one_turn_beyond():
    at_boundary = _arbitrate(
        "ფასი?",
        (_candidate(turn_distance=2),),
        act=_program_act(),
    )
    beyond = _arbitrate(
        "ფასი?",
        (_candidate(turn_distance=3),),
        act=_program_act(),
    )
    assert at_boundary.context_use is ContextUse.PRIOR_CONTEXT_SELECTED
    assert beyond.context_use is ContextUse.NO_RELEVANT_CONTEXT
    assert beyond.primary_reason is ContextArbitrationReason.STALE_CONTEXT_ONLY
    assert beyond.selected_program_id is None


def test_custom_policy_changes_only_explicit_turn_freshness_boundary():
    policy = ContextArbitrationPolicy(
        strong_context_max_turn_distance=0,
        assistant_context_max_turn_distance=0,
    )
    fresh = _arbitrate(
        "ფასი?",
        (_candidate(turn_distance=0),),
        act=_program_act(),
        policy=policy,
    )
    stale = _arbitrate(
        "ფასი?",
        (_candidate(turn_distance=1),),
        act=_program_act(),
        policy=policy,
    )
    assert fresh.context_use is ContextUse.PRIOR_CONTEXT_SELECTED
    assert stale.primary_reason is ContextArbitrationReason.STALE_CONTEXT_ONLY


def test_assistant_reference_is_fallback_only_by_default():
    assistant = _candidate(
        source=ContextSource.ASSISTANT_REFERENCED_PROGRAM,
        turn_distance=1,
    )
    decision = _arbitrate("ფასი?", (assistant,), act=_program_act())
    assert decision.context_use is ContextUse.PRIOR_CONTEXT_FALLBACK_ONLY
    assert decision.selected_program_id is None
    assert decision.eligible_program_ids == (ProgramId.SUMMER_CAMP,)
    assert decision.confidence < 0.5


def test_policy_may_explicitly_allow_fresh_assistant_selection():
    assistant = _candidate(
        source=ContextSource.ASSISTANT_REFERENCED_PROGRAM,
        turn_distance=1,
    )
    policy = ContextArbitrationPolicy(allow_assistant_context_selection=True)
    decision = _arbitrate(
        "ფასი?",
        (assistant,),
        act=_program_act(),
        policy=policy,
    )
    assert decision.context_use is ContextUse.PRIOR_CONTEXT_SELECTED
    assert decision.selected_program_id is ProgramId.SUMMER_CAMP
    assert decision.primary_reason is ContextArbitrationReason.SINGLE_FRESH_ASSISTANT_CONTEXT


def test_stale_assistant_reference_is_not_even_fallback_eligible():
    assistant = _candidate(
        source=ContextSource.ASSISTANT_REFERENCED_PROGRAM,
        turn_distance=2,
    )
    decision = _arbitrate("ფასი?", (assistant,), act=_program_act())
    assert decision.context_use is ContextUse.NO_RELEVANT_CONTEXT
    assert decision.primary_reason is ContextArbitrationReason.STALE_CONTEXT_ONLY


@pytest.mark.parametrize(
    "source",
    [ContextSource.LEGACY_STICKY_STATE, ContextSource.LEGACY_SEGMENT_INFERENCE],
)
def test_legacy_sources_are_never_authoritative(source: ContextSource):
    legacy = _candidate(source=source, turn_distance=0)
    decision = _arbitrate("ფასი?", (legacy,), act=_program_act())
    assert decision.context_use is ContextUse.NO_RELEVANT_CONTEXT
    assert decision.selected_program_id is None
    assert decision.primary_reason is ContextArbitrationReason.LEGACY_CONTEXT_NON_AUTHORITATIVE


def test_two_different_fresh_programs_are_ambiguous_and_order_independent():
    camp = _candidate(ProgramId.SUMMER_CAMP)
    school = _candidate(ProgramId.SUNDAY_SCHOOL)
    first = _arbitrate("ფასი?", (camp, school), act=_program_act())
    second = _arbitrate("ფასი?", (school, camp), act=_program_act())
    assert first == second
    assert first.context_use is ContextUse.AMBIGUOUS
    assert first.selected_program_id is None
    assert first.eligible_program_ids == (
        ProgramId.SUMMER_CAMP,
        ProgramId.SUNDAY_SCHOOL,
    )
    assert first.primary_reason is ContextArbitrationReason.CONFLICTING_FRESH_CONTEXTS


def test_same_program_duplicates_consolidate_to_strongest_fresh_source():
    confirmed = _candidate(source=ContextSource.USER_CONFIRMED_PROGRAM, turn_distance=2)
    explicit = _candidate(source=ContextSource.USER_EXPLICIT_PROGRAM, turn_distance=0)
    assistant = _candidate(source=ContextSource.ASSISTANT_REFERENCED_PROGRAM, turn_distance=0)
    legacy = _candidate(source=ContextSource.LEGACY_STICKY_STATE, turn_distance=0)
    decision = _arbitrate(
        "ფასი?",
        (legacy, assistant, explicit, confirmed, explicit),
        act=_program_act(),
    )
    assert decision.context_use is ContextUse.PRIOR_CONTEXT_SELECTED
    assert decision.eligible_candidates == (confirmed,)
    assert explicit in decision.rejected_candidates
    assert assistant in decision.rejected_candidates
    assert legacy in decision.rejected_candidates
    assert len(decision.rejected_candidates) == 3


def test_fresh_candidate_wins_when_other_program_candidate_is_stale():
    camp = _candidate(ProgramId.SUMMER_CAMP, turn_distance=0)
    school = _candidate(ProgramId.SUNDAY_SCHOOL, turn_distance=9)
    decision = _arbitrate("ფასი?", (school, camp), act=_program_act())
    assert decision.context_use is ContextUse.PRIOR_CONTEXT_SELECTED
    assert decision.selected_program_id is ProgramId.SUMMER_CAMP
    assert decision.eligible_candidates == (camp,)
    assert decision.rejected_candidates == (school,)


@pytest.mark.parametrize("text", ["14 წლის", "14", "...", "რომელი?"])
def test_unknown_fragments_never_reuse_fresh_or_legacy_camp(text: str):
    candidates = (
        _candidate(),
        _candidate(source=ContextSource.LEGACY_STICKY_STATE),
    )
    message = normalize_message(text)
    act = resolve_conversation_act(message)
    decision = arbitrate_context(message, act, candidates)
    assert act.act is ConversationAct.UNKNOWN
    assert decision.context_use is ContextUse.BLOCKED
    assert decision.selected_program_id is None


def test_decision_contract_has_no_program_resolution_topic_or_workflow_fields():
    assert {field.name for field in fields(ContextArbitrationDecision)} == {
        "context_use",
        "selected_program_id",
        "eligible_program_ids",
        "eligible_candidates",
        "rejected_candidates",
        "confidence",
        "primary_reason",
        "evidence",
    }
    forbidden = {
        "current_program_id",
        "requested_program_id",
        "topic",
        "price",
        "registration",
        "future_program",
        "alternative_program",
        "manager_contact",
        "transport",
        "location",
        "duration",
        "lifecycle",
        "pending_workflow",
        "response",
        "copy",
        "route",
    }
    assert not ({field.name for field in fields(ContextArbitrationDecision)} & forbidden)


def test_current_text_cannot_resolve_program_without_prior_candidate():
    decision = _arbitrate("ბანაკი რა ღირს?")
    assert decision.context_use is ContextUse.CURRENT_MESSAGE_AUTHORITATIVE
    assert decision.selected_program_id is None
    assert decision.eligible_program_ids == ()


def test_one_word_program_noun_is_not_elliptical_by_length_alone():
    decision = _arbitrate(
        "ბანაკი?",
        (_candidate(ProgramId.SUNDAY_SCHOOL),),
        act=_program_act(),
    )
    assert decision.context_use is ContextUse.CURRENT_MESSAGE_AUTHORITATIVE
    assert decision.selected_program_id is None


def test_result_is_deterministic_and_confidence_is_rule_strength_metadata():
    candidates = (
        _candidate(source=ContextSource.USER_EXPLICIT_PROGRAM, turn_distance=1),
    )
    first = _arbitrate("ფასი?", candidates, act=_program_act())
    second = _arbitrate("ფასი?", candidates, act=_program_act())
    no_context = _arbitrate("ფასი?", act=_program_act())
    blocked = _arbitrate("მადლობა", candidates)
    substantive = _arbitrate("ბანაკი რა ღირს?", candidates)
    assert first == second
    assert 0.0 <= first.confidence <= 1.0
    assert first.confidence > no_context.confidence
    assert first.confidence > 0.9
    assert blocked.confidence == 0.0
    assert substantive.confidence == 0.0


def test_evidence_and_repr_do_not_expose_message_phone_or_private_identity():
    phone = "555 123 456"
    sender = "private-sender-123"
    decision = _arbitrate(
        f"ფასი? {phone}",
        (_candidate(),),
        act=_program_act(),
    )
    serialized = repr(decision)
    for forbidden in (phone, "555", sender, "ფასი"):
        assert forbidden not in serialized
    assert all(item == item.strip() and item for item in decision.evidence)


@pytest.mark.parametrize(
    "constructor",
    [
        lambda: ProgramContextCandidate(
            ProgramId.SUMMER_CAMP,
            ContextSource.USER_EXPLICIT_PROGRAM,
            -1,
        ),
        lambda: ProgramContextCandidate(
            "summer_camp",  # type: ignore[arg-type]
            ContextSource.USER_EXPLICIT_PROGRAM,
            0,
        ),
        lambda: ProgramContextCandidate(
            ProgramId.SUMMER_CAMP,
            "user_explicit_program",  # type: ignore[arg-type]
            0,
        ),
        lambda: ContextArbitrationPolicy(strong_context_max_turn_distance=-1),
        lambda: ContextArbitrationPolicy(assistant_context_max_turn_distance=-1),
        lambda: ContextArbitrationPolicy(
            allow_assistant_context_selection=1  # type: ignore[arg-type]
        ),
    ],
)
def test_invalid_candidate_and_policy_contracts_fail_loudly(constructor):
    with pytest.raises(ContextArbitrationError):
        constructor()


def test_mutable_or_wrong_arbiter_inputs_are_rejected():
    message = normalize_message("ფასი?")
    act = _program_act()
    candidate = _candidate()
    with pytest.raises(TypeError, match="NormalizedMessage"):
        arbitrate_context("ფასი?", act, (candidate,))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="ConversationActDecision"):
        arbitrate_context(message, ConversationAct.PROGRAM_QUESTION, (candidate,))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="immutable tuple"):
        arbitrate_context(message, act, [candidate])  # type: ignore[arg-type]
    with pytest.raises(ContextArbitrationError, match="ProgramContextCandidate"):
        arbitrate_context(message, act, ({"program": "camp"},))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="ContextArbitrationPolicy"):
        arbitrate_context(message, act, (candidate,), {})  # type: ignore[arg-type]


def test_decision_validation_rejects_selected_program_mismatch_and_bad_confidence():
    with pytest.raises(ContextArbitrationError, match="requires"):
        ContextArbitrationDecision(
            context_use=ContextUse.NO_RELEVANT_CONTEXT,
            selected_program_id=ProgramId.SUMMER_CAMP,
            eligible_program_ids=(ProgramId.SUMMER_CAMP,),
            eligible_candidates=(_candidate(),),
            rejected_candidates=(),
            confidence=0.5,
            primary_reason=ContextArbitrationReason.NO_ELIGIBLE_CONTEXT,
            evidence=("context.test",),
        )
    with pytest.raises(ContextArbitrationError, match="match eligible"):
        ContextArbitrationDecision(
            context_use=ContextUse.NO_RELEVANT_CONTEXT,
            selected_program_id=None,
            eligible_program_ids=(ProgramId.SUMMER_CAMP,),
            eligible_candidates=(),
            rejected_candidates=(),
            confidence=0.0,
            primary_reason=ContextArbitrationReason.NO_ELIGIBLE_CONTEXT,
            evidence=("context.test",),
        )
    with pytest.raises(ContextArbitrationError, match="confidence"):
        ContextArbitrationDecision(
            context_use=ContextUse.NO_RELEVANT_CONTEXT,
            selected_program_id=None,
            eligible_program_ids=(),
            eligible_candidates=(),
            rejected_candidates=(),
            confidence=1.1,
            primary_reason=ContextArbitrationReason.NO_ELIGIBLE_CONTEXT,
            evidence=("context.test",),
        )


def test_phase4_module_imports_only_local_domain_models():
    path = DOMAIN_DIR / "context_arbiter.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    assert set(imported) <= {"__future__", "models"}


def test_phase4_source_has_no_state_program_resolution_or_external_io_dependency():
    source = (DOMAIN_DIR / "context_arbiter.py").read_text(encoding="utf-8")
    forbidden = (
        "app.services",
        "app.flows",
        "PROGRAM_REGISTRY",
        "ProgramRegistry",
        "redis",
        "openai",
        "notification",
        "calendar",
        "approved_copy",
        "prompt",
        "os.environ",
        "getenv",
        "datetime",
        "Conversation(",
        "pending_booking",
        "ASK_AGE",
    )
    assert not any(item in source for item in forbidden)


def test_phase4_does_not_change_or_import_phase3_resolver():
    source = (DOMAIN_DIR / "conversation_act.py").read_text(encoding="utf-8")
    assert "ContextSource" not in source
    assert "ContextUse" not in source
    assert "arbitrate_context" not in source


def test_decision_package_import_remains_side_effect_free_without_environment():
    command = (
        "import sys; "
        "import app.domain.decision as decision; "
        "message = decision.normalize_message('14'); "
        "act = decision.resolve_conversation_act(message); "
        "result = decision.arbitrate_context(message, act, ()); "
        "assert result.context_use; "
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
