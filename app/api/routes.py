import logging
from hashlib import sha256
from pathlib import Path
from secrets import compare_digest
from uuid import uuid4

from fastapi import APIRouter, File, Header, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import get_settings
from app.rag.state import PolicyFilters
from app.rag.workflow import ask
from app.rag.vectorstore import index_document_chunks
from app.services.audit import write_audit
from app.services.ingestion import SUPPORTED, chunk_documents, load_file

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")
MAX_UPLOAD_SIZE = 20 * 1024 * 1024


class ChatRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    question: str = Field(min_length=2, max_length=3000)
    filters: PolicyFilters | None = None
    allow_web: bool = True


@router.get("/health")
def health():
    return {"status": "ok", "service": get_settings().app_name}


@router.post("/chat")
def chat(payload: ChatRequest):
    try:
        filters = payload.filters.model_dump(exclude_none=True) if payload.filters else None
        result = ask(payload.question, filters=filters, allow_web=payload.allow_web)
        write_audit(payload.question, result["source_used"], result.get("trace", []))
    except Exception as exc:
        logger.warning("Chat request failed (%s)", type(exc).__name__)
        raise HTTPException(
            status_code=500, detail="Could not process the question. Please try again."
        ) from exc

    if result["status"] == "error":
        raise HTTPException(
            status_code=500, detail="Could not process the question. Please try again."
        )

    return {
        "answer": result["answer"],
        "status": result["status"],
        "source_used": result["source_used"],
        "trace": result.get("trace", []),
        "citations": result.get("citations", []),
        "limitations": result.get("limitations", []),
        "rewritten_query": result.get("current_query", payload.question),
    }


@router.post("/ingest")
def ingest(file: UploadFile = File(...), x_admin_key: str = Header(default="")):
    settings = get_settings()
    admin_key = settings.admin_api_key.get_secret_value()
    if not admin_key:
        raise HTTPException(status_code=503, detail="Document ingestion is not configured.")
    if not compare_digest(x_admin_key.encode(), admin_key.encode()):
        raise HTTPException(status_code=401, detail="Invalid admin key")

    name = Path(file.filename or "").name
    suffix = Path(name).suffix.lower()
    if suffix not in SUPPORTED:
        raise HTTPException(status_code=400, detail=f"Supported: {', '.join(sorted(SUPPORTED))}")
    content = file.file.read(MAX_UPLOAD_SIZE + 1)
    if not content:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="The file must be no larger than 20 MB.")

    destination = settings.upload_dir / f"{uuid4().hex}{suffix}"
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    except OSError as exc:
        logger.warning("Upload storage failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Could not save the uploaded file.") from exc

    try:
        documents = load_file(destination)
        document_hash = sha256(content).hexdigest()
        # Keep readable citations and stable vector IDs despite the unique upload filename.
        for document in documents:
            document.metadata.update(
                source=f"uploads/{name}", document_title=name, sha256=document_hash
            )
        chunks = chunk_documents(documents)
    except Exception as exc:
        destination.unlink(missing_ok=True)
        logger.warning("Document parsing failed (%s)", type(exc).__name__)
        raise HTTPException(
            status_code=400, detail="Could not read the document. Use a readable, unencrypted file."
        ) from exc

    try:
        ids = index_document_chunks(chunks)
    except Exception as exc:
        logger.warning("Document indexing failed (%s)", type(exc).__name__)
        raise HTTPException(
            status_code=500, detail="Could not index the document. Please try again."
        ) from exc
    return {
        "message": "Document indexed",
        "file": name,
        "chunks": len(chunks),
        "ids_indexed": len(ids),
    }
