import logging
from time import sleep
from typing import Any

from openai import OpenAI

from app.config import Settings, settings
from app.services import anthropic_service
from data.prompts import (
    DETECT_SEGMENT,
    OPENAI_CONTEXT_LABEL,
    PARENT_PRESENT_VALUE_CONTEXT,
    PARENT_PRESENT_VALUE_FALLBACK,
    START_INTENT_DETECT,
    SUMMARY_PROMPT,
    SYSTEM_PROMPT_ADULT,
    SYSTEM_PROMPT_BASE,
    SYSTEM_PROMPT_PARENT,
)

logger = logging.getLogger(__name__)


# =========================================================================
# OpenAI Model Compatibility Patch (2026-06-02)
# =========================================================================
#
# GPT-5.x / GPT-5.4-mini / o1 / o3 / o4-mini and successor families reject
# the legacy ``max_tokens`` request parameter — they require
# ``max_completion_tokens`` instead. Older models (gpt-4.1-mini, gpt-4o,
# etc.) still use ``max_tokens``. Sending both is also a 400. We branch on
# the configured model family at request time so the operator can flip
# OPENAI_MODEL in .env without touching code.
#
# Live error this patch resolves:
#   openai.BadRequestError: Unsupported parameter: 'max_tokens' is not
#   supported with this model. Use 'max_completion_tokens' instead.

# Model-family prefixes / fragments that DO require max_completion_tokens.
# Keep the matcher conservative — match on prefix or specific substring,
# not free-form contains, so a future gpt-X.5 (unrelated) doesn't get
# misrouted.
_MAX_COMPLETION_TOKENS_PREFIXES: tuple[str, ...] = (
    "gpt-5",
    "o1",
    "o3",
    "o4",
)
_MAX_COMPLETION_TOKENS_FRAGMENTS: tuple[str, ...] = (
    "5.4",  # gpt-5.4-mini and successors using the same naming
)


def _uses_max_completion_tokens(model: str | None) -> bool:
    """Return True for model families that require
    ``max_completion_tokens`` instead of the legacy ``max_tokens``.

    Empty / None / unknown models return False so the legacy path is the
    safe default for the currently-running production model
    (gpt-4.1-mini).
    """
    name = (model or "").strip().lower()
    if not name:
        return False
    for prefix in _MAX_COMPLETION_TOKENS_PREFIXES:
        if name.startswith(prefix):
            return True
    for fragment in _MAX_COMPLETION_TOKENS_FRAGMENTS:
        if fragment in name:
            return True
    return False


def _token_param_name(model: str | None) -> str:
    """Return the actual kwarg name for the output-token cap for this
    model. Exposed for the optional boot-log line."""
    return (
        "max_completion_tokens"
        if _uses_max_completion_tokens(model)
        else "max_tokens"
    )


def _build_completion_kwargs(
    *,
    model: str,
    messages: list[dict[str, Any]],
    max_tokens: int,
    temperature: float | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | None = None,
) -> dict[str, Any]:
    """Assemble the ``client.chat.completions.create`` kwargs dict with
    the correct token-cap parameter name for the active model.

    NEVER sends both ``max_tokens`` AND ``max_completion_tokens`` — the
    API rejects that as a 400 too. The model-family check picks one.
    """
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
    }
    kwargs[_token_param_name(model)] = max_tokens
    if temperature is not None:
        kwargs["temperature"] = temperature
    if tools is not None:
        kwargs["tools"] = tools
    if tool_choice is not None:
        kwargs["tool_choice"] = tool_choice
    return kwargs


# Boot-log line — one-time, non-secret. Lets the operator confirm at a
# glance which token-param shape is being sent for the configured model
# without grepping code. Never logs the API key or any prompt content.
logger.info(
    "[openai] model=%s token_param=%s llm_provider=%s openai_key=%s "
    "anthropic_fallback=%s",
    settings.OPENAI_MODEL or "<unset>",
    _token_param_name(settings.OPENAI_MODEL),
    settings.LLM_PROVIDER,
    # Presence only — never the key itself, never its length.
    "set" if settings.OPENAI_API_KEY else "unset",
    settings.ANTHROPIC_FALLBACK_TO_OPENAI,
)


