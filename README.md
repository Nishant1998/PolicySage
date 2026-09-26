# PolicySage — Agentic RAG for Indian Insurance

PolicySage helps users explore Indian insurance policies through a conversational assistant. It retrieves policy passages, assesses whether they answer the question, and provides references so users can inspect the original wording. A managed document workflow supports PDF upload, review, publication, replacement, and withdrawal.

**[Try the live demo](https://policysage.nishantvalvi.me/)** · [Architecture](docs/architecture.md) · [Full setup and deployment guide](docs/setup.md)

[![PolicySage architecture, including the agent workflow, PDF ingestion, storage and deployment options](docs/assets/policysage-architecture-hero.png)](docs/assets/policysage-architecture-hero.png)

## Agentic RAG features

- **Adaptive research with LangGraph.** Routes questions using conversation context, breaks down complex questions when needed, and selects a research path based on the evidence.
- **Hybrid policy retrieval.** Combines Qdrant dense and BM25 search with reciprocal rank fusion and a MiniLM cross-encoder to rerank candidate passages.
- **Evidence grading and bounded retries.** Assesses policy evidence before answering. When permitted and needed, it searches selected official websites, grades the combined evidence, and may rewrite the query within request limits.
- **Answers with inspectable references.** Shows supporting sources, excerpts and page numbers when available. Citation IDs are checked against the evidence supplied to the model.
- **Clarification and limitations.** Can ask for missing details or say when evidence is insufficient. The chat interface streams research stages as they occur.
- **Document lifecycle management.** Admins can upload or replace PDFs, review and approve revisions, retry failed jobs, and withdraw documents. Only eligible published revisions are used for new searches.
- **Operational controls.** PostgreSQL-backed quotas and concurrency locks, request and token budgets, structured logs, and optional metadata-oriented LangSmith tracing help manage a public demo.

The live demo uses Modal. Web search is optional and its availability depends on deployment settings. A useful first question, once the relevant policies are published, is: “How do cashless and reimbursement claims differ?”

## How it works

1. A React interface sends a question to FastAPI. LangGraph routes the request and may split it into smaller searches.
2. Dense and BM25 retrieval search eligible policy revisions. Fusion and reranking prepare passages for evidence grading.
3. If needed and enabled, the workflow researches selected official websites. It then generates an answer with validated citation IDs, asks for clarification, or explains the evidence gap.
4. Admin uploads are registered in PostgreSQL and object storage. A separate ingestion worker uses Docling, semantic chunking, and embeddings to index and verify the revision in Qdrant before publication.

## Technology

| Area | Tools |
| --- | --- |
| Interface and API | React, Tailwind CSS, FastAPI, streamed chat events |
| Agent and models | LangGraph, OpenAI chat models and embeddings |
| Retrieval | Qdrant dense and BM25 search, reciprocal rank fusion, MiniLM cross-encoder |
| Ingestion and storage | Docling, PostgreSQL, Qdrant, S3-compatible object storage |
| Deployment and operations | Modal, Docker, optional Tavily or Brave search, optional LangSmith |

## Quick start — local machine

The project uses Python 3.11, [uv](https://docs.astral.sh/uv/), Node.js 22, and Yarn 1.22.22. Configure OpenAI, PostgreSQL, Qdrant, and S3-compatible storage as described in the [setup guide](docs/setup.md).

```powershell
git clone https://github.com/Nishant1998/PolicySage.git
cd PolicySage
Copy-Item .env.example .env
# Edit .env with your service credentials and set APP_ENV=development.
uv sync --locked --python 3.11
yarn --cwd frontend install --frozen-lockfile
yarn --cwd frontend build
uv run --locked python -m app.ingestion init
uv run --locked python -m uvicorn app.main:app --no-access-log --host 127.0.0.1 --port 8000
```

In a second terminal at the repository root, start the ingestion worker:

```powershell
uv run --locked python -m app.ingestion worker --watch
```

Open [localhost:8000](http://127.0.0.1:8000/) for chat and [localhost:8000/admin](http://127.0.0.1:8000/admin) to upload a PDF. For a first run, wait until the document is published before asking a question about it.

See the [setup guide](docs/setup.md) for Docker commands and Modal deployment and updates. Docker runs the frontend, API, and worker in one container. Modal runs the web app and scheduled ingestion function separately.

## Evaluation and limitations

The [software tests](tests/) cover selected behaviors including routing, citation validation, access controls, quota handling, and document publication and recovery. Retrieval relevance, answer correctness, and whether a citation supports a particular claim need separate evaluation.

Generated answers can be wrong or incomplete. Policy terms depend on the product and revision, so verify important details against the applicable original policy.
