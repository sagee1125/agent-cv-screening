# JD Parsing & Weighting Logic: Technical Specification

**Version:** v1.0
**Status:** Ready for Implementation
**Last Updated:** 2026-08-14

---

## 1. Overview

This document defines the end-to-end logic for extracting structured requirements from an unstructured Job Description (JD), normalizing skills, assigning weights, and calculating candidate match scores.

---

### 1.1 The Complete Pipeline

Step 0: Raw JD Text (Unstructured Input)

- Example: "Senior Backend Engineer: 5+ years Python, AWS required. Kubernetes preferred. Master's degree preferred."

Step 1: LLM Extraction (JD Parser Agent)

- Input: Raw JD text
- Output: Structured JSON (skills, experience, education, language, visa)
- Requires: LLM (OpenAI / Claude)

Step 2: Skill Normalizer

- Input: Raw skill names from LLM (e.g., "python3", "k8s", "py")
- Output: Standardized skill names (e.g., "Python", "Kubernetes")
- Requires: Mapping Table (NO LLM)

Step 3: Skill Taxonomy Classification

- Input: Standardized skill names
- Output: Category labels (e.g., "programming_language", "cloud")
- Requires: Pre-defined Taxonomy Tree (NO LLM)

Step 4: Skill Weighting (Rank-Order)

- Input: HR-dragged skill order
- Output: Numeric weights (0-1) for each skill
- Requires: Mathematical calculation (NO LLM)

Step 5: Experience Quality Scoring

- Input: Candidate CV experience text + target skill
- Output: Quality score (0-100)
- Requires: Rule Engine (NO LLM for MVP)

Step 6: Final Candidate Match Score

- Formula: Skill Match (60%) + Experience Quality (20%) + Education (10%) + Language (10%)
- Output: Score 0-100

---

## 2. Step 1: LLM Extraction (JD Parser Agent)

### 2.1 Purpose

Extract structured data from unstructured JD text using a Large Language Model.

### 2.2 Input

- Raw JD text (string, plain text format)

### 2.3 Output JSON Schema (Fixed)

{
"must_have_skills": ["Python", "AWS", "Docker"],
"preferred_skills": ["Kubernetes", "TypeScript"],
"years_of_experience": 5,
"education": "Master",
"language": {
"type": "English",
"proficiency": "Fluent"
},
"visa_sponsorship": true,
"certifications": ["AWS Certified Solutions Architect"]
}

### 2.4 System Prompt Template

You are a JD parsing expert. Extract structured information from the given job description.

Classification Rules:

- MUST_HAVE: Skills preceded by "must have", "required", "essential", "mandatory"
- PREFERRED: Skills preceded by "nice to have", "preferred", "plus", "desired"
- If no modifier is present, default to PREFERRED (avoid false exclusion)

Output only valid JSON. Do not add any additional text.

### 2.5 API Call Configuration (Python Example)

response = openai.chat.completions.create(
model="gpt-4o-mini",
messages=[
{"role": "system", "content": SYSTEM_PROMPT},
{"role": "user", "content": jd_text}
],
temperature=0,
seed=42,
response_format={"type": "json_object"}
)

### 2.6 Ensuring Output Stability

- LLM outputs different results each run -> Use temperature=0 + seed=42
- Skill names inconsistent -> Pass to Step 2 (Skill Normalizer)
- Missing fields in JSON -> Validate against schema; trigger HR follow-up
- Hallucinated skills -> Post-processing: validate against Skill Taxonomy

---

## 3. Step 2: Skill Normalizer

### 3.1 Purpose

Map inconsistent skill names from LLM to a standardized format.

### 3.2 Why This Is Necessary

- LLM may output: "python", "Python", "python3", "py" -> all should be "Python"
- Candidate CVs also use inconsistent naming
- Matching requires a unified "skill name" as the join key

### 3.3 Implementation: Mapping Table (MVP)

