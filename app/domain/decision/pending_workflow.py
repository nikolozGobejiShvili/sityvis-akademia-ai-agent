"""Pure arbitration of pending-workflow relevance for one inbound turn."""
from __future__ import annotations

import re

from .models import (
    ContextArbitrationDecision,
    ConversationAct,
    ConversationActDecision,
    ExpectedReplyKind,
    NormalizedMessage,
    PendingWorkflowAction,
    PendingWorkflowDecision,
    PendingWorkflowError,
    PendingWorkflowKind,
    PendingWorkflowPolicy,
    PendingWorkflowReason,
    PendingWorkflowSnapshot,
    PendingWorkflowStatus,
)


DEFAULT_PENDING_WORKFLOW_POLICY = PendingWorkflowPolicy()

_NON_ANSWER_ACTS = frozenset(
    (
        ConversationAct.CLARIFICATION,
        ConversationAct.CORRECTION,
        ConversationAct.COMPLAINT,
        ConversationAct.NEGATIVE_FEEDBACK,
        ConversationAct.INSULT,
        ConversationAct.GREETING,
        ConversationAct.THANKS,
        ConversationAct.UNRELATED,
    )
)
_EXPECTED_REPLY_ORDER = {
    item: index for index, item in enumerate(ExpectedReplyKind)
}
_LOCAL_PHONE_RE = re.compile(r"5\d{2}[ -]?\d{3}[ -]?\d{3}")
_INTERNATIONAL_PHONE_RE = re.compile(
    r"\+995[ -]?5\d{2}[ -]?\d{3}[ -]?\d{3}"
)
_CHILD_AGE_RE = re.compile(r"(\d{1,2})(?: წლის(?:აა)?)?")
_GEORGIAN_OR_LATIN_NAME_RE = re.compile(r"(?:[ა-ჰ]+|[A-Za-z]+)")
_NON_NAME_WORDS = frozenset(
    (
        "კი",
        "დიახ",
        "ჰო",
        "ხო",
        "მინდა",
        "არა",
        "მადლობა",
        "გმადლობთ",
        "გმადლობ",
        "გამარჯობა",
        "სალამი",
        "დამირეკეთ",
        "გადმომირეკეთ",
    )
)


def _snapshot_sort_key(
    snapshot: PendingWorkflowSnapshot,
) -> tuple[object, ...]:
    return (
        snapshot.workflow_id,
        snapshot.owner_id,
        snapshot.kind.value,
        snapshot.source.value,
        snapshot.status.value,
        tuple(item.value for item in snapshot.expected_reply_kinds),
        snapshot.turn_distance,
        snapshot.program_id.value if snapshot.program_id is not None else "",
    )


def _unique_sorted(
    snapshots: tuple[PendingWorkflowSnapshot, ...],
) -> tuple[PendingWorkflowSnapshot, ...]:
    return tuple(sorted(set(snapshots), key=_snapshot_sort_key))


def _decision(
    action: PendingWorkflowAction,
    reason: PendingWorkflowReason,
    confidence: float,
    *,
    selected_workflow: PendingWorkflowSnapshot | None = None,
    eligible_workflows: tuple[PendingWorkflowSnapshot, ...] = (),
    rejected_workflows: tuple[PendingWorkflowSnapshot, ...] = (),
    matched_reply_kinds: tuple[ExpectedReplyKind, ...] = (),
    evidence: tuple[str, ...],
) -> PendingWorkflowDecision:
    return PendingWorkflowDecision(
        action=action,
        selected_workflow=selected_workflow,
        eligible_workflows=_unique_sorted(eligible_workflows),
        rejected_workflows=_unique_sorted(rejected_workflows),
        matched_reply_kinds=tuple(
            sorted(
                matched_reply_kinds,
                key=_EXPECTED_REPLY_ORDER.__getitem__,
            )
        ),
        confidence=confidence,
        primary_reason=reason,
        evidence=evidence,
    )


def _has_conflicting_identity(
    snapshots: tuple[PendingWorkflowSnapshot, ...],
) -> bool:
    by_workflow_id: dict[str, list[PendingWorkflowSnapshot]] = {}
    for snapshot in snapshots:
        by_workflow_id.setdefault(snapshot.workflow_id, []).append(snapshot)
    return any(
        len(records) > 1
        and any(
            record.status is PendingWorkflowStatus.ACTIVE
            for record in records
        )
        for records in by_workflow_id.values()
    )


def _is_logically_valid(snapshot: PendingWorkflowSnapshot) -> bool:
    expected = frozenset(snapshot.expected_reply_kinds)
    if not expected:
        return False
    if snapshot.kind is PendingWorkflowKind.CONTACT_COLLECTION:
        return expected <= frozenset(
            (ExpectedReplyKind.USER_NAME, ExpectedReplyKind.USER_PHONE)
        )
    if snapshot.kind is PendingWorkflowKind.CHILD_AGE_COLLECTION:
        return expected == frozenset((ExpectedReplyKind.CHILD_AGE,))
    if snapshot.kind is PendingWorkflowKind.AFFIRMATION_CONFIRMATION:
        return expected == frozenset((ExpectedReplyKind.AFFIRMATION,))
    return False


