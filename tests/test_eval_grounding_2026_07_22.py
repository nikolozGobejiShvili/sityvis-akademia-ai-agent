from evals.grounding import grade_grounding

FACTS = ["480", "ვაკე", "18:00"]
FORBIDDEN = ["2150", "კაჭრეთი"]


def test_grounded_reply_scores_high_and_passes():
    r = grade_grounding("ღირს 480 ლარი, ვაკეში, ორშაბათს 18:00.", FACTS, FORBIDDEN)
    assert r["grounded"] is True and r["score"] == 1.0 and r["inventions"] == []


def test_omitted_fact_lowers_score_but_may_still_ground():
    r = grade_grounding("ვაკეში ტარდება, 18:00.", FACTS, FORBIDDEN)   # price omitted (the Q2 failure)
    assert r["grounded"] is True and r["score"] < 1.0 and "480" in r["facts_missing"]


def test_invented_fact_vetoes_grounding():
    r = grade_grounding("ღირს 2150 ლარი.", FACTS, FORBIDDEN)  # invented camp price
    assert r["grounded"] is False and "2150" in r["inventions"]


def test_no_facts_at_all_is_not_grounded():
    r = grade_grounding("გამარჯობა, როგორ ხართ?", FACTS, FORBIDDEN)
    assert r["grounded"] is False and r["score"] == 0.0


def test_invention_vetoes_even_when_other_facts_present():
    # VETO semantics: an invention forces grounded=False regardless of how
    # many real facts are ALSO present (score can still be high).
    r = grade_grounding("ღირს 480 ლარი, ვაკეში, 18:00 საათზე — ან იქნებ 2150?",
                         FACTS, FORBIDDEN)
    assert r["score"] == 1.0
    assert r["inventions"] == ["2150"]
    assert r["grounded"] is False


# ── negation guard (hard constraint, 2026-07-22 revision) ──────────────────
# A cheap substring check would wrongly count "480" as PRESENT inside
# "არა 480 არ ღირს" (the user/agent explicitly saying it is NOT 480). This is
# a lightweight structural guard — NOT a full negation/scope parser, and NOT
# a responsiveness judge (see the module docstring) — but it must catch the
# textbook immediately-preceding-negation case.
def test_negated_fact_is_not_counted_as_present():
    r = grade_grounding("არა 480 არ ღირს", ["480"], [])
    assert "480" not in r["facts_present"]
    assert "480" in r["facts_missing"]
    assert r["grounded"] is False


def test_negated_occurrence_does_not_block_a_later_non_negated_occurrence():
    # "480" appears twice: once negated ("არა 480"), once asserted plainly.
    # At least one non-negated occurrence ⇒ still counts as present.
    r = grade_grounding("არა 480, სინამდვილეში ღირს 480 ლარი.", ["480"], [])
    assert "480" in r["facts_present"]


def test_negation_word_embedded_in_a_longer_word_does_not_suppress_the_fact():
    # "არა" appearing as a PREFIX of a longer, unrelated word right before the
    # fact must not be mistaken for the negation particle itself.
    r = grade_grounding("არაფერი — ღირს 480 ლარი", ["480"], [])
    assert "480" in r["facts_present"]


def test_negation_in_an_earlier_clause_does_not_suppress_a_later_fact():
    # The negation is in an earlier CLAUSE (separated by a period) — it must
    # not reach across the clause boundary to suppress an unrelated fact.
    r = grade_grounding("ეს არ არის სწორი. სხვა პროგრამა ღირს 480 ლარი.", ["480"], [])
    assert "480" in r["facts_present"]