SKILL_NORMALIZATION_MAP = { # Programming Languages
"python": "Python",
"python3": "Python",
"py": "Python",
"java": "Java",
"javascript": "JavaScript",
"js": "JavaScript",
"typescript": "TypeScript",
"ts": "TypeScript",
"golang": "Go",
"go": "Go",
"rust": "Rust",
"c++": "C++",
"cpp": "C++",
"c#": "C#",
"csharp": "C#",

    # Cloud & Infrastructure
    "aws": "AWS",
    "amazon web services": "AWS",
    "azure": "Azure",
    "gcp": "GCP",
    "google cloud": "GCP",
    "kubernetes": "Kubernetes",
    "k8s": "Kubernetes",
    "docker": "Docker",
    "terraform": "Terraform",
    "ansible": "Ansible",

    # Frameworks & Libraries
    "react": "React",
    "reactjs": "React",
    "vue": "Vue.js",
    "vuejs": "Vue.js",
    "angular": "Angular",
    "django": "Django",
    "flask": "Flask",
    "spring": "Spring Boot",
    "springboot": "Spring Boot",
    "express": "Express",
    "node": "Node.js",
    "nodejs": "Node.js",

    # Databases
    "postgresql": "PostgreSQL",
    "postgres": "PostgreSQL",
    "mysql": "MySQL",
    "mongodb": "MongoDB",
    "mongo": "MongoDB",
    "redis": "Redis",
    "elasticsearch": "Elasticsearch",
    "cassandra": "Cassandra",

    # Soft Skills
    "leadership": "Leadership",
    "communication": "Communication",
    "problemsolving": "Problem Solving",
    "problem solving": "Problem Solving",
    "teamwork": "Teamwork",
    "collaboration": "Collaboration"

}

### 3.4 Normalization Function (Python)

def normalize_skill(skill_name: str) -> str:
normalized = skill_name.lower().strip()
if normalized in SKILL_NORMALIZATION_MAP:
return SKILL_NORMALIZATION_MAP[normalized]
return skill_name.strip().title()

### 3.5 Maintenance Strategy

- Initial list: 50+ common skills (provided above)
- Ongoing: HR reports unknown skills -> Add to mapping table
- Future: Auto-suggest via LLM for unknown skills

---

## 4. Step 3: Skill Taxonomy Classification

### 4.1 Purpose

Categorize skills into groups for analytics, diagnosis, and future weighting adjustments.

### 4.2 Taxonomy Tree (MVP)

SKILL_TAXONOMY = {
"programming_language": {
"display_name": "Programming Language",
"skills": ["Python", "Java", "JavaScript", "TypeScript", "Go", "Rust", "C++", "C#"]
},
"framework_library": {
"display_name": "Framework & Library",
"skills": ["React", "Vue.js", "Angular", "Django", "Flask", "Spring Boot", "Express", "Node.js"]
},
"cloud_infrastructure": {
"display_name": "Cloud & Infrastructure",
"skills": ["AWS", "Azure", "GCP", "Docker", "Kubernetes", "Terraform", "Ansible"]
},
"database": {
"display_name": "Database",
"skills": ["PostgreSQL", "MySQL", "MongoDB", "Redis", "Elasticsearch", "Cassandra"]
},
"soft_skill": {
"display_name": "Soft Skill",
"skills": ["Leadership", "Communication", "Problem Solving", "Teamwork", "Collaboration"]
},
"certification": {
"display_name": "Certification",
"skills": ["CKA", "CKAD", "AWS Certified", "PMP", "SCJP"]
}
}

### 4.3 Classification Function (Python)

def get_skill_taxonomy(skill_name: str) -> str:
skill_name = normalize_skill(skill_name)
for category, data in SKILL_TAXONOMY.items():
if skill_name in data["skills"]:
return category
return "unknown"

---

## 5. Step 4: Skill Weighting (Rank-Order)

### 5.1 Purpose

Convert HR's drag-and-drop order into numeric weights for each skill.

### 5.2 Why Rank-Order Weighting

- HR cannot assign numeric weights directly (too complex)
- Dragging is intuitive: higher position = higher importance
- Exponential decay creates meaningful differentiation

### 5.3 Formula

Weight(i) = decay_factor ^ i

Where:

- i = position index (0-based, 0 = highest)
- decay_factor = 0.8 (configurable, each rank drops 20%)

### 5.4 Python Implementation

import math

