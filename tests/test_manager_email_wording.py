"""Manager-email wording regression tests.

Captures the live findings:
  * Genitive "სიტყვის აკადემიის" (NOT "სიტყვის აკადემიაის").
  * No "ღრმა ფესვი" / "deeper_concern" / "სიღრმისეული მიზეზი" labels.
  * deeper_concern shown ONLY when meaningful and not a duplicate of
    challenge/desired_change.
  * Challenge surfaced under "ინტერესი / გამოწვევა:", not the bare
    "გამოწვევა:".
  * Structured fields are not repeated inside the summary block.
"""

from __future__ import annotations

import dataclasses

import pytest

from app.config import settings as global_settings
from app.models.lead import Lead
from app.services import notification_service


# -- helpers --------------------------------------------------------------


def _booked_lead(**overrides) -> Lead:
    base = dict(
        sender_id="test-sender-1",
        platform="messenger",
        segment="PARENT",
        name="მარამი",
        phone="595999733",
        child_age="16",
        challenge="ახალი თავგადასავლები და ბავშვის განვითარება",
        desired_change="ახალი გარემო და განვითარება",
        deeper_concern="ბავშვი ახალ გარემოსთან შეგუებაში მორცხვობს",
        calendly_booked=True,
        booked_datetime_iso="2026-05-27T10:00:00+04:00",
        conversation_summary=(
            # LLM-style narrative that includes the structured fields
            # — must NOT be re-printed in the email body.
            "მშობელი დაინტერესებულია ბანაკით. ბავშვი 16 წლისაა. "
            "ინტერესი: ახალი თავგადასავლები."
        ),
        status="Booked",
    )
    base.update(overrides)
    return Lead(**base)


def _build_body(lead: Lead) -> str:
    """Render with the company-name patched to the canonical brand."""
    return notification_service._manager_email_body(lead)


@pytest.fixture(autouse=True)
def _pin_company_name(monkeypatch):
    swapped = dataclasses.replace(
        global_settings, COMPANY_NAME="სიტყვის აკადემია",
    )
    monkeypatch.setattr(notification_service, "settings", swapped)
    yield


# -- (1) Georgian genitive helper ---------------------------------------


@pytest.mark.parametrize(
    "stem, expected",
    [
        ("სიტყვის აკადემია", "სიტყვის აკადემიის"),
        ("აკადემია", "აკადემიის"),
        ("სკოლა", "სკოლის"),
        ("კოლეჯი", "კოლეჯის"),
        ("ცენტრი", "ცენტრის"),
        ("Word Academy", "Word Academyის"),  # consonant ending → append
    ],
)
def test_georgian_genitive_inflects_correctly(stem, expected):
    assert notification_service._georgian_genitive(stem) == expected


# -- (2) Email body greeting uses correct genitive -----------------------


def test_email_body_uses_correct_georgian_genitive():
    body = _build_body(_booked_lead())
    assert "სიტყვის აკადემიის" in body
    assert "სიტყვის აკადემიაის" not in body, (
        f"incorrect Georgian genitive leaked through:\n{body}"
    )


# -- (3) No forbidden labels in email -----------------------------------


@pytest.mark.parametrize(
    "forbidden",
    [
        "ღრმა ფესვი",
        "deeper_concern",
        "სიღრმისეული მიზეზი",
        "root cause",
        "deeper concern",
    ],
)
def test_email_body_does_not_contain_forbidden_labels(forbidden):
    body = _build_body(_booked_lead())
    assert forbidden not in body, (
        f"forbidden label {forbidden!r} leaked into:\n{body}"
    )


# -- (4) deeper_concern shown conditionally ----------------------------


def test_deeper_concern_shown_under_natural_label_when_meaningful():
    body = _build_body(_booked_lead())
    assert "მშობლის დამატებითი დაკვირვება:" in body
    assert "ბავშვი ახალ გარემოსთან შეგუებაში მორცხვობს" in body


def test_deeper_concern_line_omitted_when_empty():
    body = _build_body(_booked_lead(deeper_concern=""))
    assert "მშობლის დამატებითი დაკვირვება" not in body
    # The em-dash PLACEHOLDER ("label: —") must not appear; a free-form
    # em-dash in prose is OK after the Session 7 summary rewrite which
    # uses " — მთავარი ფოკუსი: ..." as sentence punctuation.
    assert ": —" not in body
    assert ": -" not in body


def test_deeper_concern_line_omitted_when_em_dash_placeholder():
    body = _build_body(_booked_lead(deeper_concern="—"))
    assert "მშობლის დამატებითი დაკვირვება" not in body


def test_deeper_concern_line_omitted_when_duplicate_of_challenge():
    body = _build_body(_booked_lead(
        deeper_concern="ახალი თავგადასავლები და ბავშვის განვითარება",
    ))
    # Challenge IS shown; deeper_concern duplicate is omitted.
    assert "ინტერესი / გამოწვევა:" in body
    assert "მშობლის დამატებითი დაკვირვება" not in body


def test_deeper_concern_line_omitted_when_duplicate_of_desired_change():
    body = _build_body(_booked_lead(
        deeper_concern="ახალი გარემო და განვითარება",
    ))
    assert "სასურველი ცვლილება:" in body
    assert "მშობლის დამატებითი დაკვირვება" not in body


# -- (5) Renamed challenge label ---------------------------------------


