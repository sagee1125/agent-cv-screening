// Job Post REST client, including PolyU catalog fetch and one-by-one import.
import { apiDelete, apiGet, apiPatch, apiPost, apiPut } from "./api";
import {
  convertJdParsedPayload,
  EMPTY_JD_PARSED_PAYLOAD,
  toCandidateSummary,
  toJobPost,
  toPolyUCatalogItem,
} from "../utils/jdParsedConvert";
import type {
  BackendCandidateRow,
  BackendJob,
  BackendPolyUCatalogItem,
} from "../utils/jdParsedConvert";
import type {
  CandidateListResponse,
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
  PolyUCatalogItem,
  PolyUCatalogResponse,
  PolyUImportResponse,
  WeightConfig,
} from "../types";

type BackendJobListResponse = {
  items: BackendJob[];
  total: number;
  page: number;
  limit: number;
};

type BackendJobDetailResponse = {
  job: BackendJob;
  candidates: BackendCandidateRow[];
};

// Response returned by POST /candidates/upload after a CV is stored and parsed.
type CandidateUploadResponse = {
  id: string;
  status: string;
  extractedId: string;
};

// Parsed candidate detail returned by GET /candidates/{id}.
type CandidateDetail = {
  id: string;
  email: string;
  name: string;
  phone: string;
  extractedData: Record<string, unknown> | null;
};

/** Lists job posts with optional status filter and pagination. */
export async function getJobPosts(
  query: JobPostListQuery
): Promise<JobPostListResponse> {
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

/** Fetches one job post and its attached candidates. */
export async function getJobPostDetail(
  jobId: string
): Promise<JobPostDetailResponse> {
  const response = await apiGet<BackendJobDetailResponse>(`/jobs/${jobId}`);
  return {
    job: toJobPost(response.job),
    candidates: response.candidates.map(toCandidateSummary),
  };
}

/** Creates a job post from the frontend form payload. */
export async function createJobPost(
  payload: JobPostCreateInput
): Promise<JobPost> {
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

/** Updates an existing job post. */
export async function updateJobPost(
  jobId: string,
  payload: JobPostUpdateInput
): Promise<JobPost> {
  const updated = await apiPut<BackendJob>(`/jobs/${jobId}`, {
    title: payload.title,
    description: payload.description,
    head_count: payload.headCount,
    start_date: payload.startDate,
    closed_date: payload.closedDate,
  });
  return toJobPost(updated);
}

/** Soft-deletes a job post and returns the deletion timestamp. */
export async function deleteJobPost(
  jobId: string
): Promise<{ id: string; deletedAt: string }> {
  const response = await apiDelete<{ id: string; updated_at: string }>(
    `/jobs/${jobId}`
  );
  return { id: response.id, deletedAt: response.updated_at };
}

/** Duplicates a job post and returns the new job id. */
export async function duplicateJobPost(
  jobId: string
): Promise<{ newJobId: string }> {
  const response = await apiPost<{ new_job_id: string }>(
    `/jobs/${jobId}/duplicate`
  );
  return { newJobId: response.new_job_id };
}

/** Patches job status and optional closed date. */
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

/** Saves the skill weight config for a job. */
export async function updateJobWeight(
  jobId: string,
  weightConfigJson: WeightConfig
): Promise<void> {
  await apiPut<void>(`/jobs/${jobId}/weight`, {
    weight_config_json: weightConfigJson,
  });
}

/** Triggers a rescore job after weight changes. */
export async function recalculateJob(
  jobId: string
): Promise<{ recalcJobId: string; status: string }> {
  return apiPost<{ recalcJobId: string; status: string }>(
    `/jobs/${jobId}/recalculate`,
    { reason: "weight_updated" }
  );
}

/** Parses JD text and returns frontend-shaped JD and weight payloads. */
export async function parseJobJD(
  jobId: string,
  jdText: string
): Promise<{ jdParsedJson: JDParsedPayload; weightConfigJson: WeightConfig }> {
  const response = await apiPost<{
    jd_parsed_json: unknown;
    weight_config_json: WeightConfig;
  }>(`/jobs/${jobId}/parse-jd`, { jd_text: jdText });
  return {
    jdParsedJson:
      convertJdParsedPayload(response.jd_parsed_json) ?? EMPTY_JD_PARSED_PAYLOAD,
    weightConfigJson: response.weight_config_json,
  };
}

/** Lists scored candidates for a job. */
export async function getJobCandidates(
  jobId: string,
  page = 1,
  limit = 20
): Promise<CandidateListResponse> {
  const response = await apiGet<{
    items: BackendCandidateRow[];
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

/** Fetches per-channel candidate analytics for a job. */
export async function getJobChannelStats(
  jobId: string
): Promise<ChannelAnalyticsResponse> {
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

/** Fetches must-skill satisfaction diagnosis for a job. */
export async function getJDDiagnosis(
  jobId: string
): Promise<JDDiagnosisResponse> {
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

/** Fetches the PolyU general jobs catalog and import flags. */
export async function getPolyUJobCatalog(): Promise<PolyUCatalogResponse> {
  const response = await apiGet<{
    items: BackendPolyUCatalogItem[];
    total: number;
    new_count: number;
  }>("/jobs/sync-polyu/catalog");
  return {
    items: response.items.map(toPolyUCatalogItem),
    total: response.total,
    newCount: response.new_count,
  };
}

/** Imports one PolyU listing, parses its JD, and returns the saved Job Post. */
export async function importPolyUJob(
  item: PolyUCatalogItem
): Promise<PolyUImportResponse> {
  const response = await apiPost<{
    action: "created" | "skipped";
    job: BackendJob;
    parse_error: string | null;
  }>("/jobs/sync-polyu/import", {
    job_code: item.jobCode,
    external_ref: item.externalRef,
    title: item.title,
    department: item.department,
    closing_date: item.closingDate,
    detail_url: item.detailUrl,
  });
  return {
    action: response.action,
    job: toJobPost(response.job),
    parseError: response.parse_error,
  };
}

/** Uploads a single PDF CV to the backend parsing endpoint, linked to the given job. */
export async function uploadCandidateCV(
  file: File,
  jobId: string
): Promise<CandidateUploadResponse> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("job_id", jobId);
  const response = await apiPost<{
    id: string;
    status: string;
    extracted_id: string;
  }>("/candidates/upload", formData);
  return {
    id: response.id,
    status: response.status,
    extractedId: response.extracted_id,
  };
}

/** Fetches the parsed structured data for a stored candidate by id. */
export async function getCandidateDetail(
  candidateId: string
): Promise<CandidateDetail> {
  const response = await apiGet<{
    id: string;
    email: string;
    name: string;
    phone: string;
    extracted_data: unknown;
  }>(`/candidates/${candidateId}`);
  return {
    id: response.id,
    email: response.email,
    name: response.name,
    phone: response.phone,
    extractedData: response.extracted_data as Record<string, unknown> | null,
  };
}
