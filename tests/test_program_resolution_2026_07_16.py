from __future__ import annotations

import ast
import inspect
import subprocess
import sys
from dataclasses import FrozenInstanceError, fields, replace
from pathlib import Path

import pytest

from app.domain.decision import (
    DEFAULT_PROGRAM_RESOLUTION_POLICY,
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
    PendingWorkflowKind,
    PendingWorkflowReason,
    PendingWorkflowSnapshot,
    PendingWorkflowSource,
    PendingWorkflowStatus,
    ProgramContextCandidate,
    ProgramId,
    ProgramIdentityDefinition,
    ProgramMention,
    ProgramMentionRole,
    ProgramPhraseRule,
    ProgramResolutionDecision,
    ProgramResolutionError,
    ProgramResolutionOutcome,
    ProgramResolutionPolicy,
    ProgramResolutionReason,
    ProgramResolutionSource,
    ProgramStemRule,
    ProgramTokenRule,
    PROGRAM_REGISTRY,
    ProgramRegistry,
    arbitrate_context,
    arbitrate_pending_workflow,
    normalize_message,
    resolve_conversation_act,
    resolve_program,
)


ROOT = Path(__file__).resolve().parents[1]
DOMAIN_DIR = ROOT / "app" / "domain" / "decision"
RESOLVER_PATH = DOMAIN_DIR / "program_resolver.py"


def _act(act: ConversationAct = ConversationAct.PROGRAM_QUESTION):
    reason = (
        ConversationActReason.GENERIC_PROGRAM_QUESTION
        if act is ConversationAct.PROGRAM_QUESTION
        else ConversationActReason.INSUFFICIENT_EVIDENCE
    )
    return ConversationActDecision(
        act=act,
        confidence=0.9,
        primary_reason=reason,
        evidence=(f"test.act.{act.value}",),
        candidate_acts=(act,),
    )


def _candidate(
    program_id: ProgramId,
    source: ContextSource = ContextSource.USER_EXPLICIT_PROGRAM,
) -> ProgramContextCandidate:
    return ProgramContextCandidate(program_id, source, 0)


def _context(
    context_use: ContextUse = ContextUse.NO_RELEVANT_CONTEXT,
    program_ids: tuple[ProgramId, ...] = (),
) -> ContextArbitrationDecision:
    ordered_ids = tuple(sorted(set(program_ids), key=lambda item: item.value))
    source = (
        ContextSource.ASSISTANT_REFERENCED_PROGRAM
        if context_use is ContextUse.PRIOR_CONTEXT_FALLBACK_ONLY
        else ContextSource.USER_EXPLICIT_PROGRAM
    )
    candidates = tuple(_candidate(program_id, source) for program_id in ordered_ids)
    reason = {
        ContextUse.BLOCKED: ContextArbitrationReason.ACT_BLOCKS_CONTEXT,
        ContextUse.CURRENT_MESSAGE_AUTHORITATIVE: (
            ContextArbitrationReason.CURRENT_MESSAGE_SUBSTANTIVE
        ),
        ContextUse.PRIOR_CONTEXT_SELECTED: (
            ContextArbitrationReason.SINGLE_FRESH_STRONG_CONTEXT
        ),
        ContextUse.PRIOR_CONTEXT_FALLBACK_ONLY: (
            ContextArbitrationReason.ASSISTANT_CONTEXT_FALLBACK_ONLY
        ),
        ContextUse.AMBIGUOUS: (
            ContextArbitrationReason.CONFLICTING_FRESH_CONTEXTS
        ),
        ContextUse.NO_RELEVANT_CONTEXT: (
            ContextArbitrationReason.NO_CONTEXT_CANDIDATES
        ),
    }[context_use]
    selected = (
        ordered_ids[0]
        if context_use is ContextUse.PRIOR_CONTEXT_SELECTED
        else None
    )
    return ContextArbitrationDecision(
        context_use=context_use,
        selected_program_id=selected,
        eligible_program_ids=ordered_ids,
        eligible_candidates=candidates,
        rejected_candidates=(),
        confidence=0.94 if selected is not None else 0.2,
        primary_reason=reason,
        evidence=(f"test.context.{context_use.value}",),
    )


def _no_pending() -> PendingWorkflowDecision:
    return PendingWorkflowDecision(
        action=PendingWorkflowAction.NO_PENDING_WORKFLOW,
        selected_workflow=None,
        eligible_workflows=(),
        rejected_workflows=(),
        matched_reply_kinds=(),
        confidence=1.0,
        primary_reason=PendingWorkflowReason.NO_WORKFLOW_SUPPLIED,
        evidence=("test.workflow.none",),
    )


def _workflow(
    kind: PendingWorkflowKind,
    reply_kind: ExpectedReplyKind,
) -> PendingWorkflowSnapshot:
    return PendingWorkflowSnapshot(
        workflow_id=f"workflow.{kind.value}",
        owner_id="owner.phase6.test",
        kind=kind,
        source=PendingWorkflowSource.TYPED_PENDING_RECORD,
        status=PendingWorkflowStatus.ACTIVE,
        expected_reply_kinds=(reply_kind,),
        turn_distance=0,
        program_id=ProgramId.SUMMER_CAMP,
    )


def _resolve(
    text: str,
    *,
    act: ConversationActDecision | None = None,
    context: ContextArbitrationDecision | None = None,
    pending: PendingWorkflowDecision | None = None,
    registry: ProgramRegistry = PROGRAM_REGISTRY,
    policy: ProgramResolutionPolicy = DEFAULT_PROGRAM_RESOLUTION_POLICY,
) -> ProgramResolutionDecision:
    return resolve_program(
        normalize_message(text),
        act or _act(),
        context or _context(),
        pending or _no_pending(),
        registry,
        policy,
    )


def _real_chain(
    text: str,
    *,
    context_candidates: tuple[ProgramContextCandidate, ...] = (),
    pending_workflows: tuple[PendingWorkflowSnapshot, ...] = (),
):
    message = normalize_message(text)
    act = resolve_conversation_act(message)
    context = arbitrate_context(message, act, context_candidates)
    pending = arbitrate_pending_workflow(
        message,
        act,
        context,
        pending_workflows,
    )
    decision = resolve_program(message, act, context, pending)
    return message, act, context, pending, decision


def _mention(
    program_id: ProgramId = ProgramId.SUMMER_CAMP,
    role: ProgramMentionRole = ProgramMentionRole.REQUESTED,
    start: int = 0,
    end: int = 1,
    evidence: str = "program.test.identity",
) -> ProgramMention:
    return ProgramMention(program_id, role, start, end, evidence)


def _decision_kwargs() -> dict[str, object]:
    mention = _mention()
    return {
        "outcome": ProgramResolutionOutcome.RESOLVED,
        "source": ProgramResolutionSource.CURRENT_MESSAGE,
        "selected_program_id": ProgramId.SUMMER_CAMP,
        "requested_program_ids": (ProgramId.SUMMER_CAMP,),
        "referenced_program_ids": (),
        "excluded_program_ids": (),
        "prior_context_program_ids": (),
        "mentions": (mention,),
        "confidence": 0.99,
        "primary_reason": ProgramResolutionReason.CURRENT_SINGLE_REQUESTED,
        "evidence": ("resolution.current_single_requested",),
    }


def _assert_resolved(
    text: str,
    program_id: ProgramId,
) -> ProgramResolutionDecision:
    decision = _resolve(text)
    assert decision.outcome is ProgramResolutionOutcome.RESOLVED
    assert decision.source is ProgramResolutionSource.CURRENT_MESSAGE
    assert decision.selected_program_id is program_id
    assert decision.requested_program_ids == (program_id,)
    assert decision.primary_reason is ProgramResolutionReason.CURRENT_SINGLE_REQUESTED
    return decision


def test_phase6_enums_are_exactly_closed():
    assert tuple(item.value for item in ProgramMentionRole) == (
        "requested",
        "referenced",
        "excluded",
    )
    assert tuple(item.value for item in ProgramResolutionOutcome) == (
        "resolved",
        "ambiguous",
        "absent",
        "not_applicable",
    )
    assert tuple(item.value for item in ProgramResolutionSource) == (
        "current_message",
        "prior_context",
        "none",
    )
    assert tuple(item.value for item in ProgramResolutionReason) == (
        "pending_reply_consumed",
        "act_not_eligible",
        "current_single_requested",
        "current_multiple_requested",
        "current_contradictory_roles",
        "current_excluded_only",
        "current_referenced_only",
        "prior_context_selected",
        "prior_context_ambiguous",
        "prior_context_fallback_only",
        "no_program_evidence",
    )


