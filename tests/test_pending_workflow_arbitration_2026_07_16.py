from __future__ import annotations

import ast
import inspect
import subprocess
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from app.domain.decision import (
    DEFAULT_PENDING_WORKFLOW_POLICY,
    ContextArbitrationDecision,
    ContextArbitrationReason,
    ContextSource,
    ContextUse,
    ConversationAct,
    ConversationActDecision,
    ConversationActReason,
    ExpectedReplyKind,
    PendingWorkflowAction,
    PendingWorkflowDecision,
    PendingWorkflowError,
    PendingWorkflowKind,
    PendingWorkflowPolicy,
    PendingWorkflowReason,
    PendingWorkflowSnapshot,
    PendingWorkflowSource,
    PendingWorkflowStatus,
    ProgramContextCandidate,
    ProgramId,
    arbitrate_context,
    arbitrate_pending_workflow,
    normalize_message,
    resolve_conversation_act,
)


ROOT = Path(__file__).resolve().parents[1]
DOMAIN_DIR = ROOT / "app" / "domain" / "decision"


def _snapshot(
    kind: PendingWorkflowKind = PendingWorkflowKind.CHILD_AGE_COLLECTION,
    *,
    workflow_id: str = "workflow.primary",
    owner_id: str = "owner.parent.discovery",
    source: PendingWorkflowSource = PendingWorkflowSource.LEGACY_STATE,
    status: PendingWorkflowStatus = PendingWorkflowStatus.ACTIVE,
    expected: tuple[ExpectedReplyKind, ...] | None = None,
    turn_distance: int = 0,
    program_id: ProgramId | None = ProgramId.SUMMER_CAMP,
) -> PendingWorkflowSnapshot:
    if expected is None:
        expected = {
            PendingWorkflowKind.CHILD_AGE_COLLECTION: (
                ExpectedReplyKind.CHILD_AGE,
            ),
            PendingWorkflowKind.CONTACT_COLLECTION: (
                ExpectedReplyKind.USER_PHONE,
            ),
            PendingWorkflowKind.AFFIRMATION_CONFIRMATION: (
                ExpectedReplyKind.AFFIRMATION,
            ),
        }[kind]
    return PendingWorkflowSnapshot(
        workflow_id=workflow_id,
        owner_id=owner_id,
        kind=kind,
        source=source,
        status=status,
        expected_reply_kinds=expected,
        turn_distance=turn_distance,
        program_id=program_id,
    )


def _act(act: ConversationAct) -> ConversationActDecision:
    return ConversationActDecision(
        act=act,
        confidence=0.9,
        primary_reason=ConversationActReason.INSUFFICIENT_EVIDENCE,
        evidence=(f"test.act.{act.value}",),
        candidate_acts=(act,),
    )


def _context_decision(
    context_use: ContextUse = ContextUse.BLOCKED,
) -> ContextArbitrationDecision:
    camp = ProgramContextCandidate(
        ProgramId.SUMMER_CAMP,
        ContextSource.USER_EXPLICIT_PROGRAM,
        0,
    )
    adult = ProgramContextCandidate(
        ProgramId.ADULT_EVENTS,
        ContextSource.USER_CONFIRMED_PROGRAM,
        0,
    )
    if context_use is ContextUse.PRIOR_CONTEXT_SELECTED:
        return ContextArbitrationDecision(
            context_use=context_use,
            selected_program_id=ProgramId.SUMMER_CAMP,
            eligible_program_ids=(ProgramId.SUMMER_CAMP,),
            eligible_candidates=(camp,),
            rejected_candidates=(),
            confidence=0.94,
            primary_reason=ContextArbitrationReason.SINGLE_FRESH_STRONG_CONTEXT,
            evidence=("context.test.selected",),
        )
    if context_use is ContextUse.PRIOR_CONTEXT_FALLBACK_ONLY:
        assistant = ProgramContextCandidate(
            ProgramId.SUMMER_CAMP,
            ContextSource.ASSISTANT_REFERENCED_PROGRAM,
            0,
        )
        return ContextArbitrationDecision(
            context_use=context_use,
            selected_program_id=None,
            eligible_program_ids=(ProgramId.SUMMER_CAMP,),
            eligible_candidates=(assistant,),
            rejected_candidates=(),
            confidence=0.4,
            primary_reason=ContextArbitrationReason.ASSISTANT_CONTEXT_FALLBACK_ONLY,
            evidence=("context.test.fallback",),
        )
    if context_use is ContextUse.AMBIGUOUS:
        return ContextArbitrationDecision(
            context_use=context_use,
            selected_program_id=None,
            eligible_program_ids=(
                ProgramId.ADULT_EVENTS,
                ProgramId.SUMMER_CAMP,
            ),
            eligible_candidates=(adult, camp),
            rejected_candidates=(),
            confidence=0.2,
            primary_reason=ContextArbitrationReason.CONFLICTING_FRESH_CONTEXTS,
            evidence=("context.test.ambiguous",),
        )
    reason = {
        ContextUse.BLOCKED: ContextArbitrationReason.ACT_BLOCKS_CONTEXT,
        ContextUse.CURRENT_MESSAGE_AUTHORITATIVE: (
            ContextArbitrationReason.CURRENT_MESSAGE_SUBSTANTIVE
        ),
        ContextUse.NO_RELEVANT_CONTEXT: (
            ContextArbitrationReason.NO_CONTEXT_CANDIDATES
        ),
    }[context_use]
    return ContextArbitrationDecision(
        context_use=context_use,
        selected_program_id=None,
        eligible_program_ids=(),
        eligible_candidates=(),
        rejected_candidates=(),
        confidence=0.0,
        primary_reason=reason,
        evidence=(f"context.test.{context_use.value}",),
    )


def _run(
    text: str,
    workflows: tuple[PendingWorkflowSnapshot, ...],
    *,
    act: ConversationActDecision | None = None,
    context: ContextArbitrationDecision | None = None,
    policy: PendingWorkflowPolicy = DEFAULT_PENDING_WORKFLOW_POLICY,
) -> PendingWorkflowDecision:
    message = normalize_message(text)
    act_decision = act or resolve_conversation_act(message)
    context_result = context or arbitrate_context(message, act_decision, ())
    return arbitrate_pending_workflow(
        message,
        act_decision,
        context_result,
        workflows,
        policy,
    )


def _real_chain(
    text: str,
    workflow: PendingWorkflowSnapshot,
) -> tuple[object, ConversationActDecision, PendingWorkflowDecision]:
    message = normalize_message(text)
    act = resolve_conversation_act(message)
    decision = arbitrate_pending_workflow(
        message,
        act,
        arbitrate_context(message, act, ()),
        (workflow,),
    )
    return message, act, decision


def _fresh_name_workflow() -> PendingWorkflowSnapshot:
    return _snapshot(
        PendingWorkflowKind.CONTACT_COLLECTION,
        expected=(ExpectedReplyKind.USER_NAME,),
    )


def _assert_explicit_name_reply_continues(text: str) -> None:
    workflow = _fresh_name_workflow()
    message, act, decision = _real_chain(text, workflow)
    assert message.normalized_text
    assert act.act is ConversationAct.UNKNOWN
    assert decision.action is PendingWorkflowAction.CONTINUE_PENDING_WORKFLOW
    assert decision.primary_reason is PendingWorkflowReason.EXPECTED_REPLY_MATCHED
    assert decision.matched_reply_kinds == (ExpectedReplyKind.USER_NAME,)
    assert decision.selected_workflow == workflow


