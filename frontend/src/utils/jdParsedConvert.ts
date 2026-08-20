// Converts backend snake_case job/JD JSON into frontend camelCase view models.
import type {
  CandidateSummary,
  EducationRequirement,
  JDParsedPayload,
  JobPost,
  LanguageRequirement,
  PolyUCatalogItem,
  SkillItem,
  VisaRequirement,
  WeightConfig,
} from "../types";

type JsonObject = Record<string, unknown>;

/** Backend job row returned by /jobs endpoints. */
export type BackendJob = {
  id: string;
  title: string;
  description: string;
  jd_summary_200: string;
  head_count: number;
  status: string;
  start_date: string;
  closed_date: string | null;
  jd_parsed_json: unknown;
  weight_config_json: WeightConfig | null;
  created_at: string;
  updated_at: string;
};

/** Backend candidate row from job detail or candidate list endpoints. */
export type BackendCandidateRow = {
  candidate_id: string;
  resume_id?: string;
  candidate_name?: string;
  candidate_email?: string;
  original_filename?: string;
  source_channel: string;
  cv_parse_status: "success" | "failed" | "pending";
  extracted_data?: Record<string, unknown> | null;
  uploaded_at?: string;
  match_score?: number;
  fit_level?: "high" | "medium" | "low";
  score_breakdown?: CandidateSummary["scoreBreakdown"];
  candidate_scoring_status?: CandidateSummary["candidateScoringStatus"];
  recommendation_rank?: number | null;
  fit_band?: CandidateSummary["fitBand"];
  eligibility_status?: CandidateSummary["eligibilityStatus"];
  evidence_confidence?: number | null;
  top_strengths?: string[];
  key_gaps?: string[];
  radar_summary?: CandidateSummary["radarSummary"];
};

/** Backend PolyU catalog item from /jobs/sync-polyu/catalog. */
export type BackendPolyUCatalogItem = {
  job_code: string;
  external_ref: string;
  title: string;
  department: string;
  closing_date: string | null;
  detail_url: string;
  already_imported: boolean;
};

/** Empty JD payload used when parse succeeds but structured data is missing. */
export const EMPTY_JD_PARSED_PAYLOAD: JDParsedPayload = {
  mustSkills: [],
  preferredSkills: [],
  languageRequirements: [],
  educationRequirement: null,
  visaRequirement: null,
};

/** Returns an object record, or null when the value is not an object. */
function asObject(value: unknown): JsonObject | null {
  if (value === null || typeof value !== "object") {
    return null;
  }
  return value as JsonObject;
}

/**
 * Reads one field from stored JSON.
 * Canonical wire keys are snake_case; camelCase is accepted for legacy records.
 */
function pickField(obj: JsonObject, camel: string, snake: string): unknown {
  return obj[camel] ?? obj[snake];
}

/** Reads a boolean wire field, defaulting to false when both keys are absent. */
function pickBoolean(obj: JsonObject, camel: string, snake: string): boolean {
  const camelVal = obj[camel];
  if (typeof camelVal === "boolean") return camelVal;
  const snakeVal = obj[snake];
  if (typeof snakeVal === "boolean") return snakeVal;
  return false;
}

/** Reads a string wire field, or undefined when neither key is a string. */
function pickString(
  obj: JsonObject,
  camel: string,
  snake: string
): string | undefined {
  const value = pickField(obj, camel, snake);
  return typeof value === "string" ? value : undefined;
}

/** Extracts the human-readable source sentence from a requirement or skill item. */
function pickSourceSentence(raw: JsonObject): string | undefined {
  const direct = pickString(raw, "sourceSentence", "source_sentence");
  if (direct) return direct;
  if (typeof raw.provenance === "string") return raw.provenance;
  const provenance = asObject(raw.provenance);
  if (provenance && typeof provenance.source_sentence === "string") {
    return provenance.source_sentence;
  }
  return undefined;
}

/** Maps one backend skill object into a frontend SkillItem. */
function mapSkill(
  item: unknown,
  type: "must" | "preferred",
  index: number
): SkillItem {
  const raw = asObject(item) ?? {};
  const displayName = pickString(raw, "displayName", "display_name");
  const canonicalSkill = pickString(raw, "canonicalSkill", "canonical_skill");
  const skillId = pickString(raw, "skillId", "skill_id");
  const name = typeof raw.name === "string" ? raw.name : undefined;
  const weight = raw.weight;
  return {
    id: skillId ?? `${type}-${index + 1}`,
    name: displayName ?? canonicalSkill ?? name ?? `${type}-${index + 1}`,
    type,
    weight: typeof weight === "number" ? weight : undefined,
    sourceSentence: pickSourceSentence(raw),
  };
}

/** Maps a must/preferred skill array from the wire payload. */
function mapSkills(skills: unknown, type: "must" | "preferred"): SkillItem[] {
  if (!Array.isArray(skills)) return [];
  return skills.map((item, index) => mapSkill(item, type, index));
}

