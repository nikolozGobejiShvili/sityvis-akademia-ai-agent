"""Pure current-message conversation-act resolution."""
from __future__ import annotations

from .input_normalizer import match_curated_token
from .models import (
    ConversationAct,
    ConversationActDecision,
    ConversationActReason,
    NormalizedMessage,
)


_INSULT_PHRASES = (("დებილი", "ხარ"),)

_CORRECTION_PHRASES = (
    ("არასწორ", "ინფორმაციას", "მწერ"),
    ("ეს", "პასუხი", "არასწორია"),
    ("სწორად", "არ", "მითხარი"),
    ("ინფორმაცია", "შეგეშალა"),
    ("არასწორად", "რატომ", "მწერ"),
)
_CORRECTION_NEGATIONS = (
    ("არასწორი", "არ", "არის"),
    ("არასწორია", "არ", "არის"),
)

_COMPLAINT_PHRASES = (
    ("საერთოდ", "არ", "მეხმარებით"),
    ("რატომ", "მაწვალებთ"),
    ("რამდენჯერ", "უნდა", "გკითხოთ"),
    ("ცუდი", "მომსახურებაა"),
)

_NEGATIVE_FEEDBACK_PHRASES = (
    ("ვერ", "ხარ"),
    ("არ", "მომწონს"),
    ("ცუდია",),
    ("გააფრინე",),
)

_HUMAN_HANDOFF_PHRASES = (
    ("ადამიანთან", "დამაკავშირეთ"),
    ("მენეჯერს", "დამაკავშირეთ"),
    ("ოპერატორს", "მინდა", "დაველაპარაკო"),
    ("კონსულტანტს", "გადამაერთეთ"),
)

_CALLBACK_PHRASES = (
    ("დამირეკეთ",),
    ("გადმომირეკეთ",),
    ("შეგიძლიათ", "დამიკავშირდეთ"),
    ("ჩემი", "ნომერი", "დაგიტოვოთ", "და", "დამირეკავთ"),
)
_CALLBACK_NEGATIONS = frozenset(("არ", "ნუ", "აღარ"))

_CLARIFICATION_PHRASES = (
    ("რას", "გულისხმობ"),
    ("რას", "გულისხმობთ"),
    ("ვერ", "გავიგე"),
    ("შეგიძლიათ", "დამიზუსტოთ"),
    ("კიდევ", "ერთხელ", "ამიხსენით"),
)

_GREETING_PHRASES = (
    ("გამარჯობა",),
    ("გამარჯობათ",),
    ("სალამი",),
    ("საღამო", "მშვიდობისა"),
    ("დილა", "მშვიდობისა"),
)
_GREETING_LED_REMAINDERS = (
    ("კითხვა", "მაქვს"),
    ("ერთი", "კითხვა", "მაქვს"),
)

_THANKS_PHRASES = (
    ("მადლობა",),
    ("დიდი", "მადლობა"),
    ("კარგი", "მადლობა"),
    ("გმადლობთ",),
    ("გმადლობ",),
)

_CONTEXT_DEPENDENT_FRAGMENTS = (
    ("რომელი",),
    ("სად",),
    ("როდის",),
    ("ჰმ",),
    ("კი",),
    ("არა",),
)

_UNRELATED_PHRASES = (
    ("დღეს", "ამინდი", "როგორია"),
    ("ფეხბურთის", "ანგარიში", "მითხარი"),
)

_DOMAIN_STEMS = (
    "ბანაკ",
    "პროგრამ",
    "ღონისძიებ",
    "სკოლ",
    "აკადემი",
    "კურს",
)
_REQUEST_STEMS = (
    "ღირს",
    "ჯდებ",
    "ტარდებ",
    "გექნ",
    "გაქვთ",
    "დღეა",
    "მომწერ",
    "მითხარ",
    "მაინტერეს",
    "ინფორმაცი",
)
_QUESTION_WORDS = frozenset(("რა", "სად", "როდის", "რამდენი", "როგორ", "ვინ"))
_GENERIC_PROGRAM_QUESTIONS = (
    ("სად", "ტარდება"),
    ("რამდენი", "დღეა"),
)
_MANAGER_INFORMATION_NOUNS = ("ნომერ", "საათ", "ვინ")