def test_phase6_models_are_frozen_slotted_hashable_and_deeply_immutable():
    mention = _mention()
    policy = DEFAULT_PROGRAM_RESOLUTION_POLICY
    decision = ProgramResolutionDecision(**_decision_kwargs())

    assert not hasattr(mention, "__dict__")
    assert not hasattr(policy, "__dict__")
    assert not hasattr(decision, "__dict__")
    assert hash(mention)
    assert hash(policy)
    assert hash(decision)
    with pytest.raises(FrozenInstanceError):
        mention.role = ProgramMentionRole.EXCLUDED  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        policy.pivot_tokens = ("changed",)  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        decision.confidence = 0.0  # type: ignore[misc]
    with pytest.raises(AttributeError):
        decision.mentions.append(mention)  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        policy.reference_phrases.append(("changed",))  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "constructor",
    [
        lambda: ProgramMention("summer_camp", ProgramMentionRole.REQUESTED, 0, 1, "id"),
        lambda: ProgramMention(ProgramId.SUMMER_CAMP, "requested", 0, 1, "id"),
        lambda: ProgramMention(ProgramId.SUMMER_CAMP, ProgramMentionRole.REQUESTED, -1, 1, "id"),
        lambda: ProgramMention(ProgramId.SUMMER_CAMP, ProgramMentionRole.REQUESTED, 1, 1, "id"),
        lambda: ProgramMention(ProgramId.SUMMER_CAMP, ProgramMentionRole.REQUESTED, 2, 1, "id"),
        lambda: ProgramMention(ProgramId.SUMMER_CAMP, ProgramMentionRole.REQUESTED, True, 1, "id"),
        lambda: ProgramMention(ProgramId.SUMMER_CAMP, ProgramMentionRole.REQUESTED, 0, 1, ""),
        lambda: ProgramMention(ProgramId.SUMMER_CAMP, ProgramMentionRole.REQUESTED, 0, 1, " padded "),
    ],
)
def test_program_mention_rejects_invalid_types_spans_and_evidence(constructor):
    with pytest.raises(ProgramResolutionError):
        constructor()


def _single_token_rule(token: str = "synthetic") -> ProgramTokenRule:
    return ProgramTokenRule(
        exact_forms=(token,),
        evidence_id=f"program.test.token.{token}",
    )


def _single_phrase_rule(token: str = "synthetic") -> ProgramPhraseRule:
    return ProgramPhraseRule(
        components=(_single_token_rule(token),),
        maximum_gap=0,
        evidence_id=f"program.test.phrase.{token}",
    )


def _identity_definition(
    program_id: ProgramId = ProgramId.SUMMER_CAMP,
    token: str = "synthetic",
) -> ProgramIdentityDefinition:
    return ProgramIdentityDefinition(
        program_id=program_id,
        phrase_rules=(_single_phrase_rule(token),),
        evidence_id=f"program.test.identity.{program_id.value}",
    )


@pytest.mark.parametrize(
    "constructor",
    [
        lambda: ProgramStemRule("?????", ["?"], "program.test.stem"),
        lambda: ProgramStemRule("?????", ("?", "?"), "program.test.stem"),
        lambda: ProgramStemRule("?????", ("??", "?"), "program.test.stem"),
        lambda: ProgramStemRule("?????", (" ?",), "program.test.stem"),
        lambda: ProgramStemRule("??? ??????", ("",), "program.test.stem"),
        lambda: ProgramTokenRule(["camp"], (), "program.test.token"),
        lambda: ProgramTokenRule(("camp", "camp"), (), "program.test.token"),
        lambda: ProgramTokenRule(("summer camp",), (), "program.test.token"),
        lambda: ProgramTokenRule((), (), "program.test.token"),
        lambda: ProgramPhraseRule([_single_token_rule()], 0, "program.test.phrase"),
        lambda: ProgramPhraseRule((_single_token_rule(),), True, "program.test.phrase"),
        lambda: ProgramPhraseRule((_single_token_rule(),), -1, "program.test.phrase"),
        lambda: ProgramIdentityDefinition(
            ProgramId.SUMMER_CAMP,
            (_single_phrase_rule(), _single_phrase_rule()),
            "program.test.identity",
        ),
        lambda: ProgramResolutionPolicy(
            [_identity_definition()],
            DEFAULT_PROGRAM_RESOLUTION_POLICY.exclusion_following_phrases,
            DEFAULT_PROGRAM_RESOLUTION_POLICY.exclusion_leading_phrases,
            DEFAULT_PROGRAM_RESOLUTION_POLICY.reference_phrases,
            DEFAULT_PROGRAM_RESOLUTION_POLICY.pivot_tokens,
            DEFAULT_PROGRAM_RESOLUTION_POLICY.clause_boundary_tokens,
        ),
        lambda: replace(
            DEFAULT_PROGRAM_RESOLUTION_POLICY,
            program_identity_definitions=(
                DEFAULT_PROGRAM_RESOLUTION_POLICY.program_identity_definitions[1],
                DEFAULT_PROGRAM_RESOLUTION_POLICY.program_identity_definitions[0],
                DEFAULT_PROGRAM_RESOLUTION_POLICY.program_identity_definitions[2],
            ),
        ),
        lambda: replace(
            DEFAULT_PROGRAM_RESOLUTION_POLICY,
            program_identity_definitions=(
                DEFAULT_PROGRAM_RESOLUTION_POLICY.program_identity_definitions[0],
                DEFAULT_PROGRAM_RESOLUTION_POLICY.program_identity_definitions[0],
            ),
        ),
        lambda: replace(
            DEFAULT_PROGRAM_RESOLUTION_POLICY,
            pivot_tokens=("????", "????"),
        ),
        lambda: replace(
            DEFAULT_PROGRAM_RESOLUTION_POLICY,
            clause_boundary_tokens=(" ",),
        ),
        lambda: replace(
            DEFAULT_PROGRAM_RESOLUTION_POLICY,
            reference_phrases=((),),
        ),
    ],
)
def test_program_resolution_policy_rejects_mutable_or_malformed_rules(constructor):
    with pytest.raises(ProgramResolutionError):
        constructor()


def test_decision_accepts_multiple_spans_but_summarizes_each_role_once():
    mentions = (
        _mention(start=0, end=1),
        _mention(start=2, end=3, evidence="program.test.identity.repeat"),
    )
    decision = ProgramResolutionDecision(
        **{
            **_decision_kwargs(),
            "mentions": mentions,
        }
    )
    assert decision.requested_program_ids == (ProgramId.SUMMER_CAMP,)
    assert len(decision.mentions) == 2


def test_decision_rejects_duplicate_or_nondeterministically_ordered_mentions():
    first = _mention(start=0, end=1)
    second = _mention(
        ProgramId.SUNDAY_SCHOOL,
        start=2,
        end=4,
        evidence="program.test.sunday",
    )
    kwargs = _decision_kwargs()
    with pytest.raises(ProgramResolutionError):
        ProgramResolutionDecision(**{**kwargs, "mentions": (first, first)})
    with pytest.raises(ProgramResolutionError):
        ProgramResolutionDecision(
            **{
                **kwargs,
                "selected_program_id": None,
                "outcome": ProgramResolutionOutcome.AMBIGUOUS,
                "requested_program_ids": (
                    ProgramId.SUMMER_CAMP,
                    ProgramId.SUNDAY_SCHOOL,
                ),
                "mentions": (second, first),
                "primary_reason": ProgramResolutionReason.CURRENT_MULTIPLE_REQUESTED,
            }
        )


def test_decision_rejects_summary_ids_that_do_not_exactly_match_roles():
    kwargs = _decision_kwargs()
    with pytest.raises(ProgramResolutionError):
        ProgramResolutionDecision(**{**kwargs, "requested_program_ids": ()})
    with pytest.raises(ProgramResolutionError):
        ProgramResolutionDecision(
            **{
                **kwargs,
                "referenced_program_ids": (ProgramId.ADULT_EVENTS,),
            }
        )


