import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.api.admin_documents import require_admin
from app.core.config import get_settings
from app.core.observability import traced_operation
from app.db import document_repository as repository
from app.infrastructure.object_storage import signed_pdf_url
from app.services.limits import reserve_request


router = APIRouter(prefix="/api")


@router.get("/admin/kb/revisions/{revision_id}/preview", dependencies=[Depends(require_admin)])
@traced_operation("kb_admin_preview_pdf", start_trace=True)
def preview_revision(revision_id: str):
    row = repository.preview_object(revision_id)
    if not row:
        raise HTTPException(404, "PDF unavailable.")
    return {"url": signed_pdf_url(row["object_key"])}


@router.get("/kb/revisions/{revision_id}.pdf")
def open_revision(revision_id: str, request: Request):
    settings = get_settings()
    if not settings.kb_managed or not re.fullmatch(r"[1-9][0-9]{0,18}", revision_id):
        raise HTTPException(404, "PDF unavailable.")
    if not settings.public_pdf_downloads_enabled:
        raise HTTPException(404, "PDF unavailable.")
    reserve_request(request, "pdf")
    row = repository.published_object(revision_id)
    if not row:
        raise HTTPException(404, "PDF unavailable.")
    return RedirectResponse(signed_pdf_url(row["object_key"]), status_code=302,
                            headers={"Referrer-Policy": "no-referrer"})
