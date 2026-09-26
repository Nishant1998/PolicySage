# Setup and deployment

PolicySage is deployed on Modal at [policysage.nishantvalvi.me](https://policysage.nishantvalvi.me/). The following commands use PowerShell; run them from the repository root.

## Local setup

The project uses Python 3.11, uv, Node.js 22, and Yarn 1.22.22. Install the backend from `pyproject.toml` and `uv.lock` and the frontend from `frontend/package.json` and `frontend/yarn.lock`:

```powershell
git clone https://github.com/Nishant1998/PolicySage.git
cd PolicySage
Copy-Item .env.example .env
uv sync --locked --python 3.11
yarn --cwd frontend install --frozen-lockfile
yarn --cwd frontend build
```

Configure `.env` before initializing the knowledge base. Use `APP_ENV=development` for local HTTP admin access and set `PUBLIC_CHAT_ENABLED=true` to enable chat. The required services are:

| Service | Settings |
| --- | --- |
| OpenAI | `OPENAI_API_KEY`, `OPENAI_MODEL`, `EMBEDDING_MODEL` |
| PostgreSQL | `KB_MANAGED=true`, `KB_DATABASE_URL` using a direct connection with TLS for hosted databases |
| Qdrant | `QDRANT_URL`, `QDRANT_COLLECTION`, and `QDRANT_API_KEY` if required |
| S3-compatible storage | `KB_S3_ENDPOINT`, `KB_S3_REGION`, `KB_S3_BUCKET`, `KB_S3_ACCESS_KEY_ID`, `KB_S3_SECRET_ACCESS_KEY` |
| Admin | `KB_ADMIN_USERNAME` and `KB_ADMIN_PASSWORD`, or `ADMIN_API_KEY` as the password; a nonempty `ADMIN_API_KEY` takes precedence |

Set `WEB_SEARCH_ENABLED=false` to disable web research. To enable it, set `WEB_SEARCH_PROVIDER` to `tavily` or `brave` and configure that provider's key. LangSmith is optional. See [.env.example](../.env.example) for the remaining limits and settings.

For the default `text-embedding-3-small` model, create a Qdrant collection with an unnamed 1,536-dimensional cosine vector, a scored full-text payload index on `text`, and keyword indexes on `document_revision` and `embedding_model`. Use the same embedding model for ingestion and retrieval. Configure a private bucket and a PostgreSQL account allowed to initialize the schema, then run:

```powershell
uv run --locked python -m app.ingestion init
```

Start the backend and the built frontend:

```powershell
uv run --locked python -m uvicorn app.main:app --no-access-log --host 127.0.0.1 --port 8000
```

Start the ingestion worker in a second terminal:

```powershell
uv run --locked python -m app.ingestion worker --watch
```

Open `http://127.0.0.1:8000/` or `/admin`. Upload a PDF and wait for publication before querying it. To seed PDFs under `KB_DIR` instead, run `uv run --locked python -m app.ingestion bootstrap`; `--stage-only` registers them without queuing indexing. See the [architecture guide](architecture.md#document-ingestion-and-lifecycle) for revision and publication behavior.

## Docker

Build and start one container for the frontend, API, and worker. The example mounts your configured `.env` and a persistent volume for the ingestion cache:

```powershell
docker build -t policysage:local .
docker run --name policysage -p 127.0.0.1:8080:8080 --mount "type=bind,source=$($PWD.Path)\.env,target=/app/.env,readonly" --mount "type=volume,source=policysage-data,target=/app/data" -e APP_ENV=development policysage:local
```

Open `http://localhost:8080/`. PostgreSQL, Qdrant, and S3-compatible storage remain external services and must be reachable from Docker. Check the logs for both `web` and `worker`:

```powershell
docker logs policysage
docker stop policysage
docker start policysage
```

Alternatively, start and stop the existing `policysage` container from Docker Desktop's **Containers** page. Rebuild the image and create a new container after code changes. The first model or PDF conversion can download model assets.

## Modal deployment

The live application is deployed at [policysage.nishantvalvi.me](https://policysage.nishantvalvi.me/). `modal_app.py` defines an ASGI web function and a separate scheduled ingestion function built from `Dockerfile.modal`. The worker checks the queue every five minutes, holds a PostgreSQL advisory lock while draining jobs, and recovers interrupted jobs on a later run. The configured limits are 2 GiB for the web function, 4 GiB for ingestion, and up to 24 hours per ingestion run.

To deploy to your own Modal workspace:

1. Configure and initialize PostgreSQL, Qdrant, and object storage as above. Use the direct PostgreSQL URL because the worker and request slots use session-level advisory locks.
2. Install and authenticate the Modal CLI:

   ```powershell
   python -m pip install modal
   modal setup
   ```

3. Create a Modal Secret named `PolicySage` containing the required app settings from `.env`. Use `APP_ENV=production`, `KB_MANAGED=true`, and your intended values for `PUBLIC_CHAT_ENABLED` and `WEB_SEARCH_ENABLED`. Keep credentials out of Git.
4. Deploy and inspect the app:

   ```powershell
   modal deploy modal_app.py
   modal app logs policysage
   ```

Open the URL printed by Modal and check `/api/health`, admin access, a PDF upload, and a cited answer. The worker may take up to five minutes to begin, plus startup and processing time. Quota and audit tables are created in PostgreSQL at web startup. Existing SQLite quota and audit data are not migrated automatically. External model, storage, and compute usage can incur charges.

### Update a deployment

A commit or GitHub push does not automatically deploy this app. Run `modal deploy modal_app.py` from the repository root to deploy the current working tree. After changing only the Modal secret, run `modal app rollover policysage` so new containers receive the updated values. Use `modal app logs policysage` to inspect the result. If a running ingestion job is interrupted during deployment, the next scheduled worker can recover it.

To update GitHub as well, commit and push the intended changes on your branch. GitHub Actions can be configured separately for automatic deployment on push.

## Tests

```powershell
uv run --locked python -m unittest discover -s tests -v
```

PostgreSQL integration tests additionally require `POLICYSAGE_TEST_POSTGRES` to point to a disposable local database named `policysage_test`. Live provider and ingestion checks are separate.