def _assert_name_reply_not_matched(
    text: str,
    workflow: PendingWorkflowSnapshot | None = None,
) -> None:
    active = workflow or _fresh_name_workflow()
    _, _, decision = _real_chain(text, active)
    assert decision.action is PendingWorkflowAction.SUSPEND_PENDING_WORKFLOW
    assert decision.primary_reason is PendingWorkflowReason.EXPECTED_REPLY_NOT_MATCHED
    assert decision.matched_reply_kinds == ()
    assert decision.selected_workflow is None


def test_phase5_enums_are_exactly_closed():
    assert tuple(item.value for item in PendingWorkflowKind) == (
        "contact_collection",
        "child_age_collection",
        "affirmation_confirmation",
    )
    assert tuple(item.value for item in PendingWorkflowSource) == (
        "typed_pending_record",
        "recent_assistant_request",
        "legacy_state",
    )
    assert tuple(item.value for item in PendingWorkflowStatus) == (
        "active",
        "suspended",
        "completed",
        "cancelled",
    )
    assert tuple(item.value for item in ExpectedReplyKind) == (
        "user_name",
        "user_phone",
        "child_age",
        "affirmation",
    )
    assert tuple(item.value for item in PendingWorkflowAction) == (
        "continue_pending_workflow",
        "resume_pending_after_answer",
        "interrupt_with_current_request",
        "suspend_pending_workflow",
        "cancel_stale_workflow",
        "reject_malformed_workflow",
        "no_pending_workflow",
    )
    assert tuple(item.value for item in PendingWorkflowReason) == (
        "no_workflow_supplied",
        "no_active_workflow",
        "workflow_malformed",
        "workflow_stale",
        "conflicting_active_workflows",
        "expected_reply_matched",
        "resumable_program_question",
        "manager_contact_request_overrides_pending",
        "current_request_overrides_pending",
        "non_answer_act_suspends_pending",
        "expected_reply_not_matched",
    )


def test_phase5_contracts_are_frozen_slotted_hashable_and_deeply_immutable():
    snapshot = _snapshot()
    policy = PendingWorkflowPolicy()
    decision = _run("14 წლის", (snapshot,))
    assert hash(snapshot)
    assert not hasattr(snapshot, "__dict__")
    assert not hasattr(policy, "__dict__")
    assert not hasattr(decision, "__dict__")
    with pytest.raises(FrozenInstanceError):
        snapshot.turn_distance = 1  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        policy.child_age_minimum = 2  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        decision.action = PendingWorkflowAction.SUSPEND_PENDING_WORKFLOW  # type: ignore[misc]
    with pytest.raises(AttributeError):
        decision.evidence.append("changed")  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "constructor",
    [
        lambda: _snapshot(workflow_id=""),
        lambda: _snapshot(workflow_id=" wrapped "),
        lambda: _snapshot(owner_id=""),
        lambda: _snapshot(owner_id=" wrapped "),
        lambda: _snapshot(turn_distance=-1),
        lambda: _snapshot(turn_distance=True),
        lambda: _snapshot(turn_distance="1"),
        lambda: _snapshot(kind="child_age_collection"),
        lambda: _snapshot(source="legacy_state"),
        lambda: _snapshot(status="active"),
        lambda: _snapshot(program_id="summer_camp"),
        lambda: _snapshot(expected=[ExpectedReplyKind.CHILD_AGE]),
        lambda: _snapshot(expected=("child_age",)),
        lambda: _snapshot(
            expected=(
                ExpectedReplyKind.CHILD_AGE,
                ExpectedReplyKind.CHILD_AGE,
            )
        ),
        lambda: _snapshot(
            PendingWorkflowKind.CONTACT_COLLECTION,
            expected=(
                ExpectedReplyKind.USER_PHONE,
                ExpectedReplyKind.USER_NAME,
            ),
        ),
    ],
)
def test_snapshot_rejects_basic_type_and_order_corruption(constructor):
    with pytest.raises(PendingWorkflowError):
        constructor()


@pytest.mark.parametrize(
    "constructor",
    [
        lambda: PendingWorkflowPolicy(
            child_age_collection_max_turn_distance=-1
        ),
        lambda: PendingWorkflowPolicy(
            contact_collection_max_turn_distance=True
        ),
        lambda: PendingWorkflowPolicy(
            affirmation_confirmation_max_turn_distance="1"
        ),
        lambda: PendingWorkflowPolicy(child_age_minimum=0),
        lambda: PendingWorkflowPolicy(
            child_age_minimum=10, child_age_maximum=9
        ),
        lambda: PendingWorkflowPolicy(affirmation_phrases=[]),
        lambda: PendingWorkflowPolicy(affirmation_phrases=()),
        lambda: PendingWorkflowPolicy(
            affirmation_phrases=("კი", "კი")
        ),
        lambda: PendingWorkflowPolicy(manager_reference_terms=(" manager ",)),
    ],
)
def test_policy_rejects_mutable_invalid_or_unbounded_settings(constructor):
    with pytest.raises(PendingWorkflowError):
        constructor()


def test_function_signature_is_exactly_the_phase5_contract():
    assert tuple(inspect.signature(arbitrate_pending_workflow).parameters) == (
        "message",
        "conversation_act",
        "context_decision",
        "pending_workflows",
        "policy",
    )


def test_wrong_top_level_inputs_fail_loudly_with_phase5_error():
    message = normalize_message("14")
    act = resolve_conversation_act(message)
    context = _context_decision()
    snapshot = _snapshot()
    with pytest.raises(PendingWorkflowError, match="NormalizedMessage"):
        arbitrate_pending_workflow("14", act, context, (snapshot,))
    with pytest.raises(PendingWorkflowError, match="ConversationActDecision"):
        arbitrate_pending_workflow(message, ConversationAct.UNKNOWN, context, (snapshot,))
    with pytest.raises(PendingWorkflowError, match="ContextArbitrationDecision"):
        arbitrate_pending_workflow(message, act, ContextUse.BLOCKED, (snapshot,))
    with pytest.raises(PendingWorkflowError, match="immutable tuple"):
        arbitrate_pending_workflow(message, act, context, [snapshot])
    with pytest.raises(PendingWorkflowError, match="PendingWorkflowSnapshot"):
        arbitrate_pending_workflow(message, act, context, ({"pending": True},))
    with pytest.raises(PendingWorkflowError, match="PendingWorkflowPolicy"):
        arbitrate_pending_workflow(message, act, context, (snapshot,), {})


def test_repeated_arbitration_is_deterministic_and_does_not_mutate_inputs():
    message = normalize_message("14 წლის")
    act = resolve_conversation_act(message)
    context = _context_decision()
    workflows = (_snapshot(),)
    before = (message, act, context, workflows)
    first = arbitrate_pending_workflow(message, act, context, workflows)
    second = arbitrate_pending_workflow(message, act, context, workflows)
    assert first == second
    assert before == (message, act, context, workflows)


@pytest.mark.parametrize(
    "status",
    (
        PendingWorkflowStatus.SUSPENDED,
        PendingWorkflowStatus.COMPLETED,
        PendingWorkflowStatus.CANCELLED,
    ),
)
def test_inactive_workflows_never_consume_the_message(status):
    decision = _run("14 წლის", (_snapshot(status=status),))
    assert decision.action is PendingWorkflowAction.NO_PENDING_WORKFLOW
    assert decision.primary_reason is PendingWorkflowReason.NO_ACTIVE_WORKFLOW
    assert decision.selected_workflow is None
    assert len(decision.rejected_workflows) == 1


