"""FastAPI app：CORS + routers（sessions / tenders / chat）。"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .agent.agent import init_agent, shutdown_agent
from .api import chat, sessions, tenders, upload

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_agent()
    yield
    await shutdown_agent()


app = FastAPI(title="tender-assistant backend", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sessions.router)
app.include_router(tenders.router)
app.include_router(chat.router)
app.include_router(upload.router)
