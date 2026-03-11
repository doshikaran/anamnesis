"""
Anamnesis Backend — FastAPI entrypoint.
Lifespan: verify DB + Redis on startup. /health checks both.
CORS, global exception handler, request_id middleware, structlog.
"""

import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.config import get_settings
from app.core.database import engine
from app.core.exceptions import AnamnesisException
from app.core.redis import get_redis_pool
from app.api.router import api_router

# Register EventBus handlers (MessageIngested, CommitmentCreated, RelationshipSilenceDetected)
import app.workers.analysis_tasks  # noqa: F401, E402
import app.workers.insight_tasks  # noqa: F401, E402

settings = get_settings()
log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: verify DB and Redis. Shutdown: dispose pools."""
    # Verify DB
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        log.info("database.connected")
    except Exception as e:
        log.error("database.connection_failed", error=str(e))
        raise
    # Verify Redis
    try:
        from redis.asyncio import Redis
        client = Redis(connection_pool=get_redis_pool())
        await client.ping()
        await client.aclose()
        log.info("redis.connected")
    except Exception as e:
        log.error("redis.connection_failed", error=str(e))
        raise
    yield
    await engine.dispose()
    log.info("shutdown.complete")


app = FastAPI(
    title="Anamnesis API",
    description="Personal relationship and commitment intelligence platform",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL] if settings.FRONTEND_URL else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """Attach a unique request_id to each request for logging and error responses."""
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["x-request-id"] = request_id
    return response


@app.exception_handler(AnamnesisException)
async def anamnesis_exception_handler(request: Request, exc: AnamnesisException):
    """Format all Anamnesis errors consistently."""
    request_id = getattr(request.state, "request_id", None)
    log.warning(
        "api.error",
        code=exc.code,
        message=exc.message,
        status_code=exc.status_code,
        request_id=request_id,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "request_id": request_id,
            }
        },
    )


app.include_router(api_router, prefix="/api", tags=["api"])


@app.get("/health")
async def health():
    """Health check: DB and Redis. Used by load balancer and docker healthcheck."""
    db_ok = False
    redis_ok = False
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass
    try:
        from redis.asyncio import Redis
        client = Redis(connection_pool=get_redis_pool())
        await client.ping()
        await client.aclose()
        redis_ok = True
    except Exception:
        pass
    status = "ok" if (db_ok and redis_ok) else "degraded"
    return {
        "status": status,
        "db": "connected" if db_ok else "disconnected",
        "redis": "connected" if redis_ok else "disconnected",
    }


@app.get("/")
async def root():
    return {"service": "Anamnesis API", "docs": "/docs"}
