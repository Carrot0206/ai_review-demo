"""独立规则库与规则引擎 FastAPI 应用。"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.material_router import router as material_router
from .api.rule_library_router import router as rule_library_router
from .api.rule_engine_router import router as rule_engine_router
from .services.ai_client import close_ai_client, load_ai_config
from .storage import database


@asynccontextmanager
async def lifespan(_: FastAPI):
    database.init_db()
    database.mark_running_interrupted()
    database.cleanup_ai_traces()
    yield
    await close_ai_client()


app = FastAPI(
    title="信托登记规则库与规则引擎",
    description="独立提供规则库管理，并承载后续脚本执行器、AI执行器和异步审核API。",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/rule-engine/health")
def health():
    config = load_ai_config(require_key=False)
    return {
        "status": "ok",
        "service": "trust-rule-engine",
        "ai_configured": bool(config.api_key),
        "ai_model": config.model,
    }


app.include_router(rule_library_router)
app.include_router(material_router)
app.include_router(rule_engine_router)
