"""With no camp running, ask for the contact instead of offering to connect.

„თუ გსურთ, დეტალებზე მენეჯერთან დაგაკავშირებთ" left the next move to the
parent and most of those conversations ended there. The operator's instruction
is to say the camp is over and ask for the name and number outright, so the
manager can call back about the next intake.

Only ever reached when NO camp is running: another active camp takes the turn
to its own programme before this, and two active camps are asked about. So the
sentence is only said when it is true of every camp in the panel.

The promise was checked before it was written. Measured 2026-09-09 through the
real flow: a parent who then sends „ნიკა 599123456" gets „ინფორმაცია გადავეცი
მენეჯერს", and a manager dispatch really is attempted — that reply is only
produced on a confirmed send. What the same measurement also showed is recorded
at the bottom of this file.
"""
import dataclasses

import pytest

from app import config as config_module
from app.flows import parent_flow as pf

_SCHOOL_NAME = "საკვირაო სკოლა"


@pytest.fixture
def audience(monkeypatch):
    def _install(names, template=None):
        monkeypatch.setattr(
            "app.services.admin_config_service.get_active_child_program_names",
            lambda: list(names))
        monkeypatch.setattr(
            "app.services.admin_config_service.render_template",
            lambda tid, ctx: (template or ""))
        monkeypatch.setattr(pf, "settings", dataclasses.replace(
            config_module.settings, USE_PROGRAM_AUDIENCE=True))
    return _install


def test_the_parent_is_asked_for_a_name_and_a_number(audience):
    audience([_SCHOOL_NAME])
    out = pf._camp_off_alt()
    assert "სახელი" in out and "ნომერი" in out
    assert "მენეჯერი დაგიკავშირდებათ" in out


def test_the_old_offer_to_connect_is_gone(audience):
    """It is what the change replaces: an offer the parent had to accept."""
    audience([_SCHOOL_NAME])
    assert "თუ გსურთ, დეტალებზე მენეჯერთან დაგაკავშირებთ" not in pf._camp_off_alt()


def test_what_else_is_running_is_still_named(audience):
    """Asking for the contact does not cost the parent the alternatives, and
    the names still come from the panel."""
    audience([_SCHOOL_NAME, "პარიზის ბანაკი"])
    out = pf._camp_off_alt()
    assert _SCHOOL_NAME in out and "პარიზის ბანაკი" in out
    assert "სახელი" in out


def test_with_nothing_else_running_only_the_ask_remains(audience):
    audience([])
    out = pf._camp_off_alt()
    assert "სახელი" in out and "ნომერი" in out
    assert "აქტიურია" not in out


def test_the_operator_owns_the_wording(audience):
    audience([_SCHOOL_NAME], template="დაგვიტოვეთ ნომერი, დაგირეკავთ.")
    assert "დაგვიტოვეთ ნომერი, დაგირეკავთ." in pf._camp_off_alt()


def test_it_reaches_every_camp_off_status(audience):
    """ended / hidden / full / coming_soon all close the same way."""
    audience([_SCHOOL_NAME])
    for status in ("ended", "hidden", "full", "coming_soon"):
        assert "სახელი" in pf._camp_status_message(status), status
    assert "სახელი" in pf._camp_ended_direct()


def test_the_flag_off_path_is_untouched(monkeypatch):
    """`USE_PROGRAM_AUDIENCE` off still returns the approved static offer."""
    monkeypatch.setattr(pf, "settings", dataclasses.replace(
        config_module.settings, USE_PROGRAM_AUDIENCE=False))
    assert pf._camp_off_alt() == pf._CAMP_OFF_ALT


# ── measured, and NOT fixed here ───────────────────────────────────────────
#
# The contact a parent leaves after this message is dispatched — but through
# `notify_sunday_school_handoff`, and written to the Sheets tab as a Sunday
# School lead, because that flow owns contact collection once Sunday School is
# the active programme. The manager is reached, so nothing this message promises
# is untrue; the programme on the record is wrong. Asking for the contact will
# make more parents leave one, so it is worth correcting — deliberately left for
# its own change rather than folded in here.
