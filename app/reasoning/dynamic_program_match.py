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


def _bounded_levenshtein(a: str, b: str, max_d: int) -> int:
    """Levenshtein distance between `a` and `b`, capped: returns a value > max_d
    (specifically max_d + 1) as soon as the true distance is known to exceed it.
    Pure, O(len(a) * len(b)) worst case but early-exits per row. Used only for the
    fuzzy program-name path (short strings), so the cost is negligible."""
    if abs(len(a) - len(b)) > max_d:
        return max_d + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        row_min = i
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            v = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            cur.append(v)
            if v < row_min:
                row_min = v
        if row_min > max_d:
            return max_d + 1
        prev = cur
    return prev[-1]


def _fuzzy_token_match(tok: str, term: str) -> bool:
    """Typo/transposition/dropped-letter tolerant match of a message token `tok`
    against a program-name `term` (both already lowered, term >= 6 chars). Compares
    `term` against the ALIGNED prefix of `tok` (so a declension suffix on `tok` is
    ignored) and allows a small edit distance scaled to term length: 1 for names
    <= 8 chars, 2 for longer. A transposition („დინს…" for „დისნ…") costs 2 subs, so
    an 11-char name tolerates it. Length-guarded so a short noise token never matches."""
    allowed = 1 if len(term) <= 8 else 2
    if len(tok) < len(term) - allowed or len(tok) > len(term) + 3:
        return False
    prefix = tok[: len(term)]
    return _bounded_levenshtein(term, prefix, allowed) <= allowed


def _token_matches(msg_tokens: list[str], term: str, *, fuzzy: bool = False) -> bool:
    """True when a message token equals `term`, or (for terms >= 6 chars) `term`
    is a declension-tolerant prefix of a token (`რობოტიკის` matches `რობოტიკა`).
    Short terms (< 6) require EXACT equality, so `camp` never matches `campaign`.

    When `fuzzy=True` (caller passes `settings.USE_FUZZY_PROGRAM_MATCH`), terms >= 6
    also accept a small edit distance so a typo/transposition/dropped letter still
    identifies the program (`დინსეილენდის` matches `დისნეილენდი`). fuzzy=False ⇒
    byte-identical to the exact + declension-prefix behaviour."""
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
            if fuzzy and _fuzzy_token_match(tok, term):
                return True
    return False


def _is_ambiguous(tag: str) -> bool:
    tag = tag.strip().lstrip("#").lower()
    return any(tag.startswith(a) or a.startswith(tag) for a in _AMBIGUOUS_TAG_STEMS)


def match_dynamic_program(
    message_text: str, sections: list[dict], *, fuzzy: bool = False,
) -> dict | None:
    """Return {'program_id','type'} for the first ACTIVE section the message NAMES
    with sufficient specificity, else None. Specificity = a match on a NON-AMBIGUOUS
    NAME token OR a match on a non-ambiguous hashtag. Pure; iterates `sections` in
    given order.

    `fuzzy` (caller passes `settings.USE_FUZZY_PROGRAM_MATCH`) enables typo/dropped-
    letter tolerance on name/tag tokens for EVERY active program. fuzzy=False ⇒
    byte-identical to the exact + declension-prefix matcher."""
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
            _token_matches(toks, nt, fuzzy=fuzzy)
            for nt in _tokens(s.get("name") or "")
            if len(nt) >= _MIN_LEN and not _is_ambiguous(nt)
        )
        specific_tags = [
            str(t) for t in (s.get("hashtags") or [])
            if len(str(t).strip().lstrip("#")) >= _MIN_LEN and not _is_ambiguous(str(t))
        ]
        tag_hit = any(_token_matches(toks, t, fuzzy=fuzzy) for t in specific_tags)
        if name_hit or tag_hit:
            return {"program_id": pid, "type": s.get("type")}
    return None
