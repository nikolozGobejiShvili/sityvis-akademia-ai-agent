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
