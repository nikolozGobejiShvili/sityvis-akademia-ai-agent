from __future__ import annotations

import ast
import subprocess
import sys
import unicodedata
from dataclasses import FrozenInstanceError, fields
from pathlib import Path

import pytest

from app.domain.decision import (
    PHONE_REDACTION_PLACEHOLDER,
    CuratedMatchKind,
    CuratedMatchReason,
    CuratedTokenMatch,
    InputNormalizationError,
    NormalizedMessage,
    TransformationReason,
    TypoMatchPolicy,
    derive_conservative_token_form,
    match_curated_token,
    normalize_message,
    redact_phone_like,
    tokenize_message,
)


ROOT = Path(__file__).resolve().parents[1]
DOMAIN_DIR = ROOT / "app" / "domain" / "decision"

GREETING = "\u10d2\u10d0\u10db\u10d0\u10e0\u10ef\u10dd\u10d1\u10d0"
THANKS = "\u10db\u10d0\u10d3\u10da\u10dd\u10d1\u10d0"
PLEASE = "\u10d2\u10d7\u10ee\u10dd\u10d5\u10d7"
HELP = "\u10d3\u10d0\u10db\u10d4\u10ee\u10db\u10d0\u10e0\u10dd\u10d7"
TEXT = "\u10e2\u10d4\u10e5\u10e1\u10e2\u10d8"
ONE = "\u10d4\u10e0\u10d7\u10d8"
TWO = "\u10dd\u10e0\u10d8"
NOT = "\u10d0\u10e0\u10d0"
WHY = "\u10e0\u10d0\u10e2\u10dd\u10db"
GEORGIAN = "\u10e5\u10d0\u10e0\u10d7\u10e3\u10da\u10d8"
GOOD = "\u10d9\u10d0\u10e0\u10d2\u10d8"
BOOK = "\u10ec\u10d8\u10d2\u10dc\u10d8"
STRETCHED = "\u10d5\u10d0\u10d0\u10d0\u10d0"
MANAGER = "\u10db\u10d4\u10dc\u10d4\u10ef\u10d4\u10e0\u10d8\u10e1"
MANAGER_TYPO = "\u10db\u10d4\u10dc\u10ef\u10d4\u10e0\u10d8\u10e1"
UNRELATED = "\u10e1\u10e0\u10e3\u10da\u10d8\u10d0\u10d3"
OTHER = "\u10e1\u10ee\u10d5\u10d0"
CALL_ME = "\u10d3\u10d0\u10db\u10d8\u10d9\u10d0\u10d5\u10e8\u10d8\u10e0\u10d3\u10d8\u10d7"
AT_NUMBER = "\u10dc\u10dd\u10db\u10d4\u10e0\u10d6\u10d4"
NUMBER = "\u10dc\u10dd\u10db\u10d4\u10e0\u10d8"
YEAR_OLD = "\u10ec\u10da\u10d8\u10e1"
PRICE = "\u10e4\u10d0\u10e1\u10d8"
YEAR = "\u10ec\u10d4\u10da\u10d8"
AND = "\u10d3\u10d0"


def test_original_text_is_preserved_exactly():
    raw = f" \t{GREETING}   {THANKS}!!!\r\n"
    result = normalize_message(raw)
    assert result.original_text == raw
    assert result.normalized_text == f"{GREETING} {THANKS}!"


def test_unicode_is_normalized_with_nfc_and_georgian_is_preserved():
    decomposed = f"Cafe\u0301 {AND} {GREETING}"
    result = normalize_message(decomposed)
    assert result.normalized_text == unicodedata.normalize("NFC", decomposed)
    assert GREETING in result.normalized_text
    assert TransformationReason.UNICODE_NFC in result.transformations


def test_compatibility_characters_are_not_nfkc_normalized():
    result = normalize_message(f"\uff21 {GREETING}")
    assert result.normalized_text == f"\uff21 {GREETING}"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (f"  {TEXT}  ", TEXT),
        (f"{ONE}\t{TWO}", f"{ONE} {TWO}"),
        (f"{ONE}\r\n{TWO}", f"{ONE} {TWO}"),
        (f"{ONE}\u00a0\u00a0{TWO}", f"{ONE} {TWO}"),
    ],
)
def test_whitespace_is_collapsed_deterministically(raw: str, expected: str):
    result = normalize_message(raw)
    assert result.normalized_text == expected
    assert TransformationReason.WHITESPACE_COLLAPSED in result.transformations