def calculate_rank_weights(ranked_skills: list, decay_factor: float = 0.8) -> dict:
weights = {}
for i, skill in enumerate(ranked_skills):
weights[skill] = math.pow(decay_factor, i)
return weights

### 5.5 Example Output

Input: ranked_skills = ["Python", "AWS", "Docker", "Kubernetes"]
Output:
{
"Python": 1.0,
"AWS": 0.8,
"Docker": 0.64,
"Kubernetes": 0.512
}

### 5.6 Normalization (Optional)

To make weights sum to 1:
def normalize_weights(weights: dict) -> dict:
total = sum(weights.values())
return {k: v / total for k, v in weights.items()}

Output (normalized):
{
"Python": 0.338,
"AWS": 0.270,
"Docker": 0.216,
"Kubernetes": 0.176
}

### 5.7 HR Workflow

1. JD parsed -> Skills displayed in LLM extraction order
2. HR drags to reorder (highest = most important)
3. Each drag triggers API call to update weight_config_json
4. All candidates recalculated asynchronously with new weights

---

## 6. Step 5: Experience Quality Scoring

### 6.1 Purpose

Evaluate the depth of a candidate's experience with a specific skill, beyond just years.

### 6.2 Why This Matters

- Both candidates have "5 years Python" but one built large-scale systems, the other wrote scripts
- Years alone is insufficient for quality assessment

### 6.3 MVP Approach: Rule Engine (NO LLM)

- Faster and cheaper
- Fully explainable to HR (can show score breakdown)
- Consistent results across runs

### 6.4 Scoring Components

Component 1: Years of Experience (0-40 points)

- > = 5 years: 40 points
- > = 3 years: 25 points
- > = 1 year: 10 points
- < 1 year: 0 points

Component 2: Depth Keywords (bonus/penalty)

- Positive keywords (add points):

  - "architecture": +15
  - "design": +12
  - "scale", "scalability": +12
  - "performance", "optimization": +10
  - "production": +10
  - "lead", "led": +8
  - "mentor": +8
  - "deployment": +8
  - "testing": +5

- Negative keywords (subtract points):
  - "script", "scripts": -10
  - "basic": -10
  - "tutorial": -10
  - "beginner": -10

### 6.5 Python Implementation

def score_experience_quality(experience_text: str, required_skill: str) -> float:
text_lower = experience_text.lower()
score = 0.0

    # Component 1: Years extraction
    years = extract_years_from_text(experience_text)  # Custom parser
    if years >= 5:
        score += 40
    elif years >= 3:
        score += 25
    elif years >= 1:
        score += 10

    # Component 2: Depth keywords
    depth_keywords = {
        "architecture": 15,
        "design": 12,
        "scale": 12,
        "scalability": 12,
        "performance": 10,
        "optimization": 10,
        "production": 10,
        "lead": 8,
        "led": 8,
        "mentor": 8,
        "deployment": 8,
        "testing": 5,
        "script": -10,
        "scripts": -10,
        "basic": -10,
        "tutorial": -10,
        "beginner": -10
    }

    for keyword, weight in depth_keywords.items():
        if keyword in text_lower:
            score += weight

    return max(0, min(100, score))

### 6.6 Year Extraction Helper

import re

def extract_years_from_text(text: str) -> float:
patterns = [
r'(\d+)\+?\s*years?',
r'(\d+)\s*\+\s*years?',
r'(\d+\.?\d*)\s*years?'
]
for pattern in patterns:
match = re.search(pattern, text, re.IGNORECASE)
if match:
return float(match.group(1))
return 0.0

### 6.7 Future Enhancement: LLM-based Scoring (V2)

- For more nuanced evaluation
- Use LLM with low temperature for consistency
- Cache results to reduce API costs

---

## 7. Final Candidate Match Score

### 7.1 Formula

Total Score = (Skill Match _ 0.6) + (Experience Quality _ 0.2) + (Education _ 0.1) + (Language _ 0.1)

### 7.2 Component Details

Component 1: Skill Match (60%)

- Must-have skills: Candidate must match 100%, otherwise auto-classified as "Low Fit"
- Preferred skills: Weighted average based on HR-defined weights
- Formula:
  skill_score = sum(matched_preferred_weight) / sum(all_preferred_weight) \* 100

