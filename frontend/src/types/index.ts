// Shared frontend TypeScript types for job posts, candidates, and JD parsing.
export type JobPostStatus = "draft" | "active" | "closed";
export type FitLevel = "high" | "medium" | "low";
export type CVParseStatus = "success" | "failed" | "pending";

export type SkillType = "must" | "preferred";

export interface SkillItem {
  id: string;
  name: string;
  type: SkillType;
  weight?: number;
  sourceSentence?: string;
}

export interface LanguageRequirement {
  language: string;
  level: "basic" | "business" | "fluent" | "native";
  isMandatory: boolean;
  sourceSentence?: string;
}

export interface EducationRequirement {
  minimumDegree: "none" | "bachelor" | "master" | "phd";
  fieldOfStudy?: string | null;
  isMandatory: boolean;
  sourceSentence?: string | null;
}

export interface VisaRequirement {
  requirementType: "none" | "required" | "preferred" | "unknown";
  targetRegion?: string | null;
  sourceSentence?: string | null;
}

export interface JDParsedPayload {
  mustSkills: SkillItem[];
  preferredSkills: SkillItem[];
  languageRequirements: LanguageRequirement[];
  educationRequirement: EducationRequirement | null;
  visaRequirement: VisaRequirement | null;
}

export interface WeightConfig {
  skills: Array<{
    skillId: string;
    weight: number;
  }>;
}

export interface JobPost {
  id: string;
  title: string;
  description: string;
  headCount: number;
  status: JobPostStatus;
  startDate: string;
  closedDate?: string | null;
  jdParsedJson: JDParsedPayload | null;
  weightConfigJson: WeightConfig | null;
  createdAt: string;
  updatedAt: string;
}

export interface JobPostListResponse {
  items: JobPost[];
  total: number;
  page: number;
  limit: number;
}

export interface PolyUCatalogItem {
  jobCode: string;
  externalRef: string;
  title: string;
  department: string;
  closingDate: string | null;
  detailUrl: string;
  alreadyImported: boolean;
}

export interface PolyUCatalogResponse {
  items: PolyUCatalogItem[];
  total: number;
  newCount: number;
}

export interface PolyUImportResponse {
  action: "created" | "skipped";
  job: JobPost;
  parseError: string | null;
}

export interface CandidateScoreBreakdown {
  skill: number;
  experience: number;
  education: number;
  language: number;
}

export interface CandidateSummary {
  candidateId: string;
  candidateName: string;
  resumeId?: string;
  candidateEmail?: string;
  originalFilename?: string;
  sourceChannel: string;
  cvParseStatus: CVParseStatus;
  extractedData?: Record<string, unknown> | null;
  uploadedAt?: string;
  matchScore?: number;
  fitLevel?: FitLevel;
  scoreBreakdown?: CandidateScoreBreakdown;
}

export interface CandidateListResponse {
  items: CandidateSummary[];
  total: number;
  page: number;
  limit: number;
}

export interface ChannelAnalyticsItem {
  sourceChannel: string;
  candidateCount: number;
  avgMatchScore: number;
}

export interface ChannelAnalyticsResponse {
  jobPostId: string;
  byChannel: ChannelAnalyticsItem[];
}

export interface MustSkillDiagnosis {
  skill: string;
  satisfactionRate: number;
  flagLow: boolean;
}

export interface JDDiagnosisResponse {
  jobPostId: string;
  mustSkillSatisfaction: MustSkillDiagnosis[];
}

export interface JobPostDetailResponse {
  job: JobPost;
  candidates: CandidateSummary[];
}

export interface JobPostCreateInput {
  title: string;
  description: string;
  headCount: number;
  startDate: string;
  status?: JobPostStatus;
  closedDate?: string | null;
}

export interface JobPostUpdateInput extends Partial<JobPostCreateInput> {}

export interface JobPostStatusPatchInput {
  status: JobPostStatus;
  closedDate?: string | null;
}

export interface JobPostListQuery {
  status?: JobPostStatus | "all";
  page?: number;
  limit?: number;
}
