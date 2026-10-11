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
    # a description any programme can carry (2026-10-06): the Paris camp is
    # named „…პარიზში - საგანმანათლებლო ბანაკი", and „საგანმანათლებლო" alone
    # read as Paris — „საგანმანათლებლო პროგრამები გაქვთ?" was tagged Paris, and
    # a Sunday-School reply describing itself so filed that chat under Paris.
    "საგანმანათლებლ",
    # who takes part, like „ბავშვ" and „მოზარდ" above (2026-10-09). The Paris
    # brief itself says „25 მონაწილესთან ერთად მოგზაურობს 5 ზრდასრული", and
    # „რამდენი ზრდასრული მიყვება ბავშვებს?" in a Paris chat was read as the
    # switched-off „ზრდასრულთა ღონისძიებები": the turn lost Paris's facts and the
    # agent said it had no such detail. The full name still names that section.
    "ზრდასრულ",
    # ordinary words in „სიტყვის აკადემია მსოფლიოს გარშემო" (2026-10-12). The
    # Paris description says „მსოფლიო დონის მიუზიკლი"; quoted in a Paris chat,
    # that reply alone handed the chat to the new programme. Both words together
    # still name it.
    "მსოფლიო", "გარშემო",
)
# The company's own name. Every programme is the company's and the agent says it
# in all of them („„სიტყვის აკადემიის“ 6-დღიანი ბანაკი", „სიტყვის აკადემიის
# გუნდი…"), so it names no programme, and a programme called after it is named by
# the rest of its name. Measured 2026-10-12 with „სიტყვის აკადემია მსოფლიოს
# გარშემო" on sale: a Paris or Sunday-School chat whose last reply mentioned the
# company was handed that programme's facts, price and number.
_COMPANY_NAME_STEMS: tuple[str, ...] = ("სიტყვის", "აკადემი")
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


def _matching_positions(
    msg_tokens: list[str], term: str, *, fuzzy: bool = False,
) -> set[int]:
    """Positions of the message tokens `term` matches: equal, or (for terms >= 6
    chars) `term` a declension-tolerant prefix of the token (`რობოტიკის` matches
    `რობოტიკა`). Short terms (< 6) require EXACT equality, so `camp` never
    matches `campaign`.

    When `fuzzy=True` (caller passes `settings.USE_FUZZY_PROGRAM_MATCH`), terms >= 6
    also accept a small edit distance so a typo/transposition/dropped letter still
    identifies the program (`დინსეილენდის` matches `დისნეილენდი`). fuzzy=False ⇒
    the exact + declension-prefix behaviour."""
    term = term.strip().lstrip("#").lower()
    found: set[int] = set()
    if len(term) < _MIN_LEN:
        return found
    for i, tok in enumerate(msg_tokens):
        if tok == term:
            found.add(i)
            continue
        if len(term) >= 6:
            shared = 0
            for a, b in zip(tok, term):
                if a != b:
                    break
                shared += 1
            if shared >= 5 and shared >= len(term) - 2:
                found.add(i)
            elif fuzzy and _fuzzy_token_match(tok, term):
                found.add(i)
    return found


def _token_matches(msg_tokens: list[str], term: str, *, fuzzy: bool = False) -> bool:
    """True when some message token matches `term` — see `_matching_positions`."""
    return bool(_matching_positions(msg_tokens, term, fuzzy=fuzzy))


def _is_ambiguous(tag: str) -> bool:
    tag = tag.strip().lstrip("#").lower()
    return any(tag.startswith(a) or a.startswith(tag) for a in _AMBIGUOUS_TAG_STEMS)


def _is_company_word(token: str) -> bool:
    token = token.strip().lstrip("#").lower()
    return any(token.startswith(c) for c in _COMPANY_NAME_STEMS)


def _name_words(text: str) -> list[str]:
    """The words of a programme's name (or of one of its other names) that can
    say which programme it is — long enough, and not the company's name."""
    return [t for t in _tokens(text) if len(t) >= _MIN_LEN and not _is_company_word(t)]


