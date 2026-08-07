from __future__ import annotations

import asyncio
import json
import logging
import re
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
        allow_json_repair: bool = True,
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
            parsed = self._parse_json_relaxed(content)
        except json.JSONDecodeError as exc:
            snippet = content[:500].replace("\n", "\\n")
            logger.warning("Invalid JSON snippet: %s", snippet)
            if allow_json_repair:
                try:
                    repaired = await self._repair_json_response(
                        raw_content=content,
                        model=request_kwargs["model"],
                        seed=seed,
                    )
                    content = repaired["raw_content"]
                    parsed = repaired["parsed"]
                except Exception:
                    logger.exception("JSON repair attempt failed.")
                    raise ValueError("LLM response is not valid JSON.") from exc
            else:
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

    @staticmethod
    def _parse_json_relaxed(content: str) -> dict[str, Any]:
        candidate = content.strip()
        try:
            loaded = json.loads(candidate)
            if isinstance(loaded, dict):
                return loaded
            raise json.JSONDecodeError("Top-level JSON is not an object", candidate, 0)
        except json.JSONDecodeError:
            pass

        fenced = re.sub(r"^\s*```(?:json)?\s*", "", candidate, flags=re.IGNORECASE)
        fenced = re.sub(r"\s*```\s*$", "", fenced)
        try:
            loaded = json.loads(fenced)
            if isinstance(loaded, dict):
                return loaded
            raise json.JSONDecodeError("Top-level JSON is not an object", fenced, 0)
        except json.JSONDecodeError:
            pass

        json_block = LLMClient._extract_first_json_object(fenced)
        if not json_block:
            raise json.JSONDecodeError("No JSON object found", candidate, 0)
        loaded = json.loads(json_block)
        if not isinstance(loaded, dict):
            raise json.JSONDecodeError("Top-level JSON is not an object", json_block, 0)
        return loaded

    @staticmethod
    def _extract_first_json_object(text: str) -> str | None:
        start = text.find("{")
        if start == -1:
            return None
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            ch = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : index + 1]
        return None

    async def _repair_json_response(
        self,
        *,
        raw_content: str,
        model: str,
        seed: int,
    ) -> dict[str, Any]:
        repair_system = (
            "You repair malformed JSON. "
            "Return one valid JSON object only, with no markdown or commentary."
        )
        repair_user = (
            "Convert the following model output into valid JSON object. "
            "Do not drop keys unless they are syntactically unrecoverable.\n\n"
            f"Raw output:\n{raw_content}"
        )
        logger.info("Attempting one-pass JSON repair.")
        return await self.chat_completion_messages(
            [
                {"role": "system", "content": repair_system},
                {"role": "user", "content": repair_user},
            ],
            model=model,
            response_format={"type": "json_object"},
            temperature=0,
            seed=seed,
            allow_json_repair=False,
        )
