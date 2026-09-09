# PolicySage architecture

The app has one FastAPI web process and a separate managed ingestion worker. Local bootstrap and the admin upload and replacement routes call the same registration function. Registration stores the original PDF under an immutable revision key and records its queued or staged revision. The worker verifies the checksum, parses the PDF, chunks and embeds it, and verifies the resulting records. The web process serves chat, admin management, and authorized document links.

| Area | Responsibility |
| --- | --- |
| `main.py` and `api/` | Web startup, HTTP contracts, authorization, and document routes |
| `ingestion/` | Catalogue and bootstrap, job loop, PDF parsing, semantic chunking, indexing, and publication |
| `db/` | PostgreSQL connection, revision queries, and existing schema initialization |
| `infrastructure/` | S3-compatible storage, embedding clients, and Qdrant operations |
| `services/` | PDF registration and withdrawal, usage limits, and audit writes |
| `rag/` | LangGraph workflow, hybrid or dense retrieval, reranking, prompts, and web search |
| `core/` | Settings, observability, budgets, privacy, HTTP body limits, and stable vector IDs |

## Publication and citations

PostgreSQL is authoritative for managed publication. Dense and BM25 queries use a per-chat snapshot of active, unwithdrawn, approved revisions and restrict Qdrant candidates by revision ID. Once all replacement vectors are verified, one PostgreSQL transaction retires the previous revision and publishes the new one. A review-required revision remains in `verifying` until approved. Withdrawal changes the registry immediately for new requests. Old vectors remain for six minutes for requests already using a snapshot, and the worker then removes them.

The `documents` table holds one row per revision. Object keys still use `documents/<document_id>/revisions/<revision_id>/<sha256>.pdf` and managed vectors still use `<revision_id>-<six-digit chunk index>`. Retries reuse these identifiers. The worker verifies previously indexed records again before publishing a resumed or approved revision. S3 registration can leave an orphan object if the process stops before the PostgreSQL commit. The service checks the registry before compensating for a failed or ambiguous registration.

Retrieval merges catalogue fields such as `effective_from` and `source_url` from PostgreSQL while keeping the vector chunk's page range. Managed hybrid search can filter by the registry checksum. Dense-only chat retains the existing `document_id` filter contract. Publisher links are used when public stored downloads are disabled. With downloads enabled, managed citations resolve to the exact stored revision and include the PDF page range. Admin preview requires authentication.

## Ingestion commands

Use `python -m app.ingestion bootstrap` to register local PDFs. Use `bootstrap --stage-only` when existing vectors need reconciliation. `index-staged` queues explicitly selected staged revisions, and `worker --watch` processes queued work.

See the [managed KB guide](managed-kb.md) for deployment order, recovery, and worker commands.