def test_quotes_apostrophes_and_punctuation_are_canonicalized_safely():
    result = normalize_message(
        f"\u201c{GREETING}\u201d ,  don\u2019t  ( {TEXT} )  ???  !!!"
    )
    assert result.normalized_text == f'"{GREETING}", don\'t ({TEXT})?!'
    assert TransformationReason.QUOTE_CANONICALIZATION in result.transformations
    assert TransformationReason.PUNCTUATION_SPACING in result.transformations
    assert TransformationReason.REPEATED_PUNCTUATION in result.transformations


def test_question_negation_hyphens_and_phone_separators_are_preserved():
    raw = f"{NOT}, X-12 {WHY}? 555-123-456"
    result = normalize_message(raw)
    assert result.normalized_text == raw
    assert "?" in result.normalized_text
    assert NOT in result.normalized_text
    assert "X-12" in result.normalized_text
    assert "555-123-456" in result.normalized_text


def test_greetings_thanks_and_politeness_are_not_removed():
    result = normalize_message(f"{GREETING}, {PLEASE} {HELP}, {THANKS}")
    assert result.tokens == (
        GREETING,
        ",",
        PLEASE,
        HELP,
        ",",
        THANKS,
    )


def test_tokenization_preserves_order_and_separates_punctuation():
    text = f"{GEORGIAN} Latin X-12 14, {GOOD}?"
    assert tokenize_message(text) == (
        GEORGIAN,
        "Latin",
        "X-12",
        "14",
        ",",
        GOOD,
        "?",
    )


def test_empty_whitespace_and_non_string_input_contract():
    assert normalize_message("") == NormalizedMessage(
        original_text="",
        normalized_text="",
        tokens=(),
        comparison_tokens=(),
        trace_text="",
        transformations=(),
    )
    whitespace = normalize_message(" \t\n ")
    assert whitespace.original_text == " \t\n "
    assert whitespace.normalized_text == ""
    with pytest.raises(TypeError):
        normalize_message(None)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        tokenize_message(123)  # type: ignore[arg-type]


def test_very_long_string_is_preserved_without_an_invented_length_limit():
    raw = (GREETING + " ") * 5000
    result = normalize_message(raw)
    assert result.original_text == raw
    assert result.normalized_text == raw.strip()
    assert len(result.tokens) == 5000


def test_normalized_message_and_nested_collections_are_immutable():
    result = normalize_message(GREETING + "aaaa!")
    with pytest.raises(FrozenInstanceError):
        result.normalized_text = "changed"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        result.tokens.append("changed")  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        result.transformations.append(  # type: ignore[attr-defined]
            TransformationReason.UNICODE_NFC
        )


def test_repeated_letters_change_comparison_only_and_record_evidence():
    result = normalize_message(STRETCHED)
    assert result.normalized_text == STRETCHED
    assert result.tokens == (STRETCHED,)
    assert result.comparison_tokens == ("\u10d5\u10d0\u10d0",)
    assert (
        TransformationReason.REPEATED_CHARACTER_COMPARISON
        in result.transformations
    )


@pytest.mark.parametrize(
    "token",
    [GOOD, BOOK, "11", "111111111", "X111", "555-123-456"],
)
def test_conservative_token_form_does_not_rewrite_unqualified_tokens(token: str):
    assert derive_conservative_token_form(token) == token


def test_double_letters_are_not_collapsed():
    double_a = "\u10d0\u10d0"
    assert derive_conservative_token_form(double_a) == double_a


def test_curated_exact_match_has_distance_zero():
    match = match_curated_token(MANAGER, (MANAGER,))
    assert match is not None
    assert match.original_token == MANAGER
    assert match.canonical_candidate == MANAGER
    assert match.match_kind is CuratedMatchKind.EXACT
    assert match.edit_distance == 0
    assert match.confidence == 1.0
    assert match.reason is CuratedMatchReason.EXACT_MATCH


def test_curated_safe_one_edit_georgian_typo_matches_explicit_candidate():
    match = match_curated_token(MANAGER_TYPO, (MANAGER,))
    assert match is not None
    assert match.original_token == MANAGER_TYPO
    assert match.canonical_candidate == MANAGER
    assert match.match_kind is CuratedMatchKind.CONSERVATIVE_TYPO
    assert match.edit_distance == 1
    assert 0.0 < match.confidence < 1.0
    assert match.reason is CuratedMatchReason.EDIT_DISTANCE


@pytest.mark.parametrize(
    ("token", "candidates"),
    [
        (UNRELATED, (MANAGER,)),
        ("ab", ("ac",)),
        (MANAGER + "abcdef", (MANAGER,)),
        ("X-12", ("X-13",)),
    ],
)
def test_curated_matcher_rejects_false_positives(
    token: str,
    candidates: tuple[str, ...],
):
    assert match_curated_token(token, candidates) is None


