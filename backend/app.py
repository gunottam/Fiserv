"""FastAPI entrypoint for Contextual Inventory Intelligence."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Load .env before any service module reads env vars (services read at import
# time for things like GROQ_API_KEY and MODEL_PATH).
load_dotenv()

from routes.chat import router as chat_router  # noqa: E402
from routes.demand import router as demand_router  # noqa: E402
from routes.predict import router as predict_router  # noqa: E402
from services import telegram_bot  # noqa: E402
from services.demand_series import dataset_is_available  # noqa: E402
from services.inference import model_is_loaded  # noqa: E402
from services.telegram import telegram_is_configured  # noqa: E402
from utils.preprocessing import item_stats_loaded  # noqa: E402

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
)
logger = logging.getLogger("app")


def _parse_origins(raw: str) -> list[str]:
    """Split a comma-separated CORS_ORIGINS env var into a clean list."""
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the Telegram bot listener with the API, stop it on shutdown.

    The bot runs in the same event loop as uvicorn. When TELEGRAM_BOT_TOKEN
    is not set, `telegram_bot.start()` becomes a no-op so boot is clean in
    dev/test environments.
    """
    logger.info(
        "Contextual Inventory Intelligence ready · model=%s · item_stats=%s · groq=%s · telegram=%s",
        "loaded" if model_is_loaded() else "fallback",
        "loaded" if item_stats_loaded() else "fallback",
        "configured" if os.getenv("GROQ_API_KEY", "").strip() else "fallback",
        "configured" if telegram_is_configured() else "disabled",
    )
    try:
        await telegram_bot.start()
    except Exception as exc:  # noqa: BLE001 — bot failure must not block API
        logger.warning("Telegram bot failed to start: %s", exc)
    try:
        yield
    finally:
        try:
            await telegram_bot.stop()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Telegram bot failed to stop cleanly: %s", exc)


app = FastAPI(
    title="Contextual Inventory Intelligence",
    description=(
        "Turns a live inventory snapshot into a restock decision backed by a "
        "short, grounded rationale."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_parse_origins(
        os.getenv("CORS_ORIGINS", "http://localhost:3000")
    ),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(predict_router, tags=["predict"])
app.include_router(chat_router, tags=["chat"])
app.include_router(demand_router, tags=["demand"])


@app.get("/", tags=["meta"])
def health() -> dict[str, object]:
    """Lightweight health / status probe — used by uptime checks and the UI."""
    return {
        "service": "contextual-inventory-intelligence",
        "status": "ok",
        "model_loaded": model_is_loaded(),
        "item_stats_loaded": item_stats_loaded(),
        "dataset_available": dataset_is_available(),
        "groq_configured": bool(os.getenv("GROQ_API_KEY", "").strip()),
        "telegram_configured": telegram_is_configured(),
        "telegram_bot_running": telegram_bot.is_running(),
    }
