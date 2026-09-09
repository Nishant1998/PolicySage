from contextlib import asynccontextmanager
from asyncio import to_thread

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api import admin_documents, chat, document_sources, health
from app.core.config import BASE_DIR, get_settings
from app.core.logging import configure_logging
from app.core.observability import APP_VERSION, observe_request
from app.core.http import RequestBodyLimit, body_limit, upload_path
from app.services.audit import init_db
from app.services.limits import init_usage
from app.rag.retrieval import reranker


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    try:
        init_db()
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Audit storage unavailable")
    init_usage()
    await to_thread(reranker)
    yield


app = FastAPI(title="PolicySage", version=APP_VERSION, lifespan=lifespan)
app.add_middleware(RequestBodyLimit)
for api in (health, chat, admin_documents, document_sources):
    app.include_router(api.router)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@app.middleware("http")
async def limit_request_size(request: Request, call_next):
    if request.method == "POST" and (request.url.path == "/api/chat" or upload_path(request.url.path)):
        value = request.headers.get("content-length")
        if value is None:
            return JSONResponse({"detail": "Content-Length is required."}, status_code=411)
        try:
            size = int(value)
        except ValueError:
            return JSONResponse({"detail": "Invalid Content-Length."}, status_code=400)
        limit = body_limit(request.url.path)
        if size < 0 or size > limit:
            return JSONResponse({"detail": "Request is too large."}, status_code=413)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


@app.middleware("http")
async def observe_http_request(request: Request, call_next):
    path = request.url.path if request.url.path in {"/api/chat", "/api/health", "/"} else "other"
    if request.url.path.startswith("/api/admin/kb/"):
        path = "/api/admin/kb"
    elif request.url.path.startswith("/api/kb/revisions/"):
        path = "/api/kb/revisions"
    with observe_request(path, request.method, export=False) as observation:
        response = await call_next(request)
        observation["http_status"] = response.status_code
        if response.status_code >= 500:
            observation["error_type"] = "RequestFailed"
            observation["cost_complete"] = False
        response.headers["X-Request-ID"] = observation["id"]
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        )
        return response


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"app_name": get_settings().app_name, "kb_managed": get_settings().kb_managed},
    )


@app.get("/admin", response_class=HTMLResponse, include_in_schema=False)
def admin_page(request: Request):
    if not get_settings().kb_managed:
        raise HTTPException(404)
    return templates.TemplateResponse(
        request=request, name="admin.html", context={"app_name": get_settings().app_name},
    )
