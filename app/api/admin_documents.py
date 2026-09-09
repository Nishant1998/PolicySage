import logging
from pathlib import Path
from secrets import compare_digest
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.core.config import get_settings
from app.core.observability import traced_operation
from app.db import document_repository as repository
from app.services.document_service import MAX_PDF_BYTES, register_document, withdraw
from app.services.limits import request_slot, reserve_request


logger = logging.getLogger(__name__)


basic = HTTPBasic(auto_error=False)


def require_admin(request: Request, credentials: HTTPBasicCredentials | None = Depends(basic)):
    settings = get_settings()
    if not settings.kb_managed:
        raise HTTPException(404, "Managed knowledge base is disabled.")
    if settings.app_env == "production" and request.url.scheme != "https":
        raise HTTPException(403, "Admin access requires HTTPS.")
    password = settings.admin_api_key.get_secret_value() or settings.kb_admin_password.get_secret_value()
    if not password or not settings.kb_admin_username:
        raise HTTPException(503, "Admin access is not configured.")
    username_ok = credentials and compare_digest(credentials.username.encode(), settings.kb_admin_username.encode())
    password_ok = credentials and compare_digest(credentials.password.encode(), password.encode())
    if not (username_ok and password_ok):
        reserve_request(request, "kb-admin-login")
        raise HTTPException(401, "Invalid username or password.")


router = APIRouter(prefix="/api/admin/kb", dependencies=[Depends(require_admin)])


@router.get("/documents")
def list_documents():
    return repository.list_documents()


@router.get("/jobs")
def list_jobs():
    return repository.list_jobs()


def receive_pdf(request, file, metadata, document_id=None):
    reserve_request(request, "upload")
    filename = Path((file.filename or "").replace("\\", "/")).name
    if not filename.lower().endswith(".pdf") or len(filename) > 255 or not filename.isprintable():
        raise HTTPException(400, "Select a PDF with a valid filename.")
    url = metadata.get("source_url", "").strip()
    if url:
        try:
            parts = urlsplit(url)
            if (parts.scheme != "https" or not parts.hostname or parts.username or parts.password
                    or any(char.isspace() for char in url)):
                raise ValueError
            parts.port
        except ValueError:
            raise HTTPException(400, "Enter an HTTPS source URL without credentials.") from None
        metadata["source_url"] = url
    with request_slot("upload"):
        content = file.file.read(MAX_PDF_BYTES + 1)
        if len(content) > MAX_PDF_BYTES:
            raise HTTPException(413, "The PDF must be no larger than 20 MB.")
        try:
            return register_document(content, filename, metadata, document_id=document_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        except Exception as exc:
            logger.warning("Managed PDF registration failed (%s)", type(exc).__name__)
            raise HTTPException(503, "Could not register this PDF. Try again.") from None


def upload_metadata(
    title: str = Form(default="", max_length=200),
    source_url: str = Form(default="", max_length=2048),
    insurer: str = Form(default="", max_length=200),
    category: str = Form(default="", max_length=100),
    product_name: str = Form(default="", max_length=200),
    document_type: str = Form(default="", max_length=100),
    uin: str = Form(default="", max_length=1000),
    review_required: bool = Form(default=False),
):
    return {
        "document_title": title.strip(),
        "source_url": source_url,
        "insurer": insurer.strip(),
        "category": category.strip(),
        "product_name": product_name.strip(),
        "document_type": document_type.strip(),
        "uin": [value.strip() for value in uin.split(";") if value.strip()],
        "review_required": review_required,
    }


@router.post("/documents", status_code=202)
@traced_operation("kb_admin_upload", start_trace=True)
def add_document(request: Request, file: UploadFile = File(...), metadata=Depends(upload_metadata)):
    return receive_pdf(request, file, metadata)


@router.post("/documents/{document_id}/revisions", status_code=202)
@traced_operation("kb_admin_replace", start_trace=True)
def add_revision(request: Request, document_id: int, file: UploadFile = File(...),
                 metadata=Depends(upload_metadata)):
    return receive_pdf(request, file, metadata, document_id)


@router.post("/revisions/{revision_id}/approve", status_code=202)
@traced_operation("kb_admin_approve", start_trace=True)
def approve_revision(revision_id: int):
    approved = repository.approve_revision(revision_id)
    if not approved:
        raise HTTPException(409, "This revision is not waiting for review.")
    return {"status": "approved"}


@router.delete("/documents/{document_id}")
@traced_operation("kb_admin_withdraw", start_trace=True)
def withdraw_document(document_id: int):
    try:
        withdraw(document_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from None
    except Exception as exc:
        logger.warning("Document withdrawal failed (%s)", type(exc).__name__)
        raise HTTPException(503, "Could not confirm withdrawal. Try again.") from None
    return {"status": "withdrawn"}


@router.post("/jobs/{job_id}/retry", status_code=202)
@traced_operation("kb_admin_retry", start_trace=True)
def retry_job(job_id: int):
    job = repository.retry_job(job_id)
    if not job:
        raise HTTPException(409, "Only failed jobs can be retried.")
    return {"status": "queued"}
