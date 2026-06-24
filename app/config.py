import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

from app.agent.services.knowledge_loader import load_knowledge

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
ENV_PATH = BASE_DIR / ".env"

load_dotenv(dotenv_path=ENV_PATH)
ENV_VALUES = dotenv_values(ENV_PATH)

REQUIRED_VARIABLES = (
    "OPENAI_API_KEY",
    "GOOGLE_SHEET_ID",
    "GOOGLE_CALENDAR_ID",
    "META_PAGE_ID",
    "INSTAGRAM_ACCOUNT_ID",
    "MESSENGER_PAGE_ACCESS_TOKEN",
    "MESSENGER_VERIFY_TOKEN",
)


class ConfigurationError(RuntimeError):
    pass


def _env(name: str) -> str:
    """Resolve a configuration variable, Railway-safe.

    Resolution order (2026-06-18 Railway-readiness fix):
      1. ``os.environ`` — the process environment. Railway injects its
         dashboard variables here and there is NO ``.env`` file in the
         container, so this MUST win. (Previously this helper read ONLY
         ``ENV_VALUES = dotenv_values(.env)``, so on Railway every value
         came back empty and ``Settings.from_env()`` crashed the boot.)
      2. ``ENV_VALUES`` — the local ``.env`` file, parsed once at import.
         The dev fallback; unchanged for local runs.

    ``load_dotenv`` above also populates ``os.environ`` from ``.env``
    WITHOUT overriding existing process vars, so locally this returns the
    same value as before unless a real environment variable is explicitly
    set (which, by 12-factor convention, should win). Never logs values.
    """
    value = os.environ.get(name)
    if value is None or value == "":
        value = ENV_VALUES.get(name, "")
    return str(value or "").strip()


