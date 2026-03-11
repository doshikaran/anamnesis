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
