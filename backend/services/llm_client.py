"""LLM 客户端：DeepSeek（OpenAI 兼容协议）。

读取环境变量配置；提供异步 chat() 与同步 chat_sync()。
"""
from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

# 自动加载 backend/.env
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
if _ENV_PATH.exists():
    load_dotenv(_ENV_PATH)


@dataclass
class LLMConfig:
    provider: str
    api_key: str
    base_url: str
    model: str
    temperature: float
    timeout: float
    max_retries: int


def load_config() -> LLMConfig:
    provider = os.getenv("LLM_PROVIDER", "deepseek").strip().lower()
    if provider != "deepseek":
        raise RuntimeError(
            f"CLI 阶段只支持 LLM_PROVIDER=deepseek，当前为 {provider!r}。"
        )
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "未配置 DEEPSEEK_API_KEY。请复制 backend/.env.example 为 backend/.env 并填入真实 key。"
        )
    return LLMConfig(
        provider=provider,
        api_key=api_key,
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1").rstrip("/"),
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        temperature=float(os.getenv("LLM_TEMPERATURE", "0.1")),
        timeout=float(os.getenv("LLM_TIMEOUT_SECONDS", "60")),
        max_retries=int(os.getenv("LLM_MAX_RETRIES", "2")),
    )


@dataclass
class LLMResponse:
    content: str
    parsed: dict[str, Any]
    input_tokens: int = 0
    output_tokens: int = 0


def _safe_json_loads(text: str) -> dict[str, Any]:
    """尽量从模型输出中抽取合法 JSON。"""
    text = (text or "").strip()
    if not text:
        return {"issues": []}
    # 1) 直接尝试
    try:
        return json.loads(text)
    except Exception:
        pass
    # 2) 去掉 markdown 围栏
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        try:
            return json.loads(text)
        except Exception:
            pass
    # 3) 截取第一个 { ... 最后一个 }
    l = text.find("{")
    r = text.rfind("}")
    if l != -1 and r != -1 and r > l:
        try:
            return json.loads(text[l : r + 1])
        except Exception:
            pass
    raise ValueError(f"模型输出不是合法 JSON：{text[:200]}...")


class DeepSeekClient:
    """OpenAI 兼容协议；response_format=json_object 强制 JSON。"""

    def __init__(self, config: LLMConfig | None = None) -> None:
        self.config = config or load_config()

    async def chat(self, messages: list[dict[str, str]]) -> LLMResponse:
        url = f"{self.config.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "response_format": {"type": "json_object"},
        }

        last_err: Exception | None = None
        for attempt in range(self.config.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.config.timeout) as client:
                    resp = await client.post(url, json=payload, headers=headers)
                    resp.raise_for_status()
                    data = resp.json()
                content = data["choices"][0]["message"]["content"]
                usage = data.get("usage", {}) or {}
                parsed = _safe_json_loads(content)
                return LLMResponse(
                    content=content,
                    parsed=parsed,
                    input_tokens=int(usage.get("prompt_tokens", 0) or 0),
                    output_tokens=int(usage.get("completion_tokens", 0) or 0),
                )
            except (httpx.HTTPError, ValueError, KeyError) as e:
                last_err = e
                if attempt < self.config.max_retries:
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                break
        raise RuntimeError(f"DeepSeek 调用失败（重试 {self.config.max_retries} 次后）：{last_err}")

    def chat_sync(self, messages: list[dict[str, str]]) -> LLMResponse:
        return asyncio.run(self.chat(messages))