Component 2: Experience Quality (20%)

- Average of experience quality scores for all matched skills
- If candidate has no experience for a required skill, score = 0 for that skill

Component 3: Education (10%)

- Candidate education >= JD requirement: 100 points
- Candidate education < JD requirement: 0 points
- Education level ordering: PhD > Master > Bachelor > Associate > High School

Component 4: Language (10%)

- Fully meets requirement: 100 points
- Partially meets (e.g., required Fluent, candidate Business): 50 points
- Does not meet: 0 points

### 7.3 Python Implementation

def calculate_match_score(job_requirements: dict, candidate_data: dict, skill_weights: dict) -> dict: # 1. Skill Match
must_skills = job_requirements.get("must_have_skills", [])
preferred_skills = job_requirements.get("preferred_skills", [])
candidate_skills = candidate_data.get("skills", [])

    # Check must-haves
    missing_must = [s for s in must_skills if s not in candidate_skills]
    if missing_must:
        fit_level = "low"
        skill_score = 0
    else:
        # Calculate preferred match
        total_weight = 0
        matched_weight = 0
        for skill in preferred_skills:
            weight = skill_weights.get(skill, 0)
            total_weight += weight
            if skill in candidate_skills:
                matched_weight += weight
        skill_score = (matched_weight / total_weight * 100) if total_weight > 0 else 100

    # 2. Experience Quality
    exp_scores = []
    for skill in must_skills + preferred_skills:
        if skill in candidate_skills:
            exp_text = candidate_data.get("experience_text", "")
            exp_scores.append(score_experience_quality(exp_text, skill))
    exp_score = sum(exp_scores) / len(exp_scores) if exp_scores else 0

    # 3. Education
    edu_order = {"PhD": 4, "Master": 3, "Bachelor": 2, "Associate": 1, "High School": 0}
    required_edu = job_requirements.get("education", "Bachelor")
    candidate_edu = candidate_data.get("education", "Bachelor")
    edu_score = 100 if edu_order.get(candidate_edu, 0) >= edu_order.get(required_edu, 0) else 0

    # 4. Language
    required_lang = job_requirements.get("language", {})
    candidate_lang = candidate_data.get("language", {})
    if required_lang.get("type") == candidate_lang.get("type"):
        prof_order = {"Native": 3, "Fluent": 2, "Business": 1, "Basic": 0}
        required_prof = required_lang.get("proficiency", "Fluent")
        candidate_prof = candidate_lang.get("proficiency", "Basic")
        lang_score = 100 if prof_order.get(candidate_prof, 0) >= prof_order.get(required_prof, 0) else 50
    else:
        lang_score = 0

    # 5. Total
    total_score = (skill_score * 0.6) + (exp_score * 0.2) + (edu_score * 0.1) + (lang_score * 0.1)

    # 6. Fit Level
    if total_score >= 80:
        fit_level = "high"
    elif total_score >= 60:
        fit_level = "medium"
    else:
        fit_level = "low"

    return {
        "match_score": round(total_score, 2),
        "score_breakdown": {
            "skill_score": round(skill_score, 2),
            "experience_score": round(exp_score, 2),
            "education_score": edu_score,
            "language_score": lang_score
        },
        "fit_level": fit_level,
        "missing_must_skills": missing_must
    }

---

## 8. Infrastructure Readiness Checklist

Before implementing, ensure the following are prepared:

| #   | Item                              | Description                                            | Priority |
| :-- | :-------------------------------- | :----------------------------------------------------- | :------- |
| 1   | LLM API Key                       | OpenAI or Anthropic API access                         | P0       |
| 2   | Skill Normalization Mapping Table | Minimum 50 common skills (see Section 3.3)             | P0       |
| 3   | JD Parser System Prompt           | Fixed prompt template (see Section 2.4)                | P0       |
| 4   | JD Output JSON Schema             | Fixed schema for frontend/backend alignment            | P0       |
| 5   | Skill Taxonomy Tree               | 5-8 categories with 5-10 skills each (see Section 4.2) | P1       |
| 6   | Weight Calculation Formula        | Rank-Order algorithm (see Section 5.3)                 | P0       |
| 7   | Experience Quality Rule Set       | Keywords + year extraction (see Section 6.4)           | P1       |
| 8   | Test JD Dataset                   | 20 real JDs for accuracy validation                    | P0       |
| 9   | Candidate CV Test Dataset         | 20 anonymized CVs for matching validation              | P0       |