def test_empty_and_mixed_inactive_inputs_have_distinct_no_pending_reasons():
    empty = _run("14 წლის", ())
    inactive = _run(
        "14 წლის",
        (
            _snapshot(status=PendingWorkflowStatus.SUSPENDED),
            _snapshot(
                workflow_id="workflow.done",
                status=PendingWorkflowStatus.COMPLETED,
            ),
            _snapshot(
                workflow_id="workflow.cancelled",
                status=PendingWorkflowStatus.CANCELLED,
            ),
        ),
    )
    assert empty.primary_reason is PendingWorkflowReason.NO_WORKFLOW_SUPPLIED
    assert empty.rejected_workflows == ()
    assert inactive.primary_reason is PendingWorkflowReason.NO_ACTIVE_WORKFLOW
    assert len(inactive.rejected_workflows) == 3


@pytest.mark.parametrize(
    ("kind", "expected", "distance", "expected_action"),
    [
        (PendingWorkflowKind.CHILD_AGE_COLLECTION, ExpectedReplyKind.CHILD_AGE, 0, PendingWorkflowAction.CONTINUE_PENDING_WORKFLOW),
        (PendingWorkflowKind.CHILD_AGE_COLLECTION, ExpectedReplyKind.CHILD_AGE, 1, PendingWorkflowAction.CONTINUE_PENDING_WORKFLOW),
        (PendingWorkflowKind.CHILD_AGE_COLLECTION, ExpectedReplyKind.CHILD_AGE, 2, PendingWorkflowAction.CANCEL_STALE_WORKFLOW),
        (PendingWorkflowKind.CONTACT_COLLECTION, ExpectedReplyKind.USER_PHONE, 0, PendingWorkflowAction.CONTINUE_PENDING_WORKFLOW),
        (PendingWorkflowKind.CONTACT_COLLECTION, ExpectedReplyKind.USER_PHONE, 2, PendingWorkflowAction.CONTINUE_PENDING_WORKFLOW),
        (PendingWorkflowKind.CONTACT_COLLECTION, ExpectedReplyKind.USER_PHONE, 3, PendingWorkflowAction.CANCEL_STALE_WORKFLOW),
        (PendingWorkflowKind.AFFIRMATION_CONFIRMATION, ExpectedReplyKind.AFFIRMATION, 0, PendingWorkflowAction.CONTINUE_PENDING_WORKFLOW),
        (PendingWorkflowKind.AFFIRMATION_CONFIRMATION, ExpectedReplyKind.AFFIRMATION, 1, PendingWorkflowAction.CONTINUE_PENDING_WORKFLOW),
        (PendingWorkflowKind.AFFIRMATION_CONFIRMATION, ExpectedReplyKind.AFFIRMATION, 2, PendingWorkflowAction.CANCEL_STALE_WORKFLOW),
    ],
)
def test_exact_default_freshness_boundaries(
    kind,
    expected,
    distance,
    expected_action,
):
    text = {
        ExpectedReplyKind.CHILD_AGE: "14",
        ExpectedReplyKind.USER_PHONE: "595999733",
        ExpectedReplyKind.AFFIRMATION: "კი",
    }[expected]
    decision = _run(
        text,
        (_snapshot(kind, turn_distance=distance),),
    )
    assert decision.action is expected_action


def test_custom_policy_changes_only_the_explicit_freshness_boundary():
    policy = PendingWorkflowPolicy(
        child_age_collection_max_turn_distance=3
    )
    decision = _run(
        "14",
        (_snapshot(turn_distance=3),),
        policy=policy,
    )
    assert decision.action is PendingWorkflowAction.CONTINUE_PENDING_WORKFLOW


def test_fresh_workflow_remains_eligible_when_another_is_stale():
    fresh = _snapshot(workflow_id="workflow.fresh", turn_distance=0)
    stale = _snapshot(workflow_id="workflow.stale", turn_distance=2)
    decision = _run("14", (stale, fresh))
    assert decision.selected_workflow == fresh
    assert decision.eligible_workflows == (fresh,)
    assert decision.rejected_workflows == (stale,)


@pytest.mark.parametrize(
    "workflow",
    [
        _snapshot(expected=()),
        _snapshot(expected=(ExpectedReplyKind.USER_PHONE,)),
        _snapshot(expected=(ExpectedReplyKind.AFFIRMATION,)),
        _snapshot(
            PendingWorkflowKind.CONTACT_COLLECTION,
            expected=(ExpectedReplyKind.CHILD_AGE,),
        ),
        _snapshot(
            PendingWorkflowKind.CONTACT_COLLECTION,
            expected=(ExpectedReplyKind.AFFIRMATION,),
        ),
        _snapshot(
            PendingWorkflowKind.AFFIRMATION_CONFIRMATION,
            expected=(ExpectedReplyKind.USER_PHONE,),
        ),
        _snapshot(
            PendingWorkflowKind.AFFIRMATION_CONFIRMATION,
            expected=(ExpectedReplyKind.CHILD_AGE,),
        ),
    ],
)
def test_logically_malformed_active_workflows_fail_closed(workflow):
    decision = _run("14", (workflow,))
    assert decision.action is PendingWorkflowAction.REJECT_MALFORMED_WORKFLOW
    assert decision.primary_reason is PendingWorkflowReason.WORKFLOW_MALFORMED
    assert decision.selected_workflow is None
    assert decision.matched_reply_kinds == ()


@pytest.mark.parametrize(
    "changed",
    [
        _snapshot(owner_id="owner.other"),
        _snapshot(
            PendingWorkflowKind.CONTACT_COLLECTION,
            expected=(ExpectedReplyKind.USER_PHONE,),
        ),
        _snapshot(expected=(ExpectedReplyKind.USER_PHONE,)),
        _snapshot(status=PendingWorkflowStatus.SUSPENDED),
    ],
)
def test_same_workflow_id_with_conflicting_metadata_is_malformed(changed):
    decision = _run("14", (_snapshot(), changed))
    assert decision.action is PendingWorkflowAction.REJECT_MALFORMED_WORKFLOW
    assert decision.selected_workflow is None


def test_exact_duplicate_evidence_is_consolidated_without_changing_result():
    snapshot = _snapshot()
    single = _run("14", (snapshot,))
    duplicate = _run("14", (snapshot, snapshot, snapshot))
    assert duplicate == single
    assert duplicate.eligible_workflows == (snapshot,)


def test_multiple_fresh_workflows_conflict_without_arbitrary_selection():
    age = _snapshot(workflow_id="workflow.age", owner_id="owner.age")
    phone = _snapshot(
        PendingWorkflowKind.CONTACT_COLLECTION,
        workflow_id="workflow.phone",
        owner_id="owner.phone",
    )
    first = _run("14", (phone, age))
    second = _run("14", (age, phone))
    assert first == second
    assert first.action is PendingWorkflowAction.SUSPEND_PENDING_WORKFLOW
    assert first.primary_reason is PendingWorkflowReason.CONFLICTING_ACTIVE_WORKFLOWS
    assert first.selected_workflow is None
    assert first.eligible_workflows == (age, phone)


