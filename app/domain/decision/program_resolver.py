"""Pure deterministic resolution of current and eligible prior programs."""
from __future__ import annotations

from dataclasses import dataclass

from .models import (
    ContextArbitrationDecision,
    ContextUse,
    ConversationAct,
    ConversationActDecision,
    NormalizedMessage,
    PendingWorkflowAction,
    PendingWorkflowDecision,
    ProgramId,
    ProgramMention,
    ProgramMentionRole,
    ProgramResolutionDecision,
    ProgramResolutionError,
    ProgramResolutionOutcome,
    ProgramResolutionPolicy,
    ProgramResolutionReason,
    ProgramResolutionSource,
)
from .program_registry import PROGRAM_REGISTRY, ProgramRegistry


DEFAULT_PROGRAM_RESOLUTION_POLICY = ProgramResolutionPolicy(
    georgian_stem_suffixes=(
        "ა",
        "ი",
        "ო",
        "ს",
        "ის",
        "ში",
        "ზე",
        "ით",
        "მა",
        "თან",
        "ამდე",
        "იდან",
        "ები",
        "ებმა",
        "ებს",
        "ების",
        "ებში",
        "ებზე",
        "ებიდან",
        "თა",
        "თვის",
        "ისთვის",
        "ებისთვის",
        "აში",
        "აზე",
        "ული",
    ),
    summer_camp_stems=("ბანაკ", "ლაგერ"),
    summer_camp_exact_tokens=("camp",),
    summer_camp_modifier_tokens=("საზაფხულო", "ბავშვთა"),
    summer_camp_phrases=(("summer", "camp"), ("summer-camp",)),
    sunday_school_lead_tokens=("საკვირაო",),
    sunday_school_school_stems=("სკოლ",),
    sunday_school_compound_tokens=(
        "საკვირაოსკოლა",
        "sunday-school",
        "sundayschool",
    ),
    sunday_school_phrases=(("sunday", "school"),),
    adult_audience_stems=("ზრდასრულ",),
    adult_event_identity_stems=("ღონისძიებ", "კულტურ", "საღამო"),
    adult_cultural_stems=("კულტურულ",),
    adult_evening_stems=("საღამო",),
    adult_event_phrases=(
        ("adult", "events"),
        ("adult", "event"),
        ("adult-events",),
        ("cultural", "evenings"),
        ("cultural", "evening"),
        ("cultural-evenings",),
    ),
    exclusion_following_phrases=(
        ("გარდა",),
        ("ნაცვლად",),
        ("არ", "მინდა"),
        ("არ", "მაინტერესებს"),
        ("არ", "გეკითხები"),
        ("შესახებ", "არ", "ვკითხულობ"),
        ("არა",),
    ),
    exclusion_leading_phrases=(
        ("არ", "მინდა"),
        ("არ", "მაინტერესებს"),
        ("არ", "გეკითხები"),
        ("არ", "ვკითხულობ"),
    ),
    reference_phrases=(
        ("ადრე", "ვსაუბრობდით"),
        ("რომ", "ვსაუბრობდით"),
        ("რომ", "ახსენეთ"),
    ),
    pivot_tokens=("ახლა",),
    clause_boundary_tokens=(",", ";", ".", "?", "!"),
)


@dataclass(frozen=True, slots=True)
class _IdentityMatch:
    program_id: ProgramId
    token_start: int
    token_end: int
    evidence_id: str


def _matches_bounded_stem(
    token: str,
    stems: tuple[str, ...],
    suffixes: tuple[str, ...],
) -> bool:
    return any(
        token == stem
        or (
            token.startswith(stem)
            and token[len(stem) :] in suffixes
        )
        for stem in stems
    )


def _matches_phrase(
    tokens: tuple[str, ...],
    start: int,
    phrase: tuple[str, ...],
) -> bool:
    end = start + len(phrase)
    return end <= len(tokens) and tokens[start:end] == phrase


def _match_any_phrase(
    tokens: tuple[str, ...],
    start: int,
    phrases: tuple[tuple[str, ...], ...],
) -> tuple[str, ...] | None:
    matches = tuple(
        phrase for phrase in phrases if _matches_phrase(tokens, start, phrase)
    )
    if not matches:
        return None
    return sorted(matches, key=lambda item: (-len(item), item))[0]