---

## 9. LLM Usage Summary

| Step                            | Requires LLM? | Reason                               |
| :------------------------------ | :------------ | :----------------------------------- |
| Step 1: JD Extraction           | YES           | Unstructured text -> Structured JSON |
| Step 2: Skill Normalizer        | NO            | Pure mapping table                   |
| Step 3: Skill Taxonomy          | NO            | Pure lookup table                    |
| Step 4: Skill Weighting         | NO            | Mathematical formula                 |
| Step 5: Experience Quality      | NO (MVP)      | Rule engine; LLM optional for V2     |
| Step 6: Match Score Calculation | NO            | Deterministic formula                |

**Conclusion:** LLM is only required for JD extraction. All other steps use rules and mathematics, ensuring consistent, explainable, and low-cost results.

---

## 10. Ensuring Consistent Results Across Runs

| Layer              | Consistency Mechanism                               |
| :----------------- | :-------------------------------------------------- |
| LLM Extraction     | temperature=0, seed=42, response_format=json_object |
| Skill Normalizer   | Pure mapping table (no randomness)                  |
| Skill Taxonomy     | Pure lookup table (no randomness)                   |
| Skill Weighter     | Pure mathematical formula (no randomness)           |
| Experience Quality | Rule engine (no randomness)                         |
| Match Score        | Deterministic formula (no randomness)               |

---

## 11. Next Steps

1. Prepare Skill Normalization Mapping Table with 50+ common skills
2. Set up LLM API key and test JD extraction with 5 sample JDs
3. Build Skill Taxonomy tree (start with 5 categories)
4. Implement rank-order weighting function
5. Implement rule-based experience quality scoring
6. Test end-to-end pipeline with 20 JDs and 20 candidate CVs
7. Validate extraction accuracy against manual HR parsing (target: 90%+)

---

## 12. Appendix: Example End-to-End Flow

### Input JD Text

"Senior Backend Engineer with 5+ years of Python experience. Must have AWS. Kubernetes preferred. Nice to have TypeScript. Master's degree preferred. Fluent English required."

### Step 1: LLM Extraction Output

{
"must_have_skills": ["Python", "AWS"],
"preferred_skills": ["Kubernetes", "TypeScript"],
"years_of_experience": 5,
"education": "Master",
"language": {"type": "English", "proficiency": "Fluent"}
}

### Step 2: Skill Normalization

- "Python" -> "Python" (already standardized)
- "AWS" -> "AWS" (already standardized)
- "Kubernetes" -> "Kubernetes" (already standardized)
- "TypeScript" -> "TypeScript" (already standardized)

### Step 3: Taxonomy Classification

- "Python" -> "programming_language"
- "AWS" -> "cloud_infrastructure"
- "Kubernetes" -> "cloud_infrastructure"
- "TypeScript" -> "programming_language"

### Step 4: HR Drag Order + Weighting

HR drag order: ["Python", "AWS", "Kubernetes", "TypeScript"]
Output weights:
{
"Python": 1.0,
"AWS": 0.8,
"Kubernetes": 0.64,
"TypeScript": 0.512
}

### Step 5: Candidate Data (from CV Parser)

{
"skills": ["Python", "AWS", "Docker"],
"experience_text": "5 years building scalable Python backend services on AWS. Led team of 4 engineers.",
"education": "Master",
"language": {"type": "English", "proficiency": "Fluent"}
}

### Step 6: Match Score Calculation

- Skill Match: Must skills matched (Python, AWS) -> 100%. Preferred: Kubernetes (not matched), TypeScript (not matched) -> 0%
- Experience Quality: 85 (5 years + "scalable" + "led" keywords)
- Education: 100 (Master >= Master)
- Language: 100 (Fluent >= Fluent)

Total Score = (100 _ 0.6) + (85 _ 0.2) + (100 _ 0.1) + (100 _ 0.1) = 97.0
Fit Level = "high"
