"""真实 LLM API 客户端 — OpenAI 兼容接口。

支持：
  - 智谱 GLM（bigmodel.cn）
  - DeepSeek
  - OpenAI / Azure OpenAI
  - 任何 OpenAI 兼容 API

配置方式：
  1. 环境变量：SAGENT_LLM_API_KEY, SAGENT_LLM_BASE_URL, SAGENT_LLM_MODEL
  2. config.json 的 llm 节

所有 LLM 调用都有 JSON 解析容错和规则引擎 fallback。
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from .llm import FallbackEvent, LLMClient, PromptRequest


def _get_llm_config(env: dict[str, str] | None = None) -> dict[str, str]:
    """从环境变量读取 LLM 配置。"""
    e = env or dict(os.environ)
    return {
        "api_key": e.get("SAGENT_LLM_API_KEY", ""),
        "base_url": e.get(
            "SAGENT_LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4"
        ),
        "model": e.get("SAGENT_LLM_MODEL", "glm-4-flash"),
        "fallback_model": e.get("SAGENT_LLM_FALLBACK_MODEL", ""),
        "fallback_base_url": e.get("SAGENT_LLM_FALLBACK_BASE_URL", ""),
        "fallback_api_key": e.get("SAGENT_LLM_FALLBACK_API_KEY", ""),
    }


class OpenAILLMClient:
    """OpenAI 兼容 LLM 客户端。

    使用 requests 直连，不依赖 openai SDK。
    返回解析后的 JSON dict。
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://open.bigmodel.cn/api/paas/v4",
        model: str = "glm-4-flash",
        timeout: int = 30,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def complete(self, request: PromptRequest) -> dict:
        """调用 LLM 并解析 JSON 响应。"""
        import requests

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": request.model or self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是一个专业的 A 股交易分析助手。你必须只输出合法 JSON，"
                        "不要包含任何其他文字、markdown 代码块或解释。"
                    ),
                },
                {"role": "user", "content": request.prompt},
            ],
            "temperature": 0.3,
            "max_tokens": 512,
        }

        resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()

        content = data["choices"][0]["message"]["content"].strip()
        return _parse_json_response(content)


def _parse_json_response(content: str) -> dict:
    """从 LLM 响应中提取 JSON。

    支持：
      - 纯 JSON
      - ```json ... ``` 包裹
      - 混合文字 + JSON
    """
    # 尝试直接解析
    content = content.strip()
    if content.startswith("```"):
        # 去掉 markdown 代码块
        lines = content.split("\n")
        # 去掉首尾的 ``` 行
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        content = "\n".join(lines)

    # 尝试找到 JSON 对象
    json_match = re.search(r"\{[^{}]*\}", content, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

    # 尝试整体解析
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {"_raw": content, "_parse_error": True}


def create_llm_client(env: dict[str, str] | None = None) -> LLMClient | None:
    """根据环境配置创建 LLM 客户端。

    无 API key 时返回 None（使用规则引擎 fallback）。
    """
    config = _get_llm_config(env)

    if not config["api_key"]:
        return None

    primary = OpenAILLMClient(
        api_key=config["api_key"],
        base_url=config["base_url"],
        model=config["model"],
    )

    # 如果有 fallback 配置，包装为 FallbackChain
    fb_key = config["fallback_api_key"]
    fb_model = config["fallback_model"]
    if fb_key and fb_model:
        fb_url = config["fallback_base_url"] or config["base_url"]
        fallback = OpenAILLMClient(
            api_key=fb_key,
            base_url=fb_url,
            model=fb_model,
        )
        return _FallbackChain(
            primary=primary,
            fallback=fallback,
            primary_model=config["model"],
            fallback_model=fb_model,
        )

    return primary


class _FallbackChain:
    """双模型自动降级链。"""

    def __init__(
        self,
        primary: OpenAILLMClient,
        fallback: OpenAILLMClient,
        primary_model: str,
        fallback_model: str,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.primary_model = primary_model
        self.fallback_model = fallback_model
        self.fallback_log: list[FallbackEvent] = []

    def complete(self, request: PromptRequest) -> dict:
        try:
            return self.primary.complete(request)
        except Exception as e:
            self.fallback_log.append(
                FallbackEvent(
                    original_model=self.primary_model,
                    fallback_model=self.fallback_model,
                    purpose=request.purpose,
                    reason=str(e),
                )
            )
            return self.fallback.complete(
                PromptRequest(
                    model=self.fallback_model,
                    prompt=request.prompt,
                    purpose=request.purpose,
                )
            )


def llm_status(env: dict[str, str] | None = None) -> dict[str, Any]:
    """检查 LLM 配置状态（不调用 API）。"""
    config = _get_llm_config(env)
    has_key = bool(config["api_key"])
    has_fallback = bool(config["fallback_api_key"] and config["fallback_model"])
    return {
        "configured": has_key,
        "model": config["model"] if has_key else "规则引擎",
        "base_url": config["base_url"] if has_key else "",
        "fallback_configured": has_fallback,
        "fallback_model": config["fallback_model"] if has_fallback else "",
    }
