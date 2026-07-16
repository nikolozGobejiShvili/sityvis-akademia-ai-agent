"""Pure arbitration of prior program-context relevance."""
from __future__ import annotations

from .models import (
    ContextArbitrationDecision,
    ContextArbitrationError,
    ContextArbitrationPolicy,
    ContextArbitrationReason,
    ContextSource,
    ContextUse,
    ConversationAct,
    ConversationActDecision,
    NormalizedMessage,
    ProgramContextCandidate,
    ProgramId,
)


DEFAULT_CONTEXT_ARBITRATION_POLICY = ContextArbitrationPolicy()

_BLOCKING_ACTS = frozenset(
    (
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
)

_RESET_MARKERS = frozenset(("სხვა", "გარდა", "ნაცვლად", "აღარ"))
_RESET_PHRASES = (
    ("არ", "მინდა"),
    ("სხვა", "თემაზე"),
    ("ამის", "გარდა"),
    ("ამის", "ნაცვლად"),
)
_ELLIPTICAL_SINGLE_WORDS = frozenset(("ფასი", "სად", "როდის", "რამდენი"))
_ELLIPTICAL_QUESTION_WORDS = frozenset(("სად", "როდის", "რამდენი"))
_CONTINUATION_MARKERS = frozenset(("და", "კიდევ", "ხოლო"))

_SOURCE_STRENGTH = {
    ContextSource.USER_CONFIRMED_PROGRAM: 3,
    ContextSource.USER_EXPLICIT_PROGRAM: 2,
    ContextSource.ASSISTANT_REFERENCED_PROGRAM: 1,
    ContextSource.LEGACY_STICKY_STATE: 0,
    ContextSource.LEGACY_SEGMENT_INFERENCE: 0,
}
_LEGACY_SOURCES = frozenset(
    (
        ContextSource.LEGACY_STICKY_STATE,
        ContextSource.LEGACY_SEGMENT_INFERENCE,
    )
)
_STRONG_SOURCES = frozenset(
    (
        ContextSource.USER_CONFIRMED_PROGRAM,
        ContextSource.USER_EXPLICIT_PROGRAM,
    )
)


def _word_tokens(message: NormalizedMessage) -> tuple[str, ...]:
    return tuple(
        token.casefold()
        for token in message.comparison_tokens
        if token.isalpha()
    )


def _contains_phrase(
    words: tuple[str, ...],
    phrase: tuple[str, ...],
) -> bool:
    width = len(phrase)
    if width > len(words):
        return False
    return any(
        words[index : index + width] == phrase
        for index in range(len(words) - width + 1)
    )


def _has_context_reset(words: tuple[str, ...]) -> bool:
    if any(word in _RESET_MARKERS for word in words):
        return True
    return any(_contains_phrase(words, phrase) for phrase in _RESET_PHRASES)


def _is_structurally_elliptical(
    message: NormalizedMessage,
    words: tuple[str, ...],
) -> bool:
    if not words or "?" not in message.normalized_text:
        return False
    if len(words) == 1:
        return words[0] in _ELLIPTICAL_SINGLE_WORDS
    if len(words) <= 3 and words[0] in _CONTINUATION_MARKERS:
        return True
    if len(words) <= 2 and words[0] in _ELLIPTICAL_QUESTION_WORDS:
        return True
    return False


def _candidate_sort_key(
    candidate: ProgramContextCandidate,
) -> tuple[str, int, int, str]:
    return (
        candidate.program_id.value,
        -_SOURCE_STRENGTH[candidate.source],
        candidate.turn_distance,
        candidate.source.value,
    )


def _is_fresh(
    candidate: ProgramContextCandidate,
    policy: ContextArbitrationPolicy,
) -> bool:
    if candidate.source in _STRONG_SOURCES:
        return (
            candidate.turn_distance
            <= policy.strong_context_max_turn_distance
        )
    if candidate.source is ContextSource.ASSISTANT_REFERENCED_PROGRAM:
        return (
            candidate.turn_distance
            <= policy.assistant_context_max_turn_distance
        )
    return False


def _decision(
    context_use: ContextUse,
    reason: ContextArbitrationReason,
    confidence: float,
    *,
    selected_program_id: ProgramId | None = None,
    eligible_candidates: tuple[ProgramContextCandidate, ...] = (),
    rejected_candidates: tuple[ProgramContextCandidate, ...] = (),
    evidence: tuple[str, ...],
) -> ContextArbitrationDecision:
    eligible_program_ids = tuple(
        sorted(
            {candidate.program_id for candidate in eligible_candidates},
            key=lambda item: item.value,
        )
    )
    return ContextArbitrationDecision(
        context_use=context_use,
        selected_program_id=selected_program_id,
        eligible_program_ids=eligible_program_ids,
        eligible_candidates=eligible_candidates,
        rejected_candidates=rejected_candidates,
        confidence=confidence,
        primary_reason=reason,
        evidence=evidence,
    )


def _consolidate_candidates(
    candidates: tuple[ProgramContextCandidate, ...],
    policy: ContextArbitrationPolicy,
) -> tuple[
    tuple[ProgramContextCandidate, ...],
    tuple[ProgramContextCandidate, ...],
]:
    unique_candidates = tuple(sorted(set(candidates), key=_candidate_sort_key))
    fresh_by_program: dict[ProgramId, list[ProgramContextCandidate]] = {}
    rejected: list[ProgramContextCandidate] = []

    for candidate in unique_candidates:
        if candidate.source in _LEGACY_SOURCES or not _is_fresh(
            candidate, policy
        ):
            rejected.append(candidate)
            continue
        fresh_by_program.setdefault(candidate.program_id, []).append(candidate)

    eligible: list[ProgramContextCandidate] = []
    for program_id in sorted(fresh_by_program, key=lambda item: item.value):
        ranked = sorted(fresh_by_program[program_id], key=_candidate_sort_key)
        eligible.append(ranked[0])
        rejected.extend(ranked[1:])

    return (
        tuple(sorted(eligible, key=_candidate_sort_key)),
        tuple(sorted(rejected, key=_candidate_sort_key)),
    )


def arbitrate_context(
    message: NormalizedMessage,
    conversation_act: ConversationActDecision,
    context_candidates: tuple[ProgramContextCandidate, ...],
    policy: ContextArbitrationPolicy = DEFAULT_CONTEXT_ARBITRATION_POLICY,
) -> ContextArbitrationDecision:
    """Decide whether supplied prior program context may influence resolution."""

    if not isinstance(message, NormalizedMessage):
        raise TypeError("message must be NormalizedMessage")
    if not isinstance(conversation_act, ConversationActDecision):
        raise TypeError(
            "conversation_act must be ConversationActDecision"
        )
    if not isinstance(context_candidates, tuple):
        raise TypeError("context_candidates must be an immutable tuple")
    if not all(
        isinstance(candidate, ProgramContextCandidate)
        for candidate in context_candidates
    ):
        raise ContextArbitrationError(
            "context_candidates must contain ProgramContextCandidate values"
        )
    if not isinstance(policy, ContextArbitrationPolicy):
        raise TypeError("policy must be ContextArbitrationPolicy")

    act = conversation_act.act
    if act in _BLOCKING_ACTS:
        return _decision(
            ContextUse.BLOCKED,
            ContextArbitrationReason.ACT_BLOCKS_CONTEXT,
            0.0,
            rejected_candidates=tuple(
                sorted(set(context_candidates), key=_candidate_sort_key)
            ),
            evidence=(f"act.blocked.{act.value}",),
        )
    if act is ConversationAct.CLARIFICATION:
        return _decision(
            ContextUse.BLOCKED,
            ContextArbitrationReason.CLARIFICATION_DOES_NOT_SELECT_CONTEXT,
            0.0,
            rejected_candidates=tuple(
                sorted(set(context_candidates), key=_candidate_sort_key)
            ),
            evidence=("act.clarification.no_program_selection",),
        )
    if act is not ConversationAct.PROGRAM_QUESTION:
        raise ContextArbitrationError("conversation act is unsupported")

    words = _word_tokens(message)
    if _has_context_reset(words):
        return _decision(
            ContextUse.CURRENT_MESSAGE_AUTHORITATIVE,
            ContextArbitrationReason.CONTEXT_RESET_OR_EXCLUSION,
            0.0,
            rejected_candidates=tuple(
                sorted(set(context_candidates), key=_candidate_sort_key)
            ),
            evidence=("message.context_reset_or_exclusion",),
        )
    if not _is_structurally_elliptical(message, words):
        return _decision(
            ContextUse.CURRENT_MESSAGE_AUTHORITATIVE,
            ContextArbitrationReason.CURRENT_MESSAGE_SUBSTANTIVE,
            0.0,
            rejected_candidates=tuple(
                sorted(set(context_candidates), key=_candidate_sort_key)
            ),
            evidence=("message.current_authoritative",),
        )
    if not context_candidates:
        return _decision(
            ContextUse.NO_RELEVANT_CONTEXT,
            ContextArbitrationReason.NO_CONTEXT_CANDIDATES,
            0.0,
            evidence=("context.none_supplied",),
        )

    eligible, rejected = _consolidate_candidates(
        context_candidates,
        policy,
    )
    if len(eligible) > 1:
        return _decision(
            ContextUse.AMBIGUOUS,
            ContextArbitrationReason.CONFLICTING_FRESH_CONTEXTS,
            0.20,
            eligible_candidates=eligible,
            rejected_candidates=rejected,
            evidence=("context.multiple_fresh_programs",),
        )
    if len(eligible) == 1:
        candidate = eligible[0]
        if candidate.source in _STRONG_SOURCES:
            confidence = (
                0.98
                if candidate.source is ContextSource.USER_CONFIRMED_PROGRAM
                else 0.94
            )
            return _decision(
                ContextUse.PRIOR_CONTEXT_SELECTED,
                ContextArbitrationReason.SINGLE_FRESH_STRONG_CONTEXT,
                confidence,
                selected_program_id=candidate.program_id,
                eligible_candidates=eligible,
                rejected_candidates=rejected,
                evidence=(
                    f"context.selected.{candidate.source.value}",
                    f"context.turn_distance.{candidate.turn_distance}",
                ),
            )
        if policy.allow_assistant_context_selection:
            return _decision(
                ContextUse.PRIOR_CONTEXT_SELECTED,
                ContextArbitrationReason.SINGLE_FRESH_ASSISTANT_CONTEXT,
                0.70,
                selected_program_id=candidate.program_id,
                eligible_candidates=eligible,
                rejected_candidates=rejected,
                evidence=(
                    "context.selected.assistant_reference",
                    f"context.turn_distance.{candidate.turn_distance}",
                ),
            )
        return _decision(
            ContextUse.PRIOR_CONTEXT_FALLBACK_ONLY,
            ContextArbitrationReason.ASSISTANT_CONTEXT_FALLBACK_ONLY,
            0.40,
            eligible_candidates=eligible,
            rejected_candidates=rejected,
            evidence=("context.assistant_reference.fallback_only",),
        )

    has_legacy = any(
        candidate.source in _LEGACY_SOURCES for candidate in rejected
    )
    has_stale = any(
        candidate.source not in _LEGACY_SOURCES for candidate in rejected
    )
    if has_stale:
        reason = ContextArbitrationReason.STALE_CONTEXT_ONLY
        evidence = ("context.stale_only",)
    elif has_legacy:
        reason = ContextArbitrationReason.LEGACY_CONTEXT_NON_AUTHORITATIVE
        evidence = ("context.legacy_non_authoritative",)
    else:
        reason = ContextArbitrationReason.NO_ELIGIBLE_CONTEXT
        evidence = ("context.none_eligible",)
    return _decision(
        ContextUse.NO_RELEVANT_CONTEXT,
        reason,
        0.05,
        rejected_candidates=rejected,
        evidence=evidence,
    )
