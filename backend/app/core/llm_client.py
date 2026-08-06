from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from tenacity import retry, stop_after_attempt, wait_exponential
from zai import ZhipuAiClient

from app.config import settings

logger = logging.getLogger(__name__)


class LLMClient:
    """Async wrapper around Zhipu AI SDK."""

    def __init__(self) -> None:
        self._client = ZhipuAiClient(
            api_key=settings.zai_api_key,
            base_url=settings.llm_base_url,
        )
        self._model = settings.llm_model

    @retry(wait=wait_exponential(multiplier=1, min=1, max=8), stop=stop_after_attempt(3), reraise=True)
    async def chat_completion(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        response_format: dict[str, str] | None = None,
        temperature: float = 0,
        seed: int = 42,
    ) -> dict[str, Any]:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        return await self.chat_completion_messages(
            messages,
            model=self._model,
            response_format=response_format,
            temperature=temperature,
            seed=seed,
        )

    @retry(wait=wait_exponential(multiplier=1, min=1, max=8), stop=stop_after_attempt(3), reraise=True)
    async def chat_completion_messages(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        response_format: dict[str, str] | None = None,
        temperature: float = 0,
        seed: int = 42,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        request_kwargs: dict[str, Any] = {
            "model": model or self._model,
            "messages": [
                {"role": item["role"], "content": item["content"]}
                for item in messages
            ],
            "temperature": temperature,
            "response_format": response_format,
            "seed": seed,
        }
        try:
            response = await asyncio.to_thread(self._client.chat.completions.create, **request_kwargs)
        except TypeError:
            # Some model endpoints may not accept seed/response_format args.
            request_kwargs.pop("seed", None)
            request_kwargs.pop("response_format", None)
            response = await asyncio.to_thread(self._client.chat.completions.create, **request_kwargs)
        latency_ms = (time.perf_counter() - started) * 1000
        usage_obj = getattr(response, "usage", None)
        if hasattr(usage_obj, "model_dump"):
            usage = usage_obj.model_dump()
        elif isinstance(usage_obj, dict):
            usage = usage_obj
        else:
            usage = {}
        logger.info(
            "LLM completion success model=%s latency_ms=%.2f usage=%s",
            request_kwargs["model"],
            latency_ms,
            usage,
        )

        content = response.choices[0].message.content if response.choices else None
        if not content:
            raise ValueError("LLM returned empty content.")

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            logger.exception("LLM response is not valid JSON.")
            raise ValueError("LLM response is not valid JSON.") from exc

        return {
            "model": request_kwargs["model"],
            "seed": seed,
            "temperature": temperature,
            "usage": usage,
            "raw_content": content,
            "parsed": parsed,
        }
