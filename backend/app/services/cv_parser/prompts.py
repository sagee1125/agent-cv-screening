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
