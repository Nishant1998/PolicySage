# Release verification

The results below predate removal of the unmanaged ingestion and chat-cache paths. Run the project checks again before relying on them for this version.

- [x] Canonical managed registration and worker paths are covered by bootstrap, admin upload, retry, replacement, and approval tests.
- [x] Managed dense and hybrid retrieval enforce the registry publication gate. Tests cover stale vector flags, an unavailable registry, catalogue fields, and PDF citation access.
- [x] Synthetic malformed PDFs, invalid input, object-storage registration failures, and embedding failure followed by retry are covered.
- [x] HTTP contract tests verify that unauthenticated document and job listing requests stop before the repository and that authenticated requests return the fields used by the admin UI.
- [x] In the fresh locked environment, with dummy credentials and external connections blocked, 81 tests passed and the opt-in PostgreSQL test was skipped. The standalone PostgreSQL result is recorded separately below. Ruff and `git diff --check` passed.
- [x] The real queue test passed on a temporary PostgreSQL 18.6 instance bound to loopback. It exercised the current schema, two simultaneous connections, locked-row skipping, interrupted-job recovery, and the review gate.
- [x] Both the canonical ingestion CLI and the documented managed alias returned the expected help and command list before the final CLI cleanup.
- [ ] Verify the managed-only CLI and application after removal of the unmanaged paths.
- [x] Application syntax compilation and the direct-import dependency audit passed. Botocore, LangSmith, and Pydantic are explicit dependencies. The locked package versions match the prior release archive, and a fresh offline locked install passed `uv pip check` for all 166 installed packages.
- [ ] Build the production image and exercise the documented web and worker commands against staging. Verify the existing registry and vector revision IDs agree, then check upload, publication, search, and an authorized signed PDF link.
- [x] Review the working-tree diff and map release evidence to the architecture, ingestion, API, retrieval, and dependency requirements. Remaining verification is listed below.

## Release verdict

**Blocked on container and staging verification.** The Docker Linux engine endpoint was unavailable and no `.env.staging` file was present in the checkout. The offline suite and disposable PostgreSQL check establish local behavior. Image startup and the real object-storage, vector, and signed-PDF path still require a running container engine and an isolated staging environment.

The reviewed architecture retains the existing package layout. Bootstrap and the admin upload endpoint both call `register_document`. The worker claims and recovers jobs through the PostgreSQL repository, and managed retrieval gates Qdrant results on the registry. See [architecture](architecture.md).

## Local PostgreSQL queue check

With a disposable database named `policysage_test` on a local PostgreSQL instance, set `POLICYSAGE_TEST_POSTGRES` to its connection string using `127.0.0.1` or `::1` as the host. The test creates and removes its own randomly named schema.

```powershell
uv run --frozen python -m unittest discover -s tests -p test_postgres_queue.py -v
```

## Container and staging checks

Run these checks with a staging PostgreSQL database, private bucket, and Qdrant collection. Use an approved PDF and a staging environment file with credentials for those resources. For production-mode admin checks, access the web container through an HTTPS staging proxy configured as a trusted forwarder.

```powershell
docker build -t policysage-release-check .
docker run --rm --env-file .env.staging policysage-release-check python -m app.ingestion init
docker run --rm --name policysage-check-web --env-file .env.staging -p 127.0.0.1:8080:8080 policysage-release-check
# In a separate terminal:
docker run --rm --name policysage-check-worker --env-file .env.staging policysage-release-check python -m app.ingestion worker --watch
```

1. Record the image build result and check `/api/health`. Confirm the worker acquires the staging registry lock.
2. Upload a test PDF through the admin UI with review required. Confirm it reaches `verifying` and is absent from managed search. Approve it and confirm it reaches `active`.
3. Ask a question grounded in that PDF. Record the returned revision and page. With public downloads enabled in staging, open the citation and verify the signed URL opens that revision at the cited page. With downloads disabled, confirm the public endpoint returns 404 and authenticated admin preview still works.
4. Replace the document and confirm the original remains searchable until the replacement is verified. Withdraw the logical document and confirm a new search excludes both revisions.
5. Record the staging registry and vector metadata agreement, expected statuses, and observed results in this checklist. Stop both staging containers when finished.

See the [deployment instructions](../DEPLOYMENT.md) and [managed KB guide](managed-kb.md) for configuration and upgrade order.