/** Maps language requirement objects, dropping items without language/level. */
function mapLanguageRequirements(value: unknown): LanguageRequirement[] {
  if (!Array.isArray(value)) return [];
  return value.reduce<LanguageRequirement[]>((acc, item) => {
    const raw = asObject(item);
    if (
      !raw ||
      typeof raw.language !== "string" ||
      typeof raw.level !== "string"
    ) {
      return acc;
    }
    const mapped: LanguageRequirement = {
      language: raw.language,
      level: raw.level as LanguageRequirement["level"],
      isMandatory: pickBoolean(raw, "isMandatory", "is_mandatory"),
    };
    const sourceSentence = pickSourceSentence(raw);
    if (sourceSentence) {
      mapped.sourceSentence = sourceSentence;
    }
    acc.push(mapped);
    return acc;
  }, []);
}

/** Maps the education requirement object, or null when absent. */
function mapEducationRequirement(
  value: unknown
): JDParsedPayload["educationRequirement"] {
  const raw = asObject(value);
  if (!raw) return null;
  const minimumDegree =
    (pickField(raw, "minimumDegree", "minimum_degree") as
      | EducationRequirement["minimumDegree"]
      | undefined) ?? "none";
  return {
    minimumDegree,
    fieldOfStudy: pickString(raw, "fieldOfStudy", "field_of_study") ?? null,
    isMandatory: pickBoolean(raw, "isMandatory", "is_mandatory"),
    sourceSentence: pickSourceSentence(raw) ?? null,
  };
}

/** Maps the visa requirement object, or null when absent. */
function mapVisaRequirement(
  value: unknown
): JDParsedPayload["visaRequirement"] {
  const raw = asObject(value);
  if (!raw) return null;
  const requirementType =
    (pickField(raw, "requirementType", "requirement_type") as
      | VisaRequirement["requirementType"]
      | undefined) ?? "unknown";
  return {
    requirementType,
    targetRegion: pickString(raw, "targetRegion", "target_region") ?? null,
    sourceSentence: pickSourceSentence(raw) ?? null,
  };
}

/**
 * Converts stored/API JD JSON into the frontend JDParsedPayload schema.
 * Canonical keys: must_skills, preferred_skills, language_requirements,
 * education_requirement, visa_requirement.
 */
export function convertJdParsedPayload(value: unknown): JDParsedPayload | null {
  const payload = asObject(value);
  if (!payload) return null;

  return {
    mustSkills: mapSkills(
      pickField(payload, "mustSkills", "must_skills"),
      "must"
    ),
    preferredSkills: mapSkills(
      pickField(payload, "preferredSkills", "preferred_skills"),
      "preferred"
    ),
    languageRequirements: mapLanguageRequirements(
      pickField(payload, "languageRequirements", "language_requirements")
    ),
    educationRequirement: mapEducationRequirement(
      pickField(payload, "educationRequirement", "education_requirement")
    ),
    visaRequirement: mapVisaRequirement(
      pickField(payload, "visaRequirement", "visa_requirement")
    ),
  };
}

/** Restores real newlines from stored JD description text. */
export function restoreDescriptionNewlines(value: string): string {
  return value
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n")
    .replace(/\\r\\n/g, "\n")
    .replace(/\\n/g, "\n");
}

/** Maps a backend job row into the frontend JobPost schema. */
export function toJobPost(job: BackendJob): JobPost {
  return {
    id: job.id,
    title: job.title,
    description: restoreDescriptionNewlines(job.description),
    headCount: job.head_count,
    status: job.status as JobPost["status"],
    startDate: job.start_date,
    closedDate: job.closed_date,
    jdParsedJson: convertJdParsedPayload(job.jd_parsed_json),
    weightConfigJson: job.weight_config_json,
    createdAt: job.created_at,
    updatedAt: job.updated_at,
  };
}

/** Maps a backend candidate row into the frontend CandidateSummary schema. */
export function toCandidateSummary(
  item: BackendCandidateRow
): CandidateSummary {
  return {
    candidateId: item.candidate_id,
    candidateName: item.candidate_name ?? item.candidate_id,
    resumeId: item.resume_id,
    candidateEmail: item.candidate_email,
    originalFilename: item.original_filename,
    sourceChannel: item.source_channel,
    cvParseStatus: item.cv_parse_status,
    extractedData: item.extracted_data ?? null,
    uploadedAt: item.uploaded_at,
    matchScore: item.match_score,
    fitLevel: item.fit_level,
    scoreBreakdown: item.score_breakdown,
    candidateScoringStatus: item.candidate_scoring_status,
    recommendationRank: item.recommendation_rank ?? null,
    fitBand: item.fit_band ?? null,
    eligibilityStatus: item.eligibility_status ?? null,
    evidenceConfidence: item.evidence_confidence ?? null,
    topStrengths: item.top_strengths ?? [],
    keyGaps: item.key_gaps ?? [],
    radarSummary: item.radar_summary ?? {},
  };
}

/** Maps a backend PolyU catalog item into the frontend PolyUCatalogItem schema. */
export function toPolyUCatalogItem(
  item: BackendPolyUCatalogItem
): PolyUCatalogItem {
  return {
    jobCode: item.job_code,
    externalRef: item.external_ref,
    title: item.title,
    department: item.department,
    closingDate: item.closing_date,
    detailUrl: item.detail_url,
    alreadyImported: item.already_imported,
  };
}
