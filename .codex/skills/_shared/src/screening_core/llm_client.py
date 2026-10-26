# Shared Zhipu chat client with OS-store TLS verification (Windows/corporate CAs).
from __future__ import annotations

import asyncio
import json
import logging
import re
import ssl
import time
from typing import Any

import httpx
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential
from zai import ZhipuAiClient

from screening_core.config import settings

logger = logging.getLogger(__name__)


# Raised when the model hit its output-token cap mid-JSON (finish_reason=length).
# With temperature=0 a retry reproduces the identical truncation byte-for-byte
# (measured 3x on 2026-10-22), so the tenacity decorators below deliberately
# never retry this type.
class LLMResponseTruncated(Exception):
    pass

# Measured 2026-10-22 on the prod endpoint: glm-4-flash generates at ~15-17 tok/s
# and a full CV JSON is 4-6K tokens, i.e. up to ~7 minutes. The endpoint sends no
# body until generation completes, so the read timeout covers the whole generation;
# the previous 180s killed every long-CV extraction before it could finish.
LLM_CV_READ_TIMEOUT_SECONDS = 420.0
LLM_JD_READ_TIMEOUT_SECONDS = 60.0
LLM_CONNECT_TIMEOUT_SECONDS = 20.0


# Builds the wait limit for one model call. Connect stays short so a dead network fails fast.
def llm_call_timeout(read_seconds: float) -> httpx.Timeout:
    return httpx.Timeout(read_seconds, connect=LLM_CONNECT_TIMEOUT_SECONDS)


# Wait used for CV parsing and CV refinement.
def cv_llm_timeout() -> httpx.Timeout:
    return llm_call_timeout(LLM_CV_READ_TIMEOUT_SECONDS)


# Wait used for job-ad refinement and other short calls.
def jd_llm_timeout() -> httpx.Timeout:
    return llm_call_timeout(LLM_JD_READ_TIMEOUT_SECONDS)


# Builds an httpx client that verifies TLS with the OS certificate store.
def _os_trust_http_client() -> httpx.Client:
    # The client ceiling is the longer CV wait. Each call still passes its own limit.
    return httpx.Client(
        verify=ssl.create_default_context(),
        timeout=cv_llm_timeout(),
    )


class LLMClient:
    """Async wrapper around Zhipu AI SDK."""

    # Builds the Zhipu SDK client from process settings.
    def __init__(self) -> None:
        self._client = ZhipuAiClient(
            api_key=settings.zai_api_key,
            base_url=settings.llm_base_url,
            # The zai SDK silently re-fires each request up to 3 more times inside
            # one create() call (ZAI_DEFAULT_MAX_RETRIES=3). Stacked below the
            # engine-level retries that produced the 2026-10-22 stall: one create()
            # could reach 4 HTTP attempts x 180s x tenacity x 3 with no visible
            # output. The engine tenacity policy is the only retry layer now, so
            # every attempt stays legible and bounded.
            max_retries=0,
            http_client=_os_trust_http_client(),
        )
        self._model = settings.llm_model

    # Sends a system+user chat request and returns parsed JSON.
    @retry(wait=wait_exponential(multiplier=1, min=1, max=8), stop=stop_after_attempt(3), retry=retry_if_not_exception_type(LLMResponseTruncated), reraise=True)
    async def chat_completion(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        response_format: dict[str, str] | None = None,
        temperature: float = 0,
        seed: int = 42,
        timeout: httpx.Timeout | float | None = None,
        max_tokens: int | None = None,
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
            timeout=timeout,
            max_tokens=max_tokens,
        )

    # Sends chat messages. Omitting timeout uses the shorter job-ad wait, not the CV wait.
    @retry(wait=wait_exponential(multiplier=1, min=1, max=8), stop=stop_after_attempt(3), retry=retry_if_not_exception_type(LLMResponseTruncated), reraise=True)
    async def chat_completion_messages(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        response_format: dict[str, str] | None = None,
        temperature: float = 0,
        seed: int = 42,
        allow_json_repair: bool = True,
        timeout: httpx.Timeout | float | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        request_timeout = jd_llm_timeout() if timeout is None else timeout
        request_kwargs: dict[str, Any] = {
            "model": model or self._model,
            "messages": [
                {"role": item["role"], "content": item["content"]}
                for item in messages
            ],
            "temperature": temperature,
            "response_format": response_format,
            "seed": seed,
            "timeout": request_timeout,
        }
        if max_tokens is not None:
            # Bounded output keeps generation time under the read timeout; a
            # cut-off JSON object is repaired locally by _salvage_truncated_json.
            request_kwargs["max_tokens"] = max_tokens
        try:
            response = await asyncio.to_thread(self._client.chat.completions.create, **request_kwargs)
        except TypeError:
            # Some model endpoints may not accept seed/response_format/max_tokens args.
            request_kwargs.pop("seed", None)
            request_kwargs.pop("response_format", None)
            request_kwargs.pop("max_tokens", None)
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

        choice = response.choices[0] if response.choices else None
        content = choice.message.content if choice else None
        if not content:
            raise ValueError("LLM returned empty content.")
        if getattr(choice, "finish_reason", None) == "length":
            # Deterministic dead end: a retry reproduces the same cut byte-for-byte
            # with temperature=0. cv-parser records the note and falls back to the
            # rules path immediately instead of burning the retry quota.
            raise LLMResponseTruncated(
                "LLM output hit the model token cap (finish_reason=length); llm_output_truncated=true"
            )

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
                        timeout=request_timeout,
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
            # A response cut off mid-object leaves one unclosed brace; closing
            # it locally avoids both the LLM repair call and a rule fallback.
            salvaged = LLMClient._salvage_truncated_json(fenced)
            if salvaged is not None:
                return salvaged
            raise json.JSONDecodeError("No JSON object found", candidate, 0)
        loaded = json.loads(json_block)
        if not isinstance(loaded, dict):
            raise json.JSONDecodeError("Top-level JSON is not an object", json_block, 0)
        return loaded

    # Closes an unterminated JSON object left by a truncated model response.
    @staticmethod
    def _salvage_truncated_json(text: str) -> dict[str, Any] | None:
        start = text.find("{")
        if start == -1:
            return None
        stack: list[str] = []
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
            elif ch in "{[":
                stack.append(ch)
            elif ch in "}]":
                if stack:
                    stack.pop()
        if not stack and not in_string:
            return None
        candidate = text[start:].rstrip()
        # A cut can also leave a trailing separator or an orphan key ("c": or ,"c"),
        # so strip those before closing the open brackets.
        while True:
            while candidate and candidate[-1] in ",:":
                candidate = candidate[:-1].rstrip()
            if candidate.endswith('"'):
                opening = candidate.rfind('"', 0, len(candidate) - 1)
                if opening == -1:
                    break
                candidate = candidate[:opening].rstrip()
                continue
            break
        if in_string:
            candidate += '"'
        candidate += "".join("}" if ch == "{" else "]" for ch in reversed(stack))
        try:
            loaded = json.loads(candidate)
        except json.JSONDecodeError:
            return None
        return loaded if isinstance(loaded, dict) else None

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
        timeout: httpx.Timeout | float | None = None,
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
            timeout=timeout,
        )