def _match_identity_at(
    tokens: tuple[str, ...],
    start: int,
    policy: ProgramResolutionPolicy,
) -> _IdentityMatch | None:
    token = tokens[start]

    if token in policy.sunday_school_compound_tokens:
        return _IdentityMatch(
            ProgramId.SUNDAY_SCHOOL,
            start,
            start + 1,
            "program.sunday_school.compound",
        )
    if (
        token in policy.sunday_school_lead_tokens
        and start + 1 < len(tokens)
        and _matches_bounded_stem(
            tokens[start + 1],
            policy.sunday_school_school_stems,
            policy.georgian_stem_suffixes,
        )
    ):
        return _IdentityMatch(
            ProgramId.SUNDAY_SCHOOL,
            start,
            start + 2,
            "program.sunday_school.georgian_compound",
        )
    phrase = _match_any_phrase(tokens, start, policy.sunday_school_phrases)
    if phrase is not None:
        return _IdentityMatch(
            ProgramId.SUNDAY_SCHOOL,
            start,
            start + len(phrase),
            "program.sunday_school.english_compound",
        )

    phrase = _match_any_phrase(tokens, start, policy.adult_event_phrases)
    if phrase is not None:
        return _IdentityMatch(
            ProgramId.ADULT_EVENTS,
            start,
            start + len(phrase),
            "program.adult_events.direct_phrase",
        )
    if (
        _matches_bounded_stem(
            token,
            policy.adult_cultural_stems,
            policy.georgian_stem_suffixes,
        )
        and start + 1 < len(tokens)
        and _matches_bounded_stem(
            tokens[start + 1],
            policy.adult_evening_stems,
            policy.georgian_stem_suffixes,
        )
    ):
        return _IdentityMatch(
            ProgramId.ADULT_EVENTS,
            start,
            start + 2,
            "program.adult_events.cultural_evening",
        )
    if _matches_bounded_stem(
        token,
        policy.adult_audience_stems,
        policy.georgian_stem_suffixes,
    ):
        identity_end = None
        for index in range(start + 1, min(start + 3, len(tokens))):
            if _matches_bounded_stem(
                tokens[index],
                policy.adult_event_identity_stems,
                policy.georgian_stem_suffixes,
            ):
                identity_end = index + 1
        if identity_end is not None:
            return _IdentityMatch(
                ProgramId.ADULT_EVENTS,
                start,
                identity_end,
                "program.adult_events.audience_identity",
            )

    phrase = _match_any_phrase(tokens, start, policy.summer_camp_phrases)
    if phrase is not None:
        return _IdentityMatch(
            ProgramId.SUMMER_CAMP,
            start,
            start + len(phrase),
            "program.summer_camp.direct_phrase",
        )
    if (
        token in policy.summer_camp_modifier_tokens
        and start + 1 < len(tokens)
        and _matches_bounded_stem(
            tokens[start + 1],
            policy.summer_camp_stems,
            policy.georgian_stem_suffixes,
        )
    ):
        return _IdentityMatch(
            ProgramId.SUMMER_CAMP,
            start,
            start + 2,
            "program.summer_camp.modified_identity",
        )
    if _matches_bounded_stem(
        token,
        policy.summer_camp_stems,
        policy.georgian_stem_suffixes,
    ):
        return _IdentityMatch(
            ProgramId.SUMMER_CAMP,
            start,
            start + 1,
            "program.summer_camp.georgian_stem",
        )
    if token in policy.summer_camp_exact_tokens:
        return _IdentityMatch(
            ProgramId.SUMMER_CAMP,
            start,
            start + 1,
            "program.summer_camp.exact_token",
        )
    return None


def _identity_matches(
    message: NormalizedMessage,
    policy: ProgramResolutionPolicy,
) -> tuple[_IdentityMatch, ...]:
    tokens = tuple(token.casefold() for token in message.comparison_tokens)
    matches: list[_IdentityMatch] = []
    index = 0
    while index < len(tokens):
        match = _match_identity_at(tokens, index, policy)
        if match is None:
            index += 1
            continue
        matches.append(match)
        index = match.token_end
    return tuple(matches)


def _clause_start(
    tokens: tuple[str, ...],
    index: int,
    boundaries: tuple[str, ...],
) -> int:
    boundary_set = frozenset(boundaries)
    for cursor in range(index - 1, -1, -1):
        if tokens[cursor] in boundary_set:
            return cursor + 1
    return 0


