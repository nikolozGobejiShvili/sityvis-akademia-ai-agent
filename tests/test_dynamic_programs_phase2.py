from app.reasoning.dynamic_program_match import match_dynamic_program, _AMBIGUOUS_TAG_STEMS

_ROBOTICS = {"id": "robotics_club", "name": "რობოტიკის კლუბი", "type": "kids_program",
             "status": "active", "hashtags": ["რობოტიკა", "robotics"]}
_ADULT = {"id": "adult_events", "name": "ზრდასრულთა ღონისძიება", "type": "adult_events",
          "status": "active", "hashtags": ["ღონისძიება", "საღამო"]}
_CAMP = {"id": "summer_camp", "name": "საზაფხულო ბანაკი", "type": "camp",
         "status": "active", "hashtags": ["ბანაკი", "camp"]}

def test_matches_inflected_program_name():
    assert match_dynamic_program("რობოტიკის კლუბი რა ღირს?", [_ROBOTICS, _ADULT, _CAMP]) \
        == {"program_id": "robotics_club", "type": "kids_program"}

def test_no_latin_substring_false_positive():
    assert match_dynamic_program("this is a campaign about prevention", [_CAMP]) is None

def test_bare_ambiguous_hashtag_does_not_hijack_to_adult():
    m = match_dynamic_program("ბანაკში საღამოს რა ხდება?", [_ADULT, _CAMP])
    assert m is None or m["program_id"] == "summer_camp"   # never adult via bare "საღამო"

def test_empty_and_no_match():
    assert match_dynamic_program("", [_ROBOTICS]) is None
    assert match_dynamic_program("ამინდი როგორია დღეს", [_ROBOTICS]) is None

def test_ambiguous_stems_cover_classifier_keywords():
    # Drift guard: every camp/adult/price keyword the router already owns must be
    # reflected in the matcher's ambiguous set, so a hashtag equal to one of them
    # can never trigger a dynamic override. Fails if someone adds a keyword to
    # conversation_service without updating _AMBIGUOUS_TAG_STEMS.
    from app.services.conversation_service import (
        CAMP_KEYWORDS, ADULT_KEYWORDS, PRICE_KEYWORDS,
    )
    amb = tuple(_AMBIGUOUS_TAG_STEMS)
    for kw in (*CAMP_KEYWORDS, *ADULT_KEYWORDS, *PRICE_KEYWORDS):
        k = kw.lower()
        assert any(k.startswith(a) or a.startswith(k) for a in amb), \
            f"classifier keyword {kw!r} not covered by _AMBIGUOUS_TAG_STEMS"

def test_ambiguous_word_in_name_does_not_hijack():
    poetry = {"id": "poetry", "name": "პოეზიის საღამო", "type": "adult_events",
              "status": "active", "hashtags": []}
    # A bare ambiguous word ("საღამო") appearing in the message must NOT match
    # the program via its NAME token, same as the hashtag-gating rule.
    assert match_dynamic_program("დღეს საღამოს რა ხდება?", [poetry]) is None
    # But a program with a specific (non-ambiguous) name token is still matched
    # by that specific word.
    assert match_dynamic_program("რობოტიკის კლუბი რა ღირს?", [_ROBOTICS, poetry]) \
        == {"program_id": "robotics_club", "type": "kids_program"}

def test_inactive_section_not_matched():
    inactive_robotics = dict(_ROBOTICS, status="inactive")
    assert match_dynamic_program("რობოტიკის კლუბი რა ღირს?", [inactive_robotics]) is None
