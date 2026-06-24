"""ADULT Off-Topic Guard + Event Grounding + Default Min-Age Fix
— scope-guard regression tests.

Live observation: the ADULT engine answered general-knowledge
questions ("ვინაა ელტონ ჯონი?", "მუფასა სიმბას მამა თუ დედა?"). The
deterministic guard added to `adult_llm_engine` must:

  * Block "ვინ არის / ვინაა / რა არის / მითხარი … შესახებ" patterns
    when the topic is not configured.
  * Block relation questions ("მამაა თუ დედა?") when no in-scope cue.
  * Block known-fiction stems and known general-knowledge category
    stems regardless of question pattern.
  * NOT block messages that contain configured event titles / guests /
    themes / formats / locations.
  * NOT block in-scope domain stems (event vocab, reservation vocab,
    manager vocab, etc.).
  * NOT call OpenAI when the guard fires.
  * NOT affect PARENT flow.
"""

from __future__ import annotations

import textwrap
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.agent.llm import adult_llm_engine
from app.agent.llm.adult_llm_engine import _maybe_adult_offtopic_reply
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import admin_config_service


@pytest.fixture
def admin_yaml_no_elton(monkeypatch, tmp_path):
    """Default fixture: configured events do NOT contain 'ელტონ ჯონი',
    'მუფასა', or any other fictional / celebrity stem the guard tests
    will probe."""
    yaml_text = textwrap.dedent(
        """\
        sections:
        - id: adult_events
          name: ზრდასრულთა ღონისძიებები
          type: adult_events
          status: active
          hashtags: [ღონისძიება]
          auto_dm_template_id: adult_events_comment_dm
          events:
          - id: poetry_evening
            title: პოეზიის საღამო
            status: active
            min_age: 13
            date_text: ივლისი
            location: თბილისი
            theme: თანამედროვე ქართული პოეზია
            guest: გიორგი ხელაია
            format: ლიტერატურული შეხვედრა
            reservation_url: https://example.com/poetry
          - id: book_club
            title: საკითხავი კლუბი
            status: active
            min_age: 13
            date_text: აგვისტო
            location: თბილისი
            theme: წიგნის განხილვა
            guest: ''
            format: დისკუსია
        """,
    )
    sections_path = tmp_path / "sections.yaml"
    sections_path.write_text(yaml_text, encoding="utf-8")
    monkeypatch.setattr(admin_config_service, "SECTIONS_PATH", sections_path)
    return sections_path


@pytest.fixture
def admin_yaml_with_elton(monkeypatch, tmp_path):
    """Alt fixture: an event whose guest IS 'ელტონ ჯონი'. The guard
    must NOT redirect for "ვინაა ელტონ ჯონი?" here — it's a
    legitimately configured guest."""
    yaml_text = textwrap.dedent(
        """\
        sections:
        - id: adult_events
          name: ზრდასრულთა ღონისძიებები
          type: adult_events
          status: active
          hashtags: [ღონისძიება]
          auto_dm_template_id: adult_events_comment_dm
          events:
          - id: elton_recital
            title: ელტონ ჯონის სოლო კონცერტი
            status: active
            min_age: 13
            date_text: სექტემბერი
            location: თბილისი
            theme: სარეტრო მუსიკალური საღამო
            guest: ელტონ ჯონი
            format: კონცერტი
        """,
    )
    sections_path = tmp_path / "sections.yaml"
    sections_path.write_text(yaml_text, encoding="utf-8")
    monkeypatch.setattr(admin_config_service, "SECTIONS_PATH", sections_path)
    return sections_path


def _make_conversation() -> Conversation:
    conv = Conversation(sender_id="s_offtopic", platform="instagram", segment="ADULT")
    conv.lead = Lead(sender_id="s_offtopic", platform="instagram", segment="ADULT")
    return conv


# =========================================================================
# 1 — Mufasa relation question is blocked
# =========================================================================


def test_mufasa_question_blocked(admin_yaml_no_elton):
    conv = _make_conversation()
    reply = _maybe_adult_offtopic_reply(
        "მუფასა ვინ არის სიმბას მამა თუ დედა?", conv,
    )
    assert reply is not None
    # Generic / "ვერ დაგეხმარები" branch — no factual claim about Mufasa.
    assert "მუფასა" not in reply
    assert "მამა" not in reply
    assert "დედა" not in reply
    # Brand-suggestion / redirect line is present (wording softened 2026-06-23 so
    # a „who is X?" question is NOT framed as an event-not-found).
    assert "ღონისძიებ" in reply


# =========================================================================
# 2 — Elton John blocked when not configured
# =========================================================================


def test_elton_john_blocked_when_not_configured(admin_yaml_no_elton):
    conv = _make_conversation()
    reply = _maybe_adult_offtopic_reply("ვინაა ელტონ ჯონი?", conv)
    assert reply is not None
    # The "name not in program" wording must be used (a who-question
    # was asked).
    assert "პროგრამის გარეთ" in reply  # who-variant redirect (softened 2026-06-23)
    # No biographical explanation.
    assert "მომღერალი" not in reply
    assert "ბრიტანელი" not in reply
    assert "მუსიკოსი" not in reply