@pytest.mark.parametrize(
    "kind",
    tuple(PendingWorkflowKind),
)
@pytest.mark.parametrize(
    ("text", "act"),
    [
        ("მენეჯერს დამაკავშირეთ", ConversationAct.HUMAN_HANDOFF),
        ("დამირეკეთ", ConversationAct.CALLBACK_REQUEST),
        ("სხვა ოპერატორთან გადამაერთეთ", ConversationAct.HUMAN_HANDOFF),
        ("ხვალ დამიკავშირდით", ConversationAct.CALLBACK_REQUEST),
    ],
)
def test_typed_handoff_and_callback_always_override_pending(kind, text, act):
    decision = _run(text, (_snapshot(kind),), act=_act(act))
    assert decision.action is PendingWorkflowAction.INTERRUPT_WITH_CURRENT_REQUEST
    assert decision.primary_reason is PendingWorkflowReason.CURRENT_REQUEST_OVERRIDES_PENDING
    assert decision.selected_workflow is None
    assert decision.matched_reply_kinds == ()


@pytest.mark.parametrize("kind", tuple(PendingWorkflowKind))
def test_generic_program_question_resumes_one_fresh_pending_workflow(kind):
    workflow = _snapshot(kind)
    decision = _run(
        "ბანაკი რა ღირს?",
        (workflow,),
        act=_act(ConversationAct.PROGRAM_QUESTION),
    )
    assert decision.action is PendingWorkflowAction.RESUME_PENDING_AFTER_ANSWER
    assert decision.primary_reason is PendingWorkflowReason.RESUMABLE_PROGRAM_QUESTION
    assert decision.selected_workflow == workflow


@pytest.mark.parametrize(
    "text",
    [
        "მენეჯერის ნომერი მომწერეთ",
        "მენეჯერის საკონტაქტო მომეცით",
        "მენეჯერის ტელეფონი გამომიგზავნეთ",
        "მენეჯერის ნომერი შეგიძლიათ მომწეროთ?",
        "მენეჯერის კონტაქტი მომეცით",
        "მენეჯერის კონტაქტი გამომიგზავნეთ",
        "მენეჯერის კონტაქტს მომწერთ?",
    ],
)
def test_real_manager_contact_request_narrowly_overrides_pending(text):
    message = normalize_message(text)
    act = resolve_conversation_act(message)
    decision = arbitrate_pending_workflow(
        message,
        act,
        arbitrate_context(message, act, ()),
        (_snapshot(PendingWorkflowKind.CONTACT_COLLECTION),),
    )
    assert decision.action is PendingWorkflowAction.INTERRUPT_WITH_CURRENT_REQUEST
    assert decision.primary_reason is PendingWorkflowReason.MANAGER_CONTACT_REQUEST_OVERRIDES_PENDING


def test_exact_manager_number_anchor_keeps_current_phase3_program_question_result():
    message = normalize_message("მენეჯერის ნომერი მომწერეთ")
    assert resolve_conversation_act(message).act is ConversationAct.PROGRAM_QUESTION


def test_manager_contact_anchor_real_chain_interrupts_even_while_phase3_is_unknown():
    message = normalize_message("მენეჯერის კონტაქტი მომეცით")
    act = resolve_conversation_act(message)
    assert act.act is ConversationAct.UNKNOWN
    decision = arbitrate_pending_workflow(
        message,
        act,
        arbitrate_context(message, act, ()),
        (_snapshot(),),
    )
    assert decision.action is PendingWorkflowAction.INTERRUPT_WITH_CURRENT_REQUEST
    assert decision.primary_reason is PendingWorkflowReason.MANAGER_CONTACT_REQUEST_OVERRIDES_PENDING
    assert decision.selected_workflow is None
    assert decision.matched_reply_kinds == ()


@pytest.mark.parametrize(
    "text",
    (
        "მენეჯერს ჩემი ნომერი გადაეცით",
        "მენეჯერს ჩემი კონტაქტი მიეცით",
        "მენეჯერს დამარეკინეთ",
        "ჩემი ნომერია 595999733",
    ),
)
def test_manager_contact_guard_rejects_user_owned_contact_false_positives(text):
    message = normalize_message(text)
    act = resolve_conversation_act(message)
    decision = arbitrate_pending_workflow(
        message,
        act,
        arbitrate_context(message, act, ()),
        (_snapshot(),),
    )
    assert decision.action is PendingWorkflowAction.SUSPEND_PENDING_WORKFLOW
    assert decision.primary_reason is PendingWorkflowReason.EXPECTED_REPLY_NOT_MATCHED
    assert decision.selected_workflow is None
    assert decision.matched_reply_kinds == ()


def test_manager_reference_plus_user_owned_number_is_not_manager_contact_request():
    decision = _run(
        "მენეჯერს ჩემი ნომერი გადაეცით",
        (_snapshot(PendingWorkflowKind.CONTACT_COLLECTION),),
        act=_act(ConversationAct.PROGRAM_QUESTION),
    )
    assert decision.action is PendingWorkflowAction.RESUME_PENDING_AFTER_ANSWER
    assert decision.primary_reason is PendingWorkflowReason.RESUMABLE_PROGRAM_QUESTION


def test_e1_helper_built_program_question_resumes_pending_age_after_answer():
    workflow = _snapshot()
    decision = _run(
        "კიდევ არის ადგილი?",
        (workflow,),
        act=_act(ConversationAct.PROGRAM_QUESTION),
    )
    assert decision.action is PendingWorkflowAction.RESUME_PENDING_AFTER_ANSWER
    assert decision.primary_reason is PendingWorkflowReason.RESUMABLE_PROGRAM_QUESTION
    assert decision.selected_workflow == workflow


def test_e1_real_phase2_phase3_phase5_chain_documents_elliptical_seam():
    message = normalize_message("კიდევ არის ადგილი?")
    act = resolve_conversation_act(message)
    assert act.act is ConversationAct.UNKNOWN
    context = arbitrate_context(message, act, ())
    decision = arbitrate_pending_workflow(
        message,
        act,
        context,
        (_snapshot(),),
    )
    # TODO(Phase 3 elliptical seam):
    # „კიდევ არის ადგილი?“ currently resolves to UNKNOWN. This test
    # intentionally documents today's real chained behavior. When the Phase 3
    # elliptical-seam patch classifies it as PROGRAM_QUESTION, update this
    # assertion together with that seam integration.
    assert decision.action is PendingWorkflowAction.SUSPEND_PENDING_WORKFLOW
    assert decision.primary_reason is PendingWorkflowReason.EXPECTED_REPLY_NOT_MATCHED


@pytest.mark.parametrize(
    ("text", "expected_act"),
    [
        ("რას გულისხმობთ?", ConversationAct.CLARIFICATION),
        ("არასწორ ინფორმაციას მწერ", ConversationAct.CORRECTION),
        ("საერთოდ არ მეხმარებით", ConversationAct.COMPLAINT),
        ("ვერ ხარ", ConversationAct.NEGATIVE_FEEDBACK),
        ("დებილი ხარ", ConversationAct.INSULT),
        ("გამარჯობა", ConversationAct.GREETING),
        ("მადლობა", ConversationAct.THANKS),
        ("დღეს ამინდი როგორია?", ConversationAct.UNRELATED),
    ],
)
@pytest.mark.parametrize(
    "kind",
    (
        PendingWorkflowKind.CHILD_AGE_COLLECTION,
        PendingWorkflowKind.CONTACT_COLLECTION,
        PendingWorkflowKind.AFFIRMATION_CONFIRMATION,
    ),
)
def test_non_answer_acts_suspend_representative_pending_workflows(
    text,
    expected_act,
    kind,
):
    message = normalize_message(text)
    act = resolve_conversation_act(message)
    assert act.act is expected_act
    decision = arbitrate_pending_workflow(
        message,
        act,
        arbitrate_context(message, act, ()),
        (_snapshot(kind),),
    )
    assert decision.action is PendingWorkflowAction.SUSPEND_PENDING_WORKFLOW
    assert decision.primary_reason is PendingWorkflowReason.NON_ANSWER_ACT_SUSPENDS_PENDING
    assert decision.matched_reply_kinds == ()