def _freshness_limit(
    kind: PendingWorkflowKind,
    policy: PendingWorkflowPolicy,
) -> int:
    if kind is PendingWorkflowKind.CHILD_AGE_COLLECTION:
        return policy.child_age_collection_max_turn_distance
    if kind is PendingWorkflowKind.CONTACT_COLLECTION:
        return policy.contact_collection_max_turn_distance
    return policy.affirmation_confirmation_max_turn_distance


def _is_fresh(
    snapshot: PendingWorkflowSnapshot,
    policy: PendingWorkflowPolicy,
) -> bool:
    return snapshot.turn_distance <= _freshness_limit(snapshot.kind, policy)


def _word_tokens(message: NormalizedMessage) -> tuple[str, ...]:
    return tuple(
        token.casefold()
        for token in message.comparison_tokens
        if token.isalpha()
    )


def _is_direct_manager_contact_request(
    message: NormalizedMessage,
    policy: PendingWorkflowPolicy,
) -> bool:
    words = _word_tokens(message)
    has_manager_owner = any(
        word in policy.manager_reference_terms for word in words
    )
    has_contact = any(
        word.startswith(stem)
        for word in words
        for stem in policy.manager_contact_stems
    )
    has_request = any(
        word.startswith(stem)
        for word in words
        for stem in policy.manager_request_stems
    )
    return has_manager_owner and has_contact and has_request


def _matches_phone(message: NormalizedMessage) -> bool:
    text = message.normalized_text
    return bool(
        _LOCAL_PHONE_RE.fullmatch(text)
        or _INTERNATIONAL_PHONE_RE.fullmatch(text)
    )


def _matches_child_age(
    message: NormalizedMessage,
    policy: PendingWorkflowPolicy,
) -> bool:
    match = _CHILD_AGE_RE.fullmatch(message.normalized_text.casefold())
    if match is None:
        return False
    age = int(match.group(1))
    return policy.child_age_minimum <= age <= policy.child_age_maximum


def _matches_user_name(message: NormalizedMessage) -> bool:
    text = message.normalized_text
    if not _GEORGIAN_OR_LATIN_NAME_RE.fullmatch(text):
        return False
    return text.casefold() not in _NON_NAME_WORDS


def _matches_affirmation(
    message: NormalizedMessage,
    policy: PendingWorkflowPolicy,
) -> bool:
    text = message.normalized_text.casefold().strip("!?.,")
    return text in policy.affirmation_phrases


def _matched_reply_kinds(
    message: NormalizedMessage,
    workflow: PendingWorkflowSnapshot,
    policy: PendingWorkflowPolicy,
) -> tuple[ExpectedReplyKind, ...]:
    matched: list[ExpectedReplyKind] = []
    for reply_kind in workflow.expected_reply_kinds:
        if reply_kind is ExpectedReplyKind.USER_NAME:
            is_match = _matches_user_name(message)
        elif reply_kind is ExpectedReplyKind.USER_PHONE:
            is_match = _matches_phone(message)
        elif reply_kind is ExpectedReplyKind.CHILD_AGE:
            is_match = _matches_child_age(message, policy)
        else:
            is_match = _matches_affirmation(message, policy)
        if is_match:
            matched.append(reply_kind)
    return tuple(matched)


