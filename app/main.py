import asyncio

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
    # Phase 3.9+ — surface feature-flag state at boot so operators can see at
    # a glance whether the deterministic-first router + LLM analyzer are in
    # the live runtime, without grepping the env or settings.
    print(f"⚙️ USE_LLM_TURN_ANALYZER={settings.USE_LLM_TURN_ANALYZER}")
    print(f"⚙️ USE_LLM_COMPOSER={settings.USE_LLM_COMPOSER}")
    print(f"⚙️ USE_PARENT_LLM_ENGINE={settings.USE_PARENT_LLM_ENGINE}")
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
