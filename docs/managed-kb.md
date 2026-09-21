# Managed knowledge base

## Setup

Use `KB_MANAGED=true` and the same `QDRANT_COLLECTION` for the app and worker. When upgrading, keep the existing collection, PostgreSQL database, bucket, and embedding model.

- `KB_DATABASE_URL` is the direct Postgres connection string with TLS. The worker uses a session advisory lock, so use the direct endpoint for both commands.
- `KB_S3_ENDPOINT`, `KB_S3_REGION`, `KB_S3_BUCKET`, `KB_S3_ACCESS_KEY_ID`, and `KB_S3_SECRET_ACCESS_KEY` identify a private S3-compatible bucket. Give the app and worker access only to the bucket they need.
- Sign in with `KB_ADMIN_USERNAME` (defaults to `admin`). The app uses `ADMIN_API_KEY` as the password, or `KB_ADMIN_PASSWORD` when the admin API key is empty. Use a long, unique ASCII value. In production, serve the app over HTTPS and configure Uvicorn to trust forwarded headers only from your proxy.
- The worker uses the existing OpenAI embedding configuration and Qdrant credentials. Embedding calls can incur charges.

```powershell
cd D:\00-INBOX\PolicySage
.\.venv\Scripts\Activate.ps1
uv sync --locked
python -m app.ingestion init
```

For an upgrade, stop the previous app and worker before running `init`. It renames `document_revisions` to `documents` in place. If you are upgrading directly from the three-table registry, it copies the registry into `documents` and retains the old tables for recovery. Revision IDs, object keys, and vector IDs are preserved.

New Qdrant chunks use one metadata allowlist: `document_id`, `document_revision`, `is_active`, `insurer`, `category`, `product_name`, `document_type`, `uin`, `document_title`, `source_url`, `chunk_index`, `page_start`, `page_end`, `start_index`, `end_index`, `embedding_model`, `token_count`, and `text`. Optional catalogue fields and page numbers for non-PDF files are omitted when unavailable. The offsets refer to the extracted text. Postgres retains document-level provenance and the embedding model for each revision.



## Bootstrap and worker

Run these commands against a new or reconciled managed knowledge base.

```powershell
python -m app.ingestion bootstrap
python -m app.ingestion worker
```

Bootstrap initializes the registry, scans `KB_DIR` for PDFs, honors included rows in `metadata.csv`, checks listed checksums, stores originals in the private bucket, and queues new revisions. A separate worker indexes the queued revisions. Use `worker --watch` to leave the worker running.

A rerun matches the PDF by source path and SHA-256. An unchanged revision keeps its existing status, so check the admin job list for queued, staged, failed, or review-required revisions. A failed revision can be retried in the admin panel. The worker uses stable revision-scoped vector IDs, skips matching chunks, and verifies all expected vectors before publication.

When moving an existing Qdrant corpus into the managed registry, use explicit staging until you have reconciled the registry and vector records.

```powershell
python -m app.ingestion bootstrap --stage-only
python -m app.ingestion index-staged --source "category/insurer/policy.pdf"
```

Repeat `--source` to queue multiple staged PDFs that you confirmed are missing from Qdrant. `index-staged` runs the worker after queueing. Stop an existing watch worker before running this command.

## Admin uploads

Start the site in one terminal and run the worker in another using the same environment.

```powershell
python -m uvicorn app.main:app --no-access-log --host 127.0.0.1 --port 8000
```

```powershell
python -m app.ingestion worker --watch
```

Open `/admin`, sign in, and queue a PDF. Use **Replace PDF** on an existing document to preserve its identity. The old version remains searchable until the replacement is verified and published. The site can serve chat with the worker offline. To process queued work on demand, run `worker` without `--watch`.

Select **Require review before publishing** to index a PDF without making it searchable. Use **Preview PDF** and **Approve publication** in the admin activity list. The worker publishes the approved revision without re-embedding it.

**Withdraw** hides a document from new chat requests and blocks new PDF links. The worker removes its vectors after a six-minute grace period for in-flight chats. Already issued download URLs expire after 60 seconds. The private originals and Postgres history are retained. Updates preserve historical citation links while the document remains public. Publish only PDFs you intend visitors to read. `PUBLIC_PDF_DOWNLOADS_ENABLED` controls the public citation endpoint and defaults to false. When it is disabled, citations use the supplied publisher URL if available, and still show source excerpts and page ranges. Authorized admins can preview stored PDFs regardless of the public setting.

## First smoke test

1. Initialize the registry. Open chat and confirm it handles a registry with no active documents.
2. Confirm an invalid admin login is rejected. Sign in and upload one small PDF. Verify it becomes searchable only after indexing and open a cited page.
3. Replace the PDF and verify the old one is searchable during indexing. Confirm the new answer cites the new revision and the earlier link still opens the previous PDF.
4. Force a replacement failure and verify the old revision stays searchable. Correct the failure and retry the job.
5. Withdraw the document. Confirm a fresh chat cannot retrieve it, the citation URL is unavailable, and vector cleanup finishes with the worker running.
6. Run bootstrap twice with the same PDFs. Confirm the worker indexes the new revisions once and that the second bootstrap reports them as unchanged.

Docling extracts text, tables, and OCR-readable material. Inspect a representative scanned page and dense table before bulk import. Image-only charts may still require a separate review. Query embeddings are cached in memory for five minutes, with up to 128 entries. Ingestion reuses its local cache for semantic chunking embeddings. Managed chat searches again for each answer so withdrawals and replacements take effect across app and worker processes.

Configure QDRANT_URL, QDRANT_API_KEY, and QDRANT_COLLECTION. The collection needs a 1536-dimensional cosine vector for text-embedding-3-small, a scored full-text payload index on text, and keyword payload indexes on document_revision and embedding_model for filtered queries.
