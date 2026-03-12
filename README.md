# Anamnesis Backend

**Remember every relationship.** Personal relationship and commitment intelligence — your contacts, promises, and patterns in one place.

Anamnesis ingests email (Gmail) and calendar (Google Calendar), extracts people and commitments with AI, and answers natural-language questions over your data. It surfaces daily briefings, commitment nudges, and relationship silence detection. This repository is the backend API, Celery workers, and ingestion connectors.

---

## Architecture (ASCII)

```
                    +------------------+
                    |   Next.js / PWA   |
                    |   (Frontend)      |
                    +--------+---------+
                             | HTTPS
                             v
                    +------------------+
                    |  nginx (proxy)   |
                    |  rate limit backup|
                    +--------+---------+
                             |
         +-------------------+-------------------+
         |                   |                   |
         v                   v                   v
  +-------------+    +-------------+    +-------------+
  |  FastAPI     |    |  Celery     |    |  Celery     |
  |  (API)       |    |  worker     |    |  beat       |
  |  /api/*      |    |  sync/      |    |  schedules  |
  |  /health     |    |  analysis/  |    |  briefings  |
  |              |    |  insights   |    |  nudges     |
  +------+-------+    +------+------+    +------+------+
         |                   |                   |
         +-------------------+-------------------+
                             |
              +--------------+--------------+
              |              |              |
              v              v              v
       +-----------+  +-----------+  +-----------+
       | PostgreSQL |  |  Redis    |  |  S3       |
       | + pgvector |  |  broker/  |  | (uploads) |
       |            |  |  cache    |  |          |
       +-----------+  +-----------+  +-----------+
```

---

## Quick start

1. **Clone and enter**
   ```bash
   git clone <repo-url> anamnesis-backend && cd anamnesis-backend
   ```

2. **Environment**
   ```bash
   cp .env.example .env
   # Set at minimum: SECRET_KEY, ENCRYPTION_MASTER_KEY, DATABASE_URL, REDIS_URL
   # For Gmail: GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI
   # For AI: ANTHROPIC_API_KEY
   ```

3. **Start Postgres and Redis**
   ```bash
   docker-compose up -d postgres redis
   ```

4. **Migrations**
   ```bash
   alembic upgrade head
   ```

5. **Run API**
   ```bash
   pip install -r requirements.txt
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

6. **Run Celery worker** (separate terminal)
   ```bash
   celery -A app.workers.celery_app worker -Q sync,analysis,insights,notifications,maintenance --loglevel=info
   ```

7. **Run Celery beat** (separate terminal)
   ```bash
   celery -A app.workers.celery_app beat --scheduler celery.beat.PersistentScheduler --loglevel=info
   ```

8. **Health check**
   ```bash
   curl http://localhost:8000/health
   # → {"status":"ok","db":"connected","redis":"connected"}
   ```

---

## API documentation

- **Swagger UI:** [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc:** [http://localhost:8000/redoc](http://localhost:8000/redoc)

---

## Gmail connection (step by step)

1. **Google Cloud Console**
   - Create a project (or use existing).
   - Enable **Gmail API** and **Google Calendar API**.
   - Go to **APIs & Services → Credentials** and create an **OAuth 2.0 Client ID** (Web application).
   - Add authorized redirect URI: `http://localhost:3000/auth/google/callback` (or your frontend) and, for backend callback, `http://localhost:8000/api/connections/google/callback`.

