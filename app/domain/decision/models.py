"""Immutable domain types for the program registry."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RegistryValidationError(ValueError):
    """Raised when a program registry contract is invalid."""


class InputNormalizationError(ValueError):
    """Raised when an input-normalization contract is invalid."""


class ProgramId(str, Enum):
    """Canonical program identifiers."""

    SUMMER_CAMP = "summer_camp"
    SUNDAY_SCHOOL = "sunday_school"
    ADULT_EVENTS = "adult_events"


class TransformationReason(str, Enum):
    """Closed-set evidence for deterministic preprocessing changes."""

    UNICODE_NFC = "unicode_nfc"
    QUOTE_CANONICALIZATION = "quote_canonicalization"
    WHITESPACE_COLLAPSED = "whitespace_collapsed"
    PUNCTUATION_SPACING = "punctuation_spacing"
    REPEATED_PUNCTUATION = "repeated_punctuation"
    REPEATED_CHARACTER_COMPARISON = "repeated_character_comparison"
    PHONE_REDACTED = "phone_redacted"


class CuratedMatchKind(str, Enum):
    """Supported outcomes from explicit curated-token matching."""

    EXACT = "exact"
    CONSERVATIVE_TYPO = "conservative_typo"


class CuratedMatchReason(str, Enum):
    """Closed-set evidence for a curated-token match."""

    EXACT_MATCH = "exact_match"
    EDIT_DISTANCE = "edit_distance"


class ConversationAct(str, Enum):
    """Canonical current-message conversational moves."""

    PROGRAM_QUESTION = "program_question"
    CLARIFICATION = "clarification"
    CORRECTION = "correction"
    COMPLAINT = "complaint"
    NEGATIVE_FEEDBACK = "negative_feedback"
    INSULT = "insult"
    GREETING = "greeting"
    THANKS = "thanks"
    HUMAN_HANDOFF = "human_handoff"
    CALLBACK_REQUEST = "callback_request"
    UNRELATED = "unrelated"
    UNKNOWN = "unknown"


class ConversationActReason(str, Enum):
    """Closed-set evidence category for conversation-act decisions."""

    EXPLICIT_INSULT = "explicit_insult"
    FACTUAL_CORRECTION = "factual_correction"
    SERVICE_COMPLAINT = "service_complaint"
    NEGATIVE_REACTION = "negative_reaction"
    EXPLICIT_HUMAN_REQUEST = "explicit_human_request"
    EXPLICIT_CALLBACK_REQUEST = "explicit_callback_request"
    CLARIFICATION_REQUEST = "clarification_request"
    GENERIC_PROGRAM_QUESTION = "generic_program_question"
    STANDALONE_THANKS = "standalone_thanks"
    GREETING_OPENING = "greeting_opening"
    CLEAR_OFF_DOMAIN = "clear_off_domain"
    CURATED_TYPO = "curated_typo"
    EMPTY_INPUT = "empty_input"
    PUNCTUATION_ONLY = "punctuation_only"
    CONTEXT_DEPENDENT_FRAGMENT = "context_dependent_fragment"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class ContextSource(str, Enum):
    """Closed provenance categories for prior program context."""

    USER_EXPLICIT_PROGRAM = "user_explicit_program"
    USER_CONFIRMED_PROGRAM = "user_confirmed_program"
    ASSISTANT_REFERENCED_PROGRAM = "assistant_referenced_program"
    LEGACY_STICKY_STATE = "legacy_sticky_state"
    LEGACY_SEGMENT_INFERENCE = "legacy_segment_inference"


class ContextUse(str, Enum):
    """Closed outcomes for prior-context eligibility."""

    BLOCKED = "blocked"
    CURRENT_MESSAGE_AUTHORITATIVE = "current_message_authoritative"
    PRIOR_CONTEXT_SELECTED = "prior_context_selected"
    PRIOR_CONTEXT_FALLBACK_ONLY = "prior_context_fallback_only"
    AMBIGUOUS = "ambiguous"
    NO_RELEVANT_CONTEXT = "no_relevant_context"


class ContextArbitrationReason(str, Enum):
    """Closed explanation codes for context arbitration."""

    ACT_BLOCKS_CONTEXT = "act_blocks_context"
    CLARIFICATION_DOES_NOT_SELECT_CONTEXT = (
        "clarification_does_not_select_context"
    )
    CURRENT_MESSAGE_SUBSTANTIVE = "current_message_substantive"
    CONTEXT_RESET_OR_EXCLUSION = "context_reset_or_exclusion"
    SINGLE_FRESH_STRONG_CONTEXT = "single_fresh_strong_context"
    SINGLE_FRESH_ASSISTANT_CONTEXT = "single_fresh_assistant_context"
    ASSISTANT_CONTEXT_FALLBACK_ONLY = "assistant_context_fallback_only"
    CONFLICTING_FRESH_CONTEXTS = "conflicting_fresh_contexts"
    NO_CONTEXT_CANDIDATES = "no_context_candidates"
    STALE_CONTEXT_ONLY = "stale_context_only"
    LEGACY_CONTEXT_NON_AUTHORITATIVE = "legacy_context_non_authoritative"
    NO_ELIGIBLE_CONTEXT = "no_eligible_context"


class ContextArbitrationError(ValueError):
    """Raised when a context-arbitration contract is invalid."""


class PendingWorkflowError(ValueError):
    """Raised when a pending-workflow contract is invalid."""


class PendingWorkflowKind(str, Enum):
    """Generic kinds of pending inbound-reply workflows."""

    CONTACT_COLLECTION = "contact_collection"
    CHILD_AGE_COLLECTION = "child_age_collection"
    AFFIRMATION_CONFIRMATION = "affirmation_confirmation"


class PendingWorkflowSource(str, Enum):
    """Closed provenance categories for pending-workflow evidence."""

    TYPED_PENDING_RECORD = "typed_pending_record"
    RECENT_ASSISTANT_REQUEST = "recent_assistant_request"
    LEGACY_STATE = "legacy_state"


class PendingWorkflowStatus(str, Enum):
    """Lifecycle status supplied by the future runtime adapter."""

    ACTIVE = "active"
    SUSPENDED = "suspended"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ExpectedReplyKind(str, Enum):
    """Bounded reply shapes that a pending workflow may request."""

    USER_NAME = "user_name"
    USER_PHONE = "user_phone"
    CHILD_AGE = "child_age"
    AFFIRMATION = "affirmation"


class PendingWorkflowAction(str, Enum):
    """Closed orchestration signals emitted by pending-workflow arbitration."""

    CONTINUE_PENDING_WORKFLOW = "continue_pending_workflow"
    RESUME_PENDING_AFTER_ANSWER = "resume_pending_after_answer"
    INTERRUPT_WITH_CURRENT_REQUEST = "interrupt_with_current_request"
    SUSPEND_PENDING_WORKFLOW = "suspend_pending_workflow"
    CANCEL_STALE_WORKFLOW = "cancel_stale_workflow"
    REJECT_MALFORMED_WORKFLOW = "reject_malformed_workflow"
    NO_PENDING_WORKFLOW = "no_pending_workflow"


class PendingWorkflowReason(str, Enum):
    """Closed explanation codes for pending-workflow decisions."""

    NO_WORKFLOW_SUPPLIED = "no_workflow_supplied"
    NO_ACTIVE_WORKFLOW = "no_active_workflow"
    WORKFLOW_MALFORMED = "workflow_malformed"
    WORKFLOW_STALE = "workflow_stale"
    CONFLICTING_ACTIVE_WORKFLOWS = "conflicting_active_workflows"
    EXPECTED_REPLY_MATCHED = "expected_reply_matched"
    RESUMABLE_PROGRAM_QUESTION = "resumable_program_question"
    MANAGER_CONTACT_REQUEST_OVERRIDES_PENDING = (
        "manager_contact_request_overrides_pending"
    )
    CURRENT_REQUEST_OVERRIDES_PENDING = "current_request_overrides_pending"
    NON_ANSWER_ACT_SUSPENDS_PENDING = "non_answer_act_suspends_pending"
    EXPECTED_REPLY_NOT_MATCHED = "expected_reply_not_matched"


def _validate_exact_text(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value:
        raise RegistryValidationError(f"{field_name} must be a non-empty string")
    if value != value.strip():
        raise RegistryValidationError(f"{field_name} must not contain outer whitespace")


@dataclass(frozen=True, slots=True)
class RegistryAlias:
    """An exact, already-canonical alias for one program."""

    value: str
    program_id: ProgramId

    def __post_init__(self) -> None:
        _validate_exact_text(self.value, "alias")
        if not isinstance(self.program_id, ProgramId):
            raise RegistryValidationError("alias program_id is unsupported")


@dataclass(frozen=True, slots=True)
class SymbolicOwnerReference:
    """A symbolic reference to an existing owner, never a runtime object."""

    value: str

    def __post_init__(self) -> None:
        _validate_exact_text(self.value, "owner reference")


@dataclass(frozen=True, slots=True)
class ProgramOwnerReferences:
    """Symbolic source owners associated with a program."""

    lifecycle_owner: SymbolicOwnerReference | None = None
    facts_owner: SymbolicOwnerReference | None = None
    approved_copy_namespace: SymbolicOwnerReference | None = None
    configuration_owner: SymbolicOwnerReference | None = None

    def __post_init__(self) -> None:
        for value in (
            self.lifecycle_owner,
            self.facts_owner,
            self.approved_copy_namespace,
            self.configuration_owner,
        ):
            if value is not None and not isinstance(value, SymbolicOwnerReference):
                raise RegistryValidationError(
                    "program owners must be symbolic owner references or None"
                )


@dataclass(frozen=True, slots=True)
class ProgramDefinition:
    """Stable program identity and symbolic ownership metadata."""

    program_id: ProgramId
    canonical_name: str
    aliases: tuple[RegistryAlias, ...]
    owners: ProgramOwnerReferences

    def __post_init__(self) -> None:
        if not isinstance(self.program_id, ProgramId):
            raise RegistryValidationError("program_id is unsupported")
        _validate_exact_text(self.canonical_name, "canonical_name")
        if self.canonical_name != self.program_id.value:
            raise RegistryValidationError(
                "canonical_name must equal the canonical program_id value"
            )
        if not isinstance(self.aliases, tuple):
            raise RegistryValidationError("aliases must be an immutable tuple")
        if not all(isinstance(alias, RegistryAlias) for alias in self.aliases):
            raise RegistryValidationError("aliases must contain RegistryAlias values")
        if not isinstance(self.owners, ProgramOwnerReferences):
            raise RegistryValidationError(
                "owners must be ProgramOwnerReferences"
            )


@dataclass(frozen=True, slots=True)
class NormalizedMessage:
    """Immutable, non-semantic representations of one inbound message."""

    original_text: str
    normalized_text: str
    tokens: tuple[str, ...]
    comparison_tokens: tuple[str, ...]
    trace_text: str
    transformations: tuple[TransformationReason, ...]

    def __post_init__(self) -> None:
        for field_name in ("original_text", "normalized_text", "trace_text"):
            if not isinstance(getattr(self, field_name), str):
                raise InputNormalizationError(f"{field_name} must be a string")
        if not isinstance(self.tokens, tuple) or not all(
            isinstance(token, str) for token in self.tokens
        ):
            raise InputNormalizationError("tokens must be an immutable string tuple")
        if not isinstance(self.comparison_tokens, tuple) or not all(
            isinstance(token, str) for token in self.comparison_tokens
        ):
            raise InputNormalizationError(
                "comparison_tokens must be an immutable string tuple"
            )
        if len(self.tokens) != len(self.comparison_tokens):
            raise InputNormalizationError(
                "tokens and comparison_tokens must have equal length"
            )
        if not isinstance(self.transformations, tuple) or not all(
            isinstance(reason, TransformationReason)
            for reason in self.transformations
        ):
            raise InputNormalizationError(
                "transformations must be an immutable reason tuple"
            )


@dataclass(frozen=True, slots=True)
class TypoMatchPolicy:
    """Conservative length-sensitive edit-distance limits."""

    minimum_typo_length: int = 5
    long_token_length: int = 10
    maximum_distance: int = 1
    maximum_long_distance: int = 1

    def __post_init__(self) -> None:
        values = (
            self.minimum_typo_length,
            self.long_token_length,
            self.maximum_distance,
            self.maximum_long_distance,
        )
        if not all(isinstance(value, int) for value in values):
            raise InputNormalizationError("typo policy values must be integers")
        if self.minimum_typo_length < 1:
            raise InputNormalizationError(
                "minimum_typo_length must be positive"
            )
        if self.long_token_length < self.minimum_typo_length:
            raise InputNormalizationError(
                "long_token_length must not be below minimum_typo_length"
            )
        if self.maximum_distance < 0:
            raise InputNormalizationError(
                "maximum_distance must not be negative"
            )
        if self.maximum_long_distance < self.maximum_distance:
            raise InputNormalizationError(
                "maximum_long_distance must not be below maximum_distance"
            )


def _validate_normalization_text(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value:
        raise InputNormalizationError(
            f"{field_name} must be a non-empty string"
        )
    if value != value.strip():
        raise InputNormalizationError(
            f"{field_name} must not contain outer whitespace"
        )


@dataclass(frozen=True, slots=True)
class CuratedTokenMatch:
    """Auditable result from matching one token to explicit candidates."""

    original_token: str
    canonical_candidate: str
    match_kind: CuratedMatchKind
    edit_distance: int
    confidence: float
    reason: CuratedMatchReason

    def __post_init__(self) -> None:
        if not isinstance(self.original_token, str):
            raise InputNormalizationError("original_token must be a string")
        _validate_normalization_text(
            self.canonical_candidate, "canonical_candidate"
        )
        if not isinstance(self.match_kind, CuratedMatchKind):
            raise InputNormalizationError("match_kind is unsupported")
        if not isinstance(self.reason, CuratedMatchReason):
            raise InputNormalizationError("match reason is unsupported")
        if not isinstance(self.edit_distance, int) or self.edit_distance < 0:
            raise InputNormalizationError(
                "edit_distance must be a non-negative integer"
            )
        if not isinstance(self.confidence, (int, float)) or not (
            0.0 <= float(self.confidence) <= 1.0
        ):
            raise InputNormalizationError("confidence must be between zero and one")


@dataclass(frozen=True, slots=True)
class ConversationActDecision:
    """Immutable decision whose confidence is deterministic rule strength."""

    act: ConversationAct
    confidence: float
    primary_reason: ConversationActReason
    evidence: tuple[str, ...]
    candidate_acts: tuple[ConversationAct, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.act, ConversationAct):
            raise ValueError("act must be ConversationAct")
        if isinstance(self.confidence, bool) or not isinstance(
            self.confidence, (int, float)
        ):
            raise ValueError("confidence must be numeric")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("confidence must be between zero and one")
        if not isinstance(self.primary_reason, ConversationActReason):
            raise ValueError("primary_reason must be ConversationActReason")
        if not isinstance(self.evidence, tuple) or not self.evidence:
            raise ValueError("evidence must be a non-empty immutable tuple")
        if not all(
            isinstance(item, str) and item and item == item.strip()
            for item in self.evidence
        ):
            raise ValueError("evidence must contain stable non-empty rule IDs")
        if len(set(self.evidence)) != len(self.evidence):
            raise ValueError("evidence rule IDs must be unique")
        if not isinstance(self.candidate_acts, tuple) or not self.candidate_acts:
            raise ValueError(
                "candidate_acts must be a non-empty immutable tuple"
            )
        if not all(
            isinstance(item, ConversationAct) for item in self.candidate_acts
        ):
            raise ValueError("candidate_acts must contain ConversationAct values")
        if len(set(self.candidate_acts)) != len(self.candidate_acts):
            raise ValueError("candidate_acts must be unique")
        if self.candidate_acts[0] is not self.act:
            raise ValueError("primary act must be the first candidate")


@dataclass(frozen=True, slots=True)
class ProgramContextCandidate:
    """Minimal immutable evidence that a prior turn concerned one program."""

    program_id: ProgramId
    source: ContextSource
    turn_distance: int

    def __post_init__(self) -> None:
        if not isinstance(self.program_id, ProgramId):
            raise ContextArbitrationError("program_id is unsupported")
        if not isinstance(self.source, ContextSource):
            raise ContextArbitrationError("context source is unsupported")
        if isinstance(self.turn_distance, bool) or not isinstance(
            self.turn_distance, int
        ):
            raise ContextArbitrationError("turn_distance must be an integer")
        if self.turn_distance < 0:
            raise ContextArbitrationError(
                "turn_distance must not be negative"
            )


@dataclass(frozen=True, slots=True)
class ContextArbitrationPolicy:
    """Deterministic turn-based freshness and weak-source policy."""

    strong_context_max_turn_distance: int = 2
    assistant_context_max_turn_distance: int = 1
    allow_assistant_context_selection: bool = False

    def __post_init__(self) -> None:
        for field_name in (
            "strong_context_max_turn_distance",
            "assistant_context_max_turn_distance",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ContextArbitrationError(
                    f"{field_name} must be an integer"
                )
            if value < 0:
                raise ContextArbitrationError(
                    f"{field_name} must not be negative"
                )
        if not isinstance(self.allow_assistant_context_selection, bool):
            raise ContextArbitrationError(
                "allow_assistant_context_selection must be boolean"
            )


@dataclass(frozen=True, slots=True)
class ContextArbitrationDecision:
    """Immutable metadata describing whether prior context may be used."""

    context_use: ContextUse
    selected_program_id: ProgramId | None
    eligible_program_ids: tuple[ProgramId, ...]
    eligible_candidates: tuple[ProgramContextCandidate, ...]
    rejected_candidates: tuple[ProgramContextCandidate, ...]
    confidence: float
    primary_reason: ContextArbitrationReason
    evidence: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.context_use, ContextUse):
            raise ContextArbitrationError("context_use is unsupported")
        if self.selected_program_id is not None and not isinstance(
            self.selected_program_id, ProgramId
        ):
            raise ContextArbitrationError(
                "selected_program_id is unsupported"
            )
        if (
            self.context_use is ContextUse.PRIOR_CONTEXT_SELECTED
        ) != (self.selected_program_id is not None):
            raise ContextArbitrationError(
                "selected program requires PRIOR_CONTEXT_SELECTED"
            )
        if not isinstance(self.eligible_program_ids, tuple) or not all(
            isinstance(item, ProgramId) for item in self.eligible_program_ids
        ):
            raise ContextArbitrationError(
                "eligible_program_ids must be an immutable ProgramId tuple"
            )
        if len(set(self.eligible_program_ids)) != len(
            self.eligible_program_ids
        ):
            raise ContextArbitrationError(
                "eligible_program_ids must be unique"
            )
        if tuple(
            sorted(self.eligible_program_ids, key=lambda item: item.value)
        ) != self.eligible_program_ids:
            raise ContextArbitrationError(
                "eligible_program_ids must be deterministically ordered"
            )
        for field_name in ("eligible_candidates", "rejected_candidates"):
            value = getattr(self, field_name)
            if not isinstance(value, tuple) or not all(
                isinstance(item, ProgramContextCandidate) for item in value
            ):
                raise ContextArbitrationError(
                    f"{field_name} must be an immutable candidate tuple"
                )
            if len(set(value)) != len(value):
                raise ContextArbitrationError(
                    f"{field_name} must contain unique candidates"
                )
        candidate_program_ids = tuple(
            sorted(
                {item.program_id for item in self.eligible_candidates},
                key=lambda item: item.value,
            )
        )
        if candidate_program_ids != self.eligible_program_ids:
            raise ContextArbitrationError(
                "eligible program IDs must match eligible candidates"
            )
        if set(self.eligible_candidates) & set(self.rejected_candidates):
            raise ContextArbitrationError(
                "a candidate cannot be both eligible and rejected"
            )
        if self.selected_program_id is not None and (
            self.selected_program_id not in self.eligible_program_ids
        ):
            raise ContextArbitrationError(
                "selected program must be eligible"
            )
        if isinstance(self.confidence, bool) or not isinstance(
            self.confidence, (int, float)
        ):
            raise ContextArbitrationError("confidence must be numeric")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ContextArbitrationError(
                "confidence must be between zero and one"
            )
        if not isinstance(self.primary_reason, ContextArbitrationReason):
            raise ContextArbitrationError(
                "primary_reason is unsupported"
            )
        if not isinstance(self.evidence, tuple) or not self.evidence:
            raise ContextArbitrationError(
                "evidence must be a non-empty immutable tuple"
            )
        if not all(
            isinstance(item, str) and item and item == item.strip()
            for item in self.evidence
        ):
            raise ContextArbitrationError(
                "evidence must contain stable non-empty rule IDs"
            )
        if len(set(self.evidence)) != len(self.evidence):
            raise ContextArbitrationError("evidence rule IDs must be unique")


_EXPECTED_REPLY_ORDER = {
    item: index for index, item in enumerate(ExpectedReplyKind)
}
_SELECTING_PENDING_ACTIONS = frozenset(
    (
        PendingWorkflowAction.CONTINUE_PENDING_WORKFLOW,
        PendingWorkflowAction.RESUME_PENDING_AFTER_ANSWER,
    )
)


def _validate_pending_text(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value:
        raise PendingWorkflowError(
            f"{field_name} must be a non-empty string"
        )
    if value != value.strip():
        raise PendingWorkflowError(
            f"{field_name} must not contain outer whitespace"
        )


def _validate_pending_string_tuple(
    value: object,
    field_name: str,
) -> None:
    if not isinstance(value, tuple):
        raise PendingWorkflowError(
            f"{field_name} must be an immutable tuple"
        )
    if not all(
        isinstance(item, str) and item and item == item.strip()
        for item in value
    ):
        raise PendingWorkflowError(
            f"{field_name} must contain non-empty trimmed strings"
        )
    if len(set(value)) != len(value):
        raise PendingWorkflowError(f"{field_name} must contain unique values")


@dataclass(frozen=True, slots=True)
class PendingWorkflowSnapshot:
    """Immutable caller-supplied evidence for one pending workflow."""

    workflow_id: str
    owner_id: str
    kind: PendingWorkflowKind
    source: PendingWorkflowSource
    status: PendingWorkflowStatus
    expected_reply_kinds: tuple[ExpectedReplyKind, ...]
    turn_distance: int
    program_id: ProgramId | None = None

    def __post_init__(self) -> None:
        _validate_pending_text(self.workflow_id, "workflow_id")
        _validate_pending_text(self.owner_id, "owner_id")
        if not isinstance(self.kind, PendingWorkflowKind):
            raise PendingWorkflowError("workflow kind is unsupported")
        if not isinstance(self.source, PendingWorkflowSource):
            raise PendingWorkflowError("workflow source is unsupported")
        if not isinstance(self.status, PendingWorkflowStatus):
            raise PendingWorkflowError("workflow status is unsupported")
        if not isinstance(self.expected_reply_kinds, tuple):
            raise PendingWorkflowError(
                "expected_reply_kinds must be an immutable tuple"
            )
        if not all(
            isinstance(item, ExpectedReplyKind)
            for item in self.expected_reply_kinds
        ):
            raise PendingWorkflowError(
                "expected_reply_kinds must contain ExpectedReplyKind values"
            )
        if len(set(self.expected_reply_kinds)) != len(
            self.expected_reply_kinds
        ):
            raise PendingWorkflowError(
                "expected_reply_kinds must contain unique values"
            )
        if tuple(
            sorted(
                self.expected_reply_kinds,
                key=_EXPECTED_REPLY_ORDER.__getitem__,
            )
        ) != self.expected_reply_kinds:
            raise PendingWorkflowError(
                "expected_reply_kinds must be deterministically ordered"
            )
        if isinstance(self.turn_distance, bool) or not isinstance(
            self.turn_distance, int
        ):
            raise PendingWorkflowError("turn_distance must be an integer")
        if self.turn_distance < 0:
            raise PendingWorkflowError(
                "turn_distance must not be negative"
            )
        if self.program_id is not None and not isinstance(
            self.program_id, ProgramId
        ):
            raise PendingWorkflowError("program_id is unsupported")


def _pending_snapshot_sort_key(
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


@dataclass(frozen=True, slots=True)
class PendingWorkflowPolicy:
    """Deterministic freshness and bounded pending-reply matching policy."""

    child_age_collection_max_turn_distance: int = 1
    contact_collection_max_turn_distance: int = 2
    affirmation_confirmation_max_turn_distance: int = 1
    child_age_minimum: int = 1
    child_age_maximum: int = 17
    affirmation_phrases: tuple[str, ...] = (
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
    manager_reference_terms: tuple[str, ...] = ("მენეჯერის",)
    manager_contact_stems: tuple[str, ...] = (
        "ნომერ",
        "საკონტაქტო",
        "ტელეფონ",
    )
    manager_request_stems: tuple[str, ...] = (
        "მომწერ",
        "მომეც",
        "გამომიგზავნ",
    )

    def __post_init__(self) -> None:
        for field_name in (
            "child_age_collection_max_turn_distance",
            "contact_collection_max_turn_distance",
            "affirmation_confirmation_max_turn_distance",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise PendingWorkflowError(f"{field_name} must be an integer")
            if value < 0:
                raise PendingWorkflowError(
                    f"{field_name} must not be negative"
                )
        for field_name in ("child_age_minimum", "child_age_maximum"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise PendingWorkflowError(f"{field_name} must be an integer")
        if self.child_age_minimum < 1:
            raise PendingWorkflowError(
                "child_age_minimum must be positive"
            )
        if self.child_age_maximum < self.child_age_minimum:
            raise PendingWorkflowError(
                "child_age_maximum must not be below child_age_minimum"
            )
        for field_name in (
            "affirmation_phrases",
            "manager_reference_terms",
            "manager_contact_stems",
            "manager_request_stems",
        ):
            _validate_pending_string_tuple(getattr(self, field_name), field_name)
            if not getattr(self, field_name):
                raise PendingWorkflowError(f"{field_name} must not be empty")


@dataclass(frozen=True, slots=True)
class PendingWorkflowDecision:
    """Immutable plan signal describing pending-workflow relevance."""

    action: PendingWorkflowAction
    selected_workflow: PendingWorkflowSnapshot | None
    eligible_workflows: tuple[PendingWorkflowSnapshot, ...]
    rejected_workflows: tuple[PendingWorkflowSnapshot, ...]
    matched_reply_kinds: tuple[ExpectedReplyKind, ...]
    confidence: float
    primary_reason: PendingWorkflowReason
    evidence: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.action, PendingWorkflowAction):
            raise PendingWorkflowError("pending workflow action is unsupported")
        if self.selected_workflow is not None and not isinstance(
            self.selected_workflow, PendingWorkflowSnapshot
        ):
            raise PendingWorkflowError(
                "selected_workflow must be PendingWorkflowSnapshot or None"
            )
        if (
            self.action in _SELECTING_PENDING_ACTIONS
        ) != (self.selected_workflow is not None):
            raise PendingWorkflowError(
                "selected_workflow does not match pending workflow action"
            )
        for field_name in ("eligible_workflows", "rejected_workflows"):
            value = getattr(self, field_name)
            if not isinstance(value, tuple) or not all(
                isinstance(item, PendingWorkflowSnapshot) for item in value
            ):
                raise PendingWorkflowError(
                    f"{field_name} must be an immutable snapshot tuple"
                )
            if len(set(value)) != len(value):
                raise PendingWorkflowError(
                    f"{field_name} must contain unique workflows"
                )
            if tuple(sorted(value, key=_pending_snapshot_sort_key)) != value:
                raise PendingWorkflowError(
                    f"{field_name} must be deterministically ordered"
                )
        if set(self.eligible_workflows) & set(self.rejected_workflows):
            raise PendingWorkflowError(
                "a workflow cannot be both eligible and rejected"
            )
        if self.selected_workflow is not None and (
            self.selected_workflow not in self.eligible_workflows
        ):
            raise PendingWorkflowError(
                "selected_workflow must be eligible"
            )
        if not isinstance(self.matched_reply_kinds, tuple) or not all(
            isinstance(item, ExpectedReplyKind)
            for item in self.matched_reply_kinds
        ):
            raise PendingWorkflowError(
                "matched_reply_kinds must be an immutable ExpectedReplyKind tuple"
            )
        if len(set(self.matched_reply_kinds)) != len(
            self.matched_reply_kinds
        ):
            raise PendingWorkflowError(
                "matched_reply_kinds must contain unique values"
            )
        if tuple(
            sorted(
                self.matched_reply_kinds,
                key=_EXPECTED_REPLY_ORDER.__getitem__,
            )
        ) != self.matched_reply_kinds:
            raise PendingWorkflowError(
                "matched_reply_kinds must be deterministically ordered"
            )
        if (
            self.action is PendingWorkflowAction.CONTINUE_PENDING_WORKFLOW
        ) != bool(self.matched_reply_kinds):
            raise PendingWorkflowError(
                "matched replies require continue_pending_workflow"
            )
        if isinstance(self.confidence, bool) or not isinstance(
            self.confidence, (int, float)
        ):
            raise PendingWorkflowError("confidence must be numeric")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise PendingWorkflowError(
                "confidence must be between zero and one"
            )
        if not isinstance(self.primary_reason, PendingWorkflowReason):
            raise PendingWorkflowError("primary_reason is unsupported")
        _validate_pending_string_tuple(self.evidence, "evidence")