def test_email_uses_interest_or_challenge_label():
    body = _build_body(_booked_lead())
    assert "ინტერესი / გამოწვევა:" in body
    # The bare "გამოწვევა:" label (without the slash form) must not
    # appear as a standalone line label, but a substring "გამოწვევა"
    # may legitimately appear elsewhere — we assert the BARE label
    # ":" delimiter form is gone.
    lines = body.splitlines()
    bare_lines = [
        ln for ln in lines
        if ln.startswith("გამოწვევა:")
    ]
    assert bare_lines == [], (
        f"bare 'გამოწვევა:' label survived in lines: {bare_lines}"
    )


# -- (6) Booking time formatted naturally ------------------------------


def test_booking_line_shows_formatted_georgian_date():
    body = _build_body(_booked_lead(
        booked_datetime_iso="2026-05-27T10:00:00+04:00",
    ))
    # The structured line and the summary both reference the same time.
    assert "27 მაისი" in body
    assert "10:00" in body


def test_booking_line_falls_back_when_iso_missing():
    body = _build_body(_booked_lead(
        booked_datetime_iso="",
    ))
    # Booked flag still set → label uses the yes-text rather than the
    # parsed date.
    assert "კონსულტაცია: დაჯავშნილია" in body


def test_unbooked_lead_shows_no_booking_yes_label():
    body = _build_body(_booked_lead(
        calendly_booked=False,
        booked_datetime_iso="",
        status="Qualified",
    ))
    # Either "ჯერ არ არის დაჯავშნული" (new default) or "არა" — anything
    # but the booked-yes sentence.
    assert "დაჯავშნილია" not in body or "ჯერ არ" in body


# -- (7) Contact-info block --------------------------------------------


def test_email_includes_contact_info_block():
    body = _build_body(_booked_lead())
    assert "საკონტაქტო ინფორმაცია:" in body
    assert "სახელი: მარამი" in body
    assert "ტელეფონი: 595999733" in body


def test_email_omits_contact_block_when_no_name_or_phone():
    body = _build_body(_booked_lead(name="", phone=""))
    assert "საკონტაქტო ინფორმაცია" not in body
    assert "სახელი:" not in body


# -- (8) Summary does not repeat structured fields ---------------------


def test_summary_is_short_fixed_georgian_not_llm_narrative():
    body = _build_body(_booked_lead())
    # Pull the summary block by looking for the section header.
    assert "მოკლე რეზიუმე:" in body
    summary_idx = body.index("მოკლე რეზიუმე:")
    summary_block = body[summary_idx:]
    # The LLM narrative the test_lead carries is NOT in the email.
    assert "ბავშვი 16 წლისაა" not in summary_block
    assert "ინტერესი: ახალი თავგადასავლები" not in summary_block
    # Instead, a short fixed sentence references the booking.
    assert "კონსულტაცია" in summary_block


def test_summary_does_not_repeat_challenge():
    body = _build_body(_booked_lead())
    challenge = "ახალი თავგადასავლები და ბავშვის განვითარება"
    # Session 7 Patch (2026-06-06) — the summary now intentionally
    # weaves the challenge into the manager-facing sentence ("მთავარი
    # ფოკუსი: <challenge>") so a manager scanning the email can see
    # the topic without reading the full structured block. We assert
    # the challenge does NOT explode to 3+ occurrences (would mean
    # accidental triple-print) and the doubled live-bug pattern is
    # absent.
    assert body.count(challenge) <= 2
    assert challenge + " " + challenge not in body


def test_summary_does_not_repeat_desired_change():
    body = _build_body(_booked_lead())
    desire = "ახალი გარემო და განვითარება"
    assert body.count(desire) == 1


def test_summary_does_not_repeat_deeper_concern():
    body = _build_body(_booked_lead())
    deeper = "ბავშვი ახალ გარემოსთან შეგუებაში მორცხვობს"
    assert body.count(deeper) == 1


def test_unbooked_summary_mentions_manager_handoff():
    body = _build_body(_booked_lead(
        calendly_booked=False,
        booked_datetime_iso="",
        status="Qualified",
    ))
    assert "მენეჯერ" in body  # the "manager contact" sentence
    assert "ჩანიშნულია" not in body  # no booking-success line


# -- (9) Full booked-lead body smoke check -----------------------------


def test_full_booked_email_structure():
    body = _build_body(_booked_lead())
    # All required sections exist in order. Session 7 Patch (2026-06-06)
    # — Bug 4: booked leads use the „ახალი კონსულტაცია ჩაინიშნა"
    # headline so a manager skimming the inbox sees the consultation
    # context. Unbooked leads keep „ახალი ლიდი".
    assert body.startswith("ახალი კონსულტაცია ჩაინიშნა სიტყვის აკადემიის AI Agent-იდან")
    sections = (
        "პლატფორმა: messenger",
        "სეგმენტი: PARENT",
        "სტატუსი: Booked",
        "ბავშვის ასაკი: 16",
        "ინტერესი / გამოწვევა:",
        "სასურველი ცვლილება:",
        "მშობლის დამატებითი დაკვირვება:",
        "კონსულტაცია:",
        "საკონტაქტო ინფორმაცია:",
        "სახელი: მარამი",
        "ტელეფონი: 595999733",
        "მოკლე რეზიუმე:",
    )
    last_idx = -1
    for needle in sections:
        idx = body.find(needle)
        assert idx > last_idx, (
            f"section {needle!r} out of order or missing in:\n{body}"
        )
        last_idx = idx