def test_elton_john_response_does_not_ask_about_which_event(admin_yaml_no_elton):
    """The bug: bot was saying „რომელ ღონისძიებასთან დაკავშირებით
    გაინტერესებთ?" — implies Elton John might be in the program. The
    deterministic redirect must NEVER use that wording.
    """
    conv = _make_conversation()
    reply = _maybe_adult_offtopic_reply("ვინაა ელტონ ჯონი?", conv)
    assert reply is not None
    assert "რომელ ღონისძიებასთან" not in reply
    assert "რომელ ღონისძიებაში" not in reply


# =========================================================================
# 3 — Elton John ALLOWED when configured as guest
# =========================================================================


def test_elton_john_allowed_when_configured_as_guest(admin_yaml_with_elton):
    conv = _make_conversation()
    reply = _maybe_adult_offtopic_reply("ვინაა ელტონ ჯონი?", conv)
    # In-scope (configured) → guard MUST yield to the LLM.
    assert reply is None


def test_configured_event_title_in_message_allowed(admin_yaml_no_elton):
    conv = _make_conversation()
    reply = _maybe_adult_offtopic_reply(
        "პოეზიის საღამოს შესახებ მითხარით მეტი", conv,
    )
    assert reply is None


def test_configured_guest_in_message_allowed(admin_yaml_no_elton):
    conv = _make_conversation()
    reply = _maybe_adult_offtopic_reply(
        "გიორგი ხელაია ვინაა?", conv,
    )
    # Configured guest — in-scope; LLM will answer from configured data.
    assert reply is None


# =========================================================================
# 4 — Climate change → redirect
# =========================================================================


def test_climate_change_blocked(admin_yaml_no_elton):
    conv = _make_conversation()
    reply = _maybe_adult_offtopic_reply(
        "რა არის კლიმატის ცვლილება?", conv,
    )
    assert reply is not None
    assert "კლიმატ" not in reply


# =========================================================================
# 5 — Math / physics / fiction stems blocked even without "ვინ/რა"
# =========================================================================


def test_math_topic_blocked(admin_yaml_no_elton):
    conv = _make_conversation()
    reply = _maybe_adult_offtopic_reply(
        "მათემატიკის ფორმულა ვერ მახსოვს, შემიძლია გაიხსენო?", conv,
    )
    assert reply is not None


def test_fiction_character_blocked_no_question_mark(admin_yaml_no_elton):
    """Even a flat statement mentioning a known fictional character
    should not get a legitimate response from the agent."""
    conv = _make_conversation()
    reply = _maybe_adult_offtopic_reply(
        "გენდალფი ვინ იყო ბეჭდების მბრძანებელში?", conv,
    )
    assert reply is not None


# =========================================================================
# 6 — In-scope conversational messages NOT blocked
# =========================================================================


def test_ticket_request_not_blocked(admin_yaml_no_elton):
    conv = _make_conversation()
    assert _maybe_adult_offtopic_reply(
        "ბილეთი მინდა შემოვიდე ღონისძიებაზე", conv,
    ) is None


def test_greeting_not_blocked(admin_yaml_no_elton):
    conv = _make_conversation()
    assert _maybe_adult_offtopic_reply("გამარჯობა 🌿", conv) is None


def test_age_disclosure_not_blocked(admin_yaml_no_elton):
    conv = _make_conversation()
    assert _maybe_adult_offtopic_reply("30 წლის ვარ", conv) is None


def test_short_message_skips_guard(admin_yaml_no_elton):
    """Short conversational replies (< 10 chars) MUST never trigger
    the off-topic guard — they're acks like „კი", „კარგი", „მინდა"
    that the LLM should disambiguate from history.
    """
    conv = _make_conversation()
    for short in ("კი", "კარგი", "მინდა", "არა"):
        assert _maybe_adult_offtopic_reply(short, conv) is None


def test_manager_request_not_blocked(admin_yaml_no_elton):
    conv = _make_conversation()
    assert _maybe_adult_offtopic_reply(
        "მენეჯერთან საუბარი მინდა, ნომერია 599 12 34 56", conv,
    ) is None


def test_reservation_question_not_blocked(admin_yaml_no_elton):
    conv = _make_conversation()
    assert _maybe_adult_offtopic_reply(
        "ბილეთის ჯავშნა როგორ მოვახდინო?", conv,
    ) is None


# =========================================================================
# 7 — Camp / parent-switch path still works (guard does NOT eat it)
# =========================================================================


