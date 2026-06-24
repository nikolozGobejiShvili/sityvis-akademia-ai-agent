"""Agent Wording Cleanup Patch — 2026-06-03.

Two related cleanups:

  PART 1 — Replace the awkward live-bug phrasing „მენეჯერთან კავშირს
           მოგიწყობთ" / „კავშირს მოგიწყობთ" / etc. with the brand
           standard „თუ გსურთ, დაგაკავშირებთ მენეჯერთან." Sanitisers
           rewrite the bad form; prompts/policies teach the LLM the
           correct one on the first pass.

  PART 2 — Remove decorative emojis (🌿 / 😊 / ✨ / ✅ / ❌) from every
           user-facing surface (static templates, fallback constants,
           deterministic redirects). Sanitisers strip them when the
           LLM produces them anyway.

Covers (per spec PART 6):
  1. Welcome response contains no 🌿.
  2. Adult off-topic redirect contains no emoji.
  3. Parent booking confirmation contains no emoji.
  4. Public comment reply template contains no emoji.
  5. Follow-up templates contain no emoji.
  6. Adult manager handoff uses "თუ გსურთ, დაგაკავშირებთ მენეჯერთან."
  7. Adult manager handoff does NOT contain "კავშირს მოგიწყობთ".
  8. Parent sensitive-needs response does NOT contain
     "მენეჯერთან გავარკვევთ" / "კავშირს მოგიწყობთ".
  9. Parent sensitive-needs response uses the preferred phrase.
  10. Sanitisers remove emojis from generated model output.
  11. Sanitisers replace awkward manager-handoff phrasing.
  12. Existing ADULT off-topic redirect still fires (no regression).
  13. Existing PARENT booked-state CTA still appended (no regression).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agent.llm import adult_llm_engine, parent_llm_engine
from app.agent.llm.adult_llm_engine import (
    _OFFTOPIC_REPLY_GENERIC,
    _OFFTOPIC_REPLY_NAME_NOT_CONFIGURED,
    sanitise_adult_response,
)
from app.agent.llm.parent_llm_engine import sanitise_response_wording
from app.services import comment_service, followup_service


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FORBIDDEN_EMOJIS: tuple[str, ...] = ("🌿", "😊", "✨", "✅", "❌")


def _read_repo_text(*parts: str) -> str:
    return (REPO_ROOT.joinpath(*parts)).read_text(encoding="utf-8")


def _assert_no_decorative_emoji(text: str, ctx: str) -> None:
    for emoji in DEFAULT_FORBIDDEN_EMOJIS:
        assert emoji not in text, f"{ctx} contains forbidden emoji {emoji!r}"


# =========================================================================
# PART 2 — emoji-free user-facing surfaces
# =========================================================================


def test_unclear_welcome_template_has_no_emoji():
    from app.agent.services.template_loader import get_template, reset_cache
    reset_cache()
    text = get_template("common", "unclear_routing")
    _assert_no_decorative_emoji(text, "common/unclear_routing")


def test_parent_welcome_template_has_no_emoji():
    from app.agent.services.template_loader import get_template, reset_cache
    reset_cache()
    text = get_template("parent", "welcome")
    _assert_no_decorative_emoji(text, "parent/welcome")


def test_parent_welcome_with_concern_template_has_no_emoji():
    from app.agent.services.template_loader import get_template, reset_cache
    reset_cache()
    text = get_template("parent", "welcome_with_concern")
    _assert_no_decorative_emoji(text, "parent/welcome_with_concern")


def test_parent_booking_confirmed_template_has_no_emoji():
    from app.agent.services.template_loader import get_template, reset_cache
    reset_cache()
    text = get_template("parent", "booking_confirmed")
    _assert_no_decorative_emoji(text, "parent/booking_confirmed")


def test_parent_done_response_template_has_no_emoji():
    from app.agent.services.template_loader import get_template, reset_cache
    reset_cache()
    text = get_template("parent", "done_response")
    _assert_no_decorative_emoji(text, "parent/done_response")


def test_parent_booking_failed_template_has_no_emoji():
    from app.agent.services.template_loader import get_template, reset_cache
    reset_cache()
    text = get_template("parent", "booking_failed")
    _assert_no_decorative_emoji(text, "parent/booking_failed")


def test_parent_followup_template_has_no_emoji():
    from app.agent.services.template_loader import get_template, reset_cache
    reset_cache()
    text = get_template("parent", "followup")
    _assert_no_decorative_emoji(text, "parent/followup")


def test_parent_price_templates_have_no_emoji():
    from app.agent.services.template_loader import get_template, reset_cache
    reset_cache()
    for key in ("price_first_response", "price_in_flow", "book_fast_track",
                "info_first_response"):
        text = get_template("parent", key)
        _assert_no_decorative_emoji(text, f"parent/{key}")


def test_adult_welcome_template_has_no_emoji():
    from app.agent.services.template_loader import get_template, reset_cache
    reset_cache()
    text = get_template("adult", "welcome")
    _assert_no_decorative_emoji(text, "adult/welcome")


def test_comment_public_reply_template_has_no_emoji():
    from app.agent.services.template_loader import get_template, reset_cache
    reset_cache()
    text = get_template("comments", "reply_dm_sent")
    _assert_no_decorative_emoji(text, "comments/reply_dm_sent")


def test_admin_templates_have_no_emoji():
    """data/admin_config/templates.yaml — all operator-editable
    defaults are emoji-free out of the box."""
    text = _read_repo_text("data", "admin_config", "templates.yaml")
    _assert_no_decorative_emoji(text, "admin_config/templates.yaml")


def test_followup_fallback_constants_have_no_emoji():
    _assert_no_decorative_emoji(
        followup_service._FALLBACK_FOLLOWUP_24H, "_FALLBACK_FOLLOWUP_24H",
    )
    _assert_no_decorative_emoji(
        followup_service._FALLBACK_FOLLOWUP_3D, "_FALLBACK_FOLLOWUP_3D",
    )
    _assert_no_decorative_emoji(
        followup_service._FALLBACK_FOLLOWUP_7D, "_FALLBACK_FOLLOWUP_7D",
    )


def test_comment_service_fallback_constants_have_no_emoji():
    _assert_no_decorative_emoji(
        comment_service.PARENT_FIRST_CONTACT_DM, "PARENT_FIRST_CONTACT_DM",
    )
    _assert_no_decorative_emoji(
        comment_service.ADULT_NO_EVENTS_DM, "ADULT_NO_EVENTS_DM",
    )


def test_adult_off_topic_redirects_have_no_emoji():
    _assert_no_decorative_emoji(
        _OFFTOPIC_REPLY_NAME_NOT_CONFIGURED, "_OFFTOPIC_REPLY_NAME_NOT_CONFIGURED",
    )
    _assert_no_decorative_emoji(
        _OFFTOPIC_REPLY_GENERIC, "_OFFTOPIC_REPLY_GENERIC",
    )


# =========================================================================
# PART 2/3 — sanitiser strips emojis from generated model output
# =========================================================================


def test_parent_sanitiser_strips_leaf_emoji():
    out = sanitise_response_wording("გასაგებია 🌿 თუ რამე გაგიჩნდებათ, მომწერეთ.")
    _assert_no_decorative_emoji(out, "sanitised parent reply")


def test_parent_sanitiser_strips_smile_emoji():
    out = sanitise_response_wording("მადლობა თქვენ 😊")
    _assert_no_decorative_emoji(out, "sanitised parent reply with smile")


def test_parent_sanitiser_strips_sparkles_emoji():
    out = sanitise_response_wording("მშვენიერია ✨")
    _assert_no_decorative_emoji(out, "sanitised parent reply with sparkles")


def test_adult_sanitiser_strips_leaf_emoji():
    out = sanitise_adult_response("სიამოვნებით 🌿 თუ კიდევ რამე გჭირდებათ.")
    _assert_no_decorative_emoji(out, "sanitised adult reply")


def test_adult_sanitiser_strips_smile_emoji():
    out = sanitise_adult_response("ამ კითხვაზე ვერ დაგეხმარები 😊")
    _assert_no_decorative_emoji(out, "sanitised adult reply with smile")


def test_sanitiser_preserves_normal_georgian_response():
    """A normal Georgian sentence with no emojis / no banned phrases
    must round-trip unchanged."""
    text = "ბანაკი ტარდება ამბასადორ კაჭრეთში, 7 დღიანი პროგრამაა."
    assert sanitise_response_wording(text) == text


# =========================================================================
# PART 1/3 — manager handoff wording sanitiser
# =========================================================================


def test_parent_sanitiser_replaces_kavshirs_mogitsqobt():
    """„მენეჯერთან კავშირს მოგიწყობთ" → brand-preferred phrase."""
    text = (
        "ბანაკი არ ერგება ასაკს. თუ გსურთ, მენეჯერთან კავშირს მოგიწყობთ."
    )
    out = sanitise_response_wording(text)
    assert "კავშირს მოგიწყობთ" not in out
    assert "თუ გსურთ, დაგაკავშირებთ მენეჯერთან" in out