def _all_words_positions(
    msg_tokens: list[str], words: list[str], *, fuzzy: bool,
) -> set[int] | None:
    """Positions of the message tokens matching EVERY word, or None when one is
    missing."""
    positions: set[int] = set()
    for word in words:
        hit = _matching_positions(msg_tokens, word, fuzzy=fuzzy)
        if not hit:
            return None
        positions |= hit
    return positions


_VOWELS = "აეიოუ"


def _phrase_word_matches(token: str, word: str, *, fuzzy: bool) -> bool:
    """One word of another name against one message token: the name rule, or a
    word ending in a vowel with its ending changed — „სკოლა" in „სკოლის",
    „სკოლაც", „სკოლაში"."""
    if _matching_positions([token], word, fuzzy=fuzzy):
        return True
    return (
        len(word) >= 5 and word[-1] in _VOWELS
        and token.startswith(word[:-1]) and len(token) <= len(word) + 4
    )


def _phrase_positions(
    msg_tokens: list[str], words: list[str], *, fuzzy: bool,
) -> set[int] | None:
    """Positions of `words` found next to each other, in order, or None."""
    k = len(words)
    for i in range(len(msg_tokens) - k + 1):
        if all(_phrase_word_matches(msg_tokens[i + j], words[j], fuzzy=fuzzy)
               for j in range(k)):
            return set(range(i, i + k))
    return None


def _naming(msg_tokens: list[str], section: dict, *, fuzzy: bool) -> frozenset[int] | None:
    """Which message tokens name `section`, or None when it is not named.

    A section is named by a word of its name that is not a shared word, by its
    whole name, by one of the other names the operator gave it (`aliases`, every
    word present), or by a specific hashtag. The tokens are kept so that two
    namings in one message can be compared — see `named_programs`."""
    name_words = _name_words(section.get("name") or "")
    positions: set[int] = set()
    named = False
    for word in name_words:
        if _is_ambiguous(word):
            continue
        hit = _matching_positions(msg_tokens, word, fuzzy=fuzzy)
        if hit:
            named = True
            positions |= hit
    # A programme whose name is made ENTIRELY of shared words had no way to
    # be named at all. „საზაფხულო ბანაკი" is both — „ბანაკ" belongs to every
    # camp and „საზაფხულო" to the season — so a parent who wrote the name in
    # full was still asked „რომელი გაინტერესებთ: საზაფხულო ბანაკი, …?", with
    # the answer they had just given listed as an option (measured
    # 2026-09-11, every camp active).
    #
    # Saying the WHOLE name is the specificity the single tokens lack, so it
    # counts even when every token is shared. Two tokens minimum: a
    # one-word ambiguous name („ბანაკი") must keep asking, and it still does
    # — a bare „ბანაკი" matches one of this name's two tokens, not both.
    # Nothing else can collide: „საზაფხულო ბანაკი" never satisfies
    # „პარიზის ბანაკი", whose „პარიზის" is absent.
    if len(name_words) >= 2:
        whole = _all_words_positions(msg_tokens, name_words, fuzzy=fuzzy)
        if whole is not None:
            named = True
            positions |= whole
    # Other names the operator gave the programme in the panel (2026-10-12):
    # what parents call it besides its title — „ონლაინ საკვირაო სკოლა" for
    # „სიტყვის აკადემია მსოფლიოს გარშემო". The phrase must be there as written,
    # word after word (endings may change: „…სკოლის პირობები"), so its words
    # scattered through a sentence — „ონლაინ რეგისტრაცია საკვირაო სკოლაზე" —
    # do not name it. A one-word other name counts only when the word is not a
    # shared one.
    for alias in section.get("aliases") or []:
        words = _name_words(str(alias))
        if not words or (len(words) == 1 and _is_ambiguous(words[0])):
            continue
        phrase = _phrase_positions(msg_tokens, words, fuzzy=fuzzy)
        if phrase is not None:
            named = True
            positions |= phrase
    for tag in section.get("hashtags") or []:
        tag = str(tag)
        if (len(tag.strip().lstrip("#")) < _MIN_LEN or _is_ambiguous(tag)
                or _is_company_word(tag)):
            continue
        hit = _matching_positions(msg_tokens, tag, fuzzy=fuzzy)
        if hit:
            named = True
            positions |= hit
    return frozenset(positions) if named else None