@pytest.mark.parametrize("confidence", [-0.01, 1.01, True, "0.9"])
def test_decision_rejects_invalid_confidence(confidence: object):
    with pytest.raises(ProgramResolutionError):
        ProgramResolutionDecision(**{**_decision_kwargs(), "confidence": confidence})


@pytest.mark.parametrize("evidence", [(), ("",), (" padded ",), ("same", "same"), ["id"]])
def test_decision_rejects_empty_duplicate_or_mutable_evidence(evidence: object):
    with pytest.raises(ProgramResolutionError):
        ProgramResolutionDecision(**{**_decision_kwargs(), "evidence": evidence})


def test_decision_rejects_unsorted_or_duplicate_program_id_tuples():
    kwargs = _decision_kwargs()
    with pytest.raises(ProgramResolutionError):
        ProgramResolutionDecision(
            **{
                **kwargs,
                "prior_context_program_ids": (
                    ProgramId.SUMMER_CAMP,
                    ProgramId.ADULT_EVENTS,
                ),
            }
        )
    with pytest.raises(ProgramResolutionError):
        ProgramResolutionDecision(
            **{
                **kwargs,
                "prior_context_program_ids": (
                    ProgramId.SUMMER_CAMP,
                    ProgramId.SUMMER_CAMP,
                ),
            }
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"selected_program_id": None},
        {"source": ProgramResolutionSource.NONE},
        {"outcome": ProgramResolutionOutcome.ABSENT},
        {"primary_reason": ProgramResolutionReason.PRIOR_CONTEXT_SELECTED},
        {
            "selected_program_id": ProgramId.SUNDAY_SCHOOL,
        },
        {
            "excluded_program_ids": (ProgramId.SUMMER_CAMP,),
            "mentions": (
                _mention(),
                _mention(
                    role=ProgramMentionRole.EXCLUDED,
                    start=2,
                    end=3,
                    evidence="program.test.excluded",
                ),
            ),
        },
    ],
)
def test_decision_rejects_malformed_resolved_combinations(changes):
    with pytest.raises(ProgramResolutionError):
        ProgramResolutionDecision(**{**_decision_kwargs(), **changes})


def test_decision_accepts_and_validates_current_ambiguity_contracts():
    camp = _mention()
    sunday = _mention(
        ProgramId.SUNDAY_SCHOOL,
        start=2,
        end=4,
        evidence="program.test.sunday",
    )
    multiple = ProgramResolutionDecision(
        outcome=ProgramResolutionOutcome.AMBIGUOUS,
        source=ProgramResolutionSource.CURRENT_MESSAGE,
        selected_program_id=None,
        requested_program_ids=(ProgramId.SUMMER_CAMP, ProgramId.SUNDAY_SCHOOL),
        referenced_program_ids=(),
        excluded_program_ids=(),
        prior_context_program_ids=(),
        mentions=(camp, sunday),
        confidence=1.0,
        primary_reason=ProgramResolutionReason.CURRENT_MULTIPLE_REQUESTED,
        evidence=("resolution.current_multiple_requested",),
    )
    assert multiple.selected_program_id is None

    excluded = _mention(
        role=ProgramMentionRole.EXCLUDED,
        start=2,
        end=3,
        evidence="program.test.excluded",
    )
    contradictory = ProgramResolutionDecision(
        outcome=ProgramResolutionOutcome.AMBIGUOUS,
        source=ProgramResolutionSource.CURRENT_MESSAGE,
        selected_program_id=None,
        requested_program_ids=(ProgramId.SUMMER_CAMP,),
        referenced_program_ids=(),
        excluded_program_ids=(ProgramId.SUMMER_CAMP,),
        prior_context_program_ids=(),
        mentions=(camp, excluded),
        confidence=1.0,
        primary_reason=ProgramResolutionReason.CURRENT_CONTRADICTORY_ROLES,
        evidence=("resolution.current_contradictory_roles",),
    )
    assert contradictory.selected_program_id is None


def test_decision_rejects_ambiguous_without_a_valid_ambiguity_cause():
    kwargs = _decision_kwargs()
    with pytest.raises(ProgramResolutionError):
        ProgramResolutionDecision(
            **{
                **kwargs,
                "outcome": ProgramResolutionOutcome.AMBIGUOUS,
                "selected_program_id": None,
                "primary_reason": ProgramResolutionReason.CURRENT_MULTIPLE_REQUESTED,
            }
        )


def test_phase6_contract_has_no_semantic_topic_lifecycle_or_response_fields():
    names = {item.name for item in fields(ProgramResolutionDecision)}
    assert not (
        {
            "topic",
            "intent",
            "price",
            "registration",
            "lifecycle",
            "capability",
            "answer",
            "response",
            "copy",
        }
        & names
    )


def test_resolver_signature_is_exactly_the_phase6_contract():
    assert tuple(inspect.signature(resolve_program).parameters) == (
        "message",
        "conversation_act",
        "context_decision",
        "pending_decision",
        "registry",
        "policy",
    )


@pytest.mark.parametrize(
    "argument_index,bad_value",
    [
        (0, "ბანაკი"),
        (1, ConversationAct.PROGRAM_QUESTION),
        (2, {}),
        (3, None),
        (4, object()),
        (5, {}),
    ],
)
def test_resolver_rejects_every_wrong_top_level_input(
    argument_index: int,
    bad_value: object,
):
    arguments = [
        normalize_message("ბანაკი მაინტერესებს"),
        _act(),
        _context(),
        _no_pending(),
        PROGRAM_REGISTRY,
        DEFAULT_PROGRAM_RESOLUTION_POLICY,
    ]
    arguments[argument_index] = bad_value
    with pytest.raises(ProgramResolutionError):
        resolve_program(*arguments)


def test_resolver_is_deterministic_and_does_not_mutate_any_input():
    message = normalize_message("ბანაკი და საკვირაო სკოლა მაინტერესებს")
    act = _act()
    context = _context(
        ContextUse.PRIOR_CONTEXT_SELECTED,
        (ProgramId.ADULT_EVENTS,),
    )
    pending = _no_pending()
    before = (repr(message), repr(act), repr(context), repr(pending))
    first = resolve_program(message, act, context, pending)
    second = resolve_program(message, act, context, pending)
    after = (repr(message), repr(act), repr(context), repr(pending))
    assert first == second
    assert hash(first) == hash(second)
    assert before == after


class _MissingProgramRegistry(ProgramRegistry):
    def get(self, program_id):
        if program_id is ProgramId.SUMMER_CAMP:
            return None
        return super().get(program_id)


def test_selected_or_mentioned_program_must_belong_to_supplied_registry():
    registry = _MissingProgramRegistry(PROGRAM_REGISTRY.definitions)
    with pytest.raises(ProgramResolutionError):
        _resolve("ბანაკი მაინტერესებს", registry=registry)


@pytest.mark.parametrize(
    "text,kind,reply_kind",
    [
        ("14 წლის", PendingWorkflowKind.CHILD_AGE_COLLECTION, ExpectedReplyKind.CHILD_AGE),
        ("555 123 456", PendingWorkflowKind.CONTACT_COLLECTION, ExpectedReplyKind.USER_PHONE),
        ("მე ვარ ნიკოლოზი", PendingWorkflowKind.CONTACT_COLLECTION, ExpectedReplyKind.USER_NAME),
        ("დიახ", PendingWorkflowKind.AFFIRMATION_CONFIRMATION, ExpectedReplyKind.AFFIRMATION),
    ],
)
def test_consumed_pending_replies_make_program_resolution_not_applicable(
    text: str,
    kind: PendingWorkflowKind,
    reply_kind: ExpectedReplyKind,
):
    message, act, context, pending, decision = _real_chain(
        text,
        pending_workflows=(_workflow(kind, reply_kind),),
    )
    assert message.normalized_text
    assert act.act is ConversationAct.UNKNOWN
    assert pending.action is PendingWorkflowAction.CONTINUE_PENDING_WORKFLOW
    assert decision.outcome is ProgramResolutionOutcome.NOT_APPLICABLE
    assert decision.source is ProgramResolutionSource.NONE
    assert decision.selected_program_id is None
    assert decision.mentions == ()
    assert decision.primary_reason is ProgramResolutionReason.PENDING_REPLY_CONSUMED


