"""Synthetic USER — turns a persona + the conversation-so-far into the persona's
NEXT Georgian message via a CHEAP LLM.

This is the "customer" half of the simulation; the REAL engine is the "agent"
half (`conversation_service.process_message`). The persona LLM is one of the two
models UNDER TEST (allowed with a live key) — it performs NO side effects beyond
the OpenAI call and NEVER touches Calendar / Sheets / Meta / Redis.

Cost control: uses a cheap model, configurable via ``EVAL_PERSONA_MODEL`` (mini
tier by default). It reuses the app's own token-param builder so the request
shape is correct for whatever model is configured.

Determinism / testability: the driver calls :func:`next_user_message`, but the
whole seam is injectable — `evals.simulation` accepts a ``user_responder``
callable so the harness self-tests can feed a fully scripted conversation with
NO live LLM.
"""
from __future__ import annotations

import os
import re
from typing import Any

from evals import personas as personas_mod

# Sentinel the persona model emits (and we detect) to end a conversation.
END_TOKEN = "[[END]]"

# Cheap by default; override via env. Kept model-agnostic — the app's
# `_build_completion_kwargs` picks the right token-cap param for the family.
_DEFAULT_MODEL = "gpt-4.1-mini"


def persona_model() -> str:
    return (os.environ.get("EVAL_PERSONA_MODEL") or _DEFAULT_MODEL).strip()


def _system_prompt(persona: personas_mod.Persona, facts: dict[str, Any]) -> str:
    fb = personas_mod.facts_block(facts)
    audience = "ზრდასრული მომხმარებელი" if persona.expect_adult_route else "მშობელი"
    if persona.in_domain:
        leash = (
            "დარჩი მკაცრად ამ თემებში: "
            f"{persona.topics_text()}.\n"
            "არასდროს იკითხო თემის-მიღმა რამ (მათემატიკა, ამინდი, პოლიტიკა, "
            "ზოგადი ცოდნა, კოდი და ა.შ.). ეს რეალური სასაუბროა ბანაკის/"
            "ღონისძიების გვერდზე."
        )
    else:
        probes = "; ".join(
            (p.get("question") or "").strip()
            for p in persona.off_topic_probes if p.get("question")
        )
        leash = (
            "შენ განზრახ ცდი აგენტს თემიდან გადაუხვიოს. სცადე ეს თემის-მიღმა "
            f"რამ: {probes}. თუ აგენტი უარს ამბობს ან გადაგამისამართებს — ეს "
            "სწორია; შემდეგ შეგიძლია ბანაკზეც იკითხო."
        )
    return (
        f"შენ თამაშობ რეალურ ქართველ მომხმარებელს ({audience}), რომელიც წერს "
        "სიტყვის აკადემიის გაყიდვების აგენტს Instagram/Messenger-ში.\n\n"
        f"შენი პერსონა: {persona.label} — {persona.goal}\n"
        f"სტილი: {persona.style}\n\n"
        "რეალური ფაქტები (ბანაკი/ღონისძიება ნამდვილია — ამ ფაქტებზე დააფუძნე "
        f"რეალისტური კითხვები):\n{fb}\n\n"
        f"{leash}\n\n"
        "წესები:\n"
        "- დაწერე მხოლოდ შენი შემდეგი შეტყობინება, ქართულად, პირველ პირში, "
        "პერსონაში. არანაირი თხრობა, ბრჭყალები ან როლის იარლიყი.\n"
        "- ერთ ჯერზე ერთი რამ იკითხე (თუ პერსონა სხვას არ კარნახობს).\n"
        "- შეტყობინება მოკლე და ცოცხალი (1–2 წინადადება).\n"
        "- როცა შენს მიზანს მიაღწევ, ან ცხადად უარს გეტყვიან, ან საუბარი "
        f"ბუნებრივად დასრულდება — დაწერე ზუსტად: {END_TOKEN}\n"
    )


def _render_transcript(transcript: list[dict[str, str]]) -> str:
    if not transcript:
        return "(ჯერ არაფერი უთქვამთ — შენ იწყებ საუბარს.)"
    lines = []
    for turn in transcript:
        who = "მე (მომხმარებელი)" if turn["role"] == "user" else "აგენტი"
        lines.append(f"{who}: {turn['content']}")
    return "\n".join(lines)


def _clean(text: str) -> str:
    """Strip role labels / quotes / narration the model may have leaked."""
    text = (text or "").strip()
    text = re.sub(r'^\s*(მე|user|customer|მომხმარებელი)\s*[:：]\s*', "", text,
                  flags=re.IGNORECASE)
    text = text.strip().strip('"').strip("“”").strip()
    return text


def next_user_message(
    persona: personas_mod.Persona,
    transcript: list[dict[str, str]],
    facts: dict[str, Any],
    *,
    turn_index: int = 0,
) -> str | None:
    """Produce the persona's next user line, or None to stop the conversation.

    Turn 0 uses the persona's fixed in-character opener (grounded + cheap); later
    turns are LLM-driven so the conversation genuinely diverges. Returns None
    when the model signals the end (END_TOKEN) or yields nothing usable.
    """
    if turn_index == 0 and persona.opening:
        return persona.opening

    from app.services import openai_service

    messages = [
        {"role": "system", "content": _system_prompt(persona, facts)},
        {"role": "user", "content": (
            "საუბარი აქამდე:\n" + _render_transcript(transcript) +
            "\n\nშენი შემდეგი შეტყობინება:"
        )},
    ]
    kwargs = openai_service._build_completion_kwargs(
        model=persona_model(), messages=messages, max_tokens=160, temperature=0.9,
    )
    resp = openai_service._client().chat.completions.create(**kwargs)
    raw = (resp.choices[0].message.content or "").strip()
    if END_TOKEN in raw:
        # The model may append END after a final message; if there's a real
        # message before it, deliver that, else stop.
        before = raw.split(END_TOKEN)[0].strip()
        cleaned = _clean(before)
        return cleaned or None
    cleaned = _clean(raw)
    return cleaned or None