_TYPO_CANDIDATES = (
    ("მადლობა", ConversationAct.THANKS, "typo.thanks"),
    ("გამარჯობა", ConversationAct.GREETING, "typo.greeting"),
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


def _contains_any_phrase(
    words: tuple[str, ...],
    phrases: tuple[tuple[str, ...], ...],
) -> bool:
    return any(_contains_phrase(words, phrase) for phrase in phrases)


def _is_exact_phrase(
    words: tuple[str, ...],
    phrases: tuple[tuple[str, ...], ...],
) -> bool:
    return words in phrases


def _starts_with_phrase(
    words: tuple[str, ...],
    phrase: tuple[str, ...],
) -> bool:
    return words[: len(phrase)] == phrase


def _has_stem(words: tuple[str, ...], stems: tuple[str, ...]) -> bool:
    return any(word.startswith(stem) for word in words for stem in stems)


def _word_tokens(message: NormalizedMessage) -> tuple[str, ...]:
    return tuple(
        token.casefold()
        for token in message.comparison_tokens
        if token.isalpha()
    )


def _is_correction(words: tuple[str, ...]) -> bool:
    if _contains_any_phrase(words, _CORRECTION_NEGATIONS):
        return False
    return _contains_any_phrase(words, _CORRECTION_PHRASES)


def _is_callback(words: tuple[str, ...]) -> bool:
    if any(word in _CALLBACK_NEGATIONS for word in words):
        return False
    return _contains_any_phrase(words, _CALLBACK_PHRASES)


def _is_greeting(words: tuple[str, ...]) -> bool:
    if _is_exact_phrase(words, _GREETING_PHRASES):
        return True
    for greeting in _GREETING_PHRASES:
        if not _starts_with_phrase(words, greeting):
            continue
        remainder = words[len(greeting) :]
        if remainder in _GREETING_LED_REMAINDERS:
            return True
    return False


def _is_program_question(
    words: tuple[str, ...],
    normalized_text: str,
) -> bool:
    if _contains_any_phrase(words, _GENERIC_PROGRAM_QUESTIONS):
        return True

    has_domain = _has_stem(words, _DOMAIN_STEMS)
    has_question_form = (
        "?" in normalized_text
        or any(word in _QUESTION_WORDS for word in words)
        or _has_stem(words, _REQUEST_STEMS)
    )
    if has_domain and has_question_form:
        return True

    has_manager = any(word.startswith("მენეჯერ") for word in words)
    has_information_noun = _has_stem(words, _MANAGER_INFORMATION_NOUNS)
    if has_manager and has_information_noun and has_question_form:
        return True
    return False


def _typo_signal(
    words: tuple[str, ...],
) -> tuple[ConversationAct, str] | None:
    if len(words) != 1:
        return None
    token = words[0]
    matches: list[tuple[ConversationAct, str]] = []
    for candidate, act, rule_id in _TYPO_CANDIDATES:
        match = match_curated_token(token, (candidate,))
        if match is not None and match.edit_distance == 1:
            matches.append((act, rule_id))
    if len(matches) != 1:
        return None
    return matches[0]


def _decision(
    act: ConversationAct,
    confidence: float,
    reason: ConversationActReason,
    evidence: tuple[str, ...],
    candidate_acts: tuple[ConversationAct, ...] | None = None,
) -> ConversationActDecision:
    candidates = candidate_acts or (act,)
    return ConversationActDecision(
        act=act,
        confidence=confidence,
        primary_reason=reason,
        evidence=evidence,
        candidate_acts=candidates,
    )


def resolve_conversation_act(
    message: NormalizedMessage,
) -> ConversationActDecision:
    """Resolve one conversational move using only the supplied message."""

    if not isinstance(message, NormalizedMessage):
        raise TypeError("message must be NormalizedMessage")

    words = _word_tokens(message)
    lexical_tokens = tuple(
        token.casefold()
        for token in message.comparison_tokens
        if token.isalnum()
    )
    if not message.normalized_text:
        return _decision(
            ConversationAct.UNKNOWN,
            0.0,
            ConversationActReason.EMPTY_INPUT,
            ("unknown.empty",),
        )
    if not words:
        if lexical_tokens and all(token.isdigit() for token in lexical_tokens):
            return _decision(
                ConversationAct.UNKNOWN,
                0.05,
                ConversationActReason.CONTEXT_DEPENDENT_FRAGMENT,
                ("unknown.context_dependent",),
            )
        return _decision(
            ConversationAct.UNKNOWN,
            0.0,
            ConversationActReason.PUNCTUATION_ONLY,
            ("unknown.punctuation_only",),
        )

    signals: list[
        tuple[
            ConversationAct,
            float,
            ConversationActReason,
            str,
        ]
    ] = []

    # Strongest-first precedence:
    # insult > correction > complaint > negative feedback > human handoff >
    # callback > clarification > program question > thanks > greeting >
    # unrelated. Substantive questions therefore precede polite wrappers.
    if _contains_any_phrase(words, _INSULT_PHRASES):
        signals.append((ConversationAct.INSULT, 1.0, ConversationActReason.EXPLICIT_INSULT, "insult.explicit_phrase"))
    if _is_correction(words):
        signals.append((ConversationAct.CORRECTION, 0.98, ConversationActReason.FACTUAL_CORRECTION, "correction.factual_assertion"))
    if _contains_any_phrase(words, _COMPLAINT_PHRASES):
        signals.append((ConversationAct.COMPLAINT, 0.97, ConversationActReason.SERVICE_COMPLAINT, "complaint.service_or_repetition"))
    if _is_exact_phrase(words, _NEGATIVE_FEEDBACK_PHRASES):
        signals.append((ConversationAct.NEGATIVE_FEEDBACK, 0.94, ConversationActReason.NEGATIVE_REACTION, "negative.short_reaction"))
    if _contains_any_phrase(words, _HUMAN_HANDOFF_PHRASES):
        signals.append((ConversationAct.HUMAN_HANDOFF, 0.98, ConversationActReason.EXPLICIT_HUMAN_REQUEST, "handoff.explicit_person_transfer"))
    if _is_callback(words):
        signals.append((ConversationAct.CALLBACK_REQUEST, 0.97, ConversationActReason.EXPLICIT_CALLBACK_REQUEST, "callback.explicit_request"))
    if _contains_any_phrase(words, _CLARIFICATION_PHRASES):
        signals.append((ConversationAct.CLARIFICATION, 0.96, ConversationActReason.CLARIFICATION_REQUEST, "clarification.explicit_request"))
    if _is_program_question(words, message.normalized_text):
        signals.append((ConversationAct.PROGRAM_QUESTION, 0.90, ConversationActReason.GENERIC_PROGRAM_QUESTION, "program.generic_information_request"))
    if _is_exact_phrase(words, _THANKS_PHRASES):
        signals.append((ConversationAct.THANKS, 0.99, ConversationActReason.STANDALONE_THANKS, "thanks.standalone"))
    if _is_greeting(words):
        signals.append((ConversationAct.GREETING, 0.99, ConversationActReason.GREETING_OPENING, "greeting.standalone_or_opening"))
    if _is_exact_phrase(words, _UNRELATED_PHRASES):
        signals.append((ConversationAct.UNRELATED, 0.90, ConversationActReason.CLEAR_OFF_DOMAIN, "unrelated.explicit_off_domain"))

    typo = _typo_signal(words)
    if not signals and typo is not None:
        act, rule_id = typo
        return _decision(act, 0.84, ConversationActReason.CURATED_TYPO, (rule_id,))

    if signals:
        primary = signals[0]
        candidate_acts = tuple(signal[0] for signal in signals)
        evidence = (primary[3],)
        if len(signals) > 1:
            evidence += ("arbitration.strongest_act_precedence",)
        return _decision(primary[0], primary[1], primary[2], evidence, candidate_acts)

    if (
        words in _CONTEXT_DEPENDENT_FRAGMENTS
        or (
            len(lexical_tokens) == 2
            and lexical_tokens[0].isdigit()
            and lexical_tokens[1].startswith("წლ")
        )
    ):
        return _decision(
            ConversationAct.UNKNOWN,
            0.05,
            ConversationActReason.CONTEXT_DEPENDENT_FRAGMENT,
            ("unknown.context_dependent",),
        )

    return _decision(
        ConversationAct.UNKNOWN,
        0.10,
        ConversationActReason.INSUFFICIENT_EVIDENCE,
        ("unknown.insufficient_evidence",),
    )
