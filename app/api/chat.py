import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.core.budget import request_budget
from app.core.config import get_settings
from app.core.observability import current_request, start_request_trace, trace_content
from app.db.document_repository import retrieval_snapshot
from app.rag.state import ChatTurn, PolicyFilters
from app.rag.workflow import ask
from app.services.audit import write_audit
from app.services.limits import request_slot, reserve_request


logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api")


class ChatRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    question: str = Field(min_length=2, max_length=3000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=4)
    filters: PolicyFilters | None = None
    allow_web: bool = True


def chat_access(request: Request):
    settings = get_settings()
    if not settings.public_chat_enabled or not settings.kb_managed or (
        settings.app_env == "production" and not settings.kb_managed
    ):
        raise HTTPException(503, "The public demo is temporarily unavailable.")
    reserve_request(request, "chat")
    with request_slot("chat"):
        yield


@router.post("/chat", dependencies=[Depends(chat_access)])
def chat(payload: ChatRequest, request: Request = None, response: Response = None):
    settings = get_settings()
    conversation_id = None
    if request is not None:
        try:
            supplied_id = UUID(request.headers.get("X-Conversation-ID", ""))
            if supplied_id.version == 4:
                conversation_id = supplied_id.hex
        except ValueError:
            pass
    start_request_trace(conversation_id=conversation_id, question=payload.question)
    observation = current_request.get()
    if observation is not None:
        observation["_result"] = {"status": "error"}
    try:
        filters = payload.filters.model_dump(exclude_none=True) if payload.filters else None
        history = [turn.model_dump() for turn in payload.history]
        with request_budget():
            with retrieval_snapshot():
                result = ask(payload.question, filters=filters, allow_web=payload.allow_web, history=history)
    except Exception as exc:
        logger.warning("Chat request failed (%s)", type(exc).__name__)
        raise HTTPException(
            status_code=500, detail="Could not process the question. Please try again."
        ) from exc

    if result["status"] == "error":
        raise HTTPException(
            status_code=500, detail="Could not process the question. Please try again."
        )

    try:
        write_audit(payload.question, result["source_used"], result.get("trace", []))
    except Exception:
        logger.exception("Could not write query audit")

    if observation is not None and observation.get("_root") is not None:
        status = result["status"]
        if result["source_used"] in {"web", "kb_and_web"}:
            response_type = "web_fallback"
        elif result.get("citations"):
            response_type = "grounded"
        else:
            response_type = {"answered": "direct", "clarification_required": "clarification"}.get(
                status, "abstention"
            )
        observation["_result"] = {
            "status": "success" if status == "answered" else "unanswered",
            "answer_status": status,
            "response_type": response_type,
            "source_used": result["source_used"],
            "citation_count": len(result.get("citations", [])),
            "evidence_sufficient": result.get("kb_grade") == "good" or result.get("web_grade") == "good",
            "retry_count": result.get("retry_count", 0),
            "answer": trace_content(result["answer"]),
        }
    return {
        "answer": result["answer"],
        "status": result["status"],
        "source_used": result["source_used"],
        "trace": result.get("trace", []),
        "citations": result.get("citations", []),
        "limitations": result.get("limitations", []),
        "rewritten_query": result.get("current_query", payload.question),
    }
