from fastapi import APIRouter

from app.core.config import get_settings


router = APIRouter(prefix="/api")


@router.get("/health")
def health():
    return {"status": "ok", "service": get_settings().app_name}
