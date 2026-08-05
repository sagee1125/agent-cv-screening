from __future__ import annotations

import json
import logging
import time
from typing import Any

from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings

logger = logging.getLogger(__name__)


class LLMClient:
    """Async OpenAI wrapper with deterministic defaults."""

    def __init__(self) -> None:
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)
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
        started = time.perf_counter()
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            seed=seed,
            response_format=response_format,
        )
        latency_ms = (time.perf_counter() - started) * 1000
        usage = response.usage.model_dump() if response.usage else {}
        logger.info(
            "LLM completion success model=%s latency_ms=%.2f usage=%s",
            self._model,
            latency_ms,
            usage,
        )

        content = response.choices[0].message.content if response.choices else None
        if not content:
            raise ValueError("OpenAI returned empty content.")

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            logger.exception("LLM response is not valid JSON.")
            raise ValueError("LLM response is not valid JSON.") from exc

        return {
            "model": self._model,
            "seed": seed,
            "temperature": temperature,
            "usage": usage,
            "raw_content": content,
            "parsed": parsed,
        }