def test_resume_pending_after_answer_does_not_block_program_resolution():
    workflow = _workflow(
        PendingWorkflowKind.CHILD_AGE_COLLECTION,
        ExpectedReplyKind.CHILD_AGE,
    )
    _, act, _, pending, decision = _real_chain(
        "ბანაკი მაინტერესებს",
        pending_workflows=(workflow,),
    )
    assert act.act is ConversationAct.PROGRAM_QUESTION
    assert pending.action is PendingWorkflowAction.RESUME_PENDING_AFTER_ANSWER
    assert decision.outcome is ProgramResolutionOutcome.RESOLVED
    assert decision.selected_program_id is ProgramId.SUMMER_CAMP


@pytest.mark.parametrize(
    "act",
    tuple(item for item in ConversationAct if item is not ConversationAct.PROGRAM_QUESTION),
)
def test_every_non_program_conversation_act_is_not_applicable(act: ConversationAct):
    decision = _resolve("ბანაკი მაინტერესებს", act=_act(act))
    assert decision.outcome is ProgramResolutionOutcome.NOT_APPLICABLE
    assert decision.source is ProgramResolutionSource.NONE
    assert decision.selected_program_id is None
    assert decision.mentions == ()
    assert decision.primary_reason is ProgramResolutionReason.ACT_NOT_ELIGIBLE
    assert decision.evidence == (
        "resolution.act_not_eligible",
        f"gate.act.{act.value}",
    )


@pytest.mark.parametrize(
    "text",
    [
        "ბანაკი მაინტერესებს",
        "ბანაკის ფასი რა არის?",
        "ბანაკში რა ხდება?",
        "ბანაკზე ინფორმაცია მინდა",
        "ბანაკიდან ტრანსპორტი შედის?",
        "საზაფხულო ბანაკი გაქვთ?",
        "ბავშვთა ბანაკი მაინტერესებს",
        "ლაგერი გაქვთ?",
        "summer camp მაინტერესებს",
        "camp details?",
    ],
)
def test_summer_camp_positive_identity_forms(text: str):
    decision = _assert_resolved(text, ProgramId.SUMMER_CAMP)
    assert all(
        mention.token_end <= len(normalize_message(text).tokens)
        for mention in decision.mentions
    )


@pytest.mark.parametrize(
    "text",
    [
        "ბავშვი მაინტერესებს",
        "შვილისთვის რა გაქვთ?",
        "მოზარდი მყავს",
        "საზაფხულო პროგრამა მაინტერესებს",
        "ეკრანი მაინტერესებს",
        "პროგრამა გაქვთ?",
        "დასვენება მინდა",
    ],
)
def test_generic_child_or_summer_words_do_not_prove_camp(text: str):
    decision = _resolve(text)
    assert decision.outcome is ProgramResolutionOutcome.ABSENT
    assert decision.requested_program_ids == ()
    assert decision.mentions == ()
    assert decision.primary_reason is ProgramResolutionReason.NO_PROGRAM_EVIDENCE


@pytest.mark.parametrize(
    "text",
    [
        "საკვირაო სკოლა მაინტერესებს",
        "საკვირაო სკოლის ფასი რა არის?",
        "საკვირაო სკოლაში რა ხდება?",
        "საკვირაოსკოლა გაქვთ?",
        "sunday school მაინტერესებს",
        "sunday-school გაქვთ?",
        "sundayschool details?",
    ],
)
def test_sunday_school_positive_compound_identity_forms(text: str):
    _assert_resolved(text, ProgramId.SUNDAY_SCHOOL)


@pytest.mark.parametrize(
    "text",
    [
        "საკვირაო მაინტერესებს",
        "სკოლა მაინტერესებს",
        "სკოლაში რა ხდება?",
        "კვირა მაინტერესებს",
        "კვირაობით რა გაქვთ?",
        "საზაფხულო სკოლა მაინტერესებს",
    ],
)
def test_partial_sunday_or_school_words_do_not_prove_sunday_school(text: str):
    decision = _resolve(text)
    assert decision.outcome is ProgramResolutionOutcome.ABSENT
    assert decision.mentions == ()


def test_sunday_camp_resolves_only_summer_camp():
    decision = _assert_resolved("საკვირაო ბანაკი გაქვთ?", ProgramId.SUMMER_CAMP)
    assert ProgramId.SUNDAY_SCHOOL not in decision.requested_program_ids
    assert all(
        mention.program_id is ProgramId.SUMMER_CAMP
        for mention in decision.mentions
    )


@pytest.mark.parametrize(
    "text",
    [
        "ზრდასრულთა ღონისძიებები მაინტერესებს",
        "ზრდასრულებისთვის ღონისძიებები გაქვთ?",
        "ზრდასრულთა კულტურული საღამოები მაინტერესებს",
        "კულტურული საღამოები მაინტერესებს",
        "კულტურული საღამო გაქვთ?",
        "adult events მაინტერესებს",
        "adult event details?",
        "adult-events გაქვთ?",
        "cultural evenings მაინტერესებს",
        "cultural evening details?",
        "cultural-evenings გაქვთ?",
    ],
)
def test_adult_events_positive_direct_identity_forms(text: str):
    _assert_resolved(text, ProgramId.ADULT_EVENTS)


@pytest.mark.parametrize(
    "text",
    [
        "ღონისძიება მაინტერესებს",
        "საღამო მაინტერესებს",
        "კულტურა მაინტერესებს",
        "ბილეთი რა ღირს?",
        "მუსიკა მაინტერესებს",
        "შეხვედრა გაქვთ?",
        "კლუბი მაინტერესებს",
        "ზრდასრულებისთვის რა გაქვთ?",
        "ზრდასრული ვარ",
        "event details?",
    ],
)
def test_generic_event_or_adult_words_do_not_prove_adult_events(text: str):
    decision = _resolve(text)
    assert decision.outcome is ProgramResolutionOutcome.ABSENT
    assert decision.mentions == ()
    assert decision.primary_reason is ProgramResolutionReason.NO_PROGRAM_EVIDENCE


def test_identity_matching_prefers_long_bounded_spans_without_overlap():
    message = normalize_message(
        "საზაფხულო ბანაკი და ზრდასრულთა კულტურული საღამოები"
    )
    decision = resolve_program(
        message,
        _act(),
        _context(),
        _no_pending(),
    )
    assert tuple(
        (mention.token_start, mention.token_end) for mention in decision.mentions
    ) == ((0, 2), (3, 6))
    assert len(decision.mentions) == 2
    assert decision.outcome is ProgramResolutionOutcome.AMBIGUOUS


@pytest.mark.parametrize(
    "program_id,text",
    [
        (ProgramId.SUMMER_CAMP, "ბანაკის გარდა რა პროგრამა გაქვთ?"),
        (ProgramId.SUMMER_CAMP, "ბანაკის ნაცვლად სხვა პროგრამა გაქვთ?"),
        (ProgramId.SUMMER_CAMP, "ბანაკი არ მინდა"),
        (ProgramId.SUMMER_CAMP, "ბანაკი არ მაინტერესებს"),
        (ProgramId.SUMMER_CAMP, "ბანაკზე არ გეკითხები"),
        (ProgramId.SUMMER_CAMP, "ბანაკის შესახებ არ ვკითხულობ"),
        (ProgramId.SUMMER_CAMP, "ბანაკი არა, სხვა პროგრამა მინდა"),
        (ProgramId.SUNDAY_SCHOOL, "საკვირაო სკოლის გარდა რა პროგრამა გაქვთ?"),
        (ProgramId.SUNDAY_SCHOOL, "საკვირაო სკოლის ნაცვლად სხვა პროგრამა გაქვთ?"),
        (ProgramId.SUNDAY_SCHOOL, "საკვირაო სკოლა არ მინდა"),
        (ProgramId.SUNDAY_SCHOOL, "საკვირაო სკოლა არ მაინტერესებს"),
        (ProgramId.SUNDAY_SCHOOL, "საკვირაო სკოლაზე არ გეკითხები"),
        (ProgramId.SUNDAY_SCHOOL, "საკვირაო სკოლის შესახებ არ ვკითხულობ"),
        (ProgramId.SUNDAY_SCHOOL, "საკვირაო სკოლა არა, სხვა პროგრამა მინდა"),
        (ProgramId.ADULT_EVENTS, "ზრდასრულთა ღონისძიებების გარდა რა გაქვთ?"),
        (ProgramId.ADULT_EVENTS, "ზრდასრულთა ღონისძიებების ნაცვლად სხვა რა გაქვთ?"),
        (ProgramId.ADULT_EVENTS, "ზრდასრულთა ღონისძიებები არ მინდა"),
        (ProgramId.ADULT_EVENTS, "კულტურული საღამოები არ მაინტერესებს"),
        (ProgramId.ADULT_EVENTS, "ზრდასრულთა ღონისძიებებზე არ გეკითხები"),
        (ProgramId.ADULT_EVENTS, "კულტურული საღამოების შესახებ არ ვკითხულობ"),
        (ProgramId.ADULT_EVENTS, "კულტურული საღამოები არა, სხვა პროგრამა მინდა"),
    ],
)
def test_bounded_exclusion_grammars_are_program_scoped(
    program_id: ProgramId,
    text: str,
):
    decision = _resolve(text)
    assert decision.outcome is ProgramResolutionOutcome.ABSENT
    assert decision.source is ProgramResolutionSource.NONE
    assert decision.selected_program_id is None
    assert decision.requested_program_ids == ()
    assert decision.excluded_program_ids == (program_id,)
    assert decision.primary_reason is ProgramResolutionReason.CURRENT_EXCLUDED_ONLY