# =========================================================================
# LLM provider switch — Claude setup-token support (2026-07-29)
# =========================================================================
#
# Every LLM call in this codebase funnels through exactly two functions:
# ``_chat_completion`` (plain text) and ``chat_with_tools`` (tool loop).
# Routing the provider decision here means the parent/adult engines, the
# reply composer, the turn analyzer and every test mock keep working
# untouched — they still import ``openai_service`` and still see an
# OpenAI-shaped response.
#
# ``LLM_PROVIDER=openai`` (the default) short-circuits all of this: the
# Anthropic branch is never entered and behaviour is bit-identical to
# before this patch.

# Guard so a misconfigured deploy logs the reason once at first use
# instead of on every turn.
_anthropic_misconfig_logged = False


def _use_anthropic() -> bool:
    """True when this call should go to Claude rather than OpenAI.

    A provider of "anthropic" with no usable credential is a
    configuration mistake, not a reason to fail live traffic: it logs
    once and falls through to OpenAI.
    """
    global _anthropic_misconfig_logged

    if (settings.LLM_PROVIDER or "openai").strip().lower() != "anthropic":
        return False
    if not anthropic_service.is_configured():
        if not _anthropic_misconfig_logged:
            _anthropic_misconfig_logged = True
            logger.error(
                "[llm] LLM_PROVIDER=anthropic but ANTHROPIC_AUTH_TOKEN is "
                "empty — using OpenAI. Set the token from `claude setup-token`.",
            )
        return False
    return True


def _anthropic_failed(where: str, exc: Exception) -> None:
    """Handle an Anthropic failure: re-raise, or log and let OpenAI take it.

    The exception text is Anthropic's own ``error.message`` (see
    ``anthropic_service._extract_error``) — it never contains the
    credential.
    """
    if not settings.ANTHROPIC_FALLBACK_TO_OPENAI:
        raise RuntimeError(f"Anthropic {where} failed: {exc}") from exc
    logger.warning(
        "[llm] Anthropic %s failed (%s) — falling back to OpenAI", where, exc,
    )


def _build_system_prompt(segment: str, company_name: str) -> str:
    safe_name = company_name or "სიტყვის აკადემია"
    base = SYSTEM_PROMPT_BASE.format(company_name=safe_name)
    if segment == "PARENT":
        return f"{base}\n\n{SYSTEM_PROMPT_PARENT}"
    if segment == "ADULT":
        return f"{base}\n\n{SYSTEM_PROMPT_ADULT}"
    return base


def _client() -> OpenAI:
    return OpenAI(api_key=settings.OPENAI_API_KEY)


