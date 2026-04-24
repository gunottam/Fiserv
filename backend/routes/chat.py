"""POST /chat — conversational reasoning grounded in a decision context.

Typical usage from the frontend:

1. User hits the "Approve Restock" panel.
2. They open the chatbot drawer and ask "why HIGH urgency?".
3. The UI sends the PredictResponse back as ``context`` plus the running
   message list. The LLM answers using only those numbers.

We deliberately keep this stateless: the server never stores history, the
client owns it. That keeps the deployment simple and lets the UI scope a
conversation to the SKU/alert it's about.
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from services.chat import chat_is_configured, generate_chat_reply

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class DecisionContext(BaseModel):
    """Subset of PredictResponse the chat model needs to stay grounded.

    Extra fields are tolerated so the frontend can forward the full predict
    payload without filtering — we only read the ones we render into the
    system prompt.
    """

    model_config = {"extra": "allow"}

    item_id: str
    item_name: str
    current_stock: float
    threshold: float
    day_of_week: str
    hour: int = Field(..., ge=0, le=23)
    is_peak_hour: bool

    predicted_velocity: float
    adjusted_velocity: float
    coverage_hours: float
    stockout_risk: float
    urgency: Literal["HIGH", "MEDIUM", "LOW"]
    restock: int
    context_factors: list[str] = Field(default_factory=list)
    historical_stockout_rate: float | None = None


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str

    @field_validator("content")
    @classmethod
    def _not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("content must not be empty")
        return v


class ChatRequest(BaseModel):
    """Operator question + the conversation history so far."""

    context: DecisionContext
    message: str = Field(
        ..., min_length=1, description="The new operator message to answer."
    )
    history: list[ChatMessage] = Field(
        default_factory=list,
        description=(
            "Prior turns in the conversation (oldest first). Does NOT need to "
            "include the current `message`; the server appends it."
        ),
    )

    @field_validator("message")
    @classmethod
    def _strip_message(cls, v: str) -> str:
        return v.strip()


class ChatResponse(BaseModel):
    reply: str
    groq_used: bool = Field(
        description=(
            "True when the reply came from Groq. False means the server fell "
            "back to a deterministic rule-based answer (usually because no "
            "GROQ_API_KEY is set)."
        )
    )


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/chat",
    response_model=ChatResponse,
    summary="Ask a grounded question about a specific restock decision",
)
async def chat(request: ChatRequest) -> ChatResponse:
    """Answer a "why / what-if" question grounded in ``context``.

    The server is stateless — the caller maintains ``history`` on their side
    (typically per alert / per drawer open). This keeps the chat scoped to
    one SKU at a time and avoids leaking context between users.
    """
    try:
        history = [msg.model_dump() for msg in request.history]
        context = request.context.model_dump()

        reply = await generate_chat_reply(
            context=context,
            history=history,
            user_message=request.message,
        )

        return ChatResponse(reply=reply, groq_used=chat_is_configured())

    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("Chat pipeline failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Chat pipeline failed. Check server logs for details.",
        ) from exc