@pytest.mark.parametrize("text", ["14", "14 წლის", "14 წლისაა", "1", "17"])
def test_fresh_age_workflow_consumes_only_bounded_child_age_shapes(text):
    decision = _run(text, (_snapshot(),))
    assert decision.action is PendingWorkflowAction.CONTINUE_PENDING_WORKFLOW
    assert decision.matched_reply_kinds == (ExpectedReplyKind.CHILD_AGE,)


@pytest.mark.parametrize(
    "text",
    ["0", "18", "30 წლის ვარ", "9-17", "17:00", "2026", "22 მაისს", "595999733"],
)
def test_age_workflow_rejects_non_age_or_out_of_bounds_numeric_shapes(text):
    decision = _run(text, (_snapshot(),), act=_act(ConversationAct.UNKNOWN))
    assert decision.action is PendingWorkflowAction.SUSPEND_PENDING_WORKFLOW
    assert decision.primary_reason is PendingWorkflowReason.EXPECTED_REPLY_NOT_MATCHED


def test_blocked_program_context_does_not_block_fresh_owned_age_reply():
    context = _context_decision(ContextUse.BLOCKED)
    decision = _run("14 წლის", (_snapshot(),), context=context)
    assert decision.action is PendingWorkflowAction.CONTINUE_PENDING_WORKFLOW
    assert context.context_use is ContextUse.BLOCKED


def test_phone_and_affirmation_workflows_do_not_consume_child_age():
    phone = _run(
        "14 წლის",
        (_snapshot(PendingWorkflowKind.CONTACT_COLLECTION),),
    )
    affirmation = _run(
        "14 წლის",
        (_snapshot(PendingWorkflowKind.AFFIRMATION_CONFIRMATION),),
    )
    assert phone.action is PendingWorkflowAction.SUSPEND_PENDING_WORKFLOW
    assert affirmation.action is PendingWorkflowAction.SUSPEND_PENDING_WORKFLOW


@pytest.mark.parametrize(
    "text",
    [
        "595999733",
        "595 999 733",
        "595-999-733",
        "+995 595 999 733",
        "+995-595-999-733",
    ],
)
def test_phone_workflow_consumes_only_conservative_georgian_mobile_shapes(text):
    decision = _run(
        text,
        (_snapshot(PendingWorkflowKind.CONTACT_COLLECTION),),
    )
    assert decision.action is PendingWorkflowAction.CONTINUE_PENDING_WORKFLOW
    assert decision.matched_reply_kinds == (ExpectedReplyKind.USER_PHONE,)


@pytest.mark.parametrize(
    "text",
    ["14", "14 წლის", "17:00", "9-17", "2026", "595 999 733 14", "12345"],
)
def test_phone_workflow_rejects_ambiguous_or_non_mobile_numeric_shapes(text):
    decision = _run(
        text,
        (_snapshot(PendingWorkflowKind.CONTACT_COLLECTION),),
        act=_act(ConversationAct.UNKNOWN),
    )
    assert decision.action is PendingWorkflowAction.SUSPEND_PENDING_WORKFLOW
    assert decision.matched_reply_kinds == ()


def test_callback_request_with_digits_interrupts_instead_of_matching_phone():
    decision = _run(
        "დამირეკეთ 595999733",
        (_snapshot(PendingWorkflowKind.CONTACT_COLLECTION),),
    )
    assert decision.action is PendingWorkflowAction.INTERRUPT_WITH_CURRENT_REQUEST
    assert decision.primary_reason is PendingWorkflowReason.CURRENT_REQUEST_OVERRIDES_PENDING
    assert decision.matched_reply_kinds == ()


@pytest.mark.parametrize(
    "text",
    (
        "მე ვარ ნიკოლოზი",
        "მე ნიკოლოზი ვარ",
        "ნიკოლოზი ვარ",
        "ჩემი სახელია ნიკოლოზი",
        "მე ვარ Nika",
        "Nika ვარ",
        "ჩემი სახელია Nika",
        "მე ვარ ნიკოლოზი.",
        "ჩემი სახელია ნიკოლოზი.",
        "ნიკოლოზი ვარ.",
        "მე ვარ ნიკა ბერიძე",
        "ნიკა ბერიძე ვარ",
        "ჩემი სახელია ნიკა ბერიძე",
    ),
)
def test_name_workflow_real_chain_accepts_only_explicit_self_identification(text):
    _assert_explicit_name_reply_continues(text)


@pytest.mark.parametrize("text", ("ნიკოლოზი", "Nika", "ნიკა ბერიძე"))
def test_name_workflow_real_chain_rejects_bare_name_like_tokens(text):
    message, act, decision = _real_chain(text, _fresh_name_workflow())
    assert message.normalized_text == text
    assert act.act is ConversationAct.UNKNOWN
    assert decision.action is PendingWorkflowAction.SUSPEND_PENDING_WORKFLOW
    assert decision.primary_reason is PendingWorkflowReason.EXPECTED_REPLY_NOT_MATCHED
    assert decision.matched_reply_kinds == ()
    assert decision.selected_workflow is None


@pytest.mark.parametrize(
    "text",
    (
        "ტრანსპორტი",
        "ლოკაცია",
        "ხანგრძლივობა",
        "ხელმისაწვდომობა",
        "სკოლა",
        "მასწავლებელი",
        "მონაწილეობა",
        "დეტალები",
        "ფასები",
        "რეგისტრაციაზე",
        "მისამართზე",
        "კონტაქტზე",
        "ნომერს",
        "ექსკურსია",
        "კვება",
        "საცხოვრებელი",
        "გადახდა",
        "განვადება",
        "შეხვედრა",
        "პროგრამები",
        "ასაკები",
        "ბავშვები",
        "თარიღები",
    ),
)
def test_name_workflow_real_chain_rejects_high_risk_unknown_tokens(text):
    message = normalize_message(text)
    act = resolve_conversation_act(message)
    assert act.act is ConversationAct.UNKNOWN
    decision = arbitrate_pending_workflow(
        message,
        act,
        arbitrate_context(message, act, ()),
        (
            _snapshot(
                PendingWorkflowKind.CONTACT_COLLECTION,
                expected=(ExpectedReplyKind.USER_NAME,),
            ),
        ),
    )
    assert decision.action is PendingWorkflowAction.SUSPEND_PENDING_WORKFLOW
    assert decision.primary_reason is PendingWorkflowReason.EXPECTED_REPLY_NOT_MATCHED
    assert decision.matched_reply_kinds == ()
    assert decision.selected_workflow is None


@pytest.mark.parametrize(
    "text",
    (
        "როგორ",
        "რამდენი",
        "რატომ",
        "რეგისტრაცია",
        "მისამართი",
        "დღეს",
        "ხვალ",
        "ჯერ",
        "არა",
        "მინდა",
    ),
)
def test_name_workflow_direct_matcher_rejects_bare_alphabetic_shape(text):
    workflow = _snapshot(
        PendingWorkflowKind.CONTACT_COLLECTION,
        expected=(ExpectedReplyKind.USER_NAME,),
    )
    decision = _run(text, (workflow,), act=_act(ConversationAct.UNKNOWN))
    assert decision.action is PendingWorkflowAction.SUSPEND_PENDING_WORKFLOW
    assert decision.primary_reason is PendingWorkflowReason.EXPECTED_REPLY_NOT_MATCHED
    assert decision.matched_reply_kinds == ()
    assert decision.selected_workflow is None


