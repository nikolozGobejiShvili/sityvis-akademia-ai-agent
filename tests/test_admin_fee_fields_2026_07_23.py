"""Admin monthly / one-time fee fields (2026-07-23).

Operator need: a program (Sunday School) with a MONTHLY fee — the admin form only
had a single `price_text`. New free-text fields `price_monthly` / `price_onetime`
flow admin form → section dict → get_program_info facts → LLM engine, so a dynamic
program with recurring/one-off pricing is answered correctly. Additive: empty
fields are skipped by get_program_info, so programs without them are byte-identical.
"""
from app.agent.tools.parent_tool_executor import ParentToolExecutor
from app.routes.admin import _form_to_section_dict


def test_fee_fields_are_public_so_engine_sees_them():
    fields = ParentToolExecutor._PROGRAM_PUBLIC_FIELDS
    assert "price_monthly" in fields
    assert "price_onetime" in fields


def test_form_stores_fee_fields():
    s = _form_to_section_dict(
        id="sunday_school", name="საკვირაო სკოლა", type="kids_program",
        status="active", price_monthly="200 ₾/თვე", price_onetime="50 ₾ სარეგისტრაციო",
    )
    assert s["price_monthly"] == "200 ₾/თვე"
    assert s["price_onetime"] == "50 ₾ სარეგისტრაციო"


def test_fee_fields_default_empty():
    """A program saved without the fee fields stores them as empty strings — so
    get_program_info skips them (byte-identical for programs that don't use them)."""
    s = _form_to_section_dict(id="disneyland", name="დისნეილენდი", type="trip")
    assert s["price_monthly"] == ""
    assert s["price_onetime"] == ""


def test_fee_fields_stripped():
    s = _form_to_section_dict(id="x", name="X", price_monthly="  200 ₾  ")
    assert s["price_monthly"] == "200 ₾"
