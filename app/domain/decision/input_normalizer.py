"""Pure, deterministic preprocessing for inbound message text."""
from __future__ import annotations

import re
import unicodedata

from .models import (
    CuratedMatchKind,
    CuratedMatchReason,
    CuratedTokenMatch,
    InputNormalizationError,
    NormalizedMessage,
    TransformationReason,
    TypoMatchPolicy,
)


PHONE_REDACTION_PLACEHOLDER = "[PHONE_REDACTED]"

_QUOTE_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("\u2018", "'"),
    ("\u2019", "'"),
    ("\u201b", "'"),
    ("\u2032", "'"),
    ("\u201c", '"'),
    ("\u201d", '"'),
    ("\u201e", '"'),
    ("\u201f", '"'),
    ("\u2033", '"'),
)
_WHITESPACE_RE = re.compile(r"\s+", re.UNICODE)
_SPACE_BEFORE_PUNCTUATION_RE = re.compile(r"\s+([,.;:?!])")
_SPACE_AFTER_OPENING_RE = re.compile(r"([\(\[\{])\s+")
_SPACE_BEFORE_CLOSING_RE = re.compile(r"\s+([\)\]\}])")
_REPEATED_QUESTION_RE = re.compile(r"\?{2,}")
_REPEATED_EXCLAMATION_RE = re.compile(r"!{2,}")
_TOKEN_RE = re.compile(
    r"[^\W_]+(?:[-'][^\W_]+)*|[^\w\s]",
    re.UNICODE,
)
_REPEATED_ALPHA_RE = re.compile(r"([^\W\d_])\1{2,}", re.UNICODE)
_PHONE_LIKE_RE = re.compile(
    r"(?<![\w])(?:"
    r"(?:\+\d{1,3}[ \t.-]*)?\(\d{2,4}\)"
    r"[ \t.-]*\d{2,4}[ \t.-]*\d{2,4}"
    r"|"
    r"(?:\+\d{1,3}[ \t.-]+)?\d{3}(?:[ \t.-]\d{3}){2}"
    r"|"
    r"(?:\+\d{1,3}[ \t.-]+)?\d{3}[ \t.-]\d{3}[ \t.-]\d{4}"
    r"|"
    r"(?:\+\d{1,3}[ \t.-]+)?\d{3}(?:[ \t.-]\d{2}){3}"
    r"|"
    r"\+?\d{9,15}"
    r")(?![\w\d])",
    re.UNICODE,
)
_MIN_PHONE_DIGITS = 9
_MAX_PHONE_DIGITS = 15


def _record(
    reasons: list[TransformationReason],
    reason: TransformationReason,
) -> None:
    if reason not in reasons:
        reasons.append(reason)


def tokenize_message(text: str) -> tuple[str, ...]:
    """Tokenize words/numbers in order and retain punctuation separately."""

    if not isinstance(text, str):
        raise TypeError("text must be a string")
    return tuple(match.group(0) for match in _TOKEN_RE.finditer(text))


def derive_conservative_token_form(token: str) -> str:
    """Collapse alphabetic runs of three or more to two for comparison only."""

    if not isinstance(token, str):
        raise TypeError("token must be a string")
    if not token.isalpha():
        return token
    return _REPEATED_ALPHA_RE.sub(r"\1\1", token)


def redact_phone_like(text: str) -> str:
    """Redact likely 9-15 digit contact sequences for trace output."""

    if not isinstance(text, str):
        raise TypeError("text must be a string")

    def _replace(match: re.Match[str]) -> str:
        value = match.group(0)
        digit_count = sum(character.isdigit() for character in value)
        if _MIN_PHONE_DIGITS <= digit_count <= _MAX_PHONE_DIGITS:
            return PHONE_REDACTION_PLACEHOLDER
        return value

    return _PHONE_LIKE_RE.sub(_replace, text)


def normalize_message(text: str) -> NormalizedMessage:
    """Build immutable non-semantic representations of raw inbound text."""

    if not isinstance(text, str):
        raise TypeError("text must be a string")

    reasons: list[TransformationReason] = []

    normalized = unicodedata.normalize("NFC", text)
    if normalized != text:
        _record(reasons, TransformationReason.UNICODE_NFC)

    quoted = normalized
    for source, replacement in _QUOTE_REPLACEMENTS:
        quoted = quoted.replace(source, replacement)
    if quoted != normalized:
        _record(reasons, TransformationReason.QUOTE_CANONICALIZATION)
    normalized = quoted

    whitespace_normalized = _WHITESPACE_RE.sub(" ", normalized).strip()
    if whitespace_normalized != normalized:
        _record(reasons, TransformationReason.WHITESPACE_COLLAPSED)
    normalized = whitespace_normalized

    punctuation_spaced = _SPACE_BEFORE_PUNCTUATION_RE.sub(r"\1", normalized)
    punctuation_spaced = _SPACE_AFTER_OPENING_RE.sub(r"\1", punctuation_spaced)
    punctuation_spaced = _SPACE_BEFORE_CLOSING_RE.sub(r"\1", punctuation_spaced)
    if punctuation_spaced != normalized:
        _record(reasons, TransformationReason.PUNCTUATION_SPACING)
    normalized = punctuation_spaced

    punctuation_collapsed = _REPEATED_QUESTION_RE.sub("?", normalized)
    punctuation_collapsed = _REPEATED_EXCLAMATION_RE.sub(
        "!", punctuation_collapsed
    )
    if punctuation_collapsed != normalized:
        _record(reasons, TransformationReason.REPEATED_PUNCTUATION)
    normalized = punctuation_collapsed

    tokens = tokenize_message(normalized)
    comparison_tokens = tuple(
        derive_conservative_token_form(token) for token in tokens
    )
    if comparison_tokens != tokens:
        _record(
            reasons,
            TransformationReason.REPEATED_CHARACTER_COMPARISON,
        )

    trace_text = redact_phone_like(normalized)
    if trace_text != normalized:
        _record(reasons, TransformationReason.PHONE_REDACTED)

    return NormalizedMessage(
        original_text=text,
        normalized_text=normalized,
        tokens=tokens,
        comparison_tokens=comparison_tokens,
        trace_text=trace_text,
        transformations=tuple(reasons),
    )


