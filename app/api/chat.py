"""Local, non-streaming API for the first tool-calling session."""

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field

from app.llm.contracts import StrictModel, valid_text
from app.llm.service import ask

router = APIRouter(prefix="/api", tags=["chat"])


class ChatRequest(StrictModel):
    question: str = Field(min_length=1, max_length=2000)


@router.post("/chat")
def chat(body: ChatRequest, request: Request) -> dict:
    if not valid_text(body.question, 2000):
        raise HTTPException(422, detail="Question must contain up to 2000 UTF-8 bytes of text.")
    # One active request per process. Deployment needs a shared rate/cost budget.
    if not request.app.state.chat_lock.acquire(blocking=False):
        raise HTTPException(429, detail="Another analytics request is in progress.")
    try:
        return ask(body.question)
    finally:
        request.app.state.chat_lock.release()
