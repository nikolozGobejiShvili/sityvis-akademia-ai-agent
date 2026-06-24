import re

# Copy the exact functions from the code
_CHALLENGE_QUESTION_STEMS = (
    "?",
    "როდის", "საათზე",
    "რა ღირს", "რამდენი ღირს", "ფასი", "ღირებულება",
    "რა შედის", "რას მოიცავ", "რა შემავალ",
    "როგორ ჩავეწერ", "როგორ ჩავწერ", "როგორ დავრეგისტრირდე",
    "სად ტარდება", "სად არის", "სად იქნება",
    "რა იგულისხმება", "პირობებში რა",
)

def _split_challenge_clauses(raw):
    parts = re.split(r'[,;]|\bასევე\b', raw or '')
    return [p.strip(' .,-—\t') for p in parts if p.strip(' .,-—\t')]

def _challenge_clause_is_question(clause):
    low = (clause or '').casefold()
    return any(stem in low for stem in _CHALLENGE_QUESTION_STEMS)

test_input = 'მეგობრები და როგორ ჩავეწერო'
print(f"Input: {repr(test_input)}")
print()

# Step 1: split
clauses = _split_challenge_clauses(test_input)
print(f"Step 1 - Split into clauses: {clauses}")
print()

# Step 2: check if question
for clause in clauses:
    is_q = _challenge_clause_is_question(clause)
    print(f"Clause {repr(clause)}: is_question={is_q}")
    if is_q:
        print(f"  Looking for question stems in: {repr(clause.casefold())}")
        for stem in _CHALLENGE_QUESTION_STEMS:
            if stem in clause.casefold():
                print(f"    FOUND: {repr(stem)}")

