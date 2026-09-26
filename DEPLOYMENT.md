# Deployment

See the [setup guide](docs/setup.md#deploy-on-render) for the Docker commands, Render settings and resource checks.

The [system diagram](docs/assets/policysage-architecture-hero.png) shows how the web server and ingestion worker share one container. When validating a new image, upload a test policy PDF and confirm the Docling conversion completes, the revision is published, and a cited answer points to the correct page. The worker may download Docling model assets on its first conversion.

## Public-demo protection

Deploy with `APP_ENV=production`, one application instance, one web worker, and a persistent volume for `USAGE_DB_PATH`. Anonymous production chat requires `KB_MANAGED=true`. Configure the PostgreSQL registry and verify the existing Qdrant collection before enabling chat. Hybrid search uses the registry to determine which revisions are published. Set `PUBLIC_CHAT_ENABLED=false` and restart to pause public chat.

The default limits are six chats per minute per IP, 30 chats per UTC day, 300 chats per UTC month, and two concurrent chats. Each chat can start up to six KB searches and, if web search is enabled, up to four outbound web attempts including retries. Keep `WEB_SEARCH_ENABLED=false` and `PUBLIC_PDF_DOWNLOADS_ENABLED=false` for the low-cost demo. Public citations can use official publisher URLs, while admins preview stored PDFs through the authenticated endpoint. If public stored downloads are enabled, link issuance is capped at three per IP per minute, 20 per day, and 100 per month. An issued URL can be reused until expiry, so issuance limits do not cap storage egress.

Before launch, test the monthly cap across two client IPs with a small temporary limit, confirm it persists across a restart, and confirm requests rejected by the limiter never reach a provider. Verify the public PDF and admin routes with an unauthenticated client. Set provider-side spending controls for the demo credentials, since request and token counters alone cannot guarantee a fixed invoice.

### Token budgets

`MAX_REQUEST_TOKENS=72000` bounds accounted LLM input plus output across one question and its research steps. `MAX_PROMPT_TOKENS=14000` caps estimated input per model call, including a 512-token safety buffer; `MAX_ANSWER_TOKENS=1500` reserves and caps output separately. Choose a prompt-plus-output allowance within the configured model's context window. `MAX_QUESTION_TOKENS=1024` bounds the current and resolved question individually. `MAX_HISTORY_TOKENS=2000` removes oldest complete exchanges when history grows too large. The browser still retains up to four exchanges; the server decides how much to send to the model.

Before each model call, reserve estimated prompt tokens (instructions, question, history, evidence, response schema and framing allowance) plus maximum output tokens. Reconcile with reported usage after the call; missing usage or call failure retains the conservative reservation. Research calls leave one full prompt/output allowance for the final response. Low remaining allowance skips decomposition or another rewrite; if a required call cannot fit, return a brief limitation without another model call.

Formatted evidence has an 8,000-token allowance. Prompts include compact identifying metadata; full source metadata remains available for citations. Grading and generation remove whole lowest-ranked passages until the complete prompt fits the per-call and remaining request allowances. An answer whose evidence was reduced carries a partial-context limitation.

Prompt counts use the model's tiktoken encoding when known, otherwise `cl100k_base`. These are preflight estimates, not an exact billing cap. Provider framing or reasoning-token accounting can differ; usage reported above a reservation reduces the remaining allowance and stops later calls when necessary. Embedding and web-search costs are outside this LLM token budget. Set provider-side spending limits as well.

Keep one instance and one worker with persistent `/app/data` for the existing per-client, daily and concurrency limits. Rejections return 429 or 503 with `Retry-After`. The UI displays these messages. Request-size checks cover the declared length and received body bytes; uploads remain limited to 20 MB per file. Keep a request-size limit at the hosting proxy too.

Terminate HTTPS at your hosting proxy. Configure Uvicorn's `FORWARDED_ALLOW_IPS` with only that proxy's verified IP addresses or networks so rate limits see the real client. Never set it to `*` on a publicly reachable backend. Do not add application code that blindly trusts `X-Forwarded-For`; the limiter uses the ASGI client address. The correct trusted-proxy list depends on the hosting provider. Test two clients and a forged forwarding header before launch.

Before either search provider is called, common email, Indian phone, Aadhaar-style, labelled private-ID and API-key patterns are removed from the web query. Only redaction categories and counts are logged. This is best-effort: it does not detect every name or private phrase, and does not anonymize the conversation sent to OpenAI. The public-only prompt rules and official-domain allowlist remain additional controls. Admin uploads belong to a shared public knowledge base.

Response headers restrict scripts and connections to this site, prevent framing, disable MIME sniffing and disable HTTP response caching. Retrieved text and chat output continue to render as text, not executable HTML. Prompt-injection instructions in questions or sources must not override system rules; deterministic tests do not prove model resistance. Run the manual security cases in `tests/SECURITY_CASES.md` with the selected model before launch.

## Logging and tracing

Question traces default to metadata. Set `LANGSMITH_DEBUG_CONTENT=true` in a controlled environment to export bounded question, query, prompt, and answer text. Redaction covers configured secrets and known sensitive patterns. Use synthetic or approved content because pattern redaction cannot recognize every name or private detail. Set `LANGSMITH_TRACE_SAMPLE_RATE` between 0 and 1 to control trace volume.

Trace scores are labeled by retrieval or ranking method. Citation verification checks the returned IDs against evidence sent to the model. Document accessibility and semantic support are reported as unchecked unless separately evaluated.

LangSmith exports admitted chats, authenticated admin actions that change the KB or preview a PDF, and managed ingestion jobs. Health checks, static assets, rejected chat requests, and admin polling stay in local logs. Match a chat's `X-Request-ID` to the LangSmith root run ID or local JSON logs. Worker runs include a hashed revision reference. Traces report durations, counts, error types, and LLM usage. Cost estimates cover LLM tokens where rates and usage are known.

JSON logs go to standard output, so the hosting platform can collect them. Each HTTP request returns `X-Request-ID`; search that ID in logs to inspect its stages, elapsed times, HTTP status and model token totals. Logs do not intentionally include questions, answers, chat history, credentials or source excerpts. Error events include exception types rather than exception messages.

For optional metadata-only LangSmith traces, register the existing agent in LangSmith, then set `LANGSMITH_ENABLED=true`, `LANGSMITH_API_KEY`, `LANGSMITH_AGENT_ID=policysage` and `LANGSMITH_AGENT_ENVIRONMENT=local`. Use `production` for the deployed application. Select `LANGSMITH_ENDPOINT` for your account region. Remove legacy `LANGSMITH_PROJECT`, `LANGCHAIN_PROJECT` and `LANGCHAIN_SESSION` settings. The app uses its own `LANGSMITH_ENABLED` switch; `LANGSMITH_TRACING` is not required. Automatic prompt/response capture is disabled within HTTP requests; custom request and graph-node spans export only operational metadata. A tracing failure must not discard an answer. No LangSmith connection is required for local JSON logs.

To estimate LLM cost, configure `LLM_INPUT_USD_PER_MILLION`, `LLM_OUTPUT_USD_PER_MILLION` and, when applicable, `LLM_CACHED_INPUT_USD_PER_MILLION` using the current prices for `OPENAI_MODEL`. Omit unset rates rather than using empty values. Unknown pricing or missing provider usage produces `null` cost, not a false zero. Estimates cover reported chat-model tokens only; embeddings, web search and hosting charges are separate. Failed calls may have unreported provider charges.

## Run the web application and worker

Configure the same database, object store, embedding model and Qdrant collection for both processes. Use the [managed KB guide](docs/managed-kb.md) to initialize the registry, register new seed PDFs, or stage an existing corpus for reconciliation.

```powershell
docker build -t policysage .
docker run --name policysage-web --env-file .env -p 8080:8080 -v policysage-data:/app/data policysage
docker run --name policysage-worker --restart unless-stopped --env-file .env -v policysage-worker-data:/app/data policysage python -m app.ingestion worker --watch
```

Web startup initializes usage and audit storage and loads the reranker. Allow time and memory for the initial reranker load. Persist web data for request counters and worker data for semantic embedding cache reuse. Keep one worker per registry. The watch process picks up uploads and newly queued seeds and recovers interrupted jobs after a restart.



## Checks

The [PostgreSQL claim test](tests/test_postgres_queue.py) runs when `POLICYSAGE_TEST_POSTGRES` points to a disposable local database named `policysage_test`.

Run `uv run --frozen python -m unittest discover -s tests -v`. Tests replace external services and tokenizer loading with fakes. Live provider and Docker checks are separate.

Verify a failed initial search can use fresh retry evidence; duplicate ingestion adds no extra records; a replacement returns its new clause; an audit failure still returns the answer; request limits reject excess traffic; citations show source text with and without a public URL.

The browser sends up to four previous question-and-answer pairs with each request. The router resolves follow-up questions, and response generation also receives that history. New chat or a page refresh clears the browser history; conversations are not stored on the server. Prior answers provide context, not verified insurance evidence.