def _clause_end(
    tokens: tuple[str, ...],
    index: int,
    boundaries: tuple[str, ...],
) -> int:
    boundary_set = frozenset(boundaries)
    for cursor in range(index, len(tokens)):
        if tokens[cursor] in boundary_set:
            return cursor
    return len(tokens)


def _word_slice(
    tokens: tuple[str, ...],
    start: int,
    end: int,
) -> tuple[str, ...]:
    return tuple(token for token in tokens[start:end] if token.isalpha())


def _starts_with_phrase(
    words: tuple[str, ...],
    phrase: tuple[str, ...],
) -> bool:
    return words[: len(phrase)] == phrase


def _ends_with_phrase(
    words: tuple[str, ...],
    phrase: tuple[str, ...],
) -> bool:
    return len(words) >= len(phrase) and words[-len(phrase) :] == phrase


def _contains_phrase(
    words: tuple[str, ...],
    phrase: tuple[str, ...],
) -> bool:
    width = len(phrase)
    return any(
        words[index : index + width] == phrase
        for index in range(len(words) - width + 1)
    )


def _is_excluded(
    match: _IdentityMatch,
    tokens: tuple[str, ...],
    policy: ProgramResolutionPolicy,
) -> bool:
    before = _word_slice(
        tokens,
        _clause_start(
            tokens,
            match.token_start,
            policy.clause_boundary_tokens,
        ),
        match.token_start,
    )
    after = _word_slice(
        tokens,
        match.token_end,
        _clause_end(
            tokens,
            match.token_end,
            policy.clause_boundary_tokens,
        ),
    )

    if any(
        _ends_with_phrase(before, phrase)
        for phrase in policy.exclusion_leading_phrases
    ):
        return True
    for phrase in policy.exclusion_following_phrases:
        if phrase == ("არა",):
            if after == phrase:
                return True
            continue
        if _starts_with_phrase(after, phrase):
            return True
    return False


def _has_reference_signal(
    match: _IdentityMatch,
    pivot_index: int,
    tokens: tuple[str, ...],
    policy: ProgramResolutionPolicy,
) -> bool:
    between = _word_slice(tokens, match.token_end, pivot_index)
    return any(
        _contains_phrase(between, phrase)
        for phrase in policy.reference_phrases
    )


def _assign_roles(
    matches: tuple[_IdentityMatch, ...],
    message: NormalizedMessage,
    policy: ProgramResolutionPolicy,
) -> tuple[ProgramMention, ...]:
    tokens = tuple(token.casefold() for token in message.comparison_tokens)
    preliminary = tuple(
        (
            match,
            ProgramMentionRole.EXCLUDED
            if _is_excluded(match, tokens, policy)
            else ProgramMentionRole.REQUESTED,
        )
        for match in matches
    )
    pivot_indices = tuple(
        index
        for index, token in enumerate(tokens)
        if token in policy.pivot_tokens
    )

    mentions: list[ProgramMention] = []
    for match, role in preliminary:
        if role is ProgramMentionRole.REQUESTED:
            for pivot_index in pivot_indices:
                if match.token_end > pivot_index:
                    continue
                has_distinct_current_target = any(
                    other_role is ProgramMentionRole.REQUESTED
                    and other.token_start > pivot_index
                    and other.program_id is not match.program_id
                    for other, other_role in preliminary
                )
                if has_distinct_current_target and _has_reference_signal(
                    match,
                    pivot_index,
                    tokens,
                    policy,
                ):
                    role = ProgramMentionRole.REFERENCED
                    break
        mentions.append(
            ProgramMention(
                program_id=match.program_id,
                role=role,
                token_start=match.token_start,
                token_end=match.token_end,
                evidence_id=match.evidence_id,
            )
        )

    return tuple(
        sorted(
            set(mentions),
            key=lambda item: (
                item.token_start,
                item.token_end,
                item.program_id.value,
                item.role.value,
                item.evidence_id,
            ),
        )
    )


def _sorted_program_ids(
    values: tuple[ProgramId, ...] | set[ProgramId],
) -> tuple[ProgramId, ...]:
    return tuple(sorted(set(values), key=lambda item: item.value))


def _role_program_ids(
    mentions: tuple[ProgramMention, ...],
    role: ProgramMentionRole,
) -> tuple[ProgramId, ...]:
    return _sorted_program_ids(
        tuple(
            mention.program_id
            for mention in mentions
            if mention.role is role
        )
    )


