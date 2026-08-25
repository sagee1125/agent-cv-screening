# Local Qwen3-0.6B fine-tuned JD extractor as a pluggable enrichment provider.
from __future__ import annotations

import importlib.util
import logging
from typing import Any

from app.config import settings
from app.core.llm_client import LLMClient
from jd_parser.providers.base import JDEnrichmentProvider, JDEnrichmentResult

logger = logging.getLogger(__name__)


class QwenJDExtractorProvider(JDEnrichmentProvider):
    """Extracts rich JD overview fields with a local fine-tuned Qwen model."""

    name = "qwen"

    def __init__(
        self,
        model_id: str | None = None,
        max_new_tokens: int | None = None,
        device: str | None = None,
    ) -> None:
        """Store model settings; the model itself loads lazily on first use."""
        self._model_id = model_id or settings.jd_qwen_model_id
        self._max_new_tokens = max_new_tokens or settings.jd_qwen_max_new_tokens
        self._device = device or settings.jd_qwen_device
        self._tokenizer: Any = None
        self._model: Any = None
        self._use_cuda = False

    @classmethod
    def is_available(cls) -> bool:
        """Return True when torch and transformers are importable."""
        return (
            importlib.util.find_spec("torch") is not None
            and importlib.util.find_spec("transformers") is not None
        )

    def _ensure_loaded(self) -> None:
        """Load the tokenizer and model once, lazily, with a clear error if deps are missing."""
        if self._model is not None:
            return
        if not self.is_available():
            raise RuntimeError(
                "Qwen provider requires torch and transformers; "
                "install with: pip install torch transformers accelerate"
            )
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        logger.info("Loading Qwen JD extractor model %s (first call may take a while)...", self._model_id)
        self._tokenizer = AutoTokenizer.from_pretrained(self._model_id)
        self._use_cuda = torch.cuda.is_available() and self._device in ("auto", "cuda")
        dtype = torch.bfloat16 if self._use_cuda else torch.float32
        self._model = AutoModelForCausalLM.from_pretrained(self._model_id, torch_dtype=dtype)
        self._model.eval()
        if self._use_cuda:
            self._model = self._model.to("cuda")

    async def _generate_json(self, jd_text: str) -> dict[str, Any]:
        """Run the local model on JD text and parse its JSON output."""
        self._ensure_loaded()
        import torch

        messages = [{"role": "user", "content": jd_text[:8000]}]
        prompt = self._tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = self._tokenizer(prompt, return_tensors="pt", truncation=True, max_length=8192)
        if getattr(self, "_use_cuda", False):
            inputs = {key: value.to("cuda") for key, value in inputs.items()}
        with torch.no_grad():
            outputs = self._model.generate(
                **inputs,
                max_new_tokens=self._max_new_tokens,
                do_sample=False,
                pad_token_id=self._tokenizer.eos_token_id,
            )
        decoded = self._tokenizer.decode(
            outputs[0][inputs["input_ids"].shape[1]:],
            skip_special_tokens=True,
        )
        return LLMClient._parse_json_relaxed(decoded)

    async def refine(
        self,
        *,
        jd_text: str,
        preprocessed_payload: dict[str, Any],
        rule_structured: dict[str, Any],
    ) -> JDEnrichmentResult:
        try:
            raw = await self._generate_json(jd_text)
        except Exception as exc:
            logger.warning("Qwen JD extraction failed: %s", exc)
            return JDEnrichmentResult(
                provider_name=self.name,
                error=str(exc),
                notes=["Qwen extraction failed; kept rule output."],
            )
        overview = _build_overview(raw)
        return JDEnrichmentResult(
            provider_name=self.name,
            jd_overview=overview,
            raw_output=raw,
            notes=["Qwen overview extracted; must/preferred skills kept from rule parser."],
        )


def _build_overview(raw: dict[str, Any]) -> dict[str, Any]:
    """Map the Qwen model JSON onto the project's JD overview schema."""
    def pick(*keys: str) -> Any:
        """Return the first non-empty value among candidate keys."""
        for key in keys:
            value = raw.get(key)
            if value not in (None, "", [], {}):
                return value
        return None

    return {
        "job_titles": pick("job_titles", "job_title", "titles", "title"),
        "company": {
            "name": pick("company_name", "company", "companyName"),
            "website": pick("company_website", "website", "companyWebsite"),
        },
        "skills": pick("technical_skills", "skills", "all_skills", "skill"),
        "compensation": pick("compensation", "salary"),
        "location": pick("location"),
        "work_mode": pick("work_mode", "workMode"),
        "experience": pick("experience"),
        "qualification": pick("qualification", "education"),
        "industry": pick("industry"),
        "posted_date": pick("posted_date", "postedDate"),
        "notice_period": pick("notice_period", "noticePeriod"),
        "job_type": pick("job_type", "jobType"),
    }