2. **Backend .env**
   - Set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` (usually frontend callback for app-initiated flow).

3. **Connect from frontend**
   - Call `POST /api/connections/google/init?source_type=gmail` with `Authorization: Bearer <access_token>`.
   - Response contains `auth_url`. Redirect the user to that URL.
   - After consent, Google redirects to your `GOOGLE_REDIRECT_URI` with `?code=...`. Send the `code` to your backend (or have backend callback at `/api/connections/google/callback` with the same redirect URI configured in Google).

4. **Backend callback**
   - Backend exchanges `code` for tokens, encrypts and stores them, creates a `Connection` for the user. Redirects to frontend with `?connected=gmail`.

5. **Sync**
   - Trigger sync: `POST /api/connections/{connection_id}/sync`. Celery worker runs Gmail full or incremental sync and routes messages through `ingest_message()`.

---

## First query (curl + SSE)

After connecting Gmail and syncing, you can run a natural-language query. The response is streamed via Server-Sent Events.

```bash
# Replace YOUR_ACCESS_TOKEN with a JWT from POST /api/auth/refresh or login.
curl -N -X POST http://localhost:8000/api/queries \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"input_text": "When did I last email Sarah?"}'
```

Example SSE output:

```
event: chunk
data: {"text": "Based on your messages, you last emailed Sarah on "}

event: chunk
data: {"text": "March 10, 2025"}

event: chunk
data: {"text": " about the project deadline.\n"}

event: done
data: {"tokens_used": 420, "cost_usd": 0.002, "latency_ms": 1200}
```

---

## Environment variable reference

| Variable | Required | Description |
|----------|----------|-------------|
| `APP_ENV` | No | `development` \| `staging` \| `production` (default: development) |
| `SECRET_KEY` | Yes | JWT signing key |
| `ENCRYPTION_MASTER_KEY` | Yes | Fernet key for OAuth token encryption |
| `DATABASE_URL` | Yes | PostgreSQL URL (postgresql+asyncpg://...) |
| `REDIS_URL` | Yes | Redis URL for Celery and rate limiting |
| `GOOGLE_CLIENT_ID` | Gmail/Calendar | Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | Gmail/Calendar | Google OAuth client secret |
| `ANTHROPIC_API_KEY` | Yes (AI) | Claude API key for queries and analysis |
| `FRONTEND_URL` | Yes | CORS and redirect base (e.g. http://localhost:3000) |
| `VAPID_PRIVATE_KEY` | Push | Web Push VAPID private key |
| `AWS_*` | S3/Secrets | Region, keys, bucket, Secrets Manager prefix |
| `SENTRY_DSN` | No | Error tracking |

See `.env.example` for the full list with comments.

---

## Project structure (top level)

| Path | Description |
|------|-------------|
| `app/main.py` | FastAPI app, lifespan, CORS, exception handler, /health |
| `app/api/` | Routers: auth, users, connections, people, messages, queries, insights, notifications, webhooks |
| `app/core/` | Database, Redis, security (JWT), encryption, rate limiter, exceptions, events |
| `app/models/` | SQLAlchemy ORM models |
| `app/repositories/` | Data access layer |
| `app/services/` | Auth, message ingest, people, user (deletion) |
| `app/ai/` | Query engine, analysis, embeddings, prompts, briefing |
| `app/ingestion/` | Connectors: Gmail, Google Calendar, Slack (BaseConnector) |
| `app/workers/` | Celery app, sync_tasks, analysis_tasks, insight_tasks, notification_tasks, maintenance_tasks |
| `alembic/` | Migrations |
| `docker/` | Dockerfile.api, Dockerfile.worker, Dockerfile.beat, nginx.conf |

---

## Key architectural decisions

| Decision | Reason |
|----------|--------|
| **Sliding-window rate limit in Redis** | Accurate per-user limits without fixed windows; one source of truth for 429 and Retry-After. |
| **Unit of Work + repositories** | Single transaction per operation; clear separation between persistence and business logic. |
| **EventBus (MessageIngested → analysis)** | Decouples ingestion from AI pipeline; Celery handles async analysis and insights. |
| **OAuth tokens encrypted at rest** | Per-user key derivation; tokens never stored plaintext. |
| **Hybrid search (vector + keyword)** | Combines semantic recall with exact match; prompt caching for user context reduces cost. |

---

## License

Proprietary. All rights reserved.

---

**Anamnesis Backend** — Production-ready for private beta. Next step: Frontend (Next.js).
