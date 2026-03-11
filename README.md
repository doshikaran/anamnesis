# Anamnesis Backend

Personal relationship and commitment intelligence platform — API, workers, and ingestion.

## Tech stack

- **Python 3.12+**, FastAPI (async), Uvicorn + Gunicorn
- **PostgreSQL 16** + pgvector, SQLAlchemy 2.0 (async), Alembic
- **Redis 7** (Celery broker, cache, rate limiting)
- **Celery 5** for background tasks
- **Google / Microsoft OAuth 2.0**, JWT (access 15 min, refresh 30 days)

## Quick start

1. **Copy env and set required vars**
   ```bash
   cp .env.example .env
   # Edit .env: SECRET_KEY, DATABASE_URL, REDIS_URL at minimum
   ```

2. **Start Postgres + Redis (and optional API/worker)**
   ```bash
   docker-compose up -d postgres redis
   ```

3. **Create DB and run migrations**
   ```bash
   # Create DB if needed: createdb anamnesis
   alembic upgrade head
   ```

4. **Run API locally**
   ```bash
   pip install -r requirements.txt
   uvicorn app.main:app --reload
   ```

5. **Health check**
   ```bash
   curl http://localhost:8000/health
   # → {"status":"ok","db":"connected","redis":"connected"}
   ```

## Auth (Phase 2)

- **GET /api/auth/google/login** — redirects to Google OAuth
- **GET /api/auth/google/callback** — handles callback, redirects to frontend with `access_token` and `refresh_token`
- **POST /api/auth/refresh** — body `{"refresh_token":"..."}` → new access + refresh (rotation)
- **GET /api/auth/me** — current user (header: `Authorization: Bearer <access_token>`)
- **POST /api/auth/logout** — invalidate refresh token

Set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` and ensure Google Cloud redirect URI is `http://localhost:8000/api/auth/google/callback` (or your backend URL) for local dev.

## Project layout

- `app/api/` — HTTP handlers (auth, users, connections, …)
- `app/services/` — business logic
- `app/repositories/` — DB access only
- `app/models/` — SQLAlchemy ORM
- `app/core/` — DB, Redis, security, exceptions, events
- `app/workers/` — Celery tasks (sync, analysis, notifications, maintenance)
- `alembic/` — migrations

## Tests

```bash
pip install -r requirements-dev.txt
docker-compose -f docker-compose.test.yml up -d
# Set DATABASE_URL and REDIS_URL to test services
pytest
```

---

**Pair A (Phases 1 + 2) complete.** Next: Pair B (Phases 3 + 4) — Connections and first connector, People & Messages.