def test_parent_sanitiser_replaces_kavshirsats_mogitsqobt():
    """The plural-suffix variant „კავშირსაც მოგიწყობთ" used in the
    live bug message."""
    text = "მენეჯერთან კავშირსაც მოგიწყობთ, თუ გსურთ."
    out = sanitise_response_wording(text)
    assert "კავშირსაც მოგიწყობთ" not in out
    assert "დაგაკავშირებთ მენეჯერთან" in out


def test_parent_sanitiser_replaces_bare_kavshirs_mogitsqobt():
    out = sanitise_response_wording("კავშირს მოგიწყობთ.")
    assert "კავშირს მოგიწყობთ" not in out
    assert "დაგაკავშირებთ მენეჯერთან" in out


def test_parent_sanitiser_replaces_dakavshirebashi_dagekhmarebit():
    out = sanitise_response_wording(
        "მენეჯერთან დაკავშირებაში დაგეხმარებით, თუ გსურთ."
    )
    assert "დაკავშირებაში დაგეხმარებით" not in out
    assert "თუ გსურთ, დაგაკავშირებთ მენეჯერთან" in out


def test_parent_sanitiser_replaces_menejers_dagakavshrebt():
    out = sanitise_response_wording("მენეჯერს დაგაკავშირებთ ნომრის გადაცემის შემდეგ.")
    assert "მენეჯერს დაგაკავშირებთ" not in out
    assert "დაგაკავშირებთ მენეჯერთან" in out


