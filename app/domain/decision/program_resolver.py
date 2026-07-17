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
    ProgramIdentityDefinition,
    ProgramId,
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
)
from .program_registry import PROGRAM_REGISTRY, ProgramRegistry


def _suffixes(*values: str) -> tuple[str, ...]:
    return tuple(sorted(values))


def _forms(*values: str) -> tuple[str, ...]:
    return tuple(sorted(values))


def _stem(stem: str, evidence_id: str, *suffixes: str) -> ProgramStemRule:
    return ProgramStemRule(stem, _suffixes(*suffixes), evidence_id)


def _token(
    evidence_id: str,
    *,
    exact_forms: tuple[str, ...] = (),
    stem_rules: tuple[ProgramStemRule, ...] = (),
) -> ProgramTokenRule:
    return ProgramTokenRule(
        exact_forms=_forms(*exact_forms),
        stem_rules=stem_rules,
        evidence_id=evidence_id,
    )


def _phrase(
    evidence_id: str,
    *components: ProgramTokenRule,
    maximum_gap: int = 0,
) -> ProgramPhraseRule:
    return ProgramPhraseRule(components, maximum_gap, evidence_id)


def _identity(
    program_id: ProgramId,
    evidence_id: str,
    *phrase_rules: ProgramPhraseRule,
) -> ProgramIdentityDefinition:
    return ProgramIdentityDefinition(program_id, phrase_rules, evidence_id)


_CAMP_STEM_TOKEN = _token(
    "program.summer_camp.token.georgian_stem",
    stem_rules=(
        _stem(
            "ბანაკ",
            "program.summer_camp.stem.banak",
            "",
            "ამდე",
            "ი",
            "იდან",
            "ის",
            "ზე",
            "ში",
        ),
        _stem(
            "ლაგერ",
            "program.summer_camp.stem.lager",
            "ი",
            "ში",
        ),
    ),
)
_CAMP_EXACT_TOKEN = _token(
    "program.summer_camp.token.exact",
    exact_forms=("camp",),
)
_CAMP_SUMMER_MODIFIER = _token(
    "program.summer_camp.token.summer_modifier",
    exact_forms=("საზაფხულო",),
)
_CAMP_CHILDREN_MODIFIER = _token(
    "program.summer_camp.token.children_modifier",
    exact_forms=("ბავშვთა",),
)
_CAMP_ENGLISH_SUMMER = _token(
    "program.summer_camp.token.english_summer",
    exact_forms=("summer",),
)
_CAMP_ENGLISH_HYPHEN = _token(
    "program.summer_camp.token.english_hyphen",
    exact_forms=("summer-camp",),
)

_SUNDAY_LEAD_TOKEN = _token(
    "program.sunday_school.token.sunday_lead",
    exact_forms=("საკვირაო",),
)
_SUNDAY_SCHOOL_TOKEN = _token(
    "program.sunday_school.token.school_stem",
    stem_rules=(
        _stem(
            "სკოლ",
            "program.sunday_school.stem.school",
            "ა",
            "აზე",
            "აში",
            "ის",
        ),
    ),
)
_SUNDAY_COMPOUND_TOKEN = _token(
    "program.sunday_school.token.compound",
    exact_forms=("sunday-school", "sundayschool", "საკვირაოსკოლა"),
)
_SUNDAY_ENGLISH_LEAD = _token(
    "program.sunday_school.token.english_sunday",
    exact_forms=("sunday",),
)
_SUNDAY_ENGLISH_SCHOOL = _token(
    "program.sunday_school.token.english_school",
    exact_forms=("school",),
)

