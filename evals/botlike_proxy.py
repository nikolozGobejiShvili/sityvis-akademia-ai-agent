"""Layer A — canned/botlike-footprint proxy (Phase 1, Task 2).

FREE, deterministic, READ-ONLY diagnostic. It counts how many known
canned/stock markers appear in a single agent reply — a cheap, offline
PROXY for "how templated does this reply look", not a judgement of
naturalness itself. It is meant to run on EVERY commit (no API key, no
network call), alongside the paid/occasional LLM naturalness judge that
lands in Task 3 — that judge is the ground truth; this module is only a
correlate that catches gross regressions for free. HIGHER footprint means
MORE templated. Nothing in ``app/`` is touched by this module, and nothing
outside the eval harness / tests imports it.

Marker source (Task 2 Step 1 — studied before writing this module)
--------------------------------------------------------------------
1. Canned MENU marker — ``app/agent/templates/parent/welcome.yaml``
   (loaded at runtime as ``data.prompts.PARENT_WELCOME``) is the static
   two-option PARENT welcome menu::

       გვითხარით, რა გაინტერესებთ:
       — ბავშვების საზაფხულო ბანაკი
       — ზრდასრულთა კულტურული საღამოები

   We deliberately do NOT match this byte-for-byte: the operator can
   reword the YAML, and a live reply typically PARAPHRASES the same
   two-option offer rather than repeating it verbatim (e.g. "ბანაკი თუ
   ზრდასრულთა ღონისძიება?"). So ``canned_menu`` fires on either (a) the
   distinctive literal opening line of the real welcome text, or (b) the
   MENU PATTERN itself — a reply that mentions both the camp topic and
   the adult-event topic in the same breath, which is exactly what the
   two-option menu (and any paraphrase of it) does. This is a proxy, not
   an exact-string oracle: a reply that legitimately discusses both camp
   and adult programs in one sentence would also trip it — acceptable
   for a free correlate, documented here so nobody mistakes it for truth.

2. Stock-phrase markers — ``app/agent/llm/parent_llm_engine.py``
   ``FORBIDDEN_PHRASE_REPLACEMENTS`` is a large (~191-entry, growing)
   tuple of ``(bad_phrase, approved_phrase)`` pairs; the sanitizer
   rewrites raw LLM output so it converges on the approved (right-hand
   side) phrasing every time. We do NOT import or depend on that table —
   it is large and changes on nearly every patch, which would make this
   module flaky. Instead we hardcode two small, STABLE, curated subsets
   of its right-hand-side values below (~11 phrases total), split by
   what kind of "canned" they signal:

   - ``_SANITIZER_CORRECTION_MARKERS`` — narrow, mechanical grammar/case
     corrections the sanitizer performs (e.g. the locative-case fix
     "გადატანაში დაგეხმარებით", the declension fix "ეკრანისგან
     დისტანცია"). Their presence means the reply matches an EXACT
     sanitizer-corrected string, a strong templated signal.
   - ``_STOCK_PHRASE_MARKERS`` — broader brand-standard boilerplate the
     agent recites verbatim across many conversations (manager handoff,
     booking-confirmed line, the child-data privacy notice from
     ``app/flows/parent_flow.py::_PRIVACY_NOTICE``, canned closings).

   Both lists are chosen for being (a) distinctive multi-word phrases
   unlikely to occur in genuinely varied natural language, and (b)
   load-bearing / stable across many historical patches (see CLAUDE.md
   "არასოდეს" rules referencing them) — so this module should not need
   churn every time the giant replacement table gains an entry.

Binding constraints
--------------------
FREE + deterministic: no API call, no network, no OpenAI import. Output
is byte-stable across runs for the same input. Never raises out of the
two public functions — bad/empty/``None`` input degrades to an all-zero
result instead of an exception.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Canned-menu markers
# ---------------------------------------------------------------------------

# The distinctive opening line of the real static welcome menu
# (app/agent/templates/parent/welcome.yaml -> "welcome"). Chosen because it
# is unlikely to appear outside that exact template.
_MENU_LITERAL_MARKER = "გვითხარით, რა გაინტერესებთ"

# The two topic stems the welcome menu offers side by side. A reply that
# mentions BOTH in one breath is presenting (or paraphrasing) the same
# two-option choice, regardless of exact wording.
_CAMP_MENU_STEM = "ბანაკ"
_ADULT_MENU_STEM = "ზრდასრულ"

# ---------------------------------------------------------------------------
# Stock-phrase markers — curated subset of FORBIDDEN_PHRASE_REPLACEMENTS'
# right-hand-side (approved) values. See module docstring §2 for rationale.
# Do NOT grow this list to mirror the live table — it is intentionally a
# small, stable sample, not full coverage.
# ---------------------------------------------------------------------------

_SANITIZER_CORRECTION_MARKERS: tuple[str, ...] = (
    # Locative-case reschedule fix ("გადატანას დავეხმარები" -> this).
    "კონსულტაციის გადატანაში დაგეხმარებით",
    # Declension fix for the screen-time typo ("ეკრანსიგან" -> this).
    "ეკრანისგან დისტანცია",
    # Brand-standard slot-preference question wording.
    "რომელი დროა თქვენთვის მოსახერხებელი",
    # Verb-form-corrected age request ("ჩამოუყალიბეთ..." -> this).
    "მითხარით თქვენი შვილის ასაკი",
)

_STOCK_PHRASE_MARKERS: tuple[str, ...] = (
    # Brand-standard manager-handoff core phrase (many LHS variants all
    # converge here — "მოგიწყობთ" / "კავშირით" / bare "დაგაკავშირებთ." /...).
    "დაგაკავშირებთ მენეჯერთან",
    # Booking-confirmed canned phrasing ("მყარი ჯავშანი" -> this).
    "კონსულტაცია ჩანიშნულია",
    # Canned manager-clarifies handoff line.
    "მენეჯერი დეტალებს დაგიზუსტებთ",
    # Canned business-hours range recited verbatim.
    "10:00-დან 21:00-მდე",
    # Canned contact-request phrasing.
    "მომწერეთ თქვენი 9-ნიშნა საკონტაქტო ნომერი",
    # Canned closing line.
    "თუ კიდევ რაიმე გაგიჩნდებათ, შემეხმიანეთ",
    # Child-data privacy notice (app/flows/parent_flow.py::_PRIVACY_NOTICE) —
    # not itself a FORBIDDEN_PHRASE_REPLACEMENTS entry, but the same kind of
    # verbatim, stable, brand-standard boilerplate the sanitizer layer
    # protects; included per the Task 2 brief's own example.
    "თქვენი ინფორმაცია გამოიყენება მხოლოდ კონსულტაციისთვის და საჯაროდ არ გამოქვეყნდება",
)


def canned_footprint(response: "str | None") -> dict:
    """Count known canned/stock markers in ONE reply.

    Pure, deterministic, no API call. ``None`` / non-string / empty input
    yields an all-zero footprint instead of raising.

    Returns
    -------
    dict with:
      - ``sanitizer_hits``: count of matched ``_SANITIZER_CORRECTION_MARKERS``
      - ``canned_menu``: bool — the two-option welcome menu (or a paraphrase
        of it) was detected
      - ``stock_phrase_hits``: count of matched ``_STOCK_PHRASE_MARKERS``
      - ``footprint``: ``sanitizer_hits + stock_phrase_hits +
        (1 if canned_menu else 0)`` — HIGHER means MORE templated.

    This is a PROXY for "botlike", not ground truth — see module docstring.
    """
    try:
        text = response if isinstance(response, str) else ""

        sanitizer_hits = sum(
            1 for phrase in _SANITIZER_CORRECTION_MARKERS if phrase in text
        )
        stock_phrase_hits = sum(
            1 for phrase in _STOCK_PHRASE_MARKERS if phrase in text
        )
        canned_menu = bool(text) and (
            _MENU_LITERAL_MARKER in text
            or (_CAMP_MENU_STEM in text and _ADULT_MENU_STEM in text)
        )
        footprint = sanitizer_hits + stock_phrase_hits + (1 if canned_menu else 0)

        return {
            "sanitizer_hits": sanitizer_hits,
            "canned_menu": canned_menu,
            "stock_phrase_hits": stock_phrase_hits,
            "footprint": footprint,
        }
    except Exception:
        # Never raise out of this public function — a scoring proxy must
        # never crash the eval run it's supporting.
        return {
            "sanitizer_hits": 0,
            "canned_menu": False,
            "stock_phrase_hits": 0,
            "footprint": 0,
        }


def botlike_proxy_score(responses: "list[str] | None") -> dict:
    """Aggregate ``canned_footprint`` over a batch of replies.

    Empty/``None`` input returns all-zero aggregates and never raises.

    Returns
    -------
    dict with ``avg_footprint`` (float), ``canned_menu_rate`` (float in
    [0.0, 1.0]), and ``n`` (int — the number of responses scored).
    """
    try:
        items = list(responses) if responses else []
        n = len(items)
        if n == 0:
            return {"avg_footprint": 0.0, "canned_menu_rate": 0.0, "n": 0}

        footprints: list[int] = []
        menu_hits = 0
        for item in items:
            fp = canned_footprint(item)
            footprints.append(fp["footprint"])
            if fp["canned_menu"]:
                menu_hits += 1

        return {
            "avg_footprint": sum(footprints) / n,
            "canned_menu_rate": menu_hits / n,
            "n": n,
        }
    except Exception:
        return {"avg_footprint": 0.0, "canned_menu_rate": 0.0, "n": 0}
