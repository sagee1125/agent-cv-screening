// Matching helpers and snake_case to camelCase converters for radar data.
import type {
  CandidateMatchDetail,
  EligibilityResult,
  InterviewQuestion,
  RadarDimension,
  RadarDimensionDatum,
  RadarEvidence,
  RadarGap,
  RadarReasoning,
  RadarRequirement,
  RadarSourceReference,
  RadarSummary,
} from "../types";

/** Canonical order of the six candidate matching radar dimensions. */
export const MATCHING_DIMENSION_ORDER = [
  "core_skill_match",
  "relevant_experience",
  "role_seniority_fit",
  "evidence_impact",
  "education_certification",
  "job_specific_match",
] as const;

/** Human-readable labels for the six candidate matching radar dimensions. */
export const MATCHING_DIMENSION_LABELS: Record<string, string> = {
  core_skill_match: "Core Skill Match",
  relevant_experience: "Relevant Experience",
  role_seniority_fit: "Role & Seniority Fit",
  evidence_impact: "Evidence & Impact",
  education_certification: "Education & Certification",
  job_specific_match: "Job-Specific Match",
};

/** Builds radar chart points from a compact radar_summary map. */
export function toRadarDimensions(
  summary?: RadarSummary | null
): RadarDimensionDatum[] {
  return MATCHING_DIMENSION_ORDER.map((id) => ({
    id,
    label: MATCHING_DIMENSION_LABELS[id],
    value: summary?.[id] ?? null,
  }));
}

/** Raw candidate matching detail shape returned by the backend API. */
export type BackendCandidateMatchDetail = {
  version: string;
  schema_version: string;
  job_post_id: string;
  candidate_id: string;
  resume_id: string;
  score_version: number;
  algorithm_version: string;
  scoring_status: string;
  stale: boolean;
  recommendation_rank: number | null;
  match_score: number | null;
  fit_band: CandidateMatchDetail["fitBand"];
  eligibility: {
    status: string;
    results?: unknown;
  };
  evidence_confidence: number | null;
  radar_dimensions: unknown;
  interview_questions: unknown;
  metadata?: Record<string, unknown>;
};

/** Returns a number when the value is a finite number, otherwise null. */
function toNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** Returns a string when the value is a string, otherwise undefined. */
function toStringValue(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

/** Converts a value into an object record, or null when it is not an object. */
function toObject(value: unknown): Record<string, unknown> | null {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

/** Maps a radar source reference from snake_case wire JSON. */
function mapRadarSource(value: unknown): RadarSourceReference | undefined {
  const raw = toObject(value);
  if (!raw) return undefined;
  const source: RadarSourceReference = {};
  if (typeof raw.document === "string") source.document = raw.document;
  if (typeof raw.section === "string") source.section = raw.section;
  if (typeof raw.source_sentence === "string") {
    source.sourceSentence = raw.source_sentence;
  }
  return source;
}

/** Maps radar requirement objects into frontend camelCase objects. */
function mapRadarRequirements(value: unknown): RadarRequirement[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => {
    const raw = toObject(item) ?? {};
    const requirement: RadarRequirement = {
      requirementId:
        typeof raw.requirement_id === "string" ? raw.requirement_id : "",
      text: typeof raw.text === "string" ? raw.text : "",
    };
    const source = mapRadarSource(raw.source);
    if (source) requirement.source = source;
    return requirement;
  });
}

/** Maps radar evidence objects into frontend camelCase objects. */
function mapRadarEvidence(value: unknown): RadarEvidence[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => {
    const raw = toObject(item) ?? {};
    const evidence: RadarEvidence = {
      evidenceId:
        typeof raw.evidence_id === "string" ? raw.evidence_id : "",
      document: toStringValue(raw.document),
      section: toStringValue(raw.section),
      text: typeof raw.text === "string" ? raw.text : "",
      matchType: toStringValue(raw.match_type),
      confidence: toNumber(raw.confidence),
    };
    if (Array.isArray(raw.matched_requirement_ids)) {
      evidence.matchedRequirementIds = raw.matched_requirement_ids.filter(
        (id): id is string => typeof id === "string"
      );
    }
    return evidence;
  });
}

/** Maps radar gap objects into frontend camelCase objects. */
function mapRadarGaps(value: unknown): RadarGap[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => {
    const raw = toObject(item) ?? {};
    return {
      requirementId:
        typeof raw.requirement_id === "string" ? raw.requirement_id : "",
      reasonCode: toStringValue(raw.reason_code),
      text: typeof raw.text === "string" ? raw.text : "",
    };
  });
}

