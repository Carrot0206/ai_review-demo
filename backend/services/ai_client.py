from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class AIConfig:
    api_key: str
    base_url: str
    model: str
    temperature: float
    timeout_seconds: float
    max_retries: int
    max_concurrency: int

    def snapshot(self) -> dict[str, Any]:
        return {
            "provider": "deepseek",
            "base_url": self.base_url,
            "model": self.model,
            "temperature": self.temperature,
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            "max_concurrency": self.max_concurrency,
        }


def load_ai_config(require_key: bool = True) -> AIConfig:
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if require_key and not api_key:
        raise RuntimeError("未配置DEEPSEEK_API_KEY")
    return AIConfig(
        api_key=api_key,
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1").rstrip("/"),
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        temperature=float(os.getenv("LLM_TEMPERATURE", "0.1")),
        timeout_seconds=float(os.getenv("LLM_TIMEOUT_SECONDS", "60")),
        max_retries=int(os.getenv("LLM_MAX_RETRIES", "2")),
        max_concurrency=int(os.getenv("AI_MAX_CONCURRENCY", "2500")),
    )


@dataclass
class AIResponse:
    content: str
    parsed: dict[str, Any]
    input_tokens: int = 0
    output_tokens: int = 0


def parse_json_response(content: str) -> dict[str, Any]:
    text = str(content or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:].strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("模型输出不是合法JSON")
        parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("模型输出必须是JSON对象")
    return parsed


class DeepSeekClient:
    def __init__(self, config: AIConfig | None = None) -> None:
        self.config = config or load_ai_config()
        limits = httpx.Limits(
            max_connections=self.config.max_concurrency,
            max_keepalive_connections=min(self.config.max_concurrency, 500),
        )
        self.http = httpx.AsyncClient(timeout=self.config.timeout_seconds, limits=limits)

    async def chat(self, messages: list[dict[str, str]]) -> AIResponse:
        response = await self.http.post(
            f"{self.config.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.config.api_key}"},
            json={
                "model": self.config.model,
                "messages": messages,
                "temperature": self.config.temperature,
                "response_format": {"type": "json_object"},
            },
        )
        response.raise_for_status()
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
        usage = payload.get("usage") or {}
        return AIResponse(
            content=content,
            parsed=parse_json_response(content),
            input_tokens=int(usage.get("prompt_tokens", 0) or 0),
            output_tokens=int(usage.get("completion_tokens", 0) or 0),
        )

    async def close(self) -> None:
        await self.http.aclose()


_CLIENT: DeepSeekClient | None = None
_CLIENT_LOCK = asyncio.Lock()


async def get_ai_client() -> DeepSeekClient:
    global _CLIENT
    if _CLIENT is None:
        async with _CLIENT_LOCK:
            if _CLIENT is None:
                _CLIENT = DeepSeekClient()
    return _CLIENT


async def close_ai_client() -> None:
    global _CLIENT
    if _CLIENT is not None:
        await _CLIENT.close()
        _CLIENT = None