def test_curated_matcher_fails_closed_on_equal_quality_ambiguity():
    assert match_curated_token("abcdef", ("abcdeg", "abcdeh")) is None


def test_empty_candidate_tuple_returns_none():
    assert match_curated_token(MANAGER_TYPO, ()) is None


@pytest.mark.parametrize(
    "candidates",
    [
        ("",),
        ("   ",),
        (" candidate",),
        ("candidate ",),
        ("candidate", "candidate"),
    ],
)
def test_candidate_validation_is_fail_closed(candidates: tuple[str, ...]):
    with pytest.raises(InputNormalizationError):
        match_curated_token("candidate", candidates)


def test_candidates_must_be_an_immutable_tuple_and_nfc():
    with pytest.raises(InputNormalizationError):
        match_curated_token("candidate", ["candidate"])  # type: ignore[arg-type]
    with pytest.raises(InputNormalizationError, match="NFC"):
        match_curated_token("Cafe\u0301", ("Cafe\u0301",))


def test_custom_typo_policy_is_immutable_and_validated():
    policy = TypoMatchPolicy(maximum_distance=0, maximum_long_distance=0)
    assert match_curated_token(MANAGER_TYPO, (MANAGER,), policy) is None
    with pytest.raises(FrozenInstanceError):
        policy.maximum_distance = 2  # type: ignore[misc]
    with pytest.raises(InputNormalizationError):
        TypoMatchPolicy(minimum_typo_length=0)


@pytest.mark.parametrize(
    "phone_text",
    [
        "555123456",
        "555 123 456",
        "555-123-456",
        "(555) 123-456",
        "+999 (555) 123-456",
    ],
)
def test_trace_redacts_phone_like_sentinels_without_mutating_logic_text(
    phone_text: str,
):
    raw = f"{CALL_ME} {phone_text} {AT_NUMBER}"
    result = normalize_message(raw)
    assert result.original_text == raw
    assert phone_text in result.normalized_text
    assert phone_text not in result.trace_text
    assert result.trace_text == (
        f"{CALL_ME} {PHONE_REDACTION_PLACEHOLDER} {AT_NUMBER}"
    )
    assert TransformationReason.PHONE_REDACTED in result.transformations


def test_phone_redaction_preserves_surrounding_georgian_text():
    assert redact_phone_like(f"{NUMBER}: 555 123 456, {THANKS}") == (
        f"{NUMBER}: {PHONE_REDACTION_PLACEHOLDER}, {THANKS}"
    )


@pytest.mark.parametrize("separator", [" ", ", "])
def test_phone_redaction_does_not_consume_a_following_age(separator: str):
    text = f"555 123 456{separator}14 {YEAR_OLD}"
    assert redact_phone_like(text) == (
        f"{PHONE_REDACTION_PLACEHOLDER}{separator}14 {YEAR_OLD}"
    )


@pytest.mark.parametrize(
    "text",
    ["14", f"14 {YEAR_OLD}", f"{PRICE} 2150", f"2026 {YEAR}"],
)
def test_short_numbers_and_age_are_not_redacted(text: str):
    assert redact_phone_like(text) == text
    assert normalize_message(text).trace_text == text


def test_normalization_and_matching_are_deterministic_and_order_safe():
    raw = f" \t\u201c{GREETING}\u201d  555-123-456??? "
    assert normalize_message(raw) == normalize_message(raw)
    first = match_curated_token(MANAGER_TYPO, (OTHER, MANAGER))
    second = match_curated_token(MANAGER_TYPO, (MANAGER, OTHER))
    assert first == second


def test_models_contain_no_semantic_or_response_decision_fields():
    forbidden = {
        "program_id",
        "intent",
        "topic",
        "lifecycle",
        "response",
        "copy",
        "pending_workflow",
        "conversation_act",
    }
    assert not ({field.name for field in fields(NormalizedMessage)} & forbidden)
    assert not ({field.name for field in fields(CuratedTokenMatch)} & forbidden)


def test_phase2_module_has_only_standard_library_and_local_model_imports():
    path = DOMAIN_DIR / "input_normalizer.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    assert set(imported) <= {"__future__", "re", "unicodedata", "models"}


def test_decision_package_import_remains_side_effect_free_without_environment():
    command = (
        "import sys; "
        "import app.domain.decision as decision; "
        "assert decision.normalize_message('hello').tokens == ('hello',); "
        "assert not any(name.startswith(('app.services', 'app.flows')) "
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
