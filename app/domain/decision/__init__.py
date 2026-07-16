"""Stable public API for program identity and registry metadata."""

from .input_normalizer import (
    PHONE_REDACTION_PLACEHOLDER,
    derive_conservative_token_form,
    match_curated_token,
    normalize_message,
    redact_phone_like,
    tokenize_message,
)
from .conversation_act import resolve_conversation_act
from .models import (
    ConversationAct,
    ConversationActDecision,
    ConversationActReason,
    CuratedMatchKind,
    CuratedMatchReason,
    CuratedTokenMatch,
    InputNormalizationError,
    NormalizedMessage,
    ProgramDefinition,
    ProgramId,
    ProgramOwnerReferences,
    RegistryAlias,
    RegistryValidationError,
    SymbolicOwnerReference,
    TransformationReason,
    TypoMatchPolicy,
)
from .program_registry import PROGRAM_REGISTRY, ProgramRegistry

__all__ = [
    "ConversationAct",
    "ConversationActDecision",
    "ConversationActReason",
    "CuratedMatchKind",
    "CuratedMatchReason",
    "CuratedTokenMatch",
    "InputNormalizationError",
    "NormalizedMessage",
    "PHONE_REDACTION_PLACEHOLDER",
    "PROGRAM_REGISTRY",
    "ProgramDefinition",
    "ProgramId",
    "ProgramOwnerReferences",
    "ProgramRegistry",
    "RegistryAlias",
    "RegistryValidationError",
    "SymbolicOwnerReference",
    "TransformationReason",
    "TypoMatchPolicy",
    "derive_conservative_token_form",
    "match_curated_token",
    "normalize_message",
    "redact_phone_like",
    "resolve_conversation_act",
    "tokenize_message",
]
