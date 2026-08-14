import { apiDelete, apiGet, apiPatch, apiPost, apiPut } from "./api";
import type {
  CandidateListResponse,
  CandidateSummary,
  ChannelAnalyticsResponse,
  JDDiagnosisResponse,
  JDParsedPayload,
  JobPost,
  JobPostCreateInput,
  JobPostDetailResponse,
  JobPostListQuery,
  JobPostListResponse,
  JobPostStatusPatchInput,
  JobPostUpdateInput,
  WeightConfig,
} from "../types";

type BackendJob = {
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

type BackendJobListResponse = {
  items: BackendJob[];
  total: number;
  page: number;
  limit: number;
};

type BackendJobDetailResponse = {
  job: BackendJob;
  candidates: Array<{
    candidate_id: string;
    match_score: number;
    fit_level: "high" | "medium" | "low";
    source_channel: string;
    cv_parse_status: "success" | "failed" | "pending";
    score_breakdown: { skill: number; experience: number; education: number; language: number };
  }>;
};

function restoreDescriptionNewlines(value: string): string {
  return value
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n")
    .replace(/\\r\\n/g, "\n")
    .replace(/\\n/g, "\n");
}

const toJobPost = (job: BackendJob): JobPost => ({
  id: job.id,
  title: job.title,
  description: restoreDescriptionNewlines(job.description),
  headCount: job.head_count,
  status: job.status as JobPost["status"],
  startDate: job.start_date,
  closedDate: job.closed_date,
  jdParsedJson: normalizeJDParsedPayload(job.jd_parsed_json),
  weightConfigJson: job.weight_config_json,
  createdAt: job.created_at,
  updatedAt: job.updated_at,
});

function normalizeJDParsedPayload(value: unknown): JDParsedPayload | null {
  if (!value || typeof value !== "object") {
    return null;
  }
  const payload = value as Record<string, unknown>;

  const mapSkills = (skills: unknown, type: "must" | "preferred") => {
    if (!Array.isArray(skills)) return [];
    return skills.map((item, index) => {
      const raw = (item ?? {}) as Record<string, unknown>;
      const provenance = (raw.provenance ?? {}) as Record<string, unknown>;
      const displayName = typeof raw.display_name === "string" ? raw.display_name : null;
      const fallbackName = typeof raw.canonical_skill === "string" ? raw.canonical_skill : null;
      return {
        id: typeof raw.skill_id === "string" ? raw.skill_id : `${type}-${index + 1}`,
        name: displayName ?? fallbackName ?? `${type}-${index + 1}`,
        type,
        weight: typeof raw.weight === "number" ? raw.weight : undefined,
        sourceSentence:
          typeof provenance.source_sentence === "string" ? provenance.source_sentence : undefined,
      };
    });
  };

  const mustSkills = mapSkills(payload.mustSkills ?? payload.must_skills, "must");
  const preferredSkills = mapSkills(payload.preferredSkills ?? payload.preferred_skills, "preferred");

  const normalizeSourceSentence = (raw: Record<string, unknown>): string | undefined => {
    if (typeof raw.sourceSentence === "string") return raw.sourceSentence;
    if (typeof raw.source_sentence === "string") return raw.source_sentence;
    if (typeof raw.provenance === "string") return raw.provenance;
    const provenance = (raw.provenance ?? {}) as Record<string, unknown>;
    if (typeof provenance.source_sentence === "string") return provenance.source_sentence;
    return undefined;
  };
  type LanguageItem = JDParsedPayload["languageRequirements"][number];
  type EducationItem = NonNullable<JDParsedPayload["educationRequirement"]>;
  type VisaItem = NonNullable<JDParsedPayload["visaRequirement"]>;

  const languageRaw = Array.isArray(payload.languageRequirements)
    ? payload.languageRequirements
    : Array.isArray(payload.language_requirements)
      ? payload.language_requirements
      : [];
  const languageRequirements = languageRaw.reduce<LanguageItem[]>((acc, item) => {
      const raw = (item ?? {}) as Record<string, unknown>;
      if (typeof raw.language !== "string" || typeof raw.level !== "string") return acc;
      const normalized: LanguageItem = {
        language: raw.language,
        level: raw.level as LanguageItem["level"],
        isMandatory:
          typeof raw.isMandatory === "boolean"
            ? raw.isMandatory
            : typeof raw.is_mandatory === "boolean"
              ? raw.is_mandatory
              : false,
      };
      const sourceSentence = normalizeSourceSentence(raw);
      if (sourceSentence) {
        normalized.sourceSentence = sourceSentence;
      }
      acc.push(normalized);
      return acc;
    }, []);

  const educationRaw = ((payload.educationRequirement ??
    payload.education_requirement ??
    null) ?? null) as Record<string, unknown> | null;
  const educationRequirement: JDParsedPayload["educationRequirement"] =
    educationRaw && typeof educationRaw === "object"
      ? {
          minimumDegree:
            (educationRaw.minimumDegree as EducationItem["minimumDegree"]) ??
            (educationRaw.minimum_degree as EducationItem["minimumDegree"]) ??
            "none",
          fieldOfStudy:
            (educationRaw.fieldOfStudy as string | null | undefined) ??
            (educationRaw.field_of_study as string | null | undefined) ??
            null,
          isMandatory:
            typeof educationRaw.isMandatory === "boolean"
              ? educationRaw.isMandatory
              : typeof educationRaw.is_mandatory === "boolean"
                ? educationRaw.is_mandatory
                : false,
          sourceSentence: normalizeSourceSentence(educationRaw) ?? null,
        }
      : null;

  const visaRaw = ((payload.visaRequirement ?? payload.visa_requirement ?? null) ??
    null) as Record<string, unknown> | null;
  const visaRequirement: JDParsedPayload["visaRequirement"] =
    visaRaw && typeof visaRaw === "object"
      ? {
          requirementType:
            (visaRaw.requirementType as VisaItem["requirementType"]) ??
            (visaRaw.requirement_type as VisaItem["requirementType"]) ??
            "unknown",
          targetRegion:
            (visaRaw.targetRegion as string | null | undefined) ??
            (visaRaw.target_region as string | null | undefined) ??
            null,
          sourceSentence: normalizeSourceSentence(visaRaw) ?? null,
        }
      : null;

  return {
    mustSkills,
    preferredSkills,
    languageRequirements,
    educationRequirement,
    visaRequirement,
  };
}

const toCandidateSummary = (item: BackendJobDetailResponse["candidates"][number]): CandidateSummary => ({
  candidateId: item.candidate_id,
  candidateName: item.candidate_id,
  matchScore: item.match_score,
  fitLevel: item.fit_level,
  sourceChannel: item.source_channel,
  cvParseStatus: item.cv_parse_status,
  scoreBreakdown: item.score_breakdown,
});

export async function getJobPosts(query: JobPostListQuery): Promise<JobPostListResponse> {
  const response = await apiGet<BackendJobListResponse>("/jobs", {
      status: query.status === "all" ? undefined : query.status,
      page: query.page ?? 1,
      limit: query.limit ?? 12,
  });
  return {
    items: response.items.map(toJobPost),
    total: response.total,
    page: response.page,
    limit: response.limit,
  };
}

export async function getJobPostDetail(jobId: string): Promise<JobPostDetailResponse> {
  const response = await apiGet<BackendJobDetailResponse>(`/jobs/${jobId}`);
  return {
    job: toJobPost(response.job),
    candidates: response.candidates.map(toCandidateSummary),
  };
}

export async function createJobPost(payload: JobPostCreateInput): Promise<JobPost> {
  const created = await apiPost<BackendJob>("/jobs", {
    title: payload.title,
    description: payload.description,
    head_count: payload.headCount,
    status: payload.status ?? "draft",
    start_date: payload.startDate,
    closed_date: payload.closedDate ?? null,
  });
  return toJobPost(created);
}

export async function updateJobPost(jobId: string, payload: JobPostUpdateInput): Promise<JobPost> {
  const updated = await apiPut<BackendJob>(`/jobs/${jobId}`, {
    title: payload.title,
    description: payload.description,
    head_count: payload.headCount,
    start_date: payload.startDate,
    closed_date: payload.closedDate,
  });
  return toJobPost(updated);
}

export async function deleteJobPost(jobId: string): Promise<{ id: string; deletedAt: string }> {
  const response = await apiDelete<{ id: string; updated_at: string }>(`/jobs/${jobId}`);
  return { id: response.id, deletedAt: response.updated_at };
}

export async function duplicateJobPost(jobId: string): Promise<{ newJobId: string }> {
  const response = await apiPost<{ new_job_id: string }>(`/jobs/${jobId}/duplicate`);
  return { newJobId: response.new_job_id };
}

export async function patchJobStatus(
  jobId: string,
  payload: JobPostStatusPatchInput
): Promise<{ id: string; status: string }> {
  const response = await apiPatch<{ id: string; status: string }>(
    `/jobs/${jobId}/status`,
    { status: payload.status, closed_date: payload.closedDate ?? null }
  );
  return response;
}

export async function updateJobWeight(jobId: string, weightConfigJson: WeightConfig): Promise<void> {
  await apiPut<void>(`/jobs/${jobId}/weight`, { weight_config_json: weightConfigJson });
}

export async function recalculateJob(jobId: string): Promise<{ recalcJobId: string; status: string }> {
  return apiPost<{ recalcJobId: string; status: string }>(
    `/jobs/${jobId}/recalculate`,
    { reason: "weight_updated" }
  );
}

export async function parseJobJD(jobId: string, jdText: string): Promise<{ jdParsedJson: JDParsedPayload; weightConfigJson: WeightConfig }> {
  const response = await apiPost<{
    jd_parsed_json: unknown;
    weight_config_json: WeightConfig;
  }>(`/jobs/${jobId}/parse-jd`, { jd_text: jdText });
  return {
    jdParsedJson: normalizeJDParsedPayload(response.jd_parsed_json) ?? {
      mustSkills: [],
      preferredSkills: [],
      languageRequirements: [],
      educationRequirement: null,
      visaRequirement: null,
    },
    weightConfigJson: response.weight_config_json,
  };
}

export async function getJobCandidates(
  jobId: string,
  page = 1,
  limit = 20
): Promise<CandidateListResponse> {
  const response = await apiGet<{
    items: Array<{
      candidate_id: string;
      match_score: number;
      fit_level: "high" | "medium" | "low";
      source_channel: string;
      cv_parse_status: "success" | "failed" | "pending";
      score_breakdown: { skill: number; experience: number; education: number; language: number };
    }>;
    total: number;
    page: number;
    limit: number;
  }>(`/jobs/${jobId}/candidates`, { page, limit });
  return {
    items: response.items.map(toCandidateSummary),
    total: response.total,
    page: response.page,
    limit: response.limit,
  };
}

export async function getJobChannelStats(jobId: string): Promise<ChannelAnalyticsResponse> {
  const response = await apiGet<{
    job_post_id: string;
    by_channel: Array<{
      source_channel: string;
      candidate_count: number;
      avg_match_score: number;
    }>;
  }>(`/jobs/${jobId}/candidates/stats`);
  return {
    jobPostId: response.job_post_id,
    byChannel: response.by_channel.map((item) => ({
      sourceChannel: item.source_channel,
      candidateCount: item.candidate_count,
      avgMatchScore: item.avg_match_score,
    })),
  };
}

export async function getJDDiagnosis(jobId: string): Promise<JDDiagnosisResponse> {
  const response = await apiGet<{
    job_post_id: string;
    must_skill_satisfaction: Array<{
      skill: string;
      satisfaction_rate: number;
      flag_low: boolean;
    }>;
  }>(`/jobs/${jobId}/diagnosis`);
  return {
    jobPostId: response.job_post_id,
    mustSkillSatisfaction: response.must_skill_satisfaction.map((item) => ({
      skill: item.skill,
      satisfactionRate: item.satisfaction_rate,
      flagLow: item.flag_low,
    })),
  };
}
