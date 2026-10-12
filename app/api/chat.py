"""Local, non-streaming API for the first tool-calling session."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import Field

from app.access import CREDENTIAL
from app.api.access import bearer_scheme
from app.demo_gate import AdmissionError
from app.llm.contracts import StrictModel, valid_text
from app.llm.service import ask
from app.observability import REQUEST_ID

router = APIRouter(prefix="/api", tags=["chat"])


class ChatRequest(StrictModel):
    question: str = Field(min_length=1, max_length=2000)


def admission_response(request: Request, error: AdmissionError):
    result = {
        "status": "error",
        "error": {"category": error.category},
        "request_id": REQUEST_ID.get(),
    }
    request.state.chat_result = result
    headers = {"Retry-After": str(error.retry_after)} if error.retry_after is not None else {}
    return JSONResponse(status_code=error.status_code, content=result, headers=headers)


@router.post("/chat", dependencies=[Depends(bearer_scheme)])
def chat(body: ChatRequest, request: Request):
    if not valid_text(body.question, 2000) or CREDENTIAL.search(body.question):
        raise HTTPException(422, detail="Question must contain up to 2000 UTF-8 bytes of text.")
    # Keep the cheap local guard as well as the durable, shared public policy.
    if not request.app.state.chat_lock.acquire(blocking=False):
        if request.app.state.demo_gate is not None:
            return admission_response(request, AdmissionError("demo_busy", 429, 5))
        raise HTTPException(429, detail="Another analytics request is in progress.")
    try:
        gate = request.app.state.demo_gate
        request_id = REQUEST_ID.get()
        if gate is None:
            result = ask(body.question)
        else:
            identity = getattr(request.state, "access_identity", None)
            if identity is None:
                gate.admit(request_id)
            else:
                gate.admit(request_id, identity=identity)
            result = None
            try:
                result = ask(
                    body.question,
                    settings=request.app.state.llm_settings,
                    embedding_settings=request.app.state.embedding_settings,
                )
            finally:
                gate.release(request_id, result=result)
        request.state.chat_result = result
        return result
    except AdmissionError as exc:
        return admission_response(request, exc)
    finally:
        request.app.state.chat_lock.release()