_ADULT_AUDIENCE_TOKEN = _token(
    "program.adult_events.token.audience",
    stem_rules=(
        _stem(
            "ზრდასრულ",
            "program.adult_events.stem.audience",
            "ებისთვის",
            "თა",
        ),
    ),
)
_ADULT_EVENT_TOKEN = _token(
    "program.adult_events.token.event_identity",
    stem_rules=(
        _stem(
            "ღონისძიებ",
            "program.adult_events.stem.event",
            "ა",
            "აზე",
            "აში",
            "ები",
            "ების",
            "ებზე",
            "ებს",
            "ის",
        ),
    ),
)
_ADULT_CULTURAL_TOKEN = _token(
    "program.adult_events.token.cultural",
    stem_rules=(
        _stem(
            "კულტურულ",
            "program.adult_events.stem.cultural",
            "ი",
        ),
    ),
)
_ADULT_EVENING_TOKEN = _token(
    "program.adult_events.token.evening",
    stem_rules=(
        _stem(
            "საღამო",
            "program.adult_events.stem.evening",
            "",
            "ები",
            "ების",
            "ებზე",
            "ს",
        ),
    ),
)
_ADULT_ENGLISH_ADULT = _token(
    "program.adult_events.token.english_adult",
    exact_forms=("adult",),
)
_ADULT_ENGLISH_EVENT = _token(
    "program.adult_events.token.english_event",
    exact_forms=("event", "events"),
)
_ADULT_ENGLISH_CULTURAL = _token(
    "program.adult_events.token.english_cultural",
    exact_forms=("cultural",),
)
_ADULT_ENGLISH_EVENING = _token(
    "program.adult_events.token.english_evening",
    exact_forms=("evening", "evenings"),
)
_ADULT_EVENT_HYPHEN = _token(
    "program.adult_events.token.event_hyphen",
    exact_forms=("adult-events",),
)
_ADULT_CULTURAL_HYPHEN = _token(
    "program.adult_events.token.cultural_hyphen",
    exact_forms=("cultural-evenings",),
)


