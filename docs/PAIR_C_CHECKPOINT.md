# Pair C Checkpoint — Phases 5 + 6 Complete

## Phase 5: AI Analysis Pipeline ✅

- **app/ai/client.py** — `call_claude()` with usage_events logging; `estimate_cost_usd()` exported.
- **app/ai/prompts.py** — Extraction, sentiment, commitment prompts (JSON).
- **app/ai/embeddings.py** — OpenAI `text-embedding-3-small` (1536 dim), logs to usage_events.
- **app/ai/analysis_service.py** — `analyze_message(uow, message_id)`: extract → sentiment → commitments → embedding; update message; create Commitment rows + `CommitmentCreated` events.
- **app/workers/analysis_tasks.py** — `analyze_message` Celery task; `EventBus.subscribe(MessageIngested, _on_message_ingested)`.
- **app/main.py** — Imports `app.workers.analysis_tasks` so API process registers the handler.

## Phase 6: Query Engine ✅

- **app/repositories/message_repository.py** — `hybrid_search(user_id, embedding, person_id=..., from_date=..., to_date=..., has_commitment=..., limit=...)`: pgvector cosine + structured filters.
- **app/ai/client.py** — `stream_claude()` for SSE; optional `use_system_cache=True` (persistent cache, 5 min TTL) for system prompt.
- **app/ai/query_engine.py** — `build_user_context()` (top 20 people, open commitments count, recent activity); `parse_intent()` → search/draft/summarize/ask; `hybrid_search_messages()`; `run_query()` (model: Haiku for search, Sonnet for draft/summarize/ask).
- **app/api/queries.py** — `POST /queries`: create query row → run_query → stream via SSE (`event: chunk`, `event: done`) → update query with response_text, tokens_used, cost_usd, latency_ms, model_used, source_message_ids.
- **app/api/router.py** — `queries` router at `/queries`.
- **app/schemas/query_schema.py** — `QueryCreateSchema`, `QueryResponseSchema`.

---

## Verification Steps

### 1. Phase 5 — Analysis pipeline

```bash
# Start Postgres + Redis
docker-compose up -d postgres redis

# Run migrations
alembic upgrade head

# Start API (registers MessageIngested handler)
uvicorn app.main:app --reload

# Start Celery worker (analysis queue)
celery -A app.workers.celery_app worker -Q analysis -l info
```

- Ingest a message (e.g. manual note via `POST /api/messages/note` or run a Gmail sync). Check that a row is created in `messages` and that an `analyze_message` task is queued/run.
- With `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` set, the task should populate `body_summary`, `sentiment_label`, `sentiment_score`, `topics`, `entities_mentioned`, `has_commitment`, `has_question`, `embedding` on the message. If commitments are extracted, rows appear in `commitments` and `usage_events` has entries for message_extraction, message_sentiment, message_commitments, message_embedding.

### 2. Phase 6 — Query engine

```bash
# API running (as above)
uvicorn app.main:app --reload
```

- **Intent + model**
  - `POST /api/queries` with `{"input_text": "when did I last email John?"}` → intent `search`, model Haiku, response streamed.
  - `POST /api/queries` with `{"input_text": "draft a reply saying I'll send the report by Friday"}` → intent `draft`, model Sonnet, response streamed.
  - `POST /api/queries` with `{"input_text": "summarize my conversations with Alex"}` → intent `summarize`, model Sonnet.
  - `POST /api/queries` with `{"input_text": "am I overcommitting?"}` → intent `ask`, model Sonnet.

- **Streaming**
  - Response is `text/event-stream`. Events: `chunk` (data: `{"text": "..."}`), then `done` (data: `{"tokens_used", "cost_usd", "latency_ms"}`).
  - Frontend can subscribe with `EventSource` or fetch with `ReadableStream` and parse SSE.

- **Queries table**
  - After stream completes, the query row is updated with `response_text`, `tokens_used`, `cost_usd`, `latency_ms`, `model_used`, `source_message_ids`, `source_person_ids`, `intent`.

- **Hybrid search**
  - Queries that “find something” use `hybrid_search`: query text is embedded, then pgvector cosine similarity is combined with filters (person, date range, has_commitment). Retrieved message IDs are in `source_message_ids`.

- **Prompt caching**
  - User context (top 20 people, open commitments count, recent activity) is sent as the system prompt with `use_system_cache=True` so it can be cached by the API (cost/latency optimization).

### 3. Quick curl examples

```bash
# List queries (requires Authorization: Bearer <access_token>)
curl -s -H "Authorization: Bearer $TOKEN" "http://localhost:8000/api/queries?limit=5"

# Stream a query (SSE)
curl -s -N -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"input_text": "what did I promise to Sarah?"}' \
  "http://localhost:8000/api/queries"
# Expect: event: chunk / data: {"text": "..."} repeated, then event: done / data: {"tokens_used":..., "cost_usd":..., "latency_ms":...}
```

---

## Summary

| Component            | Location / Behavior |
|----------------------|---------------------|
| Hybrid search        | `MessageRepository.hybrid_search()` — vector + person_id, from_date, to_date, has_commitment |
| Intent parsing       | `query_engine.parse_intent()` → search \| draft \| summarize \| ask |
| Model selection      | Haiku (search), Sonnet (draft, summarize, ask) |
| Streaming            | `POST /queries` → `StreamingResponse` with SSE (`event: chunk`, `event: done`) |
| Query logging        | Every query row: tokens_used, cost_usd, latency_ms, model_used, source_message_ids |
| Prompt caching      | User context (top 20 people, open commitments, recent activity) as cached system prefix |
