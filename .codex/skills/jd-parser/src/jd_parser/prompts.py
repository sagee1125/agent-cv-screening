# LLM prompts for JD skill refinement.
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
- Do not include spoken or written languages (English, Chinese, Cantonese, etc.).
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


def build_jd_structure_user_prompt(jd_text: str, preprocessed_payload: dict[str, Any]) -> str:
    """Ask the model to fill the full requirement structure from the advert and the rule evidence."""
    payload_json = json.dumps(preprocessed_payload, ensure_ascii=False)
    clipped = jd_text[:12000]
    return f"""Read the job advertisement and the rule-parser evidence. Return ONE JSON object.

The evidence is hints only. The advertisement is the source of truth.

Keys (fill every bucket the advertisement states; omit only what the text does not say):
- must_skills: string[] of concrete skills the applicant must have
- preferred_skills: string[] of advantage-only skills
- education: {{"minimum_degree": "bachelor"|"master"|"phd"|"none", "field_of_study": string, "is_mandatory": bool}}
- experience: {{"minimum_years": number|null, "raw_text": string}}
- languages: [{{"language": string, "level": "native"|"fluent"|"business"|"basic", "is_mandatory": bool}}]
- visa: {{"requirement_type": "required"|"not_required"|"unknown", "target_region": string|null}}
- reasoning_trace: [{{"skill", "bucket", "evidence", "confidence"}}]

Rules:
- A good honours degree is minimum_degree "bachelor" and is_mandatory true.
- "three or more years" is minimum_years 3.
- An advantage clause applies only to the skill or language it modifies. English and Chinese stated as a command stay mandatory when Putonghua is the advantage.
- Do not emit a skill from a duty verb or from an organisation name.
- Do not emit Microsoft Teams unless the advertisement says Microsoft Teams.
- Do not include spoken languages inside must_skills or preferred_skills.
- Use names the text actually states.

Advertisement:
{clipped}

Evidence JSON:
{payload_json}
"""


def build_jd_skill_refiner_user_prompt(preprocessed_payload: dict[str, Any]) -> str:
    """Build the legacy skill-only refiner prompt still used by the REST hybrid provider."""
    payload_json = json.dumps(preprocessed_payload, ensure_ascii=False)
    return JD_SKILL_REFINER_USER_PROMPT_TEMPLATE.format(payload_json=payload_json)

