"""
WhatsApp Bulk Sender - FastAPI Application Entry Point
Configures CORS, mounts routers, and manages app lifecycle.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic_settings import BaseSettings

from routers import whatsapp, contacts, messages, monitor, instances
from services.evolution_api import EvolutionAPIService


# ─────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────

class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env file."""

    # ── Baileys local server (replaces Evolution API Docker) ──
    evolution_api_url: str = "http://localhost:8085"
    evolution_api_key: str = "supersecretapikey"

    # ── Frontend & rate limits ──
    frontend_origin: str = "http://localhost:7070"
    message_delay_min: float = 1.5
    message_delay_max: float = 3.5
    send_rate_limit: int = 30

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# App Lifecycle
# ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage application startup and shutdown.
    Creates Evolution API client on startup, closes it on shutdown.
    """
    logger.info("🚀 Starting WhatsApp Bulk Sender API...")
    logger.info(f"   Evolution API: {settings.evolution_api_url}")

    # Initialize Evolution API service
    evolution_service = EvolutionAPIService(
        base_url=settings.evolution_api_url,
        api_key=settings.evolution_api_key,
    )

    # Attach to app state for router access
    app.state.evolution_api = evolution_service
    app.state.settings = settings

    logger.info("✅ Application ready")

    yield  # Application runs here

    # Cleanup on shutdown
    logger.info("🛑 Shutting down...")
    await evolution_service.close()


# ─────────────────────────────────────────────
# FastAPI App
# ─────────────────────────────────────────────

app = FastAPI(
    title="WhatsApp Bulk Sender API",
    description="Backend API for sending bulk WhatsApp messages via Evolution API",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS - Allow frontend to communicate with backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount routers
app.include_router(whatsapp.router, prefix="/api")
app.include_router(contacts.router, prefix="/api")
app.include_router(messages.router, prefix="/api")
app.include_router(monitor.router, prefix="/api")
app.include_router(instances.router) # Prefix is handled in the router


@app.get("/api/health")
async def health_check():
    """Health check endpoint for Docker and monitoring."""
    return {
        "status": "healthy",
        "service": "WhatsApp Bulk Sender API",
        "version": "1.0.0",
    }
