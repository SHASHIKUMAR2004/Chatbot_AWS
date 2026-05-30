"""ChatBot API — FastAPI application entrypoint."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from .config import settings
from .database import init_db
from .routers import chat, conversations, files

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
logger = logging.getLogger("chatbot")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    mode = "LIVE (Groq)" if settings.llm_enabled else "DEMO (no GROQ_API_KEY)"
    logger.info("%s v%s starting — mode: %s", settings.app_name, settings.app_version, mode)
    yield
    logger.info("Shutting down.")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Production-grade streaming chat API powered by Groq.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)

app.include_router(conversations.router)
app.include_router(chat.router)
app.include_router(files.router)


@app.get("/", tags=["meta"])
def home():
    return {
        "message": "Backend Running",
        "name": settings.app_name,
        "version": settings.app_version,
        "mode": "live" if settings.llm_enabled else "demo",
        "docs": "/docs",
    }


@app.get("/health", tags=["meta"])
def health():
    return {
        "status": "ok",
        "llm_enabled": settings.llm_enabled,
        "default_model": settings.default_model,
        "assistant_name": settings.assistant_name,
    }


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
