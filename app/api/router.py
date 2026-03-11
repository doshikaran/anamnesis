"""Master API router. Includes all sub-routers (auth, users, connections, ...)."""

from fastapi import APIRouter

from app.api import auth, users, connections, people, messages, queries, insights, notifications, webhooks

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(connections.router, prefix="/connections", tags=["connections"])
api_router.include_router(people.router, prefix="/people", tags=["people"])
api_router.include_router(messages.router, prefix="/messages", tags=["messages"])
api_router.include_router(queries.router, prefix="/queries", tags=["queries"])
api_router.include_router(insights.router, prefix="/insights", tags=["insights"])
api_router.include_router(notifications.router, prefix="/notifications", tags=["notifications"])
api_router.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