def _parse_int(name: str) -> int:
    value = _env(name)
    try:
        return int(value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer in .env.") from exc


def _parse_int_optional(name: str, default: int) -> int:
    value = _env(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer in .env.") from exc


def _parse_bool_optional(name: str, default: bool) -> bool:
    value = _env(name)
    if not value:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _parse_float_safe(name: str, default: float) -> float:
    """Parse an env float WITHOUT raising. Invalid input → default.

    Used by Sentry config so a malformed SENTRY_TRACES_SAMPLE_RATE
    cannot prevent app boot; Sentry stays at the safe default rate.
    """
    value = _env(name)
    if not value:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_csv(name: str) -> list[str]:
    value = _env(name)
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_hashtags(name: str) -> list[str]:
    """Parse a comma-separated hashtag list.

    Stripped, '#'-stripped, casefolded (safer than .lower() for Unicode;
    no-op for Mkhedruli, correct for Latin). The actual matching helper
    in `comment_service` re-applies the same normalisation on the
    extracted tags, so both sides are guaranteed to agree.
    """
    value = _env(name)
    if not value:
        return []
    # Strip Unicode whitespace too (handles odd characters like NBSP /
    # zero-width-space that occasionally sneak into .env values).
    return [
        item.strip().lstrip("#").strip().casefold()
        for item in value.split(",")
        if item.strip()
    ]


def _parse_sheet_tab() -> str:
    direct = _env("GOOGLE_SHEETS_LEADS_TAB")
    if direct:
        return direct
    raw = _env("GOOGLE_SHEET_RANGE")
    if "!" in raw:
        return raw.split("!", 1)[0].strip() or "Leads"
    return raw.strip() or "Leads"


def _parse_followup_hours() -> int:
    direct = _env("FOLLOWUP_HOURS")
    if direct:
        try:
            return int(direct)
        except ValueError:
            pass
    minutes_str = _env("FOLLOWUP_DELAY_MINUTES")
    if minutes_str:
        try:
            return max(1, int(minutes_str) // 60)
        except ValueError:
            pass
    return 48


def _resolve_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return BASE_DIR / path


def _load_text_file(path_value: str, variable_name: str) -> str:
    if not path_value:
        return ""

    path = _resolve_path(path_value)
    if not path.exists():
        raise ConfigurationError(f"{variable_name} points to a missing file: {path}")
    return path.read_text(encoding="utf-8")


KNOWLEDGE_BASE = _load_text_file(
    _env("KNOWLEDGE_BASE_PATH") or "./data/knowledge_base.txt",
    "KNOWLEDGE_BASE_PATH",
)
EVENTS = _load_text_file(
    _env("EVENTS_PATH") or "./data/events.txt",
    "EVENTS_PATH",
)


@dataclass(frozen=True)
class Settings:
    META_VERIFY_TOKEN: str = ""
    META_ACCESS_TOKEN: str = ""
    META_PAGE_ID: str = ""
    INSTAGRAM_ACCOUNT_ID: str = ""
    WHATSAPP_TOKEN: str = ""
    WHATSAPP_PHONE_NUMBER_ID: str = ""
    # Master live-send switch for the manager WhatsApp notification. When
    # False / missing, `notification_service._send_manager_whatsapp` NEVER calls
    # Meta — it logs a blocked line and returns a safe failure. A real WhatsApp
    # send requires an explicit opt-in. Default OFF for safety (tests / CI / dev
    # never reach the Cloud API even when credentials are present in `.env`).
    ALLOW_LIVE_WHATSAPP: bool = False
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4.1-mini"
    GOOGLE_SHEETS_CREDENTIALS_JSON: str = "./credentials.json"
    GOOGLE_SHEETS_SPREADSHEET_ID: str = ""
    GOOGLE_SHEETS_LEADS_TAB: str = "Leads"
    GOOGLE_CALENDAR_CREDENTIALS_JSON: str = "./credentials.json"
    GOOGLE_CALENDAR_ID: str = ""
    # Calendar Multi-Busy Check Patch (2026-06-04). The booking calendar
    # is where the agent CREATES consultation events. The busy-calendar
    # list is the set of calendars whose FreeBusy data the agent must
    # consult when deciding if a slot is free. Both fall back to
    # ``GOOGLE_CALENDAR_ID`` when unset so the single-calendar deploy
    # behaviour is preserved exactly. The busy list is stored as the raw
    # comma-separated string; ``settings.busy_calendar_ids()`` returns
    # the cleaned list (booking calendar first, deduplicated).
    BOOKING_CALENDAR_ID: str = ""
    BUSY_CALENDAR_IDS: str = ""
    MANAGER_EMAIL: str = ""
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = ""
    # Booking-notification email gate. Default True keeps the historic
    # behaviour (attempt the send when SMTP creds are configured); flip
    # to False to skip emails entirely without removing the SMTP block.
    # When True but SMTP creds / MANAGER_EMAIL are missing the sender
    # logs a clear warning and returns False — it does NOT raise, and
    # the booking remains successful.
    ENABLE_EMAIL_NOTIFICATIONS: bool = True
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_FROM_NUMBER: str = ""
    MANAGER_PHONE_NUMBER: str = ""
    MANAGER_WHATSAPP_NUMBER: str = ""
    COMPANY_NAME: str = "სიტყვის აკადემია"
    COMPANY_TONE_PARENTS: str = ""
    COMPANY_TONE_ADULTS: str = ""
    COMPANY_LANGUAGE: str = "ka"
    KNOWLEDGE_BASE_PATH: str = "./data/knowledge_base.txt"
    EVENTS_PATH: str = "./data/events.txt"
    # Authoritative price lives in app/agent/knowledge/camp_2026.yaml.
    # This dataclass default is only used if the env var CAMP_PRICE is
    # unset AND from_env() did not pass a value. from_env() always passes
    # the knowledge value (or env override), so this default is inert in
    # normal operation — kept for direct Settings() construction in tests.
    CAMP_PRICE: int = 2150
    FOLLOWUP_HOURS: int = 48
    FOLLOWUP_CONTENT_LINK: str = ""
    # Follow-up Test Mode Patch (2026-06-06). When `FOLLOWUP_ENABLED=false`
    # the scheduler short-circuits the whole tick — no message sent.
    # `FOLLOWUP_TEST_MODE=true` + a positive `FOLLOWUP_FIRST_DELAY_SECONDS`
    # overrides the FIRST cadence step (the 24h delay) so operators can
    # live-test the scheduler in two minutes instead of waiting a day.
    # Production cadence (24h → 72h → 168h) is otherwise unchanged.
    # Invalid `FOLLOWUP_FIRST_DELAY_SECONDS` → ignored (production
    # cadence remains in force, no crash).
    FOLLOWUP_ENABLED: bool = True
    FOLLOWUP_TEST_MODE: bool = False
    FOLLOWUP_FIRST_DELAY_SECONDS: int = 0
    PORT: int = 8006
    KNOWLEDGE_BASE: str = ""
    EVENTS: str = ""
    PARENT_HASHTAGS: list = field(default_factory=list)
    ADULT_HASHTAGS: list = field(default_factory=list)
    COMMENT_FALLBACK_LINK: str = ""
    COMMENT_FOLLOWUP_HOURS: int = 24
    MESSENGER_PAGE_ACCESS_TOKEN: str = ""
    MESSENGER_VERIFY_TOKEN: str = ""
    MESSENGER_APP_ID: str = ""
    MESSENGER_APP_SECRET: str = ""
    INTERNAL_API_TOKEN: str = ""
    META_APP_ID: str = ""
    META_APP_SECRET: str = ""
    # Instagram Webhook Signature Patch (2026-06-08).
    #
    # Meta serves Facebook Page webhooks and Instagram Business
    # webhooks under separate app secrets when the Instagram product
    # is added to a different Meta app (which is the live setup for
    # the connected `code.shelf` Instagram account). The signature
    # verifier accepts EITHER secret, so the same /webhook endpoint
    # can ingest both Facebook and Instagram callbacks without
    # disabling verification.
    INSTAGRAM_APP_SECRET: str = ""
    # Instagram outbound send uses a separate Page-scoped token. We
    # only ingest its presence here; the actual send wiring is the
    # next-task scope.
    INSTAGRAM_ACCESS_TOKEN: str = ""
    META_GRAPH_API_VERSION: str = "v19.0"
    META_GRAPH_API_BASE_URL: str = "https://graph.facebook.com"
    WHATSAPP_BUSINESS_ACCOUNT_ID: str = ""
    FOLLOWUP_COLD_LEAD_HOURS: int = 48
    DEBOUNCE_SECONDS: int = 5
    MAX_WAIT_SECONDS: int = 15
    # Phase 3.8 — LLM reply composer. When False (default), PARENT flow uses
    # fixed YAML templates verbatim and behavior is byte-identical to the
    # pre-3.8 baseline. When True, selected safe PARENT discovery states
    # (welcome / ask_challenge / ask_deeper / ask_desire) are rewritten by
    # the LLM via app/agent/llm/parent_reply_composer.py. The composer never
    # touches state, lead capture, slots, booking, or notifications.
    USE_LLM_COMPOSER: bool = False
    # Phase 3.9 — LLM Parent Turn Analyzer. When False (default), the PARENT
    # flow advances strictly via the existing state machine and behavior is
    # byte-identical to the pre-3.9 baseline. When True, each incoming PARENT
    # message is first classified by an LLM (via app/agent/llm/parent_turn_analyzer.py).
    # The analyzer is advisory: backend validates the JSON output, picks a
    # safe action from a whitelist, and runs the existing parsers/booking
    # logic. The analyzer cannot mutate conversation state, book slots, save
    # leads, send notifications, or accept a phone without the existing
    # phone parser. Independent of USE_LLM_COMPOSER — both can be on at once
    # (analyzer decides action, composer phrases the reply).
    USE_LLM_TURN_ANALYZER: bool = False
    # P3-C SAFE — PARENT LLM Engine with backend-validated tool calling.
    # When False (default), parent_flow.handle() routes every PARENT message
    # through the existing P0/P1/P2 state machine. When True, parent_flow
    # FIRST asks the new LLM engine (app/agent/llm/parent_llm_engine.py) to
    # reason over a closed-set tool registry (camp facts, slot lookup,
    # consultation booking, manager callback, lead-info save). The engine
    # is wrapped: any exception OR empty response falls back to the
    # existing _handle_impl() path. Backend remains the validator/executor —
    # the LLM decides what it WANTS to do; the tool executor decides whether
    # it is ALLOWED (age eligibility, phone format, slot availability,
    # business hours, future-only datetime). The final-stage fake-booking
    # guard in handle() runs on the engine's response too.
    USE_PARENT_LLM_ENGINE: bool = False
    # Reasoning Layer (Phase 1, 2026-06-23) — gated, DETERMINISTIC structured
    # intent analyzer for ambiguous PARENT turns. When False (default, and when
    # the env line is absent) the analyzer is NEVER consulted and behaviour is
    # byte-identical. When True, `app/reasoning/reasoning_layer.analyze_parent_turn`
    # classifies the turn (segment / topic / intent / question / affirmation /
    # decline / topic-switch + requested_action + confidence) — it produces
    # METADATA only, never user-facing text, and NEVER overrides a high-confidence
    # deterministic handler. Phase 1 uses it for one ambiguous case only
    # (decline + topic-switch). NO LLM call, no side effects. Pinned OFF in
    # tests/conftest.py exactly like USE_PARENT_LLM_ENGINE.
    USE_REASONING_LAYER: bool = False
    # Conversation Planner (Reasoning Layer Phase 3, 2026-06-24) — one unified,
    # DETERMINISTIC, metadata-only planning layer. Default OFF; Stage 1 wires it
    # in SHADOW (log-only) mode. Pinned OFF in tests/conftest.py.
    USE_CONVERSATION_PLANNER: bool = False
    # ADULT LLM Engine — mirrors P3-C SAFE for the adult cultural-events
    # flow. When False (default), adult_flow.handle() runs the legacy
    # deterministic state machine + PATCH 7 global intent guard exactly
    # as before. When True, conversation_service routes ADULT messages
    # through app/agent/llm/adult_llm_engine.run_adult_llm_turn, which
    # reasons over a closed-set tool registry (events list, event
    # details, save lead info, manager handoff, reservation link,
    # parent-flow switch). The engine is wrapped in a try/except: any
    # exception OR empty response falls back to the legacy adult_flow
    # state machine — no behaviour change for deployments running with
    # the flag off. Backend remains the validator/executor; the LLM
    # decides what it WANTS to do, the AdultToolExecutor decides whether
    # it is ALLOWED (min_age filter, phone format, configured event ids,
    # reservation_url presence).
    USE_ADULT_LLM_ENGINE: bool = True
    # P3-C / COMMENT FLOW PATCH 1 — public comment reply gate.
    # When False (default), the agent SKIPS the public Facebook /
    # Instagram comment reply (`reply_to_comment`) entirely and goes
    # straight to the DM. This avoids the case where Meta's "private
    # reply" API returns the SAME 200-style status as success but the
    # public comment never gets posted (silent fail) — and where the
    # public-reply failure used to block the more important DM. When
    # True the agent still tries the public reply, but its failure is
    # logged and NEVER blocks the DM either. Default off keeps
    # production behavior conservative until the public-reply path is
    # known to work end-to-end.
    # Comment Follow-up Logic Fix + Public Reply Ready (2026-05-31).
    # Default flipped True so the code is ready for Meta App Review:
    # once `pages_manage_engagement` is granted and the Page Access
    # Token refreshed, public replies auto-activate on the next
    # restart. Until then Meta rejects the call with HTTP 400 — the
    # comment handler catches it, logs safely, and the private DM
    # still goes out unchanged.
    ENABLE_PUBLIC_COMMENT_REPLY: bool = True
    # P3-B — Redis-backed persistence of Conversation / Lead /
    # pending_booking / manager-notified / processed-comment state.
    # Default behaviour stays in-memory: REDIS_URL empty OR
    # REDIS_ENABLED=false → no Redis connection attempted, no crash,
    # legacy module-level dicts remain the source of truth. When
    # REDIS_URL is set AND REDIS_ENABLED=true, the redis_state_service
    # connects on boot and mirrors state writes; reads fall back to the
    # in-memory dict on miss or Redis failure. TTL default 7 days so
    # stale leads age out automatically.
    REDIS_URL: str = ""
    REDIS_ENABLED: bool = True
    REDIS_TTL_SECONDS: int = 604800
    # Admin Panel MVP — operator UI for section / template editing.
    # Default off so a misconfigured deploy never exposes the panel.
    # When enabled, the routes under /admin require HTTP Basic Auth
    # with ADMIN_USERNAME / ADMIN_PASSWORD. The password is never
    # logged. Missing ADMIN_PASSWORD with ENABLED=true → the routes
    # return 503 with a safe error instead of silently allowing access.
    ADMIN_PANEL_ENABLED: bool = False
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = ""
    # Emergency Kill Switch.
    #   true  → agent processes messages normally (default).
    #   false → DM / comment / follow-up entry points return the safe
    #           offline message and skip every LLM / Calendar / Sheets /
    #           email / Meta-send call. Webhook verification, /health,
    #           and /admin are NOT gated by this flag — the operator
    #           still needs the platform to respond and the admin panel
    #           to flip state.
    AGENT_ENABLED: bool = True
    # Broadcast Safety Patch (2026-06-11). Master switch for OUTBOUND
    # adult-event broadcasts. When False (the DEFAULT), `broadcast_event`
    # runs in DRY-RUN mode: it resolves the event, loads subscribers, and
    # logs what it WOULD send, but never calls `messenger_service.send_*`
    # and never marks subscribers notified. This prevents tests / scripts
    # / accidental invocations on a dev machine (which may hold real Meta
    # + Sheets credentials) from DMing real subscribers. Production must
    # explicitly set `LIVE_BROADCAST_ENABLED=true` for real fan-out.
    LIVE_BROADCAST_ENABLED: bool = False
    # Webhook signature verification (Meta X-Hub-Signature-256).
    #   true  → enforce HMAC-SHA256 verification of POST /webhook
    #           bodies when META_APP_SECRET is also set.
    #   false → skip verification (legacy / local-dev behaviour).
    # Fail-open semantics: even when this is True, if META_APP_SECRET
    # is empty the handler skips verification + logs one WARNING line.
    # This protects existing dev/local/test deploys that haven't
    # propagated the secret yet.
    VERIFY_WEBHOOK_SIGNATURE: bool = True
    # Sentry / Error Monitoring (optional).
    #   SENTRY_DSN empty → Sentry disabled, app boots normally.
    #   sentry-sdk missing → no-op, app boots normally.
    # Sentry MUST NOT receive secrets — see app/services/sentry_service.py.
    SENTRY_DSN: str = ""
    SENTRY_ENVIRONMENT: str = "production"
    SENTRY_TRACES_SAMPLE_RATE: float = 0.0

    @classmethod
    def from_env(cls) -> "Settings":
        missing = [name for name in REQUIRED_VARIABLES if not _env(name)]
        if missing:
            joined = ", ".join(missing)
            raise ConfigurationError(f"Missing required variables in .env: {joined}")

        return cls(
            META_VERIFY_TOKEN=_env("META_VERIFY_TOKEN") or _env("MESSENGER_VERIFY_TOKEN"),
            META_ACCESS_TOKEN=_env("META_ACCESS_TOKEN") or _env("MESSENGER_PAGE_ACCESS_TOKEN"),
            META_PAGE_ID=_env("META_PAGE_ID"),
            INSTAGRAM_ACCOUNT_ID=_env("INSTAGRAM_ACCOUNT_ID"),
            WHATSAPP_TOKEN=_env("WHATSAPP_ACCESS_TOKEN") or _env("WHATSAPP_TOKEN"),
            WHATSAPP_PHONE_NUMBER_ID=_env("WHATSAPP_PHONE_NUMBER_ID"),
            ALLOW_LIVE_WHATSAPP=_parse_bool_optional("ALLOW_LIVE_WHATSAPP", False),
            OPENAI_API_KEY=_env("OPENAI_API_KEY"),
            OPENAI_MODEL=_env("OPENAI_MODEL") or "gpt-4.1-mini",
            GOOGLE_SHEETS_CREDENTIALS_JSON=_env("GOOGLE_SHEETS_CREDENTIALS_JSON") or "./credentials.json",
            GOOGLE_SHEETS_SPREADSHEET_ID=_env("GOOGLE_SHEET_ID") or _env("GOOGLE_SHEETS_SPREADSHEET_ID"),
            GOOGLE_SHEETS_LEADS_TAB=_parse_sheet_tab(),
            GOOGLE_CALENDAR_CREDENTIALS_JSON=_env("GOOGLE_CALENDAR_CREDENTIALS_JSON") or "./credentials.json",
            GOOGLE_CALENDAR_ID=_env("GOOGLE_CALENDAR_ID"),
            BOOKING_CALENDAR_ID=_env("BOOKING_CALENDAR_ID"),
            BUSY_CALENDAR_IDS=_env("BUSY_CALENDAR_IDS"),
            MANAGER_EMAIL=_env("MANAGER_EMAIL"),
            SMTP_HOST=_env("SMTP_HOST"),
            SMTP_PORT=_parse_int_optional("SMTP_PORT", 587),
            SMTP_USER=_env("SMTP_USER") or _env("SMTP_USERNAME"),
            SMTP_PASSWORD=_env("SMTP_PASSWORD"),
            SMTP_FROM_EMAIL=_env("SMTP_FROM_EMAIL"),
            ENABLE_EMAIL_NOTIFICATIONS=_parse_bool_optional(
                "ENABLE_EMAIL_NOTIFICATIONS", True,
            ),
            TWILIO_ACCOUNT_SID=_env("TWILIO_ACCOUNT_SID"),
            TWILIO_AUTH_TOKEN=_env("TWILIO_AUTH_TOKEN"),
            TWILIO_FROM_NUMBER=_env("TWILIO_FROM_NUMBER"),
            MANAGER_PHONE_NUMBER=_env("MANAGER_PHONE_NUMBER"),
            MANAGER_WHATSAPP_NUMBER=_env("MANAGER_WHATSAPP") or _env("MANAGER_WHATSAPP_NUMBER"),
            COMPANY_NAME=_env("COMPANY_NAME") or "სიტყვის აკადემია",
            COMPANY_TONE_PARENTS=_env("COMPANY_TONE_PARENTS") or _env("COMPANY_TONE"),
            COMPANY_TONE_ADULTS=_env("COMPANY_TONE_ADULTS") or _env("COMPANY_TONE"),
            COMPANY_LANGUAGE=_env("COMPANY_LANGUAGE") or "ka",
            KNOWLEDGE_BASE_PATH=_env("KNOWLEDGE_BASE_PATH") or "./data/knowledge_base.txt",
            EVENTS_PATH=_env("EVENTS_PATH") or "./data/events.txt",
            # Knowledge YAML is the single source of truth. Env var still
            # honored as a per-deployment override; remove .env CAMP_PRICE
            # for pure single-source behaviour.
            CAMP_PRICE=_parse_int_optional(
                "CAMP_PRICE",
                int(load_knowledge("camp_2026")["camp"]["price_gel"]),
            ),
            FOLLOWUP_HOURS=_parse_followup_hours(),
            FOLLOWUP_CONTENT_LINK=_env("FOLLOWUP_CONTENT_LINK"),
            # Follow-up Test Mode Patch (2026-06-06) — gates + override.
            LIVE_BROADCAST_ENABLED=_parse_bool_optional(
                "LIVE_BROADCAST_ENABLED", False,
            ),
            FOLLOWUP_ENABLED=_parse_bool_optional("FOLLOWUP_ENABLED", True),
            FOLLOWUP_TEST_MODE=_parse_bool_optional("FOLLOWUP_TEST_MODE", False),
            FOLLOWUP_FIRST_DELAY_SECONDS=_parse_int_optional(
                "FOLLOWUP_FIRST_DELAY_SECONDS", 0,
            ),
            PORT=_parse_int_optional("PORT", 8006),
            KNOWLEDGE_BASE=KNOWLEDGE_BASE,
            EVENTS=EVENTS,
            PARENT_HASHTAGS=_parse_hashtags("PARENT_HASHTAGS"),
            ADULT_HASHTAGS=_parse_hashtags("ADULT_HASHTAGS"),
            COMMENT_FALLBACK_LINK=_env("COMMENT_FALLBACK_LINK"),
            COMMENT_FOLLOWUP_HOURS=_parse_int_optional("COMMENT_FOLLOWUP_HOURS", 24),
            MESSENGER_PAGE_ACCESS_TOKEN=_env("MESSENGER_PAGE_ACCESS_TOKEN"),
            MESSENGER_VERIFY_TOKEN=_env("MESSENGER_VERIFY_TOKEN"),
            MESSENGER_APP_ID=_env("MESSENGER_APP_ID") or _env("META_APP_ID"),
            MESSENGER_APP_SECRET=_env("MESSENGER_APP_SECRET") or _env("META_APP_SECRET"),
            INTERNAL_API_TOKEN=_env("INTERNAL_API_TOKEN"),
            META_APP_ID=_env("META_APP_ID"),
            META_APP_SECRET=_env("META_APP_SECRET"),
            INSTAGRAM_APP_SECRET=_env("INSTAGRAM_APP_SECRET") or _env("IG_APP_SECRET"),
            INSTAGRAM_ACCESS_TOKEN=_env("INSTAGRAM_ACCESS_TOKEN") or _env("IG_ACCESS_TOKEN"),
            META_GRAPH_API_VERSION=_env("META_GRAPH_API_VERSION") or "v19.0",
            META_GRAPH_API_BASE_URL=_env("META_GRAPH_API_BASE_URL") or "https://graph.facebook.com",
            WHATSAPP_BUSINESS_ACCOUNT_ID=_env("WHATSAPP_BUSINESS_ACCOUNT_ID"),
            FOLLOWUP_COLD_LEAD_HOURS=_parse_int_optional("FOLLOWUP_COLD_LEAD_HOURS", 48),
            DEBOUNCE_SECONDS=_parse_int_optional("DEBOUNCE_SECONDS", 5),
            MAX_WAIT_SECONDS=_parse_int_optional("MAX_WAIT_SECONDS", 15),
            USE_LLM_COMPOSER=_parse_bool_optional("USE_LLM_COMPOSER", False),
            USE_LLM_TURN_ANALYZER=_parse_bool_optional("USE_LLM_TURN_ANALYZER", False),
            USE_PARENT_LLM_ENGINE=_parse_bool_optional("USE_PARENT_LLM_ENGINE", False),
            USE_REASONING_LAYER=_parse_bool_optional("USE_REASONING_LAYER", False),
            USE_CONVERSATION_PLANNER=_parse_bool_optional("USE_CONVERSATION_PLANNER", False),
            USE_ADULT_LLM_ENGINE=_parse_bool_optional("USE_ADULT_LLM_ENGINE", True),
            ENABLE_PUBLIC_COMMENT_REPLY=_parse_bool_optional(
                "ENABLE_PUBLIC_COMMENT_REPLY", False,
            ),
            REDIS_URL=_env("REDIS_URL"),
            REDIS_ENABLED=_parse_bool_optional("REDIS_ENABLED", True),
            REDIS_TTL_SECONDS=_parse_int_optional(
                "REDIS_TTL_SECONDS", 604800,
            ),
            ADMIN_PANEL_ENABLED=_parse_bool_optional(
                "ADMIN_PANEL_ENABLED", False,
            ),
            ADMIN_USERNAME=_env("ADMIN_USERNAME") or "admin",
            ADMIN_PASSWORD=_env("ADMIN_PASSWORD"),
            AGENT_ENABLED=_parse_bool_optional("AGENT_ENABLED", True),
            VERIFY_WEBHOOK_SIGNATURE=_parse_bool_optional(
                "VERIFY_WEBHOOK_SIGNATURE", True,
            ),
            SENTRY_DSN=_env("SENTRY_DSN"),
            SENTRY_ENVIRONMENT=_env("SENTRY_ENVIRONMENT") or "production",
            SENTRY_TRACES_SAMPLE_RATE=_parse_float_safe(
                "SENTRY_TRACES_SAMPLE_RATE", 0.0,
            ),
        )

    @property
    def app_name(self) -> str:
        return self.COMPANY_NAME

    @property
    def environment(self) -> str:
        return ""

    @property
    def public_base_url(self) -> str:
        return ""

    @property
    def company_name(self) -> str:
        return self.COMPANY_NAME

    @property
    def company_tone(self) -> str:
        return f"{self.COMPANY_TONE_PARENTS} {self.COMPANY_TONE_ADULTS}".strip()

    @property
    def company_language(self) -> str:
        return self.COMPANY_LANGUAGE

    @property
    def company_timezone(self) -> str:
        return ""

    @property
    def openai_api_key(self) -> str:
        return self.OPENAI_API_KEY

    @property
    def openai_model(self) -> str:
        return self.OPENAI_MODEL

    @property
    def openai_system_prompt(self) -> str:
        return ""

    @property
    def google_sheets_credentials_json(self) -> str:
        return self.GOOGLE_SHEETS_CREDENTIALS_JSON

    @property
    def google_sheets_scopes(self) -> str:
        return ""

    @property
    def google_sheet_id(self) -> str:
        return self.GOOGLE_SHEETS_SPREADSHEET_ID

    @property
    def google_sheet_range(self) -> str:
        return self.GOOGLE_SHEETS_LEADS_TAB

    @property
    def google_sheet_value_input_option(self) -> str:
        return ""

    @property
    def google_calendar_credentials_json(self) -> str:
        return self.GOOGLE_CALENDAR_CREDENTIALS_JSON

    @property
    def google_calendar_scopes(self) -> str:
        return ""

    @property
    def google_calendar_id(self) -> str:
        return self.GOOGLE_CALENDAR_ID

    @property
    def google_calendar_default_duration_minutes(self) -> int:
        return 0

    # ---- Calendar Multi-Busy Check Patch (2026-06-04) -------------------
    #
    # `booking_calendar_id()` / `busy_calendar_ids()` are the resolved
    # accessors callers SHOULD use. They fold the new `BOOKING_CALENDAR_ID`
    # and `BUSY_CALENDAR_IDS` envs into the existing single-calendar
    # contract:
    #
    #   * booking_calendar_id() — calendar the agent INSERTS events into.
    #     Resolution order: BOOKING_CALENDAR_ID → GOOGLE_CALENDAR_ID.
    #   * busy_calendar_ids()   — every calendar whose busy data the agent
    #     consults for availability. Resolution: split
    #     BUSY_CALENDAR_IDS on ',' / strip / dedupe. If empty, fall back
    #     to `[booking_calendar_id()]`. Booking calendar is always included
    #     (deduped to the front). Trailing / leading whitespace tolerated.
    #
    # The agent ONLY ever writes to `booking_calendar_id()`. It NEVER
    # writes to other entries in `busy_calendar_ids()` — those are
    # read-only sources for availability.

    def booking_calendar_id(self) -> str:
        return (self.BOOKING_CALENDAR_ID or "").strip() or self.GOOGLE_CALENDAR_ID

    def busy_calendar_ids(self) -> list[str]:
        booking = self.booking_calendar_id()
        raw = (self.BUSY_CALENDAR_IDS or "").strip()
        out: list[str] = []
        seen: set[str] = set()
        if booking:
            out.append(booking)
            seen.add(booking)
        if not raw:
            return out
        for piece in raw.split(","):
            cid = piece.strip()
            if cid and cid not in seen:
                out.append(cid)
                seen.add(cid)
        return out

    # ---- Manager WhatsApp notification (2026-06-18) --------------------
    #
    # Single read points for the WhatsApp Cloud API manager-notification
    # config, used by `notification_service._send_manager_whatsapp` and the
    # `messenger_service.send_message` WhatsApp branch. The env aliases are
    # already folded in at load time (`from_env`):
    #   * access token   ← WHATSAPP_ACCESS_TOKEN, else WHATSAPP_TOKEN
    #   * recipient      ← MANAGER_WHATSAPP, else MANAGER_WHATSAPP_NUMBER
    #   * phone-number id ← WHATSAPP_PHONE_NUMBER_ID
    # These accessors centralise the read (and normalise the recipient)
    # so the send paths never reach into the raw fields directly. They
    # NEVER log or expose the token.

    def get_whatsapp_access_token(self) -> str:
        return (self.WHATSAPP_TOKEN or "").strip()

    def get_whatsapp_phone_number_id(self) -> str:
        return (self.WHATSAPP_PHONE_NUMBER_ID or "").strip()

    def get_manager_whatsapp_number(self) -> str:
        """Manager WhatsApp recipient, normalised to digits-only
        international format for the Cloud API ``to`` field."""
        return normalize_whatsapp_number(self.MANAGER_WHATSAPP_NUMBER)

    def is_whatsapp_configured(self) -> bool:
        """True only when token + phone-number-id + a resolvable manager
        recipient are all present."""
        return bool(
            self.get_whatsapp_access_token()
            and self.get_whatsapp_phone_number_id()
            and self.get_manager_whatsapp_number()
        )

    @property
    def notification_webhook_url(self) -> str:
        return ""

    @property
    def notification_timeout_seconds(self) -> int:
        return 0

    @property
    def messenger_page_access_token(self) -> str:
        return self.MESSENGER_PAGE_ACCESS_TOKEN or self.META_ACCESS_TOKEN

    @property
    def messenger_verify_token(self) -> str:
        return self.MESSENGER_VERIFY_TOKEN or self.META_VERIFY_TOKEN

    @property
    def messenger_graph_api_base_url(self) -> str:
        return self.META_GRAPH_API_BASE_URL

    @property
    def messenger_graph_api_version(self) -> str:
        return self.META_GRAPH_API_VERSION

    @property
    def internal_api_token(self) -> str:
        return self.INTERNAL_API_TOKEN

    @property
    def followup_enabled(self) -> bool:
        # Follow-up Test Mode Patch (2026-06-06). Operator-controlled
        # `FOLLOWUP_ENABLED=false` is the hard kill — overrides
        # FOLLOWUP_HOURS regardless of value. When the flag is true
        # (default), follow-ups still require FOLLOWUP_HOURS > 0 to
        # remain backwards-compatible with the historic legacy gate.
        if not self.FOLLOWUP_ENABLED:
            return False
        return self.FOLLOWUP_HOURS > 0

    @property
    def followup_delay_minutes(self) -> int:
        return self.FOLLOWUP_HOURS * 60


def normalize_whatsapp_number(raw: str | None) -> str:
    """Best-effort normalise a phone to digits-only international format for
    the WhatsApp Cloud API ``to`` field (no ``+``, no spaces/dashes).

    Rules (conservative — never guesses wrongly):
      * strip ``+``, spaces, dashes, parentheses → digits only;
      * drop an international ``00`` prefix;
      * a number already carrying the Georgian country code (``995…``) is
        returned unchanged;
      * a domestic ``0``-prefixed 10-digit mobile (``0XXXXXXXXX``) drops the
        leading 0;
      * a bare 9-digit Georgian mobile (``5XXXXXXXX``) gets ``995`` prepended;
      * anything else returns its digits unchanged.

    Returns ``""`` for empty/garbage input. Pure string math — never logs.
    """
    if not raw:
        return ""
    digits = "".join(ch for ch in str(raw) if ch.isdigit())
    if not digits:
        return ""
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("995"):
        return digits
    if len(digits) == 10 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 9 and digits.startswith("5"):
        return "995" + digits
    return digits


def has_value(value: str | None) -> bool:
    return bool(value and value.strip())


def csv_values(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings.from_env()


settings = get_settings()