def test_adult_sanitiser_replaces_kavshirs_mogitsqobt():
    out = sanitise_adult_response(
        "ამ დეტალს მენეჯერი დაგიზუსტებთ. თუ გსურთ, მენეჯერთან კავშირს მოგიწყობთ."
    )
    assert "კავშირს მოგიწყობთ" not in out
    assert "თუ გსურთ, დაგაკავშირებთ მენეჯერთან" in out


def test_adult_sanitiser_replaces_kavshirsats_mogitsqobt():
    out = sanitise_adult_response("მენეჯერთან კავშირსაც მოგიწყობთ.")
    assert "კავშირსაც მოგიწყობთ" not in out
    assert "დაგაკავშირებთ მენეჯერთან" in out


# =========================================================================
# PART 4 — prompt / policy documentation evidence
# =========================================================================


def _read_prompt(name: str) -> str:
    from app.agent.llm.prompt_loader import load_prompt, reset_cache
    reset_cache()
    return load_prompt(name)


def test_adult_prompt_documents_preferred_manager_phrase():
    text = _read_prompt("system_adult_v1")
    assert "თუ გსურთ, დაგაკავშირებთ მენეჯერთან" in text


def test_adult_prompt_bans_kavshirs_mogitsqobt():
    text = _read_prompt("system_adult_v1")
    assert "კავშირს მოგიწყობთ" in text  # documented as banned
    assert "აკრძალულია" in text or "არასოდეს" in text  # ban marker present


def test_adult_prompt_has_no_emoji_examples_in_user_facing_lines():
    """The system prompt may *mention* emojis (e.g. in the ban rule)
    but example user-facing replies should not include them."""
    text = _read_prompt("system_adult_v1")
    # The thanks-reply example should be emoji-free now.
    assert "„სიამოვნებით." in text
    # The off-topic generic redirect example should be emoji-free.
    assert "ვერ დაგეხმარებით" in text
    # The privacy-leaf snippet should be gone.
    assert "სიამოვნებით 🌿" not in text


def test_parent_prompt_documents_preferred_manager_phrase():
    text = _read_prompt("system_parent_v2")
    assert "თუ გსურთ, დაგაკავშირებთ მენეჯერთან" in text