def named_programs(
    message_text: str, sections: list[dict], *, fuzzy: bool = False,
) -> list[dict]:
    """Every ACTIVE section the message names, in the given order — less any
    whose naming is part of a more exact naming of another.

    „ონლაინ საკვირაო სკოლა" names Sunday School by „საკვირაო სკოლა" and the
    online programme by that whole phrase, one of its other names. The words
    that name Sunday School lie inside the phrase that names the online one, so
    the parent meant the online one. Two programmes named by separate words
    („საკვირაო სკოლაც და პარიზის ბანაკიც") are both kept: the parent named both.
    Pure; never raises on missing fields."""
    toks = _tokens(message_text)
    if not toks:
        return []
    found: list[tuple[dict, frozenset[int]]] = []
    for s in sections:
        if not (s.get("id") or "").strip():
            continue
        if (s.get("status") or "active").strip().lower() != "active":
            continue
        span = _naming(toks, s, fuzzy=fuzzy)
        if span is not None:
            found.append((s, span))
    return [s for s, span in found if not any(span < other for _, other in found)]


def programs_answering_to_ambiguous_word(
    message_text: str, sections: list[dict],
) -> list[dict]:
    """Active sections a GENERIC word in the message could refer to.

    `match_dynamic_program` deliberately refuses the words in
    `_AMBIGUOUS_TAG_STEMS`, because one of them alone cannot identify a
    programme — „ბანაკი" would claim every programme with camp in its name at
    once. That is right, and it is also why the camp is unmatchable: its whole
    name, „საზაფხულო ბანაკი", is made of those words, so nothing in the panel
    can be reached by the word a parent actually types.

    This answers the narrower question the matcher cannot: WHICH active
    programmes answer to the generic word that was used. The caller decides
    what to do with the count — one candidate is not ambiguous at all and can
    be used directly; two or more genuinely need the parent to say which.

    Pure, and panel-driven: a programme is a candidate because of what the
    OPERATOR named it, never because of anything written here. Returns [] when
    the message names a programme specifically — that is the matcher's job and
    it has already won.
    """
    toks = _tokens(message_text)
    if not toks:
        return []
    if match_dynamic_program(message_text, sections) is not None:
        return []
    hits: list[dict] = []
    for s in sections:
        if not (s.get("id") or "").strip():
            continue
        if (s.get("status") or "active").strip().lower() != "active":
            continue
        terms = [
            t for t in _name_words(s.get("name") or "") if _is_ambiguous(t)
        ] + [
            str(t).strip().lstrip("#").lower()
            for t in (s.get("hashtags") or [])
            if len(str(t).strip().lstrip("#")) >= _MIN_LEN and _is_ambiguous(str(t))
            and not _is_company_word(str(t))
        ]
        if any(_token_matches(toks, term) for term in terms):
            hits.append(s)
    return hits


def match_dynamic_program(
    message_text: str, sections: list[dict], *, fuzzy: bool = False,
) -> dict | None:
    """Return {'program_id','type'} for the first ACTIVE section the message NAMES
    with sufficient specificity, else None — the first of `named_programs`.
    Specificity = a NON-AMBIGUOUS name word, the whole name, one of its other
    names, or a non-ambiguous hashtag. Pure; iterates `sections` in given order.

    `fuzzy` (caller passes `settings.USE_FUZZY_PROGRAM_MATCH`) enables typo/dropped-
    letter tolerance on name/tag tokens for EVERY active program. fuzzy=False ⇒
    the exact + declension-prefix matcher."""
    named = named_programs(message_text, sections, fuzzy=fuzzy)
    if not named:
        return None
    s = named[0]
    return {"program_id": (s.get("id") or "").strip(), "type": s.get("type")}
