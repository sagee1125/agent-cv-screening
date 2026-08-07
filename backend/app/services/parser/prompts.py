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
  "name": string,
  "email": string,
  "phone": string,
  "skills": [string],          # Extract from tech skills section or mentioned technologies
  "education": [
    {
      "school": string,        # Full institution name only
      "degree": string,        # e.g., "MEng", "BSc", "PhD"
      "major": string,         # Field of study
      "period": string         # Date range as shown (e.g., "09/2018 - 06/2022")
    }
  ],
  "experience": [
    {
      "company": string,
      "job_title": string,
      "period": string,
      "description": string    # Full combined description, not split by lines
    }
  ],
  "publications": [...]
}


Rules:
- Only extract information explicitly stated in the CV. Do not infer.
- For skills, extract exact terms used (do not standardize).
- Each education entry = ONE degree. Merge all info about that degree into ONE object.
- Each experience entry = ONE job. Merge ALL bullet points and descriptions into ONE description string.
- Do NOT split descriptions across multiple objects.
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
- Return JSON only, no markdown fences.
""".format(known_skills=", ".join(sorted(KNOWN_SKILLS)[:50]))
