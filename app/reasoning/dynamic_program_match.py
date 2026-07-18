"""Precise, flag-agnostic matcher: does a message NAME an active admin program?

Pure — no settings, no IO (caller passes `sections`). Replaces the Phase-1
raw-substring heuristic. Fixes: Latin substring false-positives (camp∈campaign),
Georgian declension misses, and bare common-word hashtag hijacks (`საღამო`)."""
from __future__ import annotations

import re

# Ambiguous single-word stems that must NOT alone trigger a dynamic-program match
# (they overlap the camp/adult/price keyword classifier in conversation_service
# and would hijack routing). Kept in sync with those tuples by
# test_ambiguous_stems_cover_classifier_keywords. Applied to BOTH hashtags and
# program NAME tokens — a bare ambiguous word inside a program's name (e.g.
# `საღამო` in `პოეზიის საღამო`) must not alone identify that program either.
_AMBIGUOUS_TAG_STEMS: tuple[str, ...] = (
    # camp
    "ბანაკ", "ლაგერ", "ბავშვ", "შვილ", "საზაფხულო", "ეკრან", "მოზარდ", "სკოლ",
    "camp", "child", "kid", "summer",
    # adult
    "ღონისძიებ", "საღამო", "ბილეთ", "კულტურ", "პოეზი", "მუსიკ", "შეხვედრ", "კლუბ",
    "event", "events", "evening", "school",
    # price
    "ფასი", "ღირს", "რამდენი", "გადახდ",
)
_MIN_LEN = 4  # ignore tokens/tags shorter than this (kills 1-3 char noise)


def _tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[^0-9a-zა-ჰ]+", (text or "").lower()) if t]


def _token_matches(msg_tokens: list[str], term: str) -> bool:
    """True when a message token equals `term`, or (for terms >= 6 chars) `term`
    is a declension-tolerant prefix of a token (`რობოტიკის` matches `რობოტიკა`).
    Short terms (< 6) require EXACT equality, so `camp` never matches `campaign`."""
    term = term.strip().lstrip("#").lower()
    if len(term) < _MIN_LEN:
        return False
    for tok in msg_tokens:
        if tok == term:
            return True
        if len(term) >= 6:
            shared = 0
            for a, b in zip(tok, term):
                if a != b:
                    break
                shared += 1
            if shared >= 5 and shared >= len(term) - 2:
                return True
    return False


def _is_ambiguous(tag: str) -> bool:
    tag = tag.strip().lstrip("#").lower()
    return any(tag.startswith(a) or a.startswith(tag) for a in _AMBIGUOUS_TAG_STEMS)


def match_dynamic_program(message_text: str, sections: list[dict]) -> dict | None:
    """Return {'program_id','type'} for the first ACTIVE section the message NAMES
    with sufficient specificity, else None. Specificity = a match on a NON-AMBIGUOUS
    NAME token OR a match on a non-ambiguous hashtag. Pure; iterates `sections` in
    given order."""
    toks = _tokens(message_text)
    if not toks:
        return None
    for s in sections:
        pid = (s.get("id") or "").strip()
        if not pid:
            continue
        if (s.get("status") or "active").strip().lower() != "active":
            continue
        name_hit = any(
            _token_matches(toks, nt)
            for nt in _tokens(s.get("name") or "")
            if len(nt) >= _MIN_LEN and not _is_ambiguous(nt)
        )
        specific_tags = [
            str(t) for t in (s.get("hashtags") or [])
            if len(str(t).strip().lstrip("#")) >= _MIN_LEN and not _is_ambiguous(str(t))
        ]
        tag_hit = any(_token_matches(toks, t) for t in specific_tags)
        if name_hit or tag_hit:
            return {"program_id": pid, "type": s.get("type")}
    return None