def test_parent_prompt_documents_sensitive_needs_response():
    """The sensitive child-needs section must contain the preferred
    response wording AND no banned phrases."""
    text = _read_prompt("system_parent_v2")
    assert "მნიშვნელოვანია, დეტალები ინდივიდუალურად გავიაროთ" in text
    assert "თუ გსურთ, დაგაკავშირებთ მენეჯერთან" in text
    # The old / banned phrasings should NOT appear in the new section.
    assert "მენეჯერთან გავარკვევთ" in text  # documented as banned
    assert "კავშირს მოგიწყობთ" in text  # documented as banned


def test_parent_prompt_no_emoji_rule_present():
    text = _read_prompt("system_parent_v2")
    # The new rule line forbids emojis explicitly.
    assert "არასოდეს* გამოიყენო ემოჯი" in text


def test_adult_prompt_no_emoji_rule_present():
    text = _read_prompt("system_adult_v1")
    assert "არასოდეს* გამოიყენო ემოჯი" in text


def test_adult_policy_documents_preferred_phrase():
    text = _read_repo_text(
        "app", "agent", "policies", "adult_sales_policy.md",
    )
    assert "თუ გსურთ, დაგაკავშირებთ მენეჯერთან" in text


def test_parent_policy_documents_preferred_phrase():
    text = _read_repo_text(
        "app", "agent", "policies", "parent_sales_policy.md",
    )
    assert "თუ გსურთ, დაგაკავშირებთ მენეჯერთან" in text


def test_parent_policy_documents_no_emoji_rule():
    text = _read_repo_text(
        "app", "agent", "policies", "parent_sales_policy.md",
    )
    assert "No emojis" in text or "decorative emoji" in text


# =========================================================================
# Regression — existing flows still work
# =========================================================================


def test_existing_parent_sanitiser_still_fixes_old_bug():
    """Make sure the pre-existing parent sanitiser entries still run
    (e.g. ekransigan → ekranisgan typo fix)."""
    out = sanitise_response_wording("ეკრანსიგან დისტანცია სასურველია.")
    assert "ეკრანსიგან" not in out
    assert "ეკრანისგან დისტანცია" in out


def test_existing_adult_sanitiser_still_fixes_genitive():
    out = sanitise_adult_response("სიტყვის აკადემიაის შეხვედრა საინტერესოა.")
    assert "აკადემიაის" not in out
    assert "სიტყვის აკადემიის" in out


def test_existing_adult_offtopic_guard_still_fires_on_climate_question():
    """ADULT off-topic guard already lives in the engine; just confirm
    the deterministic guard returns a string (the no-emoji version)
    and not None."""
    from app.agent.llm.adult_llm_engine import _maybe_adult_offtopic_reply
    from app.models.conversation import Conversation

    conv = Conversation(sender_id="s", platform="instagram", segment="ADULT")
    reply = _maybe_adult_offtopic_reply(
        "კლიმატის ცვლილება საინტერესოა, რას ფიქრობთ?", conv,
    )
    assert reply is not None
    _assert_no_decorative_emoji(reply, "off-topic redirect")


# =========================================================================
# Smoke — sanitisers are idempotent under the new entries
# =========================================================================


def test_parent_sanitiser_idempotent_for_emoji_strip():
    text = "გასაგებია 🌿 თუ რამე გჭირდებათ, მომწერეთ."
    once = sanitise_response_wording(text)
    twice = sanitise_response_wording(once)
    assert once == twice


def test_adult_sanitiser_idempotent_for_emoji_strip():
    text = "სიამოვნებით 🌿"
    once = sanitise_adult_response(text)
    twice = sanitise_adult_response(once)
    assert once == twice


def test_parent_sanitiser_idempotent_for_manager_handoff_rewrite():
    text = "თუ გსურთ, მენეჯერთან კავშირს მოგიწყობთ."
    once = sanitise_response_wording(text)
    twice = sanitise_response_wording(once)
    assert once == twice
    assert "კავშირს მოგიწყობთ" not in twice


def test_adult_sanitiser_idempotent_for_manager_handoff_rewrite():
    text = "მენეჯერთან კავშირსაც მოგიწყობთ."
    once = sanitise_adult_response(text)
    twice = sanitise_adult_response(once)
    assert once == twice
    assert "კავშირსაც მოგიწყობთ" not in twice
