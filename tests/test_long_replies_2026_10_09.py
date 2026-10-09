"""A long answer reaches the parent whole (2026-10-09).

Live 2026-10-09 16:13 a Sunday-School parent asked „შეგიძლიათ პირობები
მომწეროთ?"; the reply gave the programme's full description and stopped at
„…გაკვეთილის თ" (reply_len=1344) — the model's 900-token cap. Raising the cap
alone would let a reply pass Messenger's 2000-character limit, where Meta
rejects the whole message, so a longer reply now goes out in parts, cut at a
paragraph.
"""
from __future__ import annotations

import dataclasses

import app.config as config_module
from app.agent.llm import parent_llm_engine
from app.services import messenger_service as ms

_PARAGRAPH = ("საკვირაო სკოლა არის სამთვიანი საგანმანათლებლო პროგრამა, რომელიც "
              "აერთიანებს ლიტერატურისა და ფსიქოლოგიის ინტერაქციულ შეხვედრებს.")


def _text(paragraphs: int) -> str:
    return "\n\n".join(f"{i}. {_PARAGRAPH}" for i in range(paragraphs))


def test_a_reply_inside_the_limit_is_one_message():
    text = _text(8)
    assert len(text) < 1900
    assert ms.split_for_channel(text, 1900) == [text]


def test_a_long_reply_is_cut_at_paragraphs_and_loses_nothing():
    text = _text(40)
    parts = ms.split_for_channel(text, 1900)
    assert len(parts) >= 3
    assert all(len(p) <= 1900 for p in parts)
    assert "\n\n".join(parts) == text


def test_no_word_is_cut_when_there_are_no_paragraphs():
    text = " ".join([_PARAGRAPH] * 40)
    parts = ms.split_for_channel(text, 1900)
    assert all(len(p) <= 1900 for p in parts)
    assert " ".join(parts).split() == text.split()


def _channel(monkeypatch, delivered_before_failing: int | None = None):
    sent: list[str] = []
    delivered = [0]

    class _Response:
        def __init__(self, ok: bool):
            self.is_success = ok
            self.status_code = 200 if ok else 400
            self.text = ""

    def _post(url, headers=None, json=None, timeout=None):
        sent.append(json["message"]["text"])
        ok = delivered_before_failing is None or delivered[0] < delivered_before_failing
        delivered[0] += ok
        return _Response(ok)

    monkeypatch.setattr(ms, "settings", dataclasses.replace(
        config_module.settings, MESSENGER_PAGE_ACCESS_TOKEN="test-page-token"))
    monkeypatch.setattr(ms.httpx, "post", _post)
    monkeypatch.setattr(ms, "sleep", lambda *_: None)
    return sent


def test_a_long_reply_is_sent_in_parts_in_order(monkeypatch):
    sent = _channel(monkeypatch)
    text = _text(40)
    assert ms.send_message("psid-1", "messenger", text) is True
    assert len(sent) >= 3
    assert all(len(p) <= 1900 for p in sent)
    assert "\n\n".join(sent) == text


def test_a_short_reply_is_still_one_message(monkeypatch):
    sent = _channel(monkeypatch)
    assert ms.send_message("psid-1", "messenger", _PARAGRAPH) is True
    assert sent == [_PARAGRAPH]


def test_a_failed_part_stops_the_rest_and_reports_failure(monkeypatch):
    sent = _channel(monkeypatch, delivered_before_failing=1)
    assert ms.send_message("psid-1", "messenger", _text(40)) is False
    # the first part went out; the second failed on all three attempts
    assert len(sent) == 1 + 3


def test_the_reply_cap_covers_more_than_one_message_of_georgian():
    # 900 tokens came out as 1344 Georgian characters in the live reply.
    assert parent_llm_engine.DEFAULT_MAX_TOKENS * 1344 / 900 > 2 * 1900
