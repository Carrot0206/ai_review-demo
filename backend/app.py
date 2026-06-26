"""FastAPI 应用入口。

启动：
  cd trust-ai-review-demo
  source backend/.venv/bin/activate
  uvicorn backend.app:app --reload --port 8000
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.review_router import router as review_router
from .api.rules_router import router as rules_router
from .api.samples_router import router as samples_router
from .api.upload_router import router as upload_router
from .api.user_rules_router import router as user_rules_router

app = FastAPI(
    title="信托登记 AI 辅助审核 Demo",
    description="中信登信托产品登记 AI 辅助审核演示后端",
    version="0.1.0",
)

# 前端开发期跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"status": "ok"}


app.include_router(rules_router)
app.include_router(user_rules_router)
app.include_router(upload_router)
app.include_router(review_router)
app.include_router(samples_router)
