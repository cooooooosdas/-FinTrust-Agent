"""OpenAI 兼容的 LLM 客户端。

要点
----
1. **API Key 只存在于后端环境变量**，绝不写入前端代码，也不在任何响应中返回。
2. 未配置 Key 时 `enabled` 为 False，系统进入「本地演示模式」，
   由规则引擎完成意图识别与参数抽取，响应中会带 `demo_mode=true` 明确标注。
3. 所有调用都走熔断器：连续失败达到阈值后自动降级，避免拖垮服务。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings
from app.core.errors import LLMUnavailableError
from app.security.circuit_breaker import circuit_breaker

logger = logging.getLogger("fintrust.llm")

DEMO_NOTICE = (
    "当前未配置大模型 API Key，AI 助手运行在**本地演示模式**："
    "意图识别与参数抽取由内置规则引擎完成，不调用任何外部模型服务。"
)


class LLMClient:
    """极简 OpenAI 兼容客户端（chat/completions）。"""

    def __init__(self) -> None:
        self.base_url = settings.llm_base_url.rstrip("/")
        self.api_key = settings.llm_api_key.strip()
        self.model = settings.llm_model
        self.timeout = settings.llm_timeout

    # ------------------------------------------------------------------
    @property
    def enabled(self) -> bool:
        return bool(self.api_key) and not settings.force_demo_mode

    @property
    def demo_notice(self) -> str:
        return DEMO_NOTICE if not self.enabled else "已连接配置的模型服务"

    # ------------------------------------------------------------------
    def chat(
        self,
        messages: List[Dict[str, str]],
        *,
        temperature: float = 0.1,
        max_tokens: int = 1200,
        response_format_json: bool = False,
    ) -> str:
        """发起一次 chat/completions 调用，返回文本内容。"""
        if not self.enabled:
            raise LLMUnavailableError(DEMO_NOTICE)

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format_json:
            payload["response_format"] = {"type": "json_object"}

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        def _do_request() -> str:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
                if resp.status_code >= 400:
                    raise LLMUnavailableError(
                        f"模型服务返回错误状态 {resp.status_code}",
                        detail={"status_code": resp.status_code, "body": resp.text[:500]},
                    )
                data = resp.json()
                return data["choices"][0]["message"]["content"]

        try:
            return circuit_breaker.call(_do_request)
        except LLMUnavailableError:
            raise
        except Exception as exc:  # 网络异常等
            logger.warning("LLM 调用失败: %s", exc.__class__.__name__)
            raise LLMUnavailableError(f"模型服务调用失败：{exc.__class__.__name__}") from exc

    # ------------------------------------------------------------------
    def chat_json(
        self,
        messages: List[Dict[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: int = 800,
    ) -> Dict[str, Any]:
        """调用并解析 JSON 输出（对 ```json 包裹做容错）。"""
        text = self.chat(
            messages, temperature=temperature, max_tokens=max_tokens, response_format_json=True
        )
        return extract_json(text)


def extract_json(text: str) -> Dict[str, Any]:
    """从模型输出中稳健地提取 JSON 对象。"""
    if not text:
        raise LLMUnavailableError("模型返回内容为空")
    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.S)
    if fenced:
        cleaned = fenced.group(1)
    else:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end > start:
            cleaned = cleaned[start : end + 1]
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise LLMUnavailableError("模型返回内容不是合法 JSON") from exc


llm_client = LLMClient()

__all__ = ["LLMClient", "llm_client", "extract_json", "DEMO_NOTICE"]