def _validate_match_text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value:
        raise InputNormalizationError(
            f"{field_name} must be a non-empty string"
        )
    if value != value.strip():
        raise InputNormalizationError(
            f"{field_name} must not contain outer whitespace"
        )
    return value


def _validate_candidates(candidates: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(candidates, tuple):
        raise InputNormalizationError(
            "candidates must be an immutable string tuple"
        )
    validated = tuple(
        _validate_match_text(candidate, "candidate")
        for candidate in candidates
    )
    if any(
        unicodedata.normalize("NFC", candidate) != candidate
        for candidate in validated
    ):
        raise InputNormalizationError("candidates must already use Unicode NFC")
    if len(set(validated)) != len(validated):
        raise InputNormalizationError("duplicate candidates are not allowed")
    return validated


def _distance_limit(length: int, policy: TypoMatchPolicy) -> int:
    if length < policy.minimum_typo_length:
        return 0
    if length >= policy.long_token_length:
        return policy.maximum_long_distance
    return policy.maximum_distance


def _levenshtein_distance(left: str, right: str, limit: int) -> int:
    if left == right:
        return 0
    if abs(len(left) - len(right)) > limit:
        return limit + 1

    previous = list(range(len(right) + 1))
    for left_index, left_character in enumerate(left, start=1):
        current = [left_index]
        row_minimum = left_index
        for right_index, right_character in enumerate(right, start=1):
            current_value = min(
                current[right_index - 1] + 1,
                previous[right_index] + 1,
                previous[right_index - 1]
                + (left_character != right_character),
            )
            current.append(current_value)
            row_minimum = min(row_minimum, current_value)
        if row_minimum > limit:
            return limit + 1
        previous = current
    return previous[-1]


def match_curated_token(
    token: str,
    candidates: tuple[str, ...],
    policy: TypoMatchPolicy | None = None,
) -> CuratedTokenMatch | None:
    """Match one token against explicit canonical candidates, failing closed."""

    original_token = _validate_match_text(token, "token")
    canonical_candidates = _validate_candidates(candidates)
    if not canonical_candidates:
        return None

    token_nfc = unicodedata.normalize("NFC", original_token)
    if token_nfc in canonical_candidates:
        return CuratedTokenMatch(
            original_token=original_token,
            canonical_candidate=token_nfc,
            match_kind=CuratedMatchKind.EXACT,
            edit_distance=0,
            confidence=1.0,
            reason=CuratedMatchReason.EXACT_MATCH,
        )

    if not token_nfc.isalpha():
        return None

    active_policy = policy or TypoMatchPolicy()
    if not isinstance(active_policy, TypoMatchPolicy):
        raise InputNormalizationError("policy must be TypoMatchPolicy or None")

    token_basis = derive_conservative_token_form(token_nfc)
    matches: list[tuple[int, str, int]] = []
    for candidate in canonical_candidates:
        if not candidate.isalpha():
            continue
        candidate_basis = derive_conservative_token_form(candidate)
        compared_length = max(len(token_basis), len(candidate_basis))
        limit = _distance_limit(compared_length, active_policy)
        if limit == 0:
            continue
        distance = _levenshtein_distance(
            token_basis,
            candidate_basis,
            limit,
        )
        if distance <= limit:
            matches.append((distance, candidate, compared_length))

    if not matches:
        return None
    best_distance = min(item[0] for item in matches)
    best = [item for item in matches if item[0] == best_distance]
    if len(best) != 1:
        return None

    distance, candidate, compared_length = best[0]
    confidence = round(1.0 - (distance / compared_length), 6)
    return CuratedTokenMatch(
        original_token=original_token,
        canonical_candidate=candidate,
        match_kind=CuratedMatchKind.CONSERVATIVE_TYPO,
        edit_distance=distance,
        confidence=confidence,
        reason=CuratedMatchReason.EDIT_DISTANCE,
    )