/** Maps dimension reasoning objects into frontend camelCase objects. */
function mapRadarReasoning(value: unknown): RadarReasoning | null {
  const raw = toObject(value);
  if (!raw) return null;
  return {
    templateId: toStringValue(raw.template_id),
    summary: toStringValue(raw.summary),
    facts: toObject(raw.facts) ?? {},
  };
}

/** Maps all radar dimension objects returned by the detail API. */
function mapRadarDimensions(value: unknown): RadarDimension[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    const raw = toObject(item);
    if (!raw) return [];
    const dimensionId =
      typeof raw.dimension_id === "string" ? raw.dimension_id : "";
    const dimension: RadarDimension = {
      dimensionId,
      label:
        typeof raw.label === "string"
          ? raw.label
          : MATCHING_DIMENSION_LABELS[dimensionId] ?? dimensionId,
      active: raw.active === true,
      score: toNumber(raw.score),
      configuredWeight: typeof raw.configured_weight === "number" ? raw.configured_weight : 0,
      normalizedWeight: typeof raw.normalized_weight === "number" ? raw.normalized_weight : 0,
      weightedPoints: typeof raw.weighted_points === "number" ? raw.weighted_points : 0,
      status: typeof raw.status === "string" ? raw.status : "unknown",
      requirements: mapRadarRequirements(raw.requirements),
      evidence: mapRadarEvidence(raw.evidence),
      gaps: mapRadarGaps(raw.gaps),
      reasoning: mapRadarReasoning(raw.reasoning),
      confidence: toNumber(raw.confidence),
    };
    return [dimension];
  });
}

/** Maps eligibility result objects into frontend camelCase objects. */
function mapEligibilityResults(value: unknown): EligibilityResult[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    const raw = toObject(item);
    if (!raw) return [];
    const result: EligibilityResult = {
      ruleId: typeof raw.rule_id === "string" ? raw.rule_id : "",
      status: typeof raw.status === "string" ? raw.status : "unknown",
      reasonCode: toStringValue(raw.reason_code),
      requirement: toStringValue(raw.requirement),
    };
    if (Array.isArray(raw.evidence)) result.evidence = raw.evidence;
    return [result];
  });
}

/** Maps interview question objects into frontend camelCase objects. */
function mapInterviewQuestions(value: unknown): InterviewQuestion[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => {
    const raw = toObject(item) ?? {};
    const question: InterviewQuestion = {
      questionId: typeof raw.question_id === "string" ? raw.question_id : "",
      templateId: typeof raw.template_id === "string" ? raw.template_id : "",
      priority: typeof raw.priority === "string" ? raw.priority : "medium",
      dimensionId: toStringValue(raw.dimension_id),
      triggerReasonCode: toStringValue(raw.trigger_reason_code),
      question: typeof raw.question === "string" ? raw.question : "",
    };
    if (Array.isArray(raw.trigger_requirement_ids)) {
      question.triggerRequirementIds = raw.trigger_requirement_ids.filter(
        (id): id is string => typeof id === "string"
      );
    }
    const variables = toObject(raw.variables);
    if (variables) question.variables = variables;
    return question;
  });
}

/** Converts the backend matching detail payload into the frontend view model. */
export function convertCandidateMatchDetail(
  raw: BackendCandidateMatchDetail
): CandidateMatchDetail {
  const eligibility = raw.eligibility ?? { status: "unknown" };
  return {
    version: raw.version,
    schemaVersion: raw.schema_version,
    jobPostId: raw.job_post_id,
    candidateId: raw.candidate_id,
    resumeId: raw.resume_id,
    scoreVersion: raw.score_version,
    algorithmVersion: raw.algorithm_version,
    scoringStatus: raw.scoring_status,
    stale: raw.stale,
    recommendationRank: raw.recommendation_rank ?? null,
    matchScore: raw.match_score ?? null,
    fitBand: raw.fit_band ?? null,
    eligibility: {
      status: eligibility.status ?? "unknown",
      results: mapEligibilityResults(eligibility.results),
    },
    evidenceConfidence: raw.evidence_confidence ?? null,
    radarDimensions: mapRadarDimensions(raw.radar_dimensions),
    interviewQuestions: mapInterviewQuestions(raw.interview_questions),
    metadata: raw.metadata ?? {},
  };
}