@pytest.mark.parametrize(
    "text",
    (
        "მე ვარ",
        "ჩემი სახელია",
        "ვარ",
        "მე ვარ 14",
        "მე ვარ 14 წლის",
        "მე ვარ 595999733",
        "მე ვარ +995 595 999 733",
        "ჩემი სახელია 2026",
        "მე ვარ ???",
        "მე ვარ ნიკა?",
        "მე ვარ ნიკა და ფასი მაინტერესებს",
        "ჩემი სახელია ნიკა. ფასი რა არის?",
        "ნიკა ვარ და ბანაკი მაინტერესებს",
        "მე ვარ https://example.com",
        "მე ვარ @nika",
    ),
)
def test_name_workflow_real_chain_rejects_malformed_explicit_replies(text):
    _assert_name_reply_not_matched(text)


@pytest.mark.parametrize(
    "workflow",
    (
        _snapshot(PendingWorkflowKind.CONTACT_COLLECTION),
        _snapshot(PendingWorkflowKind.CHILD_AGE_COLLECTION),
        _snapshot(PendingWorkflowKind.AFFIRMATION_CONFIRMATION),
    ),
)
def test_explicit_self_identification_only_matches_user_name_workflow(workflow):
    _assert_name_reply_not_matched("მე ვარ ნიკოლოზი", workflow)


@pytest.mark.parametrize(
    "text",
    ("595999733", "14", "14 წლის", "კი მინდა"),
)
def test_name_workflow_rejects_other_expected_reply_shapes(text):
    _assert_name_reply_not_matched(text)


@pytest.mark.parametrize(
    "text",
    [
        "მადლობა",
        "დამირეკეთ",
        "მენეჯერს დამაკავშირეთ",
        "მენეჯერის ნომერი მომწერეთ",
        "არასწორ ინფორმაციას მწერ",
        "14",
        "595999733",
        "???",
        "კი",
        "მინდა",
    ],
)
def test_name_workflow_fails_closed_on_actions_numbers_and_non_names(text):
    workflow = _snapshot(
        PendingWorkflowKind.CONTACT_COLLECTION,
        expected=(ExpectedReplyKind.USER_NAME,),
    )
    decision = _run(text, (workflow,))
    assert decision.action is not PendingWorkflowAction.CONTINUE_PENDING_WORKFLOW
    assert decision.matched_reply_kinds == ()


@pytest.mark.parametrize(
    "text",
    [
        "კი",
        "დიახ",
        "ჰო",
        "ხო",
        "კი მინდა",
        "კი, მინდა",
        "დიახ მინდა",
        "რა თქმა უნდა",
        "კი გთხოვთ",
    ],
)
def test_e2_exact_policy_affirmations_continue_only_affirmation_workflow(text):
    workflow = _snapshot(PendingWorkflowKind.AFFIRMATION_CONFIRMATION)
    decision = _run(text, (workflow,))
    assert decision.action is PendingWorkflowAction.CONTINUE_PENDING_WORKFLOW
    assert decision.primary_reason is PendingWorkflowReason.EXPECTED_REPLY_MATCHED
    assert decision.matched_reply_kinds == (ExpectedReplyKind.AFFIRMATION,)


def test_e2_real_phase3_result_for_ki_minda_is_unknown_then_phase5_continues():
    message = normalize_message("კი მინდა")
    act = resolve_conversation_act(message)
    assert act.act is ConversationAct.UNKNOWN
    decision = arbitrate_pending_workflow(
        message,
        act,
        arbitrate_context(message, act, ()),
        (_snapshot(PendingWorkflowKind.AFFIRMATION_CONFIRMATION),),
    )
    assert decision.action is PendingWorkflowAction.CONTINUE_PENDING_WORKFLOW


@pytest.mark.parametrize(
    "text",
    ["მინდა", "არ მინდა", "არა", "ჯერ არა", "მოგვიანებით"],
)
def test_e2_negative_or_ambiguous_phrases_do_not_match_affirmation(text):
    decision = _run(
        text,
        (_snapshot(PendingWorkflowKind.AFFIRMATION_CONFIRMATION),),
        act=_act(ConversationAct.UNKNOWN),
    )
    assert decision.action is PendingWorkflowAction.SUSPEND_PENDING_WORKFLOW
    assert decision.primary_reason is PendingWorkflowReason.EXPECTED_REPLY_NOT_MATCHED


@pytest.mark.parametrize(
    "kind",
    (
        PendingWorkflowKind.CONTACT_COLLECTION,
        PendingWorkflowKind.CHILD_AGE_COLLECTION,
    ),
)
def test_affirmation_is_not_evaluated_for_an_unrelated_expected_reply(kind):
    decision = _run("კი მინდა", (_snapshot(kind),))
    assert decision.action is PendingWorkflowAction.SUSPEND_PENDING_WORKFLOW
    assert decision.matched_reply_kinds == ()


def test_affirmation_stale_no_pending_and_conflicting_guards_precede_matching():
    stale = _run(
        "კი",
        (_snapshot(PendingWorkflowKind.AFFIRMATION_CONFIRMATION, turn_distance=2),),
    )
    none = _run("კი", ())
    conflict = _run(
        "კი",
        (
            _snapshot(PendingWorkflowKind.AFFIRMATION_CONFIRMATION),
            _snapshot(
                PendingWorkflowKind.AFFIRMATION_CONFIRMATION,
                workflow_id="workflow.other",
                owner_id="owner.other",
            ),
        ),
    )
    assert stale.action is PendingWorkflowAction.CANCEL_STALE_WORKFLOW
    assert none.action is PendingWorkflowAction.NO_PENDING_WORKFLOW
    assert conflict.primary_reason is PendingWorkflowReason.CONFLICTING_ACTIVE_WORKFLOWS


@pytest.mark.parametrize("text", ["", "...", "ჰმ", "უცნობი ფრაგმენტი"])
def test_unknown_without_expected_shape_suspends_fail_closed(text):
    decision = _run(
        text,
        (_snapshot(),),
        act=_act(ConversationAct.UNKNOWN),
    )
    assert decision.action is PendingWorkflowAction.SUSPEND_PENDING_WORKFLOW
    assert decision.primary_reason is PendingWorkflowReason.EXPECTED_REPLY_NOT_MATCHED


@pytest.mark.parametrize("context_use", tuple(ContextUse))
def test_program_question_resume_behavior_is_identical_for_every_context_use(context_use):
    workflow = _snapshot()
    context = _context_decision(context_use)
    decision = _run(
        "ბანაკი რა ღირს?",
        (workflow,),
        act=_act(ConversationAct.PROGRAM_QUESTION),
        context=context,
    )
    assert decision.action is PendingWorkflowAction.RESUME_PENDING_AFTER_ANSWER
    assert decision.selected_workflow == workflow
    assert context.context_use is context_use


