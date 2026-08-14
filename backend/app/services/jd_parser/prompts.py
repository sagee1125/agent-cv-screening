from __future__ import annotations

import json
from typing import Any

JD_SKILL_REFINER_SYSTEM_PROMPT = """You are a Job Description skill normalizer.

Task:
- Read only the provided preprocessed JD payload.
- Produce final `must_skills` and `preferred_skills`.
- Keep output concise and deterministic.

Rules:
- Return ONE valid JSON object only, no markdown.
- Use explicit evidence in payload, do not invent facts.
- Keep each skill as lowercase canonical label.
- Prefer concrete technical skills over generic soft skills.
- `must_skills` and `preferred_skills` must not overlap.
- Max 5 skills per bucket.
- If confidence is low, return fewer items instead of guessing.
"""

JD_SKILL_REFINER_OUTPUT_SCHEMA: dict[str, Any] = {
    "must_skills": ["python", "sql"],
    "preferred_skills": ["docker", "aws"],
    "reasoning_trace": [
        {
            "skill": "python",
            "bucket": "must",
            "evidence": "experience with python and fastapi",
            "confidence": 0.92,
        }
    ],
}

JD_SKILL_REFINER_USER_PROMPT_TEMPLATE = """Refine the JD skills from this preprocessed payload.

Return JSON with keys:
- must_skills: string[]
- preferred_skills: string[]
- reasoning_trace: {{skill, bucket, evidence, confidence}}[]

Constraints:
- bucket must be "must" or "preferred"
- confidence is 0~1
- max 8 reasoning_trace items

Preprocessed payload JSON:
{payload_json}
"""


def build_jd_skill_refiner_user_prompt(preprocessed_payload: dict[str, Any]) -> str:
    payload_json = json.dumps(preprocessed_payload, ensure_ascii=False)
    return JD_SKILL_REFINER_USER_PROMPT_TEMPLATE.format(payload_json=payload_json)