DEFAULT_PROGRAM_RESOLUTION_POLICY = ProgramResolutionPolicy(
    program_identity_definitions=(
        _identity(
            ProgramId.ADULT_EVENTS,
            "program.adult_events.identity",
            _phrase(
                "program.adult_events.audience_identity",
                _ADULT_AUDIENCE_TOKEN,
                _ADULT_EVENT_TOKEN,
            ),
            _phrase(
                "program.adult_events.audience_cultural_evening",
                _ADULT_AUDIENCE_TOKEN,
                _ADULT_CULTURAL_TOKEN,
                _ADULT_EVENING_TOKEN,
            ),
            _phrase(
                "program.adult_events.cultural_evening",
                _ADULT_CULTURAL_TOKEN,
                _ADULT_EVENING_TOKEN,
            ),
            _phrase(
                "program.adult_events.direct_phrase",
                _ADULT_ENGLISH_ADULT,
                _ADULT_ENGLISH_EVENT,
            ),
            _phrase(
                "program.adult_events.direct_phrase",
                _ADULT_EVENT_HYPHEN,
            ),
            _phrase(
                "program.adult_events.direct_phrase",
                _ADULT_ENGLISH_CULTURAL,
                _ADULT_ENGLISH_EVENING,
            ),
            _phrase(
                "program.adult_events.direct_phrase",
                _ADULT_CULTURAL_HYPHEN,
            ),
        ),
        _identity(
            ProgramId.SUMMER_CAMP,
            "program.summer_camp.identity",
            _phrase("program.summer_camp.georgian_stem", _CAMP_STEM_TOKEN),
            _phrase("program.summer_camp.exact_token", _CAMP_EXACT_TOKEN),
            _phrase(
                "program.summer_camp.modified_identity",
                _CAMP_SUMMER_MODIFIER,
                _CAMP_STEM_TOKEN,
            ),
            _phrase(
                "program.summer_camp.modified_identity",
                _CAMP_CHILDREN_MODIFIER,
                _CAMP_STEM_TOKEN,
            ),
            _phrase(
                "program.summer_camp.direct_phrase",
                _CAMP_ENGLISH_SUMMER,
                _CAMP_EXACT_TOKEN,
            ),
            _phrase("program.summer_camp.direct_phrase", _CAMP_ENGLISH_HYPHEN),
        ),
        _identity(
            ProgramId.SUNDAY_SCHOOL,
            "program.sunday_school.identity",
            _phrase(
                "program.sunday_school.georgian_compound",
                _SUNDAY_LEAD_TOKEN,
                _SUNDAY_SCHOOL_TOKEN,
            ),
            _phrase("program.sunday_school.compound", _SUNDAY_COMPOUND_TOKEN),
            _phrase(
                "program.sunday_school.english_compound",
                _SUNDAY_ENGLISH_LEAD,
                _SUNDAY_ENGLISH_SCHOOL,
            ),
        ),
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


def _matches_stem_rule(token: str, rule: ProgramStemRule) -> bool:
    return any(token == f"{rule.stem}{suffix}" for suffix in rule.allowed_suffixes)


def _matches_token_rule(token: str, rule: ProgramTokenRule) -> bool:
    if token in rule.exact_forms:
        return True
    return any(_matches_stem_rule(token, stem_rule) for stem_rule in rule.stem_rules)


def _match_phrase_rule(
    tokens: tuple[str, ...],
    start: int,
    rule: ProgramPhraseRule,
) -> int | None:
    if not _matches_token_rule(tokens[start], rule.components[0]):
        return None

    end = start + 1
    for component in rule.components[1:]:
        upper_bound = min(len(tokens), end + rule.maximum_gap + 1)
        next_index = None
        for candidate_index in range(end, upper_bound):
            if _matches_token_rule(tokens[candidate_index], component):
                next_index = candidate_index
                break
        if next_index is None:
            return None
        end = next_index + 1
    return end


def _match_identity_definition(
    tokens: tuple[str, ...],
    start: int,
    definition: ProgramIdentityDefinition,
) -> tuple[_IdentityMatch, ...]:
    matches: list[_IdentityMatch] = []
    for phrase_rule in definition.phrase_rules:
        token_end = _match_phrase_rule(tokens, start, phrase_rule)
        if token_end is None:
            continue
        matches.append(
            _IdentityMatch(
                definition.program_id,
                start,
                token_end,
                phrase_rule.evidence_id,
            )
        )
    return tuple(matches)


def _best_identity_match_at(
    tokens: tuple[str, ...],
    start: int,
    policy: ProgramResolutionPolicy,
) -> _IdentityMatch | None:
    matches: list[_IdentityMatch] = []
    for definition in policy.program_identity_definitions:
        matches.extend(_match_identity_definition(tokens, start, definition))
    if not matches:
        return None
    return sorted(
        matches,
        key=lambda item: (
            -(item.token_end - item.token_start),
            item.program_id.value,
            item.evidence_id,
        ),
    )[0]


def _identity_matches(
    message: NormalizedMessage,
    policy: ProgramResolutionPolicy,
) -> tuple[_IdentityMatch, ...]:
    tokens = tuple(token.casefold() for token in message.comparison_tokens)
    matches: list[_IdentityMatch] = []
    index = 0
    while index < len(tokens):
        match = _best_identity_match_at(tokens, index, policy)
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


def _first_alpha_index_after(
    tokens: tuple[str, ...],
    start: int,
) -> int | None:
    for index in range(start, len(tokens)):
        if tokens[index].isalpha():
            return index
    return None


def _is_exclusion_pivot_source(
    match: _IdentityMatch,
    matches: tuple[_IdentityMatch, ...],
    tokens: tuple[str, ...],
) -> bool:
    pivot_index = _first_alpha_index_after(tokens, match.token_end)
    if pivot_index is None or tokens[pivot_index] != "არა":
        return False
    return any(
        other.token_start > pivot_index
        and other.program_id is not match.program_id
        for other in matches
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
        if (
            role is ProgramMentionRole.REQUESTED
            and _is_exclusion_pivot_source(match, matches, tokens)
        ):
            role = ProgramMentionRole.EXCLUDED
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


def _validate_policy_registry_alignment(
    registry: ProgramRegistry,
    policy: ProgramResolutionPolicy,
) -> None:
    registry_ids = tuple(
        sorted(
            (definition.program_id for definition in registry.all()),
            key=lambda item: item.value,
        )
    )
    policy_ids = tuple(
        definition.program_id
        for definition in policy.program_identity_definitions
    )
    if policy_ids != registry_ids:
        raise ProgramResolutionError(
            "program identity definitions must exactly match the supplied registry"
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
    _validate_policy_registry_alignment(registry, policy)
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