@pytest.mark.parametrize("context_use", tuple(ContextUse))
def test_manager_contact_interruption_is_identical_for_every_context_use(context_use):
    decision = _run(
        "მენეჯერის ნომერი მომწერეთ",
        (_snapshot(),),
        act=_act(ConversationAct.PROGRAM_QUESTION),
        context=_context_decision(context_use),
    )
    assert decision.primary_reason is PendingWorkflowReason.MANAGER_CONTACT_REQUEST_OVERRIDES_PENDING


def test_context_program_and_snapshot_program_metadata_are_not_reconciled():
    workflow = _snapshot(program_id=ProgramId.SUNDAY_SCHOOL)
    context = _context_decision(ContextUse.PRIOR_CONTEXT_SELECTED)
    before = context
    decision = _run("14", (workflow,), context=context)
    assert decision.selected_workflow == workflow
    assert decision.selected_workflow.program_id is ProgramId.SUNDAY_SCHOOL
    assert context == before
    assert context.selected_program_id is ProgramId.SUMMER_CAMP


def _decision_kwargs() -> dict[str, object]:
    workflow = _snapshot()
    return {
        "action": PendingWorkflowAction.CONTINUE_PENDING_WORKFLOW,
        "selected_workflow": workflow,
        "eligible_workflows": (workflow,),
        "rejected_workflows": (),
        "matched_reply_kinds": (ExpectedReplyKind.CHILD_AGE,),
        "confidence": 0.99,
        "primary_reason": PendingWorkflowReason.EXPECTED_REPLY_MATCHED,
        "evidence": ("reply.matched.child_age",),
    }


@pytest.mark.parametrize(
    ("kind", "expected", "matched"),
    (
        (
            PendingWorkflowKind.CHILD_AGE_COLLECTION,
            ExpectedReplyKind.CHILD_AGE,
            ExpectedReplyKind.CHILD_AGE,
        ),
        (
            PendingWorkflowKind.CONTACT_COLLECTION,
            ExpectedReplyKind.USER_PHONE,
            ExpectedReplyKind.USER_PHONE,
        ),
        (
            PendingWorkflowKind.CONTACT_COLLECTION,
            ExpectedReplyKind.USER_NAME,
            ExpectedReplyKind.USER_NAME,
        ),
        (
            PendingWorkflowKind.AFFIRMATION_CONFIRMATION,
            ExpectedReplyKind.AFFIRMATION,
            ExpectedReplyKind.AFFIRMATION,
        ),
    ),
)
def test_decision_accepts_valid_expected_reply_continuations(
    kind,
    expected,
    matched,
):
    workflow = _snapshot(kind, expected=(expected,))
    decision = PendingWorkflowDecision(
        action=PendingWorkflowAction.CONTINUE_PENDING_WORKFLOW,
        selected_workflow=workflow,
        eligible_workflows=(workflow,),
        rejected_workflows=(),
        matched_reply_kinds=(matched,),
        confidence=0.99,
        primary_reason=PendingWorkflowReason.EXPECTED_REPLY_MATCHED,
        evidence=(f"reply.matched.{matched.value}",),
    )
    assert decision.selected_workflow == workflow


def test_decision_accepts_valid_program_question_resume():
    workflow = _snapshot()
    decision = PendingWorkflowDecision(
        action=PendingWorkflowAction.RESUME_PENDING_AFTER_ANSWER,
        selected_workflow=workflow,
        eligible_workflows=(workflow,),
        rejected_workflows=(),
        matched_reply_kinds=(),
        confidence=0.98,
        primary_reason=PendingWorkflowReason.RESUMABLE_PROGRAM_QUESTION,
        evidence=("request.program_question",),
    )
    assert decision.selected_workflow == workflow


@pytest.mark.parametrize(
    ("kind", "expected", "matched"),
    (
        (
            PendingWorkflowKind.CHILD_AGE_COLLECTION,
            ExpectedReplyKind.CHILD_AGE,
            ExpectedReplyKind.USER_PHONE,
        ),
        (
            PendingWorkflowKind.CONTACT_COLLECTION,
            ExpectedReplyKind.USER_PHONE,
            ExpectedReplyKind.CHILD_AGE,
        ),
        (
            PendingWorkflowKind.CONTACT_COLLECTION,
            ExpectedReplyKind.USER_NAME,
            ExpectedReplyKind.AFFIRMATION,
        ),
        (
            PendingWorkflowKind.AFFIRMATION_CONFIRMATION,
            ExpectedReplyKind.AFFIRMATION,
            ExpectedReplyKind.USER_NAME,
        ),
    ),
)
def test_decision_rejects_matched_reply_not_expected_by_selected_workflow(
    kind,
    expected,
    matched,
):
    workflow = _snapshot(kind, expected=(expected,))
    with pytest.raises(PendingWorkflowError, match="must be expected"):
        PendingWorkflowDecision(
            action=PendingWorkflowAction.CONTINUE_PENDING_WORKFLOW,
            selected_workflow=workflow,
            eligible_workflows=(workflow,),
            rejected_workflows=(),
            matched_reply_kinds=(matched,),
            confidence=0.99,
            primary_reason=PendingWorkflowReason.EXPECTED_REPLY_MATCHED,
            evidence=("reply.mismatched_kind",),
        )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda values: values.update(action="continue_pending_workflow"),
        lambda values: values.update(selected_workflow=None),
        lambda values: values.update(eligible_workflows=[]),
        lambda values: values.update(rejected_workflows=[]),
        lambda values: values.update(matched_reply_kinds=[]),
        lambda values: values.update(confidence=True),
        lambda values: values.update(confidence=1.1),
        lambda values: values.update(primary_reason="expected_reply_matched"),
        lambda values: values.update(evidence=[]),
        lambda values: values.update(evidence=("duplicate", "duplicate")),
    ],
)
def test_decision_rejects_mutable_or_invalid_field_contracts(mutate):
    values = _decision_kwargs()
    mutate(values)
    with pytest.raises(PendingWorkflowError):
        PendingWorkflowDecision(**values)


def test_decision_rejects_selection_overlap_and_matched_reply_inconsistency():
    values = _decision_kwargs()
    workflow = values["selected_workflow"]
    values["rejected_workflows"] = (workflow,)
    with pytest.raises(PendingWorkflowError, match="both eligible and rejected"):
        PendingWorkflowDecision(**values)

    values = _decision_kwargs()
    values["action"] = PendingWorkflowAction.SUSPEND_PENDING_WORKFLOW
    values["selected_workflow"] = None
    with pytest.raises(PendingWorkflowError, match="matched replies"):
        PendingWorkflowDecision(**values)


def test_decision_rejects_selected_workflow_outside_eligible_tuple():
    values = _decision_kwargs()
    values["eligible_workflows"] = (
        _snapshot(workflow_id="workflow.other"),
    )
    with pytest.raises(PendingWorkflowError, match="must be eligible"):
        PendingWorkflowDecision(**values)


def test_decision_rejects_continue_without_matched_reply():
    values = _decision_kwargs()
    values["matched_reply_kinds"] = ()
    with pytest.raises(PendingWorkflowError, match="requires a matched reply"):
        PendingWorkflowDecision(**values)


def test_decision_rejects_continue_without_selected_workflow():
    values = _decision_kwargs()
    values["selected_workflow"] = None
    with pytest.raises(PendingWorkflowError, match="does not match"):
        PendingWorkflowDecision(**values)


def test_decision_rejects_continue_with_multiple_eligible_workflows():
    values = _decision_kwargs()
    selected = values["selected_workflow"]
    other = _snapshot(workflow_id="workflow.secondary")
    values["eligible_workflows"] = (selected, other)
    with pytest.raises(PendingWorkflowError, match="exactly one eligible"):
        PendingWorkflowDecision(**values)