@pytest.mark.parametrize(
    "text,program_id",
    [
        ("ბანაკი არ გაქვთ?", ProgramId.SUMMER_CAMP),
        ("ბანაკი აღარ იქნება?", ProgramId.SUMMER_CAMP),
        ("ბანაკი არ ტარდება?", ProgramId.SUMMER_CAMP),
        ("საკვირაო სკოლა ჯერ არ არის?", ProgramId.SUNDAY_SCHOOL),
        ("ზრდასრულთა ღონისძიება აღარ გაქვთ?", ProgramId.ADULT_EVENTS),
    ],
)
def test_negative_availability_questions_still_request_the_named_program(
    text: str,
    program_id: ProgramId,
):
    decision = _assert_resolved(text, program_id)
    assert decision.excluded_program_ids == ()


@pytest.mark.parametrize(
    "text,excluded,requested",
    [
        (
            "ბანაკი არ მინდა, საკვირაო სკოლა მაინტერესებს",
            ProgramId.SUMMER_CAMP,
            ProgramId.SUNDAY_SCHOOL,
        ),
        (
            "საკვირაო სკოლის ნაცვლად ბანაკი მაინტერესებს",
            ProgramId.SUNDAY_SCHOOL,
            ProgramId.SUMMER_CAMP,
        ),
        (
            "კულტურული საღამოები არ მინდა, ბანაკი მაინტერესებს",
            ProgramId.ADULT_EVENTS,
            ProgramId.SUMMER_CAMP,
        ),
    ],
)
def test_one_requested_program_wins_while_another_is_explicitly_excluded(
    text: str,
    excluded: ProgramId,
    requested: ProgramId,
):
    decision = _assert_resolved(text, requested)
    assert decision.excluded_program_ids == (excluded,)


@pytest.mark.parametrize(
    "text,referenced,requested",
    [
        (
            "ბანაკზე ადრე ვსაუბრობდით, ახლა საკვირაო სკოლა მაინტერესებს",
            ProgramId.SUMMER_CAMP,
            ProgramId.SUNDAY_SCHOOL,
        ),
        (
            "ბანაკი რომ ახსენეთ, ახლა კულტურული საღამოები მაინტერესებს",
            ProgramId.SUMMER_CAMP,
            ProgramId.ADULT_EVENTS,
        ),
        (
            "საკვირაო სკოლაზე რომ ვსაუბრობდით, ახლა ბანაკის ფასი მაინტერესებს",
            ProgramId.SUNDAY_SCHOOL,
            ProgramId.SUMMER_CAMP,
        ),
    ],
)
def test_bounded_historical_reference_yields_to_distinct_current_target(
    text: str,
    referenced: ProgramId,
    requested: ProgramId,
):
    decision = _assert_resolved(text, requested)
    assert decision.referenced_program_ids == (referenced,)
    assert decision.excluded_program_ids == ()


def test_sole_historical_target_remains_requested_without_distinct_pivot_target():
    decision = _assert_resolved(
        "ბანაკზე რომ ვსაუბრობდით, ფასი რა არის?",
        ProgramId.SUMMER_CAMP,
    )
    assert decision.referenced_program_ids == ()


@pytest.mark.parametrize(
    "text,requested_ids",
    [
        (
            "ბანაკი და საკვირაო სკოლა მაინტერესებს",
            (ProgramId.SUMMER_CAMP, ProgramId.SUNDAY_SCHOOL),
        ),
        (
            "ბანაკი თუ კულტურული საღამოები?",
            (ProgramId.ADULT_EVENTS, ProgramId.SUMMER_CAMP),
        ),
        (
            "ბანაკი, საკვირაო სკოლა და ზრდასრულთა ღონისძიებები გაქვთ?",
            (
                ProgramId.ADULT_EVENTS,
                ProgramId.SUMMER_CAMP,
                ProgramId.SUNDAY_SCHOOL,
            ),
        ),
    ],
)
def test_multiple_current_programs_are_ambiguous_without_order_selection(
    text: str,
    requested_ids: tuple[ProgramId, ...],
):
    decision = _resolve(text)
    assert decision.outcome is ProgramResolutionOutcome.AMBIGUOUS
    assert decision.source is ProgramResolutionSource.CURRENT_MESSAGE
    assert decision.selected_program_id is None
    assert decision.requested_program_ids == requested_ids
    assert decision.primary_reason is ProgramResolutionReason.CURRENT_MULTIPLE_REQUESTED


def test_same_program_requested_and_excluded_is_explicitly_contradictory():
    decision = _resolve("ბანაკი არ მინდა, მაგრამ ბანაკის ფასი მითხარით")
    assert decision.outcome is ProgramResolutionOutcome.AMBIGUOUS
    assert decision.source is ProgramResolutionSource.CURRENT_MESSAGE
    assert decision.selected_program_id is None
    assert decision.requested_program_ids == (ProgramId.SUMMER_CAMP,)
    assert decision.excluded_program_ids == (ProgramId.SUMMER_CAMP,)
    assert decision.primary_reason is ProgramResolutionReason.CURRENT_CONTRADICTORY_ROLES


@pytest.mark.parametrize(
    "text,current_program,prior_program",
    [
        ("ბანაკი მაინტერესებს", ProgramId.SUMMER_CAMP, ProgramId.ADULT_EVENTS),
        ("საკვირაო სკოლა მაინტერესებს", ProgramId.SUNDAY_SCHOOL, ProgramId.SUMMER_CAMP),
        ("კულტურული საღამოები მაინტერესებს", ProgramId.ADULT_EVENTS, ProgramId.SUNDAY_SCHOOL),
    ],
)
def test_explicit_current_program_overrides_different_selected_prior_context(
    text: str,
    current_program: ProgramId,
    prior_program: ProgramId,
):
    context = _context(ContextUse.PRIOR_CONTEXT_SELECTED, (prior_program,))
    decision = _resolve(text, context=context)
    assert decision.outcome is ProgramResolutionOutcome.RESOLVED
    assert decision.source is ProgramResolutionSource.CURRENT_MESSAGE
    assert decision.selected_program_id is current_program
    assert decision.prior_context_program_ids == (prior_program,)


def test_current_excluded_only_prevents_selection_of_same_sticky_prior_program():
    context = _context(
        ContextUse.PRIOR_CONTEXT_SELECTED,
        (ProgramId.SUMMER_CAMP,),
    )
    decision = _resolve("ბანაკის გარდა რა პროგრამა გაქვთ?", context=context)
    assert decision.outcome is ProgramResolutionOutcome.ABSENT
    assert decision.selected_program_id is None
    assert decision.excluded_program_ids == (ProgramId.SUMMER_CAMP,)
    assert decision.prior_context_program_ids == (ProgramId.SUMMER_CAMP,)
    assert decision.primary_reason is ProgramResolutionReason.CURRENT_EXCLUDED_ONLY


