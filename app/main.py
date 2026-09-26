from contextlib import asynccontextmanager
import logging
from asyncio import to_thread

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import MutableHeaders

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
    configure_logging(settings.log_level, structured=settings.app_env == "production")
    if settings.kb_managed:
        try:
            init_db()
        except Exception:
            logging.getLogger(__name__).exception("Audit storage unavailable")
        init_usage()
    await to_thread(reranker)
    logging.getLogger(__name__).info("Application started")
    try:
        yield
    finally:
        logging.getLogger(__name__).info("Application stopped")


app = FastAPI(title="PolicySage", version=APP_VERSION, lifespan=lifespan)
FRONTEND_BUILD = BASE_DIR / "frontend" / "build"
app.add_middleware(RequestBodyLimit)
for api in (health, chat, admin_documents, document_sources):
    app.include_router(api.router)
if (FRONTEND_BUILD / "static").is_dir():
    app.mount("/static", StaticFiles(directory=FRONTEND_BUILD / "static"), name="static")


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
    return await call_next(request)


class RequestObservation:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope["path"]
        routine = path.startswith("/static/") or path in {"/favicon.svg", "/favicon.ico", "/api/health"}
        safe_path = path if path in {"/api/chat", "/api/health", "/", "/about", "/admin"} else "other"
        if path.startswith("/api/admin/kb/"):
            safe_path = "/api/admin/kb"
        elif path.startswith("/api/kb/revisions/"):
            safe_path = "/api/kb/revisions"
        with observe_request(safe_path, scope["method"], export=False) as observation:
            observation["_routine"] = routine
            response_complete = False

            async def observed_receive():
                message = await receive()
                if message["type"] == "http.disconnect" and not response_complete:
                    observation["error_type"] = "ClientDisconnected"
                return message

            async def observed_send(message):
                nonlocal response_complete
                if message["type"] == "http.response.start":
                    observation["http_status"] = message["status"]
                    if message["status"] >= 500:
                        observation["error_type"] = "RequestFailed"
                    headers = MutableHeaders(raw=list(message.get("headers", [])))
                    for name, value in [
                        (b"x-request-id", observation["id"].encode("ascii")),
                        (b"x-content-type-options", b"nosniff"),
                        (b"referrer-policy", b"strict-origin-when-cross-origin"),
                        (b"x-frame-options", b"DENY"),
                        (b"cache-control", b"no-store"),
                        (b"content-security-policy", b"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"),
                    ]:
                        headers[name.decode("ascii")] = value.decode("ascii")
                    message = {**message, "headers": headers.raw}
                await send(message)
                if (message["type"] == "http.response.body" and not message.get("more_body", False)
                        or message["type"] == "http.response.pathsend"):
                    response_complete = True

            await self.app(scope, observed_receive, observed_send)


app.add_middleware(RequestObservation)


@app.get("/", include_in_schema=False)
@app.get("/about", include_in_schema=False)
def frontend_page():
    index = FRONTEND_BUILD / "index.html"
    if not index.is_file():
        raise HTTPException(503, "Build the frontend with yarn build and restart FastAPI.")
    return FileResponse(index)


@app.get("/admin", include_in_schema=False)
def admin_page():
    if not get_settings().kb_managed:
        raise HTTPException(404)
    return frontend_page()


@app.get("/{asset_path:path}", include_in_schema=False)
def frontend_asset(asset_path: str):
    asset = (FRONTEND_BUILD / asset_path).resolve()
    if not asset.is_relative_to(FRONTEND_BUILD.resolve()) or not asset.is_file():
        raise HTTPException(404)
    return FileResponse(asset)
