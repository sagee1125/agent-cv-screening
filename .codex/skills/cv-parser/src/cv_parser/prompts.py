# Defines privacy-safe prompts and canonical skill hints for CV parsing.
from __future__ import annotations

# Canonical skills list used by prompt hints and fallback extraction.
KNOWN_SKILLS = {
    "python",
    "java",
    "javascript",
    "typescript",
    "sql",
    "mysql",
    "postgresql",
    "mongodb",
    "redis",
    "docker",
    "kubernetes",
    "aws",
    "azure",
    "gcp",
    "fastapi",
    "flask",
    "django",
    "pytorch",
    "tensorflow",
    "scikit-learn",
    "react",
    "vue",
    "node.js",
    "nodejs",
    "golang",
    "go",
    "c++",
    "c#",
    "rust",
    "linux",
}

PARSER_SYSTEM_PROMPT = """You are a CV parser. Extract the following fields from the candidate's CV and output valid JSON.

Output schema:
{
  "summary": string | null,     # One short profile blurb (objective/summary), max ~2 sentences
  "location": {                 # Current location/residence, or null if not stated
    "raw": string,
    "country": string | null,
    "city": string | null
  },
  "work_authorization": {       # Work eligibility for the region where the job is, or null
    "status": string,            # one of "citizen"|"permanent_resident"|"has_work_permit"|"requires_sponsorship"|"unknown"
    "raw": string | null         # the exact phrase that supports the status, or null
  },
  "skills": [string],          # Technical skills / technologies only (NOT spoken languages)
  "languages": [               # Spoken/written languages, separate from technical skills
    {"language": string, "level": string | null}   # level: "basic"|"business"|"fluent"|"native" or null
  ],
  "education": [
    {
      "school": string,        # Full institution name only
      "degree": string,         # Raw label as shown, e.g., "MEng", "BSc", "PhD"
      "major": string,          # Field of study
      "period": string,         # Date range as shown (e.g., "09/2018 - 06/2022")
      "start_date": string,     # ISO month "YYYY-MM" if determinable, else null
      "end_date": string        # ISO month "YYYY-MM" if determinable, else null
    }
  ],
  "experience": [
    {
      "company": string,
      "job_title": string,
      "period": string,         # Raw date range as shown
      "start_date": string,     # ISO month "YYYY-MM" if determinable, else null
      "end_date": string,       # ISO month "YYYY-MM", or "Present" if ongoing, else null
      "is_current": boolean,    # true if the job is ongoing (currently held)
      "description": string,    # Full combined description, not split by lines
      "skills_used": [string]   # Technical skills mentioned in this role (exact terms, no languages)
    }
  ],
  "projects": [                 # Personal/academic/side projects (often the main skill evidence for new grads)
    {
      "name": string | null,
      "description": string,
      "period": string | null,
      "skills_used": [string]   # Technical skills used in this project (exact terms, no languages)
    }
  ],
  "certifications": [          # Professional certifications/licenses
    {"name": string, "issuer": string | null, "year": string | null}
  ],
  "publications": [
    {"title": string, "journal": string | null, "year": string | null}
  ]
}


Rules:
- Name, email, and phone have already been removed locally. Do not return or infer identity fields.
- Only extract information explicitly stated in the CV. Do not infer.
- For skills, extract exact terms used (do not standardize). Do NOT include spoken languages here.
- Put spoken/written languages (English, Chinese, Mandarin, etc.) in "languages", NOT in "skills".
- Each education entry = ONE degree. Merge all info about that degree into ONE object.
- Each experience entry = ONE job. Merge ALL bullet points and descriptions into ONE description string.
- Do NOT split descriptions across multiple objects.
- For start_date/end_date, convert the visible date to ISO "YYYY-MM" when possible. Use null if uncertain.
- For an ongoing job, set end_date to "Present" and is_current to true.
- For skills_used (experience and projects), list only concrete technical skills mentioned there.
- For work_authorization.status, use "unknown" when the CV does not state work eligibility. Do not guess.
- For location, only fill country/city when explicitly stated; otherwise put the raw phrase and leave the rest null.
- If you cannot determine a field, use null (not empty string).
- Output valid JSON only.No explanations.
"""

PARSER_VISION_USER_PROMPT = """Parse this CV into the target JSON schema.

Important:
- Read text directly from the provided page images.
- If one field is missing, set it to null or empty array.
- Return JSON only, no markdown fences."""

PARSER_VISION_FOCUS_PROMPT = """Re-read the same CV images and focus on timeline accuracy.

Skills extraction hints - look for these technologies (exact match or similar):
{known_skills}

Important:
- Group experience by job: all bullets under one company belong in ONE experience object.
- Group education by degree: each degree is ONE education object.
- For each experience, combine the full description into a single string.
- For each experience, set start_date/end_date in ISO "YYYY-MM" when visible; use "Present" for ongoing jobs.
- Put spoken/written languages in "languages", NOT in "skills".
- Return JSON only, no markdown fences.
""".format(known_skills=", ".join(sorted(KNOWN_SKILLS)[:50]))

CV_REFINER_SYSTEM_PROMPT = """You refine a draft CV parse into accurate structured JSON.

The CV text is privacy-redacted (name, email, phone, and address removed). A first-pass parser produced a draft.
Your job: fix experience timeline and split work history correctly; expand skills from explicit CV text.

Output ONE JSON object with the same schema as the draft (summary, skills, languages, education,
experience, projects, certifications, publications, location, work_authorization).

Rules:
- Do NOT return name, email, or phone.
- Each experience entry = ONE job/employer period. Split merged jobs into separate objects.
- Merge all bullets for the same job into one description string.
- Set start_date and end_date as ISO "YYYY-MM" when the CV states dates; use "Present" for ongoing roles.
- If the CV states "N years experience" without dates, infer a Present-ended range only when no better dates exist.
- skills: concrete technical/professional terms explicitly in the CV (not spoken languages).
- languages: every spoken/written language the CV states (English, Chinese, Cantonese, Mandarin/Putonghua), even when it appears in a sentence rather than a skills list.
- For each job, set skills_used to technical terms that appear in that job's description. Do not add a skill the CV text does not contain.
- Use only explicit CV facts; do not invent employers, degrees, or tools.
- Return valid JSON only, no markdown."""

CV_REFINER_MAX_CHARS = 14_000


# Builds the user message for hybrid CV refinement (redacted text + draft + optional JD).
def build_cv_refiner_user_prompt(
    masked_cv_text: str,
    draft_structured: dict,
    jd_text: str | None,
) -> str:
    import json

    from cv_parser.helpers import compress_cv_text

    clipped = compress_cv_text(raw_text=masked_cv_text, max_chars=CV_REFINER_MAX_CHARS)
    draft_json = json.dumps(draft_structured, ensure_ascii=False, indent=2)
    if len(draft_json) > 8000:
        draft_json = draft_json[:8000] + "\n... (draft truncated)"
    jd_block = ""
    if jd_text and jd_text.strip():
        jd_block = f"\n\nJob context (for relevance only, do not copy requirements as CV facts):\n{jd_text[:4000]}\n"
    return f"""Refine this draft CV parse using the redacted CV text below.

Focus:
1) Split experience into one object per job with correct company/title when visible.
2) Fill start_date/end_date (ISO YYYY-MM) or Present.
3) Expand skills and per-job skills_used from explicit mentions.

Draft JSON (first pass):
{draft_json}
{jd_block}
Redacted CV text:
{clipped}
"""
