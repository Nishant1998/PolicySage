"""Modal deployment for the PolicySage web app and queued ingestion."""
import modal

app = modal.App("policysage")
image = modal.Image.from_dockerfile("Dockerfile.modal", context_dir=".")
configuration = modal.Secret.from_name("PolicySage")


@app.function(
    image=image,
    secrets=[configuration],
    cpu=1,
    memory=2048,
    max_containers=1,
    startup_timeout=600,
    timeout=300,
    scaledown_window=120,
)
@modal.concurrent(max_inputs=20)
@modal.asgi_app()
def web():
    import os

    os.environ["APP_ENV"] = "production"
    os.environ["SEMANTIC_CACHE_PATH"] = "/app/data/semantic_cache.db"
    from app.main import app as fastapi_app

    return fastapi_app


@app.function(
    image=image,
    secrets=[configuration],
    schedule=modal.Period(minutes=5),
    cpu=1,
    memory=4096,
    max_containers=1,
    startup_timeout=600,
    timeout=86400,
)
def ingestion():
    import os

    os.environ["APP_ENV"] = "production"
    os.environ["SEMANTIC_CACHE_PATH"] = "/app/data/semantic_cache.db"
    from app.core.logging import configure_logging
    from app.core.config import get_settings
    from app.ingestion.worker import process_queued_jobs

    configure_logging(get_settings().log_level, structured=True)
    process_queued_jobs()
