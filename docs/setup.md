# Set up PolicySage

## Prerequisites

- Python 3.11 or later and [uv](https://docs.astral.sh/uv/). Use Python 3.11 for the repository's baseline environment.
- Node.js and Yarn Classic 1.22.22, as declared in [frontend/package.json](../frontend/package.json). Node 22 is the repository's build baseline.
- An OpenAI account with access to the configured chat and embedding models.
- A PostgreSQL database with a direct connection that supports advisory locks and an account allowed to initialize the schema.
- A Qdrant collection configured for dense and scored text search, and a private S3-compatible bucket. The app and worker must use the same registry, collection, bucket and embedding model.
- A writable `data/` directory and access to download reranker and PDF-processing model assets on first use if they are absent locally.

## Install and configure

Run these commands from the repository root in PowerShell. Fill in `.env` before running initialization. If you already have an environment file, keep it and compare it with the example.

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
uv sync --locked --python 3.11
yarn --cwd frontend install --frozen-lockfile
yarn --cwd frontend build
```

| Area | Settings |
| --- | --- |
| Local app | Set `APP_ENV=development` for localhost HTTP admin access. The example sets `production`, while the code defaults to `development`. `PUBLIC_CHAT_ENABLED=true` allows chat when the managed KB is enabled. |
| OpenAI | Set `OPENAI_API_KEY` and select an accessible `OPENAI_MODEL`. The default `EMBEDDING_MODEL` is `text-embedding-3-small`. Use the model that matches the indexed vectors. |
| Qdrant | Set `QDRANT_URL`, `QDRANT_COLLECTION` (default `insurance-kb`) and `QDRANT_API_KEY` if your instance requires it. |
| PostgreSQL | Set `KB_MANAGED=true` and `KB_DATABASE_URL` to the direct database connection. Use TLS for a hosted database. `KB_DIR` defaults to `data/kb` for seed PDFs. |
| Object storage | Set `KB_S3_ENDPOINT`, `KB_S3_REGION`, `KB_S3_BUCKET`, `KB_S3_ACCESS_KEY_ID` and `KB_S3_SECRET_ACCESS_KEY`. Grant access to the private bucket the app and worker use. |
| Admin and citations | Set `KB_ADMIN_USERNAME` and a unique `KB_ADMIN_PASSWORD`. A nonempty `ADMIN_API_KEY` takes precedence as the password. `PUBLIC_PDF_DOWNLOADS_ENABLED` defaults to false. |
| Web research | Set `WEB_SEARCH_ENABLED=false` to use policy evidence only. If enabled, set `WEB_SEARCH_PROVIDER=tavily` or `brave` and the corresponding `TAVILY_API_KEY` or `BRAVE_API_KEY`. The example enables web search. |
| Tracing | Optional. Set `LANGSMITH_ENABLED=true` with `LANGSMITH_API_KEY`, an existing `LANGSMITH_AGENT_ID`, and its `LANGSMITH_AGENT_ENVIRONMENT`. Set `LANGSMITH_ENDPOINT` if needed for the workspace. Keep `LANGSMITH_DEBUG_CONTENT=false` for metadata-first traces. |

Keep `.env` private. Run both processes from the repository root so the relative paths in the example resolve consistently. The code also accepts optional LangSmith usage pricing settings that the example does not list. They are unnecessary for startup. [Settings source](../app/core/config.py) · [Environment template](../.env.example)

## Initialize the knowledge base

1. Create the private bucket and a Qdrant collection. For the default embedding model, the collection needs an unnamed 1,536-dimensional dense vector with cosine distance. Create a scored full-text payload index on `text` for BM25 queries and keyword payload indexes on `document_revision` and `embedding_model`. Use a Qdrant version that supports scored text queries. [Query implementation](../app/infrastructure/qdrant_store.py)
2. Initialize PostgreSQL from the repository root.

```powershell
uv run --locked python -m app.ingestion init
```

Initialization creates the current schema. An incompatible older `documents` table requires a separately planned migration. Back up and inspect it before making schema changes.

3. To register local PDFs in bulk, place them under `KB_DIR` and run bootstrap. This step is optional if you plan to upload PDFs in the admin UI.

```powershell
uv run --locked python -m app.ingestion bootstrap
```

If `metadata.csv` exists in `KB_DIR`, `file_path` gives the relative PDF path and `include_in_index=true` selects the row. An optional checksum is validated. Bootstrap can restore a missing object from the local PDF, queue a staged match or register a replacement when active vectors are incomplete. Review the reported status before assuming nothing changed. For deliberate staging and reconciliation, use `bootstrap --stage-only` followed by `index-staged --source "category/insurer/policy.pdf"` only after checking the selected revision. Stop the watch worker before running `index-staged`. [Bootstrap](../app/ingestion/bootstrap.py) · [CLI](../app/ingestion/cli.py)

## Run the web app and worker

In one terminal, serve the frontend build and API.

```powershell
uv run --locked python -m uvicorn app.main:app --no-access-log --host 127.0.0.1 --port 8000
```

In another terminal at the repository root, start the worker.

```powershell
uv run --locked python -m app.ingestion worker --watch
```

Use `worker` without `--watch` to drain available jobs and exit. The worker handles parsing, embedding and indexing separately from the HTTP process.

Open `http://127.0.0.1:8000/` for chat, `/about` for the project overview, or `/admin` for document management. Try “How do cashless and reimbursement claims differ?” once suitable policy PDFs are published. Open a citation to inspect the excerpt and page details when available. Source access depends on the link and public download settings.

## Manage documents

| Action | Expected result |
| --- | --- |
| Upload PDF | Registers and queues a PDF up to 20 MB. The worker uses Docling to convert readable, unlocked PDFs of up to 400 pages. |
| Replace PDF | Keeps the document identity and creates a revision. The old active revision stays searchable until the replacement is published. |
| Require review | The worker indexes the revision and waits for approval. Preview it in the admin UI, approve it, then let the worker complete publication. |
| Retry | Retry a failed processing job from the admin activity list. Register the PDF again if the original upload failed. |
| Withdraw | Excludes the document from new searches and blocks new stored-PDF links. The worker cleans up vectors after a grace period. Previously signed URLs expire after 60 seconds. |

To smoke-test a disposable knowledge base, upload a small PDF, wait for publication, ask a question answered by the PDF, and inspect the citation. Repeat with a replacement that requires approval. Check that the old revision remains searchable before publication and that withdrawal excludes the document from new chats. [Publication behavior](architecture.md#document-ingestion-and-lifecycle)

## Run with Docker Desktop

Start Docker Desktop in Linux container mode and run these commands from the repository root in PowerShell. The build uses the Yarn and uv lockfiles, CPU-only PyTorch for Linux, and no runtime secrets. Docker downloads the base images and dependencies on the first build.

```powershell
docker version
docker build -t policysage:local .
```

For a local startup check, use a placeholder key and disable provider-backed requests. The first start downloads the public MiniLM reranker from Hugging Face.

```powershell
docker run --rm --name policysage-smoke -p 127.0.0.1:8080:8080 -e APP_ENV=production -e OPENAI_API_KEY=local-smoke-placeholder -e KB_MANAGED=false -e PUBLIC_CHAT_ENABLED=false -e WEB_SEARCH_ENABLED=false policysage:local
```

Open `http://localhost:8080/` and `http://localhost:8080/about`. In a second terminal, run `Invoke-RestMethod http://localhost:8080/api/health`. A healthy response confirms the web process finished startup and can serve HTTP. Verify chat, retrieval, and PDF access separately with a configured test knowledge base. Press Ctrl+C in the first terminal or run `docker stop policysage-smoke` before reusing port 8080.

To use your configured services, mount the existing `.env` read-only so the app parses quoted values the same way it does outside Docker. The named volume preserves SQLite state between runs. The `APP_ENV=development` override allows admin access over local HTTP. Keep the listener on loopback. Set file paths in `.env` relative to `/app` or use absolute Linux paths under `/app/data`.

```powershell
docker run --rm --name policysage -p 127.0.0.1:8080:8080 --mount "type=bind,source=$($PWD.Path)\.env,target=/app/.env,readonly" --mount "type=volume,source=policysage-data,target=/app/data" -e APP_ENV=development policysage:local
```

The container automatically starts the web server and ingestion worker. Uploads stay queued while the container is offline. Published documents remain available for retrieval. The worker uses the shared PostgreSQL registry to claim jobs and recover interrupted work, then uses Qdrant and object storage to verify, publish, or clean up revisions. Its first PDF conversion can download Docling model assets.

## Deploy on Render

1. In Render, create one **Web Service** linked to the GitHub branch containing the Docker changes. Select **Docker**, leave the root at the repository root, use `./Dockerfile` and context `.`, and leave the Docker command blank. Select a plan only after checking the resource and storage requirements below. Choose manual deploys if you want to control when changes go live. [Docker on Render](https://render.com/docs/docker)
2. Set the health-check path to `/api/health` and keep one instance. Uvicorn listens on `0.0.0.0` and uses Render's injected `PORT`. Local Docker defaults to 8080. [Web services](https://render.com/docs/web-services) · [Health checks](https://render.com/docs/health-checks)
3. Enter settings in Render's **Environment** tab using the settings table above. Use `APP_ENV=production`, `LOG_LEVEL=INFO`, `KB_MANAGED=true`, and initially `PUBLIC_CHAT_ENABLED=false`, `WEB_SEARCH_ENABLED=false`, and `PUBLIC_PDF_DOWNLOADS_ENABLED=false`. Enter the OpenAI key and model names, direct TLS PostgreSQL URL, Qdrant endpoint and collection settings, private S3 credentials, and admin credentials as runtime values. When enabling tracing, use `LANGSMITH_AGENT_ENVIRONMENT=production`. [Environment and secrets](https://render.com/docs/configure-environment-variables)
4. Before opening public chat, attach durable storage at `/app/data` and verify it is writable by container UID 10001. Keep the usage and audit database paths on that disk. Configure `FORWARDED_ALLOW_IPS` only for verified proxy addresses or networks. Confirm Render supplies trusted HTTPS and client IP metadata by testing admin login, distinct client rate limits, and a forged forwarding header. Keep the demo restricted if proxy trust cannot be established. [Persistent disks](https://render.com/docs/disks) · [Public-demo protection](../DEPLOYMENT.md#public-demo-protection)
5. Deploy manually and check `/`, `/about`, and `/api/health`. In a disposable environment verify unauthenticated admin access is rejected, provider-backed chat returns a citation, and the usage counter survives a restart. Upload a test revision and verify the worker processes it.

Render Free has 512 MB RAM and 0.1 CPU. It spins down after 15 idle minutes and cannot attach a persistent disk. Losing `usage.db` resets IP, daily, monthly and PDF issuance counters. Losing `audit.db` discards the local audit trail. Losing `semantic_cache.db` means recomputing cached work. The external PostgreSQL registry, Qdrant passages and private PDFs persist according to their own providers' settings. Full public chat requires durable quota enforcement even if the process fits within the memory allowance. [Render compute plans](https://render.com/docs/compute-plans) · [Free plan limits](https://render.com/docs/free)

The Linux AMD64 image measured 1.92 GB locally. With 2 GiB of RAM and one CPU, the web smoke test passed and 20 synthetic passages reranked to 10 results with a container peak of about 599 MiB. The same inference workload was killed for exceeding a hard 512 MiB limit, even with one full CPU. The separate 512 MiB and 0.1 CPU startup trial was still starting after 132 seconds with cached model files. Use the 2 GB, one-CPU paid plan as the first candidate for a full deployment test with durable storage and representative chat traffic. These measurements come from Docker Desktop. Render startup, real provider latency, and concurrent-chat headroom still need verification.

The web process and worker share the same Render service and its CPU and memory. The previous 2 GiB web-only measurement does not establish sufficient memory for simultaneous PDF processing. Test representative PDFs and chat traffic before selecting a plan. Web compute, persistent disks, bandwidth, and external OpenAI, search, database, Qdrant, object storage, and tracing usage can incur charges. [Render pricing](https://render.com/pricing)

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| PostgreSQL connection or initialization fails | Confirm the direct connection string, TLS, schema permissions and schema compatibility. |
| Qdrant returns an error or no matches | Check the collection, dense dimension, scored text and keyword indexes, embedding model, and active revisions in PostgreSQL. |
| Document stays queued or under review | Check the container logs for worker errors, verify the shared service configuration, and approve the revision if it is waiting for review. |
| Local admin login is rejected | Use `APP_ENV=development` on localhost HTTP, and confirm the username and password precedence. |
| Frontend is missing or stale | Run `yarn --cwd frontend build` from the root and restart FastAPI. |
| Docker cannot connect to its Linux engine | Start Docker Desktop, wait for the engine, and run `docker version` in your regular PowerShell terminal. |
| Docker reports port 8080 is in use | Stop the old container or change the host side of the port mapping to `127.0.0.1:8081:8080` and open port 8081. |
| The container exits before health checks pass | Read the foreground output. Omit `--rm` during troubleshooting if you want to inspect the stopped container with `docker logs <container>`. Check runtime settings, write access to `/app/data`, and access to Hugging Face when the model cache is empty. Exit code 137 can indicate a memory limit. |
| A PDF link is missing or unavailable | Check whether the revision is public and eligible for PDF access, whether public downloads are enabled, and whether a publisher URL is available. Try authorized admin preview for the stored copy. |
| Web research is unavailable | Check the enable flag, provider selection and matching key. Research also depends on the request and evidence budgets. |

Chat and embedding calls can incur charges. Web search, tracing, hosted PostgreSQL, Qdrant and object storage depend on the provider and plan. Use a small PDF for the first indexing run. Request and token limits bound application work, while provider billing depends on actual usage.
