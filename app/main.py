import asyncio
import logging
import os
import sys

# Observability (2026-07-31 live test): the app never configured logging, so
# Python fell back to `logging.lastResort` — a WARNING-only stderr handler.
# Every `logger.info` diagnostic already written in this codebase was therefore
# dropped in production: `[slot_check]`, `[book_consultation] datetime_parsed=`,
# and `[messenger_debug] turn ... in=... out=...`. A live booking failure could
# not be traced from the Railway logs at all — only `print()` output survived.
#
# This adds no new log call; it only lets the existing ones out. `basicConfig`
# is a no-op when a handler is already installed (pytest's caplog), so test
# capture is unaffected.
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    stream=sys.stdout,
)
# Third-party loggers stay at WARNING. Their INFO lines are noise and some of
# them echo request URLs — which must never reach the logs (never log a token).
for _noisy_logger in (
    "httpx", "httpcore", "urllib3", "openai", "anthropic",
    "google", "googleapiclient", "googleapiclient.discovery_cache",
    "apscheduler", "gspread",
):
    logging.getLogger(_noisy_logger).setLevel(logging.WARNING)

from fastapi import FastAPI
from app.routes.admin import router as admin_router
from app.routes.webhook import router
from app.services import comment_service, followup_service, redis_state_service
from app.services.sentry_service import init_sentry
from apscheduler.schedulers.background import BackgroundScheduler
from app.config import settings

# Initialise Sentry as early as possible so an exception during the
# rest of boot is still captured. Safe no-op when SENTRY_DSN is empty
# OR sentry-sdk is not installed.
init_sentry(
    dsn=settings.SENTRY_DSN,
    environment=settings.SENTRY_ENVIRONMENT,
    traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
)

app = FastAPI(title=f"{settings.COMPANY_NAME} AI Agent")

app.include_router(router)
# Admin Panel MVP — every endpoint inside the router is auth-gated and
# additionally refuses to serve when ADMIN_PANEL_ENABLED=false. Safe to
# always mount.
app.include_router(admin_router)


def _run_comment_followups() -> None:
    asyncio.run(comment_service.check_comment_followups())


