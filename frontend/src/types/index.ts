// Shared frontend TypeScript types for job posts, candidates, and JD parsing.
export type JobPostStatus = "draft" | "active" | "closed";
export type FitLevel = "high" | "medium" | "low";
export type CVParseStatus = "success" | "failed" | "pending";
export type CandidateScoringStatus =
  | "unscored"
  | "pending"
  | "running"
  | "ready"
  | "stale"
  | "failed";
export type FitBand = FitLevel;
export type EligibilityStatus = "passed" | "needs_review" | "failed";
export type RadarSummary = Record<string, number | null>;

/** One radar axis value used by the reusable radar chart. */
export interface RadarDimensionDatum {
  id: string;
  label: string;
  value: number | null;
}

export type SkillType = "must" | "preferred" | "other";

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

/** Frontend JD schema after convertJdParsedPayload maps the backend wire JSON. */
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
  candidateScoringStatus?: CandidateScoringStatus;
  recommendationRank?: number | null;
  fitBand?: FitBand | null;
  eligibilityStatus?: EligibilityStatus | null;
  evidenceConfidence?: number | null;
  topStrengths?: string[];
  keyGaps?: string[];
  radarSummary?: RadarSummary;
}

/** One eligibility rule result shown in the candidate matching detail. */
export interface EligibilityResult {
  ruleId: string;
  status: string;
  reasonCode?: string;
  requirement?: string;
  evidence?: unknown[];
}

/** Candidate eligibility status and its per-rule results. */
export interface CandidateEligibility {
  status: EligibilityStatus | string;
  results: EligibilityResult[];
}

/** Source reference attached to a radar requirement or evidence item. */
export interface RadarSourceReference {
  document?: string;
  section?: string;
  sourceSentence?: string;
}

/** A JD requirement used by one radar dimension. */
export interface RadarRequirement {
  requirementId: string;
  text: string;
  source?: RadarSourceReference;
}

/** A CV evidence item linked to one radar dimension. */
export interface RadarEvidence {
  evidenceId: string;
  document?: string;
  section?: string;
  text: string;
  matchedRequirementIds?: string[];
  matchType?: string;
  confidence?: number | null;
}

/** A missing-evidence gap reported for one radar dimension. */
export interface RadarGap {
  requirementId: string;
  reasonCode?: string;
  text: string;
}

/** Deterministic dimension-level reasoning text and facts. */
export interface RadarReasoning {
  templateId?: string;
  summary?: string;
  facts?: Record<string, unknown>;
}

/** Full radar dimension result returned by the matching detail API. */
export interface RadarDimension {
  dimensionId: string;
  label: string;
  active: boolean;
  score: number | null;
  configuredWeight: number;
  normalizedWeight: number;
  weightedPoints: number;
  status: string;
  requirements: RadarRequirement[];
  evidence: RadarEvidence[];
  gaps: RadarGap[];
  reasoning: RadarReasoning | null;
  confidence: number | null;
}

/** Fixed-template interview question suggested for a candidate. */
export interface InterviewQuestion {
  questionId: string;
  templateId: string;
  priority: string;
  dimensionId?: string;
  triggerReasonCode?: string;
  triggerRequirementIds?: string[];
  question: string;
  variables?: Record<string, unknown>;
}

/** Complete candidate matching payload shown in the detail modal. */
export interface CandidateMatchDetail {
  version: string;
  schemaVersion: string;
  jobPostId: string;
  candidateId: string;
  resumeId: string;
  scoreVersion: number;
  algorithmVersion: string;
  scoringStatus: string;
  stale: boolean;
  recommendationRank: number | null;
  matchScore: number | null;
  fitBand: FitBand | null;
  eligibility: CandidateEligibility;
  evidenceConfidence: number | null;
  radarDimensions: RadarDimension[];
  interviewQuestions: InterviewQuestion[];
  metadata: Record<string, unknown>;
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