def _chat_completion(
    *,
    messages: list[dict[str, str]],
    max_tokens: int,
    temperature: float,
) -> str:
    """Single text-completion entry point for the whole codebase.

    Dispatches to Claude when ``LLM_PROVIDER=anthropic``; otherwise (and
    whenever the Anthropic attempt fails with fallback enabled) runs the
    original OpenAI path unchanged.
    """
    if _use_anthropic():
        try:
            return _anthropic_chat_completion(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception as exc:
            _anthropic_failed("completion", exc)

    return _openai_chat_completion(
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
    )


def _anthropic_chat_completion(
    *,
    messages: list[dict[str, str]],
    max_tokens: int,
    temperature: float,
) -> str:
    """Claude text completion with the same 3-attempt policy as OpenAI."""
    last_error: Exception | None = None

    for attempt in range(3):
        try:
            return anthropic_service.chat_completion(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                sleep(1)

    raise RuntimeError(
        f"Anthropic request failed after 3 attempts: {last_error}",
    ) from last_error


def _openai_chat_completion(
    *,
    messages: list[dict[str, str]],
    max_tokens: int,
    temperature: float,
) -> str:
    last_error: Exception | None = None

    for attempt in range(3):
        try:
            kwargs = _build_completion_kwargs(
                model=settings.OPENAI_MODEL,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            response = _client().chat.completions.create(**kwargs)
            content = response.choices[0].message.content
            return content.strip() if content else ""
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                sleep(1)

    raise RuntimeError(f"OpenAI request failed after 3 attempts: {last_error}") from last_error


def detect_segment(message_text: str) -> str:
    result = _chat_completion(
        messages=[
            {"role": "system", "content": DETECT_SEGMENT},
            {"role": "user", "content": message_text},
        ],
        max_tokens=10,
        temperature=0,
    ).upper()

    if "PARENT" in result:
        return "PARENT"
    if "ADULT" in result:
        return "ADULT"
    return "UNCLEAR"


def detect_start_intent(message_text: str) -> str:
    """Detect the user's intent on their first message in PARENT START state.

    Returns one of: GREETING, PRICE, BOOK, INFO, CONCERN.
    Defaults to GREETING on failure or ambiguous output.
    """
    try:
        result = _chat_completion(
            messages=[
                {"role": "system", "content": START_INTENT_DETECT},
                {"role": "user", "content": message_text},
            ],
            max_tokens=10,
            temperature=0,
        ).upper()
    except Exception:
        return "GREETING"

    for intent in ("CONCERN", "PRICE", "BOOK", "INFO", "GREETING"):
        if intent in result:
            return intent
    return "GREETING"


def generate_parent_value_response(
    *,
    child_age: str,
    challenge: str,
    deeper_concern: str,
    desired_change: str,
    company_name: str,
) -> str:
    """Generate the PRESENT_VALUE response — insight-driven, based on 4-layer discovery."""
    system_prompt = _build_system_prompt("PARENT", company_name)
    context = PARENT_PRESENT_VALUE_CONTEXT.format(
        child_age=child_age or "უცნობია",
        challenge=challenge or "უცნობია",
        deeper_concern=deeper_concern or "უცნობია",
        desired_change=desired_change or "უცნობია",
    )

    full_prompt = "\n\n".join(
        [
            system_prompt,
            f"{OPENAI_CONTEXT_LABEL}\n{context}",
        ],
    )

    try:
        return _chat_completion(
            messages=[
                {"role": "system", "content": full_prompt},
                {"role": "user", "content": "გთხოვ, დაწერე insight-driven პასუხი ზემოთ აღწერილი წესების მიხედვით."},
            ],
            max_tokens=400,
            temperature=0.6,
        )
    except Exception:
        return PARENT_PRESENT_VALUE_FALLBACK


def generate_response(
    history: list,
    user_message: str,
    segment: str,
    context: str,
) -> str:
    company_name = settings.COMPANY_NAME or "სიტყვის აკადემია"
    system_prompt = "\n\n".join(
        [
            _build_system_prompt(segment, company_name),
            f"{OPENAI_CONTEXT_LABEL}\n{context}",
        ],
    )
    max_tokens = 200 if segment == "PARENT" else 500

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(_normalize_history(history))
    messages.append({"role": "user", "content": user_message})

    return _chat_completion(
        messages=messages,
        max_tokens=max_tokens,
        temperature=0.7,
    )


_SUMMARY_SYSTEM_MESSAGE = (
    "თქვენ ხართ CRM-რეზიუმის წერის ასისტენტი. "
    "უპასუხეთ მხოლოდ ქართულად. "
    "Respond only in Georgian (ქართული). Never use English words or phrases. "
    "დაწერეთ მოკლე, სარგებლო რეზიუმე გაყიდვების მენეჯერისთვის — 2-3 წინადადება. "
    "სახელები და ტელეფონის ნომრები არ ითარგმნება, დატოვეთ ისე, როგორც არის."
)

# P3-C PATCH 2 — best-effort English-detection. If the LLM ignores the
# Georgian-only instruction (which the live test surfaced), the manager
# still reads English in the CRM and notification. Catch the most
# common English manager-summary patterns and substitute a Georgian
# fallback so the CRM stays consistent.
_ENGLISH_SUMMARY_MARKERS: tuple[str, ...] = (
    "parent interested",
    "outside age range",
    "requested manager callback",
    "wants consultation",
    "child age",
    "manager callback",
    "not eligible",
    "consultation booked",
    "the user",
    "the parent",
)

_GEORGIAN_SUMMARY_FALLBACK = (
    "მომხმარებელი დაინტერესებულია ბანაკით. საუბრის დეტალები საჭიროებს "
    "მენეჯერის გადამოწმებას. გთხოვთ, დაუკავშირდეთ მითითებულ ნომერზე."
)


def _looks_like_english_summary(text: str) -> bool:
    """Best-effort English-detection for CRM summaries.

    Two signals, either is sufficient:
      1. Any of the well-known English manager-summary marker phrases
         appears (case-insensitively) in the text.
      2. The text contains a substantial run of ASCII-letter words with
         essentially no Georgian script — i.e. the model ignored the
         Georgian-only instruction and answered in English wholesale.

    Never raises. On any internal exception (defensive), returns False
    so the original LLM output is used unchanged — we'd rather ship a
    possibly-English summary than break CRM writes by raising.
    """
    if not text:
        return False
    try:
        lowered = text.lower()
        if any(marker in lowered for marker in _ENGLISH_SUMMARY_MARKERS):
            return True
        # Character-class signal: count Georgian (U+10A0–U+10FF) vs
        # ASCII letters. A summary that's mostly ASCII letters with no
        # Georgian script is almost certainly English.
        georgian_chars = sum(1 for ch in text if 0x10A0 <= ord(ch) <= 0x10FF)
        ascii_letters = sum(1 for ch in text if "a" <= ch.lower() <= "z")
        if ascii_letters >= 25 and georgian_chars == 0:
            return True
    except Exception:
        return False
    return False


def _georgian_summary_fallback() -> str:
    """Constant Georgian CRM fallback. Exposed for callers that need it
    directly (e.g. tool executor's manager-handoff path)."""
    return _GEORGIAN_SUMMARY_FALLBACK


def generate_summary(history: list) -> str:
    """Return a Georgian CRM-style summary of the conversation history.

    P3-C PATCH 2: The model is given an explicit Georgian-only system
    message. If it still emits English (live tests showed this happens),
    the output is replaced with a static Georgian fallback BEFORE being
    returned. The replacement is wrapped so a defect in the detector
    never blocks CRM writes — falling back to the original LLM text on
    any internal failure is safer than crashing the booking pipeline.
    """
    conversation_history = _history_to_text(history)
    prompt = SUMMARY_PROMPT.format(conversation_history=conversation_history)

    raw = _chat_completion(
        messages=[
            {"role": "system", "content": _SUMMARY_SYSTEM_MESSAGE},
            {"role": "user", "content": prompt},
        ],
        max_tokens=200,
        temperature=0.3,
    )

    try:
        if _looks_like_english_summary(raw):
            return _GEORGIAN_SUMMARY_FALLBACK
    except Exception:
        # Detector must never block Sheets / notification writes.
        return raw

    return raw


def compose_reply(
    *,
    system_prompt: str,
    user_payload: str,
    max_tokens: int = 500,
    temperature: float = 0.7,
) -> str:
    """Phase 3.8 — thin chat-completion entry for the LLM reply composer.

    Separated from generate_response so test_agent.py can mock the composer
    surface independently of the adult flow's per-turn LLM use, and so the
    composer (in app/agent/llm/parent_reply_composer.py) does not need a
    direct OpenAI client dependency.

    The caller is responsible for assembling both the system prompt and the
    full user payload (state, lead fields, knowledge facts, next action,
    must/must-not rules, tone anchor). This function only sends the call
    and returns the text.
    """
    return _chat_completion(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_payload},
        ],
        max_tokens=max_tokens,
        temperature=temperature,
    )


def chat_with_tools(
    *,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    tool_choice: str = "auto",
    max_tokens: int = 500,
    temperature: float = 0.7,
) -> Any:
    """P3-C SAFE — thin pass-through to OpenAI ``chat.completions.create``
    with the tool-calling parameters.

    Returns the raw response object (the engine reads ``choices[0].message``
    directly so it can branch on ``tool_calls``). Project style elsewhere
    is sync — we match that here so ``parent_flow.handle`` stays sync.

    No retry loop: the engine's own loop catches the exception and falls
    back to the legacy flow. Adding three internal retries here would
    only delay the fallback.

    Provider switch (2026-07-29): under ``LLM_PROVIDER=anthropic`` this
    returns an OpenAI-SHAPED DICT built by ``anthropic_service`` rather
    than an SDK object. The engines read responses through duck-typed
    accessors (``_first_choice`` / ``_choice_message`` / ``_tool_calls``
    / ``_message_content``) that already handle dicts, so neither engine
    needs a change.
    """
    if _use_anthropic():
        try:
            return anthropic_service.chat_with_tools(
                messages=messages,
                tools=tools,
                tool_choice=tool_choice,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception as exc:
            _anthropic_failed("tool call", exc)

    kwargs = _build_completion_kwargs(
        model=settings.OPENAI_MODEL,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        tools=tools,
        tool_choice=tool_choice,
    )
    return _client().chat.completions.create(**kwargs)


def analyze_parent_turn(
    *,
    system_prompt: str,
    user_payload: str,
    max_tokens: int = 400,
    temperature: float = 0.0,
) -> str:
    """Phase 3.9 — thin chat-completion entry for the LLM Parent Turn Analyzer.

    Separated from compose_reply so test_agent.py and tests/ can mock the
    analyzer surface independently of the composer, and so the analyzer
    module (app/agent/llm/parent_turn_analyzer.py) does not need a direct
    OpenAI client dependency.

    The caller is responsible for assembling both the system prompt and the
    full user payload (current_state, user message, lead fields, knowledge
    summary). Temperature defaults to 0 because the analyzer must return
    strict JSON — randomness is harmful. This function only sends the call
    and returns the raw text; JSON parsing/validation happens in the
    analyzer module.
    """
    return _chat_completion(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_payload},
        ],
        max_tokens=max_tokens,
        temperature=temperature,
    )