@app.on_event("startup")
async def startup():
    print(f"✅ {settings.COMPANY_NAME} AI Agent started")
    print(f"📚 Knowledge base loaded: {len(settings.KNOWLEDGE_BASE)} chars")
    print(f"🎭 Events loaded: {len(settings.EVENTS)} chars")
    # Boot marker for the log-visibility fix. Doubles as a build discriminator:
    # the 2026-07-31 arc showed USE_CONSULTATION_PROGRAM_NAME was NOT one (it
    # shipped a PR earlier), so a stuck deploy looked live. This line is new, so
    # its absence in a boot log proves an older container is still serving.
    print(f"⚙️ LOG_LEVEL={os.getenv('LOG_LEVEL', 'INFO').upper()}")
    # Live 2026-07-31: the agent refused to give the manager's number four
    # times. `get_manager_phone()` reads Admin Config ONLY (sections.yaml on the
    # Railway volume, then the manager_contacts mirror) and deliberately ignores
    # MANAGER_PHONE_NUMBER, returning "" when unset — so an empty volume config
    # silently removes the number. Presence only; the value is never logged.
    try:
        from app.services import admin_config_service

        _mgr = (admin_config_service.get_manager_phone() or "").strip()
        print(f"⚙️ manager_phone={'set' if _mgr else 'NOT set (Admin Config has none)'}")
    except Exception as exc:  # pragma: no cover — diagnostic must never block boot
        print(f"⚙️ manager_phone=UNKNOWN ({type(exc).__name__})")
    # Phase 3.9+ — surface feature-flag state at boot so operators can see at
    # a glance whether the deterministic-first router + LLM analyzer are in
    # the live runtime, without grepping the env or settings.
    print(f"⚙️ USE_LLM_TURN_ANALYZER={settings.USE_LLM_TURN_ANALYZER}")
    print(f"⚙️ USE_LLM_COMPOSER={settings.USE_LLM_COMPOSER}")
    print(f"⚙️ USE_PARENT_LLM_ENGINE={settings.USE_PARENT_LLM_ENGINE}")
    # Smart-agent feature-flag boot visibility (Phase 0a, 2026-07-20) — the
    # audit found NO boot-log signal for these flags, which contributed to an
    # admin-added dynamic program going unnoticed as "not live". Pure
    # logging, zero behavior change.
    print(f"⚙️ USE_DYNAMIC_PROGRAMS={getattr(settings, 'USE_DYNAMIC_PROGRAMS', False)}")
    print(f"⚙️ USE_LEAD_MEMORY={getattr(settings, 'USE_LEAD_MEMORY', False)}")
    print(f"⚙️ USE_SKILLS={getattr(settings, 'USE_SKILLS', False)}")
    print(f"⚙️ USE_LEARNING={getattr(settings, 'USE_LEARNING', False)}")
    # R2 / Cap#1 / R1 flags (2026-07-22) — boot visibility so an operator can
    # confirm from the deploy log whether the flag is actually read (the
    # dynamic-welcome debug: if this prints False, the env isn't set/read; if it
    # doesn't print at all, an OLD container is still serving pre-deploy code).
    print(f"⚙️ USE_DYNAMIC_WELCOME={getattr(settings, 'USE_DYNAMIC_WELCOME', False)}")
    print(f"⚙️ USE_PROGRAM_TOPICS={getattr(settings, 'USE_PROGRAM_TOPICS', False)}")
    print(
        "⚙️ USE_PER_PRODUCT_BOOKING="
        f"{getattr(settings, 'USE_PER_PRODUCT_BOOKING', False)}"
    )
    # Same reason as the flags above: the CRM "Program" column reads this flag to
    # decide between the readable program NAME and the internal program_id. It was
    # the one flag in that path with no boot signal, so "is the fix live?" could
    # only be guessed at. Pure logging, zero behaviour change.
    print(
        "⚙️ USE_CONSULTATION_PROGRAM_NAME="
        f"{getattr(settings, 'USE_CONSULTATION_PROGRAM_NAME', False)}"
    )
    # Phase 0b (2026-07-20) — boot-log the resolved admin-config directory so
    # operators can see at a glance whether config is being read/written from
    # the repo-default path (ephemeral on Railway) or an operator-mounted
    # persistent volume (ADMIN_CONFIG_DIR env override).
    from app.services import admin_config_service as _acs
    print(f"⚙️ ADMIN_CONFIG_DIR={_acs.ADMIN_CONFIG_DIR}")
    # Conversation Planner (Phase 3) rollout visibility — confirm at boot whether
    # the planner is computing (shadow) and whether it is authoritative.
    print(f"⚙️ USE_CONVERSATION_PLANNER={settings.USE_CONVERSATION_PLANNER}")
    print(
        "⚙️ CONVERSATION_PLANNER_AUTHORITATIVE="
        f"{getattr(settings, 'CONVERSATION_PLANNER_AUTHORITATIVE', False)}"
    )
    print(f"⚙️ USE_SLIM_PROMPTS={getattr(settings, 'USE_SLIM_PROMPTS', False)}")
    print(
        "⚙️ CONVERSATION_TRACE_DEBUG="
        f"{getattr(settings, 'CONVERSATION_TRACE_DEBUG', False)}"
    )
    print(f"🔍 Sentry {'enabled' if settings.SENTRY_DSN else 'disabled'}")

    # Instagram Webhook Signature Patch (2026-06-08): boot-time
    # visibility into which webhook secrets / tokens are wired in.
    # Prints only presence (set / not set), NEVER the values.
    fb_secret_set = bool(
        getattr(settings, "META_APP_SECRET", "")
        or getattr(settings, "MESSENGER_APP_SECRET", ""),
    )
    ig_secret_set = bool(getattr(settings, "INSTAGRAM_APP_SECRET", ""))
    ig_token_set = bool(getattr(settings, "INSTAGRAM_ACCESS_TOKEN", ""))
    print(
        f"🔐 webhook secrets: facebook_app_secret={'set' if fb_secret_set else 'NOT set'} "
        f"instagram_app_secret={'set' if ig_secret_set else 'NOT set'}",
    )
    print(
        f"🔐 instagram access token: "
        f"{'set' if ig_token_set else 'NOT set (outbound DM disabled)'}",
    )

    # P3-B — Redis status at boot. Logs whether Redis is enabled, whether
    # a URL is configured, and whether the connection actually works.
    # The helper never raises; if Redis is unavailable the app continues
    # in legacy in-memory mode.
    redis_state_service.log_startup_status()

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        followup_service.check_and_send_followups,
        'interval',
        hours=1
    )
    scheduler.add_job(
        _run_comment_followups,
        'interval',
        hours=1,
        id='comment_followups'
    )
    scheduler.start()
    print("⏰ Follow-up scheduler started")
    print("⏰ Comment follow-up scheduler started")

@app.get("/")
def root():
    return {
        "agent": settings.COMPANY_NAME,
        "status": "running",
        "channels": ["instagram", "messenger", "whatsapp"]
    }
