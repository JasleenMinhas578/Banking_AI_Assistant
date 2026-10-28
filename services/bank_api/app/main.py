"""Puffin Bank API entry point: creates the app and plugs in the routes."""

from fastapi import FastAPI

from app.api.errors import register_error_handlers
from app.api.routes import accounts, health, sessions

app = FastAPI(title="Puffin Bank API")

register_error_handlers(app)
app.include_router(health.router)
app.include_router(sessions.router)
app.include_router(accounts.router)