def test_current_ambiguity_is_not_resolved_by_selected_prior_context():
    context = _context(
        ContextUse.PRIOR_CONTEXT_SELECTED,
        (ProgramId.SUNDAY_SCHOOL,),
    )
    decision = _resolve(
        "ბანაკი და კულტურული საღამოები მაინტერესებს",
        context=context,
    )
    assert decision.outcome is ProgramResolutionOutcome.AMBIGUOUS
    assert decision.source is ProgramResolutionSource.CURRENT_MESSAGE
    assert decision.selected_program_id is None


@pytest.mark.parametrize("program_id", tuple(ProgramId))
def test_single_selected_prior_context_resolves_elliptical_program_question(
    program_id: ProgramId,
):
    decision = _resolve(
        "ფასი?",
        context=_context(ContextUse.PRIOR_CONTEXT_SELECTED, (program_id,)),
    )
    assert decision.outcome is ProgramResolutionOutcome.RESOLVED
    assert decision.source is ProgramResolutionSource.PRIOR_CONTEXT
    assert decision.selected_program_id is program_id
    assert decision.mentions == ()
    assert decision.prior_context_program_ids == (program_id,)
    assert decision.primary_reason is ProgramResolutionReason.PRIOR_CONTEXT_SELECTED


def test_multiple_eligible_prior_programs_remain_ambiguous():
    context = _context(
        ContextUse.AMBIGUOUS,
        (ProgramId.SUMMER_CAMP, ProgramId.ADULT_EVENTS),
    )
    decision = _resolve("სად ტარდება?", context=context)
    assert decision.outcome is ProgramResolutionOutcome.AMBIGUOUS
    assert decision.source is ProgramResolutionSource.PRIOR_CONTEXT
    assert decision.selected_program_id is None
    assert decision.prior_context_program_ids == (
        ProgramId.ADULT_EVENTS,
        ProgramId.SUMMER_CAMP,
    )
    assert decision.primary_reason is ProgramResolutionReason.PRIOR_CONTEXT_AMBIGUOUS


def test_assistant_fallback_only_context_is_never_selected():
    context = _context(
        ContextUse.PRIOR_CONTEXT_FALLBACK_ONLY,
        (ProgramId.ADULT_EVENTS,),
    )
    decision = _resolve("ფასი?", context=context)
    assert decision.outcome is ProgramResolutionOutcome.ABSENT
    assert decision.source is ProgramResolutionSource.NONE
    assert decision.selected_program_id is None
    assert decision.prior_context_program_ids == (ProgramId.ADULT_EVENTS,)
    assert decision.primary_reason is ProgramResolutionReason.PRIOR_CONTEXT_FALLBACK_ONLY


@pytest.mark.parametrize(
    "context_use",
    (
        ContextUse.BLOCKED,
        ContextUse.CURRENT_MESSAGE_AUTHORITATIVE,
        ContextUse.NO_RELEVANT_CONTEXT,
    ),
)
def test_nonselecting_context_without_current_identity_is_program_absent(
    context_use: ContextUse,
):
    decision = _resolve("ღონისძიება მაინტერესებს", context=_context(context_use))
    assert decision.outcome is ProgramResolutionOutcome.ABSENT
    assert decision.source is ProgramResolutionSource.NONE
    assert decision.selected_program_id is None
    assert decision.mentions == ()
    assert decision.primary_reason is ProgramResolutionReason.NO_PROGRAM_EVIDENCE


def test_referenced_only_decision_contract_is_closed_and_nonselecting():
    mention = _mention(role=ProgramMentionRole.REFERENCED)
    decision = ProgramResolutionDecision(
        outcome=ProgramResolutionOutcome.ABSENT,
        source=ProgramResolutionSource.NONE,
        selected_program_id=None,
        requested_program_ids=(),
        referenced_program_ids=(ProgramId.SUMMER_CAMP,),
        excluded_program_ids=(),
        prior_context_program_ids=(),
        mentions=(mention,),
        confidence=1.0,
        primary_reason=ProgramResolutionReason.CURRENT_REFERENCED_ONLY,
        evidence=("resolution.current_referenced_only",),
    )
    assert decision.selected_program_id is None


GENERIC_NON_INFERENCE_CASES = (
    "ბავშვისთვის რა გაქვთ?",
    "შვილისთვის პროგრამა მინდა",
    "მოზარდებისთვის რას გვთავაზობთ?",
    "ზრდასრულებისთვის რა გაქვთ?",
    "ღონისძიება მაინტერესებს",
    "საღამო მაინტერესებს",
    "ბილეთის ფასი მაინტერესებს",
    "სკოლა მაინტერესებს",
    "საზაფხულო პროგრამა მაინტერესებს",
    "პროგრამები რა გაქვთ?",
)


@pytest.mark.parametrize("text", GENERIC_NON_INFERENCE_CASES)
def test_generic_audience_and_topic_language_never_proves_program_identity(text: str):
    decision = _resolve(text)
    assert decision.outcome is ProgramResolutionOutcome.ABSENT
    assert decision.source is ProgramResolutionSource.NONE
    assert decision.selected_program_id is None
    assert decision.requested_program_ids == ()
    assert decision.referenced_program_ids == ()
    assert decision.excluded_program_ids == ()
    assert decision.primary_reason is ProgramResolutionReason.NO_PROGRAM_EVIDENCE


@pytest.mark.parametrize("text", GENERIC_NON_INFERENCE_CASES)
def test_real_unknown_generic_cases_stop_at_the_act_gate(text: str):
    _, act, _, _, decision = _real_chain(text)
    if act.act is ConversationAct.UNKNOWN:
        assert decision.outcome is ProgramResolutionOutcome.NOT_APPLICABLE
        assert decision.primary_reason is ProgramResolutionReason.ACT_NOT_ELIGIBLE


def test_cultural_evening_helper_contract_resolves_adult_events():
    decision = _assert_resolved(
        "კულტურული საღამოები მაინტერესებს",
        ProgramId.ADULT_EVENTS,
    )
    assert decision.primary_reason is ProgramResolutionReason.CURRENT_SINGLE_REQUESTED


def test_cultural_evening_real_chain_documents_current_phase3_seam():
    # TODO(Phase 3 cultural-evening seam): This exact program identity currently
    # resolves to UNKNOWN upstream. Phase 6 recognizes ADULT_EVENTS only when
    # supplied an eligible PROGRAM_QUESTION act. This real-chain test documents
    # current reachability and must change with the future Phase 3 seam patch.
    _, act, _, _, decision = _real_chain("კულტურული საღამოები მაინტერესებს")
    assert act.act is ConversationAct.UNKNOWN
    assert decision.outcome is ProgramResolutionOutcome.NOT_APPLICABLE
    assert decision.primary_reason is ProgramResolutionReason.ACT_NOT_ELIGIBLE


def test_elliptical_availability_real_chain_remains_unresolved_upstream():
    candidate = _candidate(ProgramId.SUMMER_CAMP)
    _, act, context, _, decision = _real_chain(
        "კიდევ არის ადგილი?",
        context_candidates=(candidate,),
    )
    assert act.act is ConversationAct.UNKNOWN
    assert context.context_use is ContextUse.BLOCKED
    assert decision.outcome is ProgramResolutionOutcome.NOT_APPLICABLE
    assert decision.primary_reason is ProgramResolutionReason.ACT_NOT_ELIGIBLE


@pytest.mark.parametrize(
    "text",
    [
        "ბანაკობა მაინტერესებს",
        "ბანაკოლოგია მაინტერესებს",
        "ლაგერობა მაინტერესებს",
        "სკოლამდელი პროგრამა მაინტერესებს",
        "ღონისძიებათაადმი ინტერესი მაქვს",
        "ზრდასრულობა მაინტერესებს",
        "კულტურულობა მაინტერესებს",
        "საღამოთი ვსეირნობ",
        "camping details?",
        "campsite details?",
        "event details?",
    ],
)
def test_identity_markers_are_bounded_and_do_not_match_arbitrary_extensions(text: str):
    decision = _resolve(text)
    assert decision.outcome is ProgramResolutionOutcome.ABSENT
    assert decision.mentions == ()