def _normalize_history(history: list) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for item in history:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role in {"system", "user", "assistant"} and content:
            normalized.append({"role": role, "content": str(content)})
    return normalized


def _history_to_text(history: list) -> str:
    lines: list[str] = []
    for item in history:
        if isinstance(item, dict):
            role = item.get("role", "")
            content = item.get("content", "")
            if content:
                lines.append(f"{role}: {content}")
    return "\n".join(lines)


class OpenAIService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def generate_reply(
        self,
        *,
        system_prompt: str,
        user_message: str,
        context: dict[str, Any],
    ) -> str | None:
        segment = detect_segment(user_message)
        context_text = f"{system_prompt}\n{context}"
        return generate_response([], user_message, segment, context_text)


# OLD_SYSTEM_PROMPT (Day 4 Task #3 backup — rollback path if new prompt regresses)
# Previously, PARENT segment used AGENT_BASE + AGENT_PARENT chained together
# with role/tone/rules. New code uses single SYSTEM_PROMPT_PARENT from prompts.py.
# To rollback: revert generate_response() PARENT branch to:
#
#     role_prompt = AGENT_PARENT.format(
#         tone_parents=settings.COMPANY_TONE_PARENTS,
#         camp_price=settings.CAMP_PRICE,
#     )
#     system_prompt = "\n".join([
#         AGENT_BASE.format(company_name=settings.COMPANY_NAME),
#         role_prompt,
#         "{}\n{}".format(OPENAI_CONTEXT_LABEL, context),
#     ])
#     max_tokens = 500