def arbitrate_pending_workflow(
    message: NormalizedMessage,
    conversation_act: ConversationActDecision,
    context_decision: ContextArbitrationDecision,
    pending_workflows: tuple[PendingWorkflowSnapshot, ...],
    policy: PendingWorkflowPolicy = DEFAULT_PENDING_WORKFLOW_POLICY,
) -> PendingWorkflowDecision:
    """Decide whether supplied pending state may consume the current message."""

    if not isinstance(message, NormalizedMessage):
        raise PendingWorkflowError("message must be NormalizedMessage")
    if not isinstance(conversation_act, ConversationActDecision):
        raise PendingWorkflowError(
            "conversation_act must be ConversationActDecision"
        )
    if not isinstance(context_decision, ContextArbitrationDecision):
        raise PendingWorkflowError(
            "context_decision must be ContextArbitrationDecision"
        )
    if not isinstance(pending_workflows, tuple):
        raise PendingWorkflowError(
            "pending_workflows must be an immutable tuple"
        )
    if not all(
        isinstance(snapshot, PendingWorkflowSnapshot)
        for snapshot in pending_workflows
    ):
        raise PendingWorkflowError(
            "pending_workflows must contain PendingWorkflowSnapshot values"
        )
    if not isinstance(policy, PendingWorkflowPolicy):
        raise PendingWorkflowError("policy must be PendingWorkflowPolicy")

    if not pending_workflows:
        return _decision(
            PendingWorkflowAction.NO_PENDING_WORKFLOW,
            PendingWorkflowReason.NO_WORKFLOW_SUPPLIED,
            1.0,
            evidence=("workflow.none_supplied",),
        )

    unique = _unique_sorted(pending_workflows)
    active = tuple(
        snapshot
        for snapshot in unique
        if snapshot.status is PendingWorkflowStatus.ACTIVE
    )
    inactive = tuple(
        snapshot
        for snapshot in unique
        if snapshot.status is not PendingWorkflowStatus.ACTIVE
    )
    if not active:
        return _decision(
            PendingWorkflowAction.NO_PENDING_WORKFLOW,
            PendingWorkflowReason.NO_ACTIVE_WORKFLOW,
            1.0,
            rejected_workflows=inactive,
            evidence=("workflow.no_active",),
        )

    if _has_conflicting_identity(unique) or not all(
        _is_logically_valid(snapshot) for snapshot in active
    ):
        return _decision(
            PendingWorkflowAction.REJECT_MALFORMED_WORKFLOW,
            PendingWorkflowReason.WORKFLOW_MALFORMED,
            1.0,
            rejected_workflows=unique,
            evidence=("workflow.malformed",),
        )

    fresh = tuple(
        snapshot for snapshot in active if _is_fresh(snapshot, policy)
    )
    stale = tuple(
        snapshot for snapshot in active if not _is_fresh(snapshot, policy)
    )
    rejected = inactive + stale
    if not fresh:
        return _decision(
            PendingWorkflowAction.CANCEL_STALE_WORKFLOW,
            PendingWorkflowReason.WORKFLOW_STALE,
            0.99,
            rejected_workflows=rejected,
            evidence=("workflow.stale",),
        )

    if len(fresh) > 1:
        return _decision(
            PendingWorkflowAction.SUSPEND_PENDING_WORKFLOW,
            PendingWorkflowReason.CONFLICTING_ACTIVE_WORKFLOWS,
            1.0,
            eligible_workflows=fresh,
            rejected_workflows=rejected,
            evidence=("workflow.multiple_fresh",),
        )

    selected = fresh[0]
    act = conversation_act.act

    if act in (
        ConversationAct.HUMAN_HANDOFF,
        ConversationAct.CALLBACK_REQUEST,
    ):
        return _decision(
            PendingWorkflowAction.INTERRUPT_WITH_CURRENT_REQUEST,
            PendingWorkflowReason.CURRENT_REQUEST_OVERRIDES_PENDING,
            1.0,
            eligible_workflows=fresh,
            rejected_workflows=rejected,
            evidence=(f"request.override.{act.value}",),
        )

    if act in (
        ConversationAct.PROGRAM_QUESTION,
        ConversationAct.UNKNOWN,
    ) and _is_direct_manager_contact_request(message, policy):
        return _decision(
            PendingWorkflowAction.INTERRUPT_WITH_CURRENT_REQUEST,
            PendingWorkflowReason.MANAGER_CONTACT_REQUEST_OVERRIDES_PENDING,
            1.0,
            eligible_workflows=fresh,
            rejected_workflows=rejected,
            evidence=("request.manager_contact",),
        )

    if act is ConversationAct.PROGRAM_QUESTION:
        return _decision(
            PendingWorkflowAction.RESUME_PENDING_AFTER_ANSWER,
            PendingWorkflowReason.RESUMABLE_PROGRAM_QUESTION,
            0.98,
            selected_workflow=selected,
            eligible_workflows=fresh,
            rejected_workflows=rejected,
            evidence=("request.program_question",),
        )

    if act in _NON_ANSWER_ACTS:
        return _decision(
            PendingWorkflowAction.SUSPEND_PENDING_WORKFLOW,
            PendingWorkflowReason.NON_ANSWER_ACT_SUSPENDS_PENDING,
            1.0,
            eligible_workflows=fresh,
            rejected_workflows=rejected,
            evidence=(f"act.non_answer.{act.value}",),
        )

    if act is not ConversationAct.UNKNOWN:
        raise PendingWorkflowError("conversation act is unsupported")

    matched = _matched_reply_kinds(message, selected, policy)
    if matched:
        return _decision(
            PendingWorkflowAction.CONTINUE_PENDING_WORKFLOW,
            PendingWorkflowReason.EXPECTED_REPLY_MATCHED,
            0.99,
            selected_workflow=selected,
            eligible_workflows=fresh,
            rejected_workflows=rejected,
            matched_reply_kinds=matched,
            evidence=tuple(f"reply.matched.{item.value}" for item in matched),
        )
    return _decision(
        PendingWorkflowAction.SUSPEND_PENDING_WORKFLOW,
        PendingWorkflowReason.EXPECTED_REPLY_NOT_MATCHED,
        0.95,
        eligible_workflows=fresh,
        rejected_workflows=rejected,
        evidence=("reply.expected_not_matched",),
    )