def test_decision_rejects_continue_with_wrong_primary_reason():
    values = _decision_kwargs()
    values["primary_reason"] = PendingWorkflowReason.RESUMABLE_PROGRAM_QUESTION
    with pytest.raises(PendingWorkflowError, match="expected_reply_matched"):
        PendingWorkflowDecision(**values)


def test_decision_rejects_resume_with_matched_reply():
    values = _decision_kwargs()
    values["action"] = PendingWorkflowAction.RESUME_PENDING_AFTER_ANSWER
    values["primary_reason"] = PendingWorkflowReason.RESUMABLE_PROGRAM_QUESTION
    with pytest.raises(PendingWorkflowError, match="cannot contain matched replies"):
        PendingWorkflowDecision(**values)


def test_decision_rejects_resume_with_wrong_primary_reason():
    values = _decision_kwargs()
    values["action"] = PendingWorkflowAction.RESUME_PENDING_AFTER_ANSWER
    values["matched_reply_kinds"] = ()
    with pytest.raises(PendingWorkflowError, match="resumable_program_question"):
        PendingWorkflowDecision(**values)


def test_decision_rejects_non_selection_action_with_selected_workflow():
    values = _decision_kwargs()
    values["action"] = PendingWorkflowAction.INTERRUPT_WITH_CURRENT_REQUEST
    values["matched_reply_kinds"] = ()
    values["primary_reason"] = PendingWorkflowReason.CURRENT_REQUEST_OVERRIDES_PENDING
    with pytest.raises(PendingWorkflowError, match="does not match"):
        PendingWorkflowDecision(**values)


def test_decision_rejects_non_selection_action_with_matched_reply():
    values = _decision_kwargs()
    values["action"] = PendingWorkflowAction.SUSPEND_PENDING_WORKFLOW
    values["selected_workflow"] = None
    values["primary_reason"] = PendingWorkflowReason.EXPECTED_REPLY_NOT_MATCHED
    with pytest.raises(PendingWorkflowError, match="cannot contain matched replies"):
        PendingWorkflowDecision(**values)


def test_decision_rejects_nondeterministic_workflow_tuple_order():
    first = _snapshot(workflow_id="workflow.a")
    second = _snapshot(workflow_id="workflow.b")
    values = _decision_kwargs()
    values["selected_workflow"] = first
    values["eligible_workflows"] = (second, first)
    with pytest.raises(PendingWorkflowError, match="deterministically ordered"):
        PendingWorkflowDecision(**values)


def test_decision_evidence_and_repr_do_not_expose_current_reply_pii():
    phone = "595 999 733"
    private_name = "PrivateNameSentinel"
    decision = _run(
        phone,
        (_snapshot(PendingWorkflowKind.CONTACT_COLLECTION),),
    )
    serialized = repr(decision)
    for forbidden in (phone, "595", private_name, "+995"):
        assert forbidden not in serialized
    assert decision.evidence == ("reply.matched.user_phone",)


def test_default_policy_owns_the_exact_bounded_affirmation_lexicon():
    assert DEFAULT_PENDING_WORKFLOW_POLICY.affirmation_phrases == (
        "კი",
        "დიახ",
        "ჰო",
        "ხო",
        "კი მინდა",
        "კი, მინდა",
        "დიახ მინდა",
        "რა თქმა უნდა",
        "კი გთხოვთ",
    )


def test_default_policy_no_longer_exposes_non_name_reply_blacklist():
    assert "non_name_reply_tokens" not in PendingWorkflowPolicy.__dataclass_fields__
    assert not hasattr(DEFAULT_PENDING_WORKFLOW_POLICY, "non_name_reply_tokens")


def test_default_policy_owns_manager_contact_terms():
    assert "კონტაქტ" in DEFAULT_PENDING_WORKFLOW_POLICY.manager_contact_stems


def test_phase5_module_imports_only_standard_library_and_local_models():
    path = DOMAIN_DIR / "pending_workflow.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    assert set(imported) <= {"__future__", "re", "models"}


def test_phase5_source_has_no_bare_alphabetic_name_fallback_or_blacklist():
    import app.domain.decision.pending_workflow as pending_workflow

    source = (DOMAIN_DIR / "pending_workflow.py").read_text(encoding="utf-8")
    matcher_source = inspect.getsource(pending_workflow._matches_user_name)
    assert "non_name_reply_tokens" not in source
    assert "_GEORGIAN_OR_LATIN_NAME_RE" not in source
    assert "not in policy" not in matcher_source
    assert "fullmatch" not in matcher_source
    assert "_extract_explicit_name_candidate" in matcher_source
    assert "_has_bounded_name_candidate_shape" in matcher_source


def test_phase5_source_has_no_runtime_state_service_or_external_io_dependency():
    source = (DOMAIN_DIR / "pending_workflow.py").read_text(encoding="utf-8")
    forbidden = (
        "app.flows",
        "app.services",
        "app.models",
        "app.agent",
        "app.reasoning",
        "redis",
        "requests",
        "httpx",
        "openai",
        "anthropic",
        "google",
        "smtplib",
        "datetime",
        "Conversation(",
        "pending_booking",
        "ASK_AGE",
        "approved_copy",
        "notification",
        "calendar",
        "os.environ",
        "getenv",
    )
    assert not any(item in source for item in forbidden)


def test_phase5_does_not_modify_or_import_phase3_or_phase4_resolvers():
    act_source = (DOMAIN_DIR / "conversation_act.py").read_text(encoding="utf-8")
    context_source = (DOMAIN_DIR / "context_arbiter.py").read_text(encoding="utf-8")
    assert "PendingWorkflow" not in act_source
    assert "PendingWorkflow" not in context_source
    assert "arbitrate_pending_workflow" not in act_source
    assert "arbitrate_pending_workflow" not in context_source


def test_public_package_exports_every_phase5_contract():
    import app.domain.decision as decision

    expected = (
        "PendingWorkflowError",
        "PendingWorkflowKind",
        "PendingWorkflowSource",
        "PendingWorkflowStatus",
        "ExpectedReplyKind",
        "PendingWorkflowAction",
        "PendingWorkflowReason",
        "PendingWorkflowSnapshot",
        "PendingWorkflowPolicy",
        "PendingWorkflowDecision",
        "DEFAULT_PENDING_WORKFLOW_POLICY",
        "arbitrate_pending_workflow",
    )
    assert all(hasattr(decision, name) for name in expected)
    assert all(name in decision.__all__ for name in expected)


def test_decision_package_import_and_phase5_call_are_side_effect_free_without_environment():
    command = (
        "import sys; "
        "import app.domain.decision as d; "
        "m=d.normalize_message('14'); "
        "a=d.resolve_conversation_act(m); "
        "c=d.arbitrate_context(m,a,()); "
        "w=d.PendingWorkflowSnapshot('w','o',d.PendingWorkflowKind.CHILD_AGE_COLLECTION,"
        "d.PendingWorkflowSource.LEGACY_STATE,d.PendingWorkflowStatus.ACTIVE,"
        "(d.ExpectedReplyKind.CHILD_AGE,),0,d.ProgramId.SUMMER_CAMP); "
        "r=d.arbitrate_pending_workflow(m,a,c,(w,)); "
        "assert r.action is d.PendingWorkflowAction.CONTINUE_PENDING_WORKFLOW; "
        "assert not any(name.startswith(('app.services','app.flows','app.agent')) "
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