@pytest.mark.parametrize(
    "text",
    [
        "ბანაკა მაინტერესებს",
        "ბანაკული მაინტერესებს",
        "ბანაკთა მაინტერესებს",
        "საკვირაო სკოლული მაინტერესებს",
        "საკვირაო სკოლთა მაინტერესებს",
        "ზრდასრულთა ღონისძიებული მაინტერესებს",
    ],
)
def test_malformed_georgian_program_morphology_does_not_match_identity(text: str):
    decision = _resolve(text)
    assert decision.outcome is ProgramResolutionOutcome.ABSENT
    assert decision.mentions == ()


@pytest.mark.parametrize(
    "text,excluded,requested",
    [
        (
            "ბანაკი არა საკვირაო სკოლა მაინტერესებს",
            ProgramId.SUMMER_CAMP,
            ProgramId.SUNDAY_SCHOOL,
        ),
        (
            "ბანაკი არა, საკვირაო სკოლა მაინტერესებს",
            ProgramId.SUMMER_CAMP,
            ProgramId.SUNDAY_SCHOOL,
        ),
        (
            "ბანაკი არა — საკვირაო სკოლა მაინტერესებს",
            ProgramId.SUMMER_CAMP,
            ProgramId.SUNDAY_SCHOOL,
        ),
        (
            "ბანაკი არა - საკვირაო სკოლა მაინტერესებს",
            ProgramId.SUMMER_CAMP,
            ProgramId.SUNDAY_SCHOOL,
        ),
        (
            "საკვირაო სკოლა არა ბანაკი მაინტერესებს",
            ProgramId.SUNDAY_SCHOOL,
            ProgramId.SUMMER_CAMP,
        ),
        (
            "საკვირაო სკოლა არა, ბანაკი მაინტერესებს",
            ProgramId.SUNDAY_SCHOOL,
            ProgramId.SUMMER_CAMP,
        ),
        (
            "კულტურული საღამოები არა ბანაკი მაინტერესებს",
            ProgramId.ADULT_EVENTS,
            ProgramId.SUMMER_CAMP,
        ),
        (
            "კულტურული საღამოები არა, ბანაკი მაინტერესებს",
            ProgramId.ADULT_EVENTS,
            ProgramId.SUMMER_CAMP,
        ),
    ],
)
def test_punctuation_independent_ara_pivot_excludes_first_program(
    text: str,
    excluded: ProgramId,
    requested: ProgramId,
):
    decision = _assert_resolved(text, requested)
    assert decision.excluded_program_ids == (excluded,)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("ბანაკი არ გაქვთ?", ProgramId.SUMMER_CAMP),
        ("ბანაკი არაა?", ProgramId.SUMMER_CAMP),
        ("ბანაკი აღარ იქნება?", ProgramId.SUMMER_CAMP),
        ("ბანაკი არ ტარდება?", ProgramId.SUMMER_CAMP),
        ("ბანაკი მაინტერესებს არა მხოლოდ ზაფხულში", ProgramId.SUMMER_CAMP),
        ("ბანაკი არა მგონია მალე დაიწყოს", ProgramId.SUMMER_CAMP),
        ("ბანაკი ალბათ არა საკვირაო სკოლაა", ProgramId.SUMMER_CAMP),
    ],
)
def test_ara_pivot_does_not_turn_availability_or_modifier_questions_into_exclusions(
    text: str,
    expected: ProgramId,
):
    decision = _assert_resolved(text, expected)
    assert decision.excluded_program_ids == ()


def test_ara_pivot_does_not_invent_a_distinct_requested_program():
    decision = _resolve("ბანაკი არა")
    assert decision.outcome is ProgramResolutionOutcome.ABSENT
    assert decision.requested_program_ids == ()
    assert decision.excluded_program_ids == (ProgramId.SUMMER_CAMP,)


def test_araa_copula_does_not_trigger_exclusion_pivot_before_distinct_program():
    decision = _resolve("ბანაკი არაა საკვირაო სკოლა")
    assert decision.outcome is ProgramResolutionOutcome.AMBIGUOUS
    assert decision.requested_program_ids == (
        ProgramId.SUMMER_CAMP,
        ProgramId.SUNDAY_SCHOOL,
    )
    assert decision.excluded_program_ids == ()


@pytest.mark.parametrize(
    "text",
    [
        "ბანაკი არა მხოლოდ საკვირაო სკოლა მაინტერესებს",
        "ბანაკი არა მგონია საკვირაო სკოლა მაინტერესებდეს",
        "ბანაკი არა უბრალოდ საკვირაო სკოლა მაინტერესებს",
        "ბანაკი არა ახლა საკვირაო სკოლა მაინტერესებს",
        "ბანაკი ალბათ არა საკვირაო სკოლა მაინტერესებს",
    ],
)
def test_ara_pivot_requires_exact_intervening_lexical_sequence(text: str):
    decision = _resolve(text)
    assert decision.outcome is ProgramResolutionOutcome.AMBIGUOUS
    assert decision.requested_program_ids == (
        ProgramId.SUMMER_CAMP,
        ProgramId.SUNDAY_SCHOOL,
    )
    assert decision.excluded_program_ids == ()


def test_explicit_exclusion_grammar_still_works_without_exact_ara_pivot():
    decision = _assert_resolved(
        "ბანაკი არ მინდა, საკვირაო სკოლა მაინტერესებს",
        ProgramId.SUNDAY_SCHOOL,
    )
    assert decision.excluded_program_ids == (ProgramId.SUMMER_CAMP,)


def test_exact_ara_pivot_can_exclude_one_program_and_leave_two_requested():
    decision = _resolve(
        "ბანაკი არა საკვირაო სკოლა და კულტურული საღამოები მაინტერესებს"
    )
    assert decision.outcome is ProgramResolutionOutcome.AMBIGUOUS
    assert decision.requested_program_ids == (
        ProgramId.ADULT_EVENTS,
        ProgramId.SUNDAY_SCHOOL,
    )
    assert decision.excluded_program_ids == (ProgramId.SUMMER_CAMP,)
    assert decision.selected_program_id is None
    assert decision.primary_reason is ProgramResolutionReason.CURRENT_MULTIPLE_REQUESTED


def test_chained_exact_ara_pivots_apply_pairwise_and_deterministically():
    decision = _assert_resolved(
        "ბანაკი არა საკვირაო სკოლა არა კულტურული საღამოები მაინტერესებს",
        ProgramId.ADULT_EVENTS,
    )
    assert decision.requested_program_ids == (ProgramId.ADULT_EVENTS,)
    assert decision.excluded_program_ids == (
        ProgramId.SUMMER_CAMP,
        ProgramId.SUNDAY_SCHOOL,
    )


@pytest.mark.parametrize(
    "text",
    [
        "ბანაკი არა ლაგერი მაინტერესებს",
        "ბანაკი არა ბანაკის ფასი მაინტერესებს",
    ],
)
def test_exact_ara_pivot_requires_distinct_program_ids(text: str):
    decision = _assert_resolved(text, ProgramId.SUMMER_CAMP)
    assert decision.excluded_program_ids == ()


def test_ara_pivot_does_not_resolve_if_not_structured_as_direct_program_switch():
    decision = _resolve("ბანაკი თუ არა საკვირაო სკოლა?")
    assert decision.outcome is ProgramResolutionOutcome.AMBIGUOUS
    assert decision.requested_program_ids == (
        ProgramId.SUMMER_CAMP,
        ProgramId.SUNDAY_SCHOOL,
    )
    assert decision.excluded_program_ids == ()


def test_program_resolution_policy_shape_is_generic_and_program_scoped():
    assert {item.name for item in fields(ProgramResolutionPolicy)} == {
        "program_identity_definitions",
        "exclusion_following_phrases",
        "exclusion_leading_phrases",
        "reference_phrases",
        "pivot_tokens",
        "clause_boundary_tokens",
    }
    assert {
        "georgian_stem_suffixes",
        "summer_camp_stems",
        "summer_camp_exact_tokens",
        "summer_camp_phrases",
        "sunday_school_phrases",
        "adult_event_phrases",
    }.isdisjoint({item.name for item in fields(ProgramResolutionPolicy)})
    assert tuple(
        definition.program_id
        for definition in DEFAULT_PROGRAM_RESOLUTION_POLICY.program_identity_definitions
    ) == tuple(
        sorted(
            (definition.program_id for definition in PROGRAM_REGISTRY.all()),
            key=lambda item: item.value,
        )
    )


