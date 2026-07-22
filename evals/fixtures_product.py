"""A synthetic, season-independent product for measuring the reasoning
mechanism (Phase 3.0, Task 3).

Camp is NOT a live product — its season ended 2026-07-20 (operator decision,
2026-07-22) — so any case that depends on live camp streams is confounded by
the registration-closed fallback. To measure the MECHANISM (does the LLM
reason over a product's real facts via `get_program_info`, not a memorised
camp answer) product-agnostically, this module injects one stable, clearly-
synthetic, non-reserved admin product ("რობოტიკის კლუბი" — a robotics club)
with KNOWN, distinctive facts and a future/season-independent identity.

Its facts ARE the ground truth (operator OQ2: a case grades a reply against
these FACTS, never against a hand-written model answer — authoring per-
question "correct" strings would re-create the template pathology Phase 3.0
removes). `FORBIDDEN_INVENTIONS` are camp's real facts (price 2150 / age
band 9-17 / "ამბასადორი" / "კაჭრეთი") — if any of these leak into a reply
about the synthetic product, the model invented / cross-contaminated facts
instead of grounding in the tool result, which is exactly the Q2-class
failure (3.0b: engine called `get_camp_info` then omitted/confused facts).
"""
from __future__ import annotations

# The product itself, shaped exactly like an admin `sections.yaml` entry (see
# app/services/admin_config_service.get_active_sections / get_section and the
# `_PROGRAM_PUBLIC_FIELDS` allowlist in
# app/agent/tools/parent_tool_executor.ParentToolExecutor._get_program_info).
PRODUCT: dict = {
    "id": "robotics_club_eval",
    "name": "რობოტიკის კლუბი",
    "type": "club",
    "status": "active",
    "age_min": 10,
    "age_max": 15,
    "price_text": "480",
    "location": "ვაკე, ჭავჭავაძის 12",
    "registration_url": "https://example.com/robotics-eval",
    "registration_status": "open",
    "description_short": "რობოტიკის კლუბი 10-15 წლის მოზარდებისთვის.",
    "schedule_text": "ორშაბათი და ხუთშაბათი 18:00",
    # "კლუბ" is itself an ambiguous stem in dynamic_program_match, so the
    # hoist relies on the NAME token "რობოტიკის" (non-ambiguous, >=4 chars)
    # — the hashtag is additional specificity only, not load-bearing.
    "hashtags": ["#რობოტიკა_eval"],
}

# Facts that a correct, grounded answer to a matching question MUST surface.
# Distinctive tokens chosen so grounding checks are unambiguous (no overlap
# with any real product's facts).
FACTS: list[str] = ["480", "10", "15", "ვაკე", "18:00"]

# Fact-shaped strings that are NOT this product's facts — they are the real
# summer-camp's facts (price / age band / location). Their appearance in a
# reply about the synthetic product is an invention (fact leakage), never a
# legitimate answer, so grade_grounding (Task 4) VETOES on any of these.
FORBIDDEN_INVENTIONS: list[str] = ["2150", "9", "17", "ამბასადორი", "კაჭრეთი"]


def install(monkeypatch) -> dict:
    """Make BOTH admin_config_service accessors the live paths read see
    exactly this one product:

      * `get_active_sections()` — read by `dynamic_program_match.match_dynamic_program`
        (via `parent_flow._is_dynamic_program_turn` / `conversation_service.
        _match_active_program_segment`) so a turn NAMING the product hoists
        straight to the LLM engine, above the camp deterministic chain.
      * `get_section(program_id)` — read by
        `ParentToolExecutor._get_program_info` so the tool's returned facts
        are exactly `PRODUCT` (and therefore `FACTS`/`FORBIDDEN_INVENTIONS`
        above describe what SHOULD and should NOT appear in a grounded
        reply).

    Returns the product dict for convenience (callers rarely need it — the
    module-level PRODUCT/FACTS/FORBIDDEN_INVENTIONS are the normal imports).
    """
    import app.services.admin_config_service as acs

    monkeypatch.setattr(acs, "get_active_sections", lambda: [dict(PRODUCT)])
    monkeypatch.setattr(
        acs, "get_section",
        lambda section_id: dict(PRODUCT) if section_id == PRODUCT["id"] else None,
    )
    return PRODUCT