def test_camp_request_not_classified_as_offtopic(admin_yaml_no_elton):
    """The earlier deterministic _user_wants_parent_flow check fires
    BEFORE the off-topic guard. But even if it didn't, the off-topic
    guard MUST recognise "ბანაკი" / "ბავშვი" / "შვილი" as in-scope and
    not redirect them.
    """
    conv = _make_conversation()
    for camp_msg in (
        "ბანაკის შესახებ მითხარი",
        "12 წლის ბავშვისთვის მინდა",
        "შვილისთვის ვეძებ ბანაკს",
    ):
        assert _maybe_adult_offtopic_reply(camp_msg, conv) is None, (
            f"camp/child message classified as off-topic: {camp_msg!r}"
        )


# =========================================================================
# 8 — End-to-end: run_adult_llm_turn returns redirect WITHOUT calling OpenAI
# =========================================================================


def test_offtopic_guard_does_not_call_openai(admin_yaml_no_elton, monkeypatch):
    from app.services import openai_service

    def _explode(*args, **kwargs):
        pytest.fail(
            "openai_service.chat_with_tools MUST NOT be called for an "
            "off-topic message — the deterministic guard must short-circuit."
        )

    monkeypatch.setattr(openai_service, "chat_with_tools", _explode)

    conv = _make_conversation()
    reply = adult_llm_engine.run_adult_llm_turn(
        user_message="ვინაა ელტონ ჯონი?",
        conversation=conv,
        lead=conv.lead,
        sender_id=conv.sender_id,
        platform="instagram",
    )

    assert reply is not None and reply != ""
    assert "პროგრამის გარეთ" in reply  # who-variant redirect (softened 2026-06-23)


def test_offtopic_guard_does_not_change_segment(admin_yaml_no_elton, monkeypatch):
    """Off-topic redirect MUST NOT flip the conversation segment to
    PARENT — only the deterministic _user_wants_parent_flow check
    should do that.
    """
    from app.services import openai_service
    monkeypatch.setattr(
        openai_service, "chat_with_tools",
        lambda **k: pytest.fail("openai must not be called"),
    )

    conv = _make_conversation()
    adult_llm_engine.run_adult_llm_turn(
        user_message="რა არის კლიმატის ცვლილება?",
        conversation=conv,
        lead=conv.lead,
        sender_id=conv.sender_id,
        platform="instagram",
    )

    assert conv.segment == "ADULT"


# =========================================================================
# 9 — Adult-to-parent switch still fires for camp keywords
# =========================================================================


def test_camp_keyword_still_switches_to_parent(admin_yaml_no_elton, monkeypatch):
    """Regression — adding the off-topic guard must NOT break the
    deterministic parent-switch on "ბანაკის შესახებ მითხარი".
    """
    from app.services import openai_service
    monkeypatch.setattr(
        openai_service, "chat_with_tools",
        lambda **k: pytest.fail("openai must not be called"),
    )

    conv = _make_conversation()
    reply = adult_llm_engine.run_adult_llm_turn(
        user_message="ბანაკის შესახებ მითხარი",
        conversation=conv,
        lead=conv.lead,
        sender_id=conv.sender_id,
        platform="instagram",
    )

    assert conv.segment == "PARENT"
    assert "ბანაკის შესახებ დაგეხმარებით" in reply


# =========================================================================
# 10 — Default min_age=13 fixture sanity
# =========================================================================


def test_default_min_age_constant_is_13():
    assert admin_config_service.ADULT_EVENT_DEFAULT_MIN_AGE == 13


def test_event_without_min_age_defaults_to_13(monkeypatch, tmp_path):
    yaml_text = textwrap.dedent(
        """\
        sections:
        - id: adult_events
          name: ზრდასრულთა ღონისძიებები
          type: adult_events
          status: active
          hashtags: [ღონისძიება]
          auto_dm_template_id: adult_events_comment_dm
          events:
          - id: default_event
            title: ღია ლექცია
            status: active
            # min_age intentionally absent
            date_text: ''
            location: ''
            theme: ''
        """,
    )
    sections_path = tmp_path / "sections.yaml"
    sections_path.write_text(yaml_text, encoding="utf-8")
    monkeypatch.setattr(admin_config_service, "SECTIONS_PATH", sections_path)

    events = admin_config_service.get_adult_events()
    assert events[0]["min_age"] == 13


def test_age_13_sees_default_event(monkeypatch, tmp_path):
    yaml_text = textwrap.dedent(
        """\
        sections:
        - id: adult_events
          name: ზრდასრულთა ღონისძიებები
          type: adult_events
          status: active
          hashtags: [ღონისძიება]
          auto_dm_template_id: adult_events_comment_dm
          events:
          - id: default_event
            title: ღია ლექცია
            status: active
            min_age: 13
            date_text: ''
            location: ''
            theme: ''
        """,
    )
    sections_path = tmp_path / "sections.yaml"
    sections_path.write_text(yaml_text, encoding="utf-8")
    monkeypatch.setattr(admin_config_service, "SECTIONS_PATH", sections_path)

    events_for_13 = admin_config_service.get_active_adult_events(user_age=13)
    assert any(e["id"] == "default_event" for e in events_for_13)