def test_program_identity_matching_is_config_driven_for_a_synthetic_token():
    from app.domain.decision.program_resolver import _identity_matches

    synthetic_definition = ProgramIdentityDefinition(
        ProgramId.SUMMER_CAMP,
        (
            ProgramPhraseRule(
                (
                    ProgramTokenRule(
                        exact_forms=("syntheticprogram",),
                        evidence_id="program.test.synthetic_token",
                    ),
                ),
                0,
                "program.test.synthetic_phrase",
            ),
        ),
        "program.test.synthetic_identity",
    )
    definitions = tuple(
        synthetic_definition
        if definition.program_id is ProgramId.SUMMER_CAMP
        else definition
        for definition in DEFAULT_PROGRAM_RESOLUTION_POLICY.program_identity_definitions
    )
    policy = replace(
        DEFAULT_PROGRAM_RESOLUTION_POLICY,
        program_identity_definitions=definitions,
    )
    message = normalize_message("syntheticprogram?")
    matches = _identity_matches(message, policy)
    assert tuple(
        (match.program_id, match.token_start, match.token_end, match.evidence_id)
        for match in matches
    ) == ((ProgramId.SUMMER_CAMP, 0, 1, "program.test.synthetic_phrase"),)

    decision = _resolve("syntheticprogram?", policy=policy)
    assert decision.outcome is ProgramResolutionOutcome.RESOLVED
    assert decision.selected_program_id is ProgramId.SUMMER_CAMP
    assert decision.evidence == (
        "resolution.current_single_requested",
        "program.test.synthetic_phrase",
    )


def test_program_resolver_has_no_program_specific_matcher_functions():
    tree = ast.parse(RESOLVER_PATH.read_text(encoding="utf-8"))
    function_names = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }
    assert {
        "_match_camp",
        "_match_sunday_school",
        "_match_adult_events",
    }.isdisjoint(function_names)


def test_program_resolver_matching_helpers_do_not_branch_on_concrete_program_ids():
    tree = ast.parse(RESOLVER_PATH.read_text(encoding="utf-8"))
    checked_functions = {
        "_matches_stem_rule",
        "_matches_token_rule",
        "_match_phrase_rule",
        "_match_identity_definition",
        "_best_identity_match_at",
        "_identity_matches",
        "_is_excluded",
        "_is_exclusion_pivot_source",
        "_assign_roles",
    }
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name not in checked_functions:
            continue
        concrete_refs = [
            child.attr
            for child in ast.walk(node)
            if isinstance(child, ast.Attribute)
            and isinstance(child.value, ast.Name)
            and child.value.id == "ProgramId"
        ]
        assert concrete_refs == [], node.name


def test_program_resolver_uses_generic_policy_identity_loop_and_phrase_matcher():
    tree = ast.parse(RESOLVER_PATH.read_text(encoding="utf-8"))
    functions = {
        node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }
    best_match = functions["_best_identity_match_at"]
    phrase_match = functions["_match_phrase_rule"]
    assert any(
        isinstance(node, ast.For)
        and isinstance(node.iter, ast.Attribute)
        and node.iter.attr == "program_identity_definitions"
        for node in ast.walk(best_match)
    )
    assert any(
        isinstance(node, ast.For)
        and any(
            isinstance(child, ast.Attribute) and child.attr == "components"
            for child in ast.walk(node.iter)
        )
        for node in ast.walk(phrase_match)
    )


def test_program_resolver_exact_ara_pivot_uses_full_intervening_span():
    source = RESOLVER_PATH.read_text(encoding="utf-8")
    assert "_first_alpha_index_after" not in source
    assert "first_intervening_token" not in source
    assert "_lexical_tokens_between_mentions" in source
    assert "_has_exact_exclusion_pivot_between" in source

    tree = ast.parse(source)
    functions = {
        node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }
    pivot_source = functions["_is_exclusion_pivot_source"]
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_has_exact_exclusion_pivot_between"
        for node in ast.walk(pivot_source)
    )


def test_evidence_and_repr_contain_no_raw_message_phone_or_private_identity():
    private_fragments = (
        "595123456",
        "ნიკოლოზი",
        "secret-token",
    )
    decision = _resolve(
        "ბანაკი მაინტერესებს, მე ვარ ნიკოლოზი 595123456 secret-token"
    )
    serialized = repr(decision)
    for fragment in private_fragments:
        assert fragment not in serialized
        assert all(fragment not in item for item in decision.evidence)
    assert all(item.startswith(("resolution.", "program.")) for item in decision.evidence)


def test_default_policy_contains_identity_grammar_only_not_business_or_copy_data():
    serialized = repr(DEFAULT_PROGRAM_RESOLUTION_POLICY).casefold()
    forbidden = (
        "price",
        "registration_url",
        "manager_phone",
        "lifecycle",
        "2150",
        "http",
        "response_copy",
    )
    assert not any(item in serialized for item in forbidden)
    assert "ბანაკ" in serialized
    assert "საკვირაო" in serialized
    assert "ზრდასრულ" in serialized


def test_program_registry_exact_alias_contract_is_unchanged():
    assert tuple(
        alias.value
        for definition in PROGRAM_REGISTRY.all()
        for alias in definition.aliases
    ) == ("summer_camp", "sunday_school", "adult_events")
    assert PROGRAM_REGISTRY.find_by_alias("ბანაკი") is None
    assert PROGRAM_REGISTRY.find_by_alias("კულტურული საღამოები") is None


def test_phase6_module_imports_only_standard_library_and_local_domain_modules():
    tree = ast.parse(RESOLVER_PATH.read_text(encoding="utf-8"))
    imports: set[str] = set()
    relative_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                relative_modules.add(node.module or "")
            elif node.module:
                imports.add(node.module)
    assert imports <= {"__future__", "dataclasses"}
    assert relative_modules == {"models", "program_registry"}


def test_phase6_source_has_no_runtime_service_external_io_or_side_effect_dependency():
    source = RESOLVER_PATH.read_text(encoding="utf-8")
    forbidden_fragments = (
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
        "Path(",
        "open(",
        "write_text",
        "write_bytes",
        "socket",
        "subprocess",
        "response_text",
        "answer_copy",
    )
    assert not any(fragment in source for fragment in forbidden_fragments)


def test_phase6_does_not_import_or_modify_phase2_through_phase5_resolvers():
    source = RESOLVER_PATH.read_text(encoding="utf-8")
    assert "from .input_normalizer import" not in source
    assert "from .conversation_act import" not in source
    assert "from .context_arbiter import" not in source
    assert "from .pending_workflow import" not in source


def test_public_package_exports_every_phase6_contract():
    import app.domain.decision as decision

    expected = {
        "ProgramResolutionError",
        "ProgramMentionRole",
        "ProgramResolutionOutcome",
        "ProgramResolutionSource",
        "ProgramResolutionReason",
        "ProgramMention",
        "ProgramStemRule",
        "ProgramTokenRule",
        "ProgramPhraseRule",
        "ProgramIdentityDefinition",
        "ProgramResolutionPolicy",
        "ProgramResolutionDecision",
        "DEFAULT_PROGRAM_RESOLUTION_POLICY",
        "resolve_program",
    }
    assert expected <= set(decision.__all__)
    assert all(hasattr(decision, name) for name in expected)


def test_decision_package_import_and_phase6_call_are_environment_independent():
    script = (
        "from app.domain.decision import *; "
        "m=normalize_message('camp?'); "
        "a=ConversationActDecision(ConversationAct.PROGRAM_QUESTION,0.9,"
        "ConversationActReason.GENERIC_PROGRAM_QUESTION,('test',),"
        "(ConversationAct.PROGRAM_QUESTION,)); "
        "c=ContextArbitrationDecision(ContextUse.NO_RELEVANT_CONTEXT,None,(),(),(),"
        "0.0,ContextArbitrationReason.NO_CONTEXT_CANDIDATES,('test',)); "
        "p=PendingWorkflowDecision(PendingWorkflowAction.NO_PENDING_WORKFLOW,None,"
        "(),(),(),1.0,PendingWorkflowReason.NO_WORKFLOW_SUPPLIED,('test',)); "
        "assert resolve_program(m,a,c,p).selected_program_id is ProgramId.SUMMER_CAMP"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