def _unique_evidence(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _decision(
    outcome: ProgramResolutionOutcome,
    source: ProgramResolutionSource,
    reason: ProgramResolutionReason,
    confidence: float,
    *,
    selected_program_id: ProgramId | None = None,
    prior_context_program_ids: tuple[ProgramId, ...] = (),
    mentions: tuple[ProgramMention, ...] = (),
    evidence: tuple[str, ...] = (),
) -> ProgramResolutionDecision:
    decision_evidence = _unique_evidence(
        (f"resolution.{reason.value}",)
        + evidence
        + tuple(mention.evidence_id for mention in mentions)
    )
    return ProgramResolutionDecision(
        outcome=outcome,
        source=source,
        selected_program_id=selected_program_id,
        requested_program_ids=_role_program_ids(
            mentions, ProgramMentionRole.REQUESTED
        ),
        referenced_program_ids=_role_program_ids(
            mentions, ProgramMentionRole.REFERENCED
        ),
        excluded_program_ids=_role_program_ids(
            mentions, ProgramMentionRole.EXCLUDED
        ),
        prior_context_program_ids=_sorted_program_ids(
            prior_context_program_ids
        ),
        mentions=mentions,
        confidence=confidence,
        primary_reason=reason,
        evidence=decision_evidence,
    )


def _validate_inputs(
    message: NormalizedMessage,
    conversation_act: ConversationActDecision,
    context_decision: ContextArbitrationDecision,
    pending_decision: PendingWorkflowDecision,
    registry: ProgramRegistry,
    policy: ProgramResolutionPolicy,
) -> None:
    contracts = (
        (message, NormalizedMessage, "message must be NormalizedMessage"),
        (
            conversation_act,
            ConversationActDecision,
            "conversation_act must be ConversationActDecision",
        ),
        (
            context_decision,
            ContextArbitrationDecision,
            "context_decision must be ContextArbitrationDecision",
        ),
        (
            pending_decision,
            PendingWorkflowDecision,
            "pending_decision must be PendingWorkflowDecision",
        ),
        (registry, ProgramRegistry, "registry must be ProgramRegistry"),
        (
            policy,
            ProgramResolutionPolicy,
            "policy must be ProgramResolutionPolicy",
        ),
    )
    for value, expected_type, error in contracts:
        if not isinstance(value, expected_type):
            raise ProgramResolutionError(error)


def _validate_registry_membership(
    registry: ProgramRegistry,
    program_ids: tuple[ProgramId, ...],
) -> None:
    unsupported = tuple(
        program_id
        for program_id in program_ids
        if registry.get(program_id) is None
    )
    if unsupported:
        raise ProgramResolutionError(
            "program resolution references an unregistered program"
        )


def resolve_program(
    message: NormalizedMessage,
    conversation_act: ConversationActDecision,
    context_decision: ContextArbitrationDecision,
    pending_decision: PendingWorkflowDecision,
    registry: ProgramRegistry = PROGRAM_REGISTRY,
    policy: ProgramResolutionPolicy = DEFAULT_PROGRAM_RESOLUTION_POLICY,
) -> ProgramResolutionDecision:
    """Resolve one canonical program without runtime state or side effects."""

    _validate_inputs(
        message,
        conversation_act,
        context_decision,
        pending_decision,
        registry,
        policy,
    )
    prior_program_ids = context_decision.eligible_program_ids
    _validate_registry_membership(registry, prior_program_ids)

    if (
        pending_decision.action
        is PendingWorkflowAction.CONTINUE_PENDING_WORKFLOW
    ):
        return _decision(
            ProgramResolutionOutcome.NOT_APPLICABLE,
            ProgramResolutionSource.NONE,
            ProgramResolutionReason.PENDING_REPLY_CONSUMED,
            1.0,
            prior_context_program_ids=prior_program_ids,
            evidence=("gate.pending_workflow.consumed",),
        )

    if conversation_act.act is not ConversationAct.PROGRAM_QUESTION:
        return _decision(
            ProgramResolutionOutcome.NOT_APPLICABLE,
            ProgramResolutionSource.NONE,
            ProgramResolutionReason.ACT_NOT_ELIGIBLE,
            1.0,
            prior_context_program_ids=prior_program_ids,
            evidence=(f"gate.act.{conversation_act.act.value}",),
        )

    mentions = _assign_roles(
        _identity_matches(message, policy),
        message,
        policy,
    )
    if any(mention.token_end > len(message.tokens) for mention in mentions):
        raise ProgramResolutionError(
            "mention span exceeds normalized message tokens"
        )
    _validate_registry_membership(
        registry,
        tuple(mention.program_id for mention in mentions),
    )

    requested = set(
        _role_program_ids(mentions, ProgramMentionRole.REQUESTED)
    )
    referenced = set(
        _role_program_ids(mentions, ProgramMentionRole.REFERENCED)
    )
    excluded = set(
        _role_program_ids(mentions, ProgramMentionRole.EXCLUDED)
    )

    if mentions:
        if requested & excluded:
            return _decision(
                ProgramResolutionOutcome.AMBIGUOUS,
                ProgramResolutionSource.CURRENT_MESSAGE,
                ProgramResolutionReason.CURRENT_CONTRADICTORY_ROLES,
                1.0,
                prior_context_program_ids=prior_program_ids,
                mentions=mentions,
            )
        if len(requested) > 1:
            return _decision(
                ProgramResolutionOutcome.AMBIGUOUS,
                ProgramResolutionSource.CURRENT_MESSAGE,
                ProgramResolutionReason.CURRENT_MULTIPLE_REQUESTED,
                1.0,
                prior_context_program_ids=prior_program_ids,
                mentions=mentions,
            )
        if len(requested) == 1:
            selected = next(iter(requested))
            return _decision(
                ProgramResolutionOutcome.RESOLVED,
                ProgramResolutionSource.CURRENT_MESSAGE,
                ProgramResolutionReason.CURRENT_SINGLE_REQUESTED,
                0.99,
                selected_program_id=selected,
                prior_context_program_ids=prior_program_ids,
                mentions=mentions,
            )
        if excluded:
            return _decision(
                ProgramResolutionOutcome.ABSENT,
                ProgramResolutionSource.NONE,
                ProgramResolutionReason.CURRENT_EXCLUDED_ONLY,
                1.0,
                prior_context_program_ids=prior_program_ids,
                mentions=mentions,
            )
        if referenced:
            return _decision(
                ProgramResolutionOutcome.ABSENT,
                ProgramResolutionSource.NONE,
                ProgramResolutionReason.CURRENT_REFERENCED_ONLY,
                1.0,
                prior_context_program_ids=prior_program_ids,
                mentions=mentions,
            )

    if context_decision.context_use is ContextUse.PRIOR_CONTEXT_SELECTED:
        selected = context_decision.selected_program_id
        if selected is None:
            raise ProgramResolutionError(
                "selected prior context is missing its program"
            )
        _validate_registry_membership(registry, (selected,))
        return _decision(
            ProgramResolutionOutcome.RESOLVED,
            ProgramResolutionSource.PRIOR_CONTEXT,
            ProgramResolutionReason.PRIOR_CONTEXT_SELECTED,
            context_decision.confidence,
            selected_program_id=selected,
            prior_context_program_ids=prior_program_ids,
            evidence=("context.prior.selected",),
        )
    if context_decision.context_use is ContextUse.AMBIGUOUS:
        if len(prior_program_ids) < 2:
            raise ProgramResolutionError(
                "ambiguous prior context requires multiple programs"
            )
        return _decision(
            ProgramResolutionOutcome.AMBIGUOUS,
            ProgramResolutionSource.PRIOR_CONTEXT,
            ProgramResolutionReason.PRIOR_CONTEXT_AMBIGUOUS,
            1.0,
            prior_context_program_ids=prior_program_ids,
            evidence=("context.prior.ambiguous",),
        )
    if context_decision.context_use is ContextUse.PRIOR_CONTEXT_FALLBACK_ONLY:
        return _decision(
            ProgramResolutionOutcome.ABSENT,
            ProgramResolutionSource.NONE,
            ProgramResolutionReason.PRIOR_CONTEXT_FALLBACK_ONLY,
            0.95,
            prior_context_program_ids=prior_program_ids,
            evidence=("context.prior.fallback_only",),
        )
    return _decision(
        ProgramResolutionOutcome.ABSENT,
        ProgramResolutionSource.NONE,
        ProgramResolutionReason.NO_PROGRAM_EVIDENCE,
        0.95,
        prior_context_program_ids=prior_program_ids,
        evidence=(
            f"context.no_program_evidence.{context_decision.context_use.value}",
        ),
    )
