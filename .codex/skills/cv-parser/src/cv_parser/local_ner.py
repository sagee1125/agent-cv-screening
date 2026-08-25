# Enhances local candidate-name detection with an optional on-device GLiNER model.
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any

from screening_core.config import settings

logger = logging.getLogger(__name__)
_NER_MODEL: Any | None = None
_NER_MODEL_LOCK = threading.Lock()
_NER_LOAD_FAILED = False


@dataclass(frozen=True)
class LocalNERResult:
    """Separates candidate-name values from other locally detected PII values."""

    names: tuple[str, ...]
    sensitive_values: tuple[str, ...]


# Lazily loads the configured local GLiNER checkpoint once per process.
def _get_ner_model() -> Any | None:
    global _NER_MODEL, _NER_LOAD_FAILED
    if not settings.cv_local_ner_enabled or _NER_LOAD_FAILED:
        return None
    if _NER_MODEL is not None:
        return _NER_MODEL
    with _NER_MODEL_LOCK:
        if _NER_MODEL is not None:
            return _NER_MODEL
        try:
            from gliner import GLiNER

            _NER_MODEL = GLiNER.from_pretrained(settings.cv_local_ner_model)
        except Exception:
            _NER_LOAD_FAILED = True
            logger.exception("Local GLiNER model failed to load; using header heuristics only.")
    return _NER_MODEL


# Detects names, addresses, and account identifiers with one local model pass.
def detect_local_pii(raw_text: str) -> LocalNERResult:
    model = _get_ner_model()
    if model is None:
        return LocalNERResult(names=(), sensitive_values=())

    inference_text = raw_text[: settings.cv_local_ner_max_chars]
    labels = [
        "person",
        "person name",
        "full address",
        "address",
        "social media handle",
        "username",
    ]
    try:
        entities = model.predict_entities(
            inference_text,
            labels,
            threshold=settings.cv_local_ner_threshold,
        )
    except Exception:
        logger.exception("Local GLiNER inference failed; using header heuristics only.")
        return LocalNERResult(names=(), sensitive_values=())

    ordered_entities = sorted(entities, key=lambda entity: int(entity.get("start", 0)))
    names: list[str] = []
    sensitive_values: list[str] = []
    seen_names: set[str] = set()
    seen_sensitive: set[str] = set()
    for entity in ordered_entities:
        value = " ".join(str(entity.get("text") or "").split()).strip()
        normalized = value.casefold()
        label = str(entity.get("label") or "").casefold()
        if not value:
            continue
        if label in {"person", "person name"}:
            if normalized not in seen_names:
                seen_names.add(normalized)
                names.append(value)
        elif normalized not in seen_sensitive:
            seen_sensitive.add(normalized)
            sensitive_values.append(value)
    return LocalNERResult(names=tuple(names), sensitive_values=tuple(sensitive_values))


# Provides a backward-compatible person-name-only view of local NER output.
def detect_person_names(raw_text: str) -> list[str]:
    return list(detect_local_pii(raw_text).names)
