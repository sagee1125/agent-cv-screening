// Modal that loads and displays one candidate's full matching detail payload.
import { useEffect, useState } from "react";
import { Modal } from "../Common/Modal";
import { FitLevelBadge } from "../CandidateList/FitLevelBadge";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Spinner } from "../ui/spinner";
import { getCandidateMatchDetail } from "../../services/jobService";
import type { CandidateMatchDetail, CandidateSummary } from "../../types";
import { RadarChart } from "./RadarChart";

interface CandidateMatchDetailModalProps {
  jobId: string;
  candidate: CandidateSummary | null;
  onClose: () => void;
}

// Maps a matching status string to a badge color variant.
function matchingStatusVariant(
  status: string
): "success" | "info" | "danger" | "secondary" {
  if (status === "ready") return "success";
  if (status === "stale") return "info";
  if (status === "failed") return "danger";
  return "secondary";
}

// Maps an eligibility status string to a badge color variant.
function eligibilityStatusVariant(
  status: string
): "success" | "info" | "danger" | "secondary" {
  if (status === "passed") return "success";
  if (status === "needs_review") return "info";
  if (status === "failed") return "danger";
  return "secondary";
}

// Loads and renders the radar, scores, reasoning, and interview questions modal.
export function CandidateMatchDetailModal({
  jobId,
  candidate,
  onClose,
}: CandidateMatchDetailModalProps) {
  const [detail, setDetail] = useState<CandidateMatchDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!candidate) {
      setDetail(null);
      setError(null);
      setLoading(false);
      return;
    }

    let cancelled = false;
    const loadDetail = async () => {
      setLoading(true);
      setError(null);
      setDetail(null);
      try {
        const response = await getCandidateMatchDetail(
          jobId,
          candidate.candidateId
        );
        if (!cancelled) setDetail(response);
      } catch (loadError) {
        if (!cancelled) {
          setError(
            loadError instanceof Error
              ? loadError.message
              : "Failed to load candidate match detail."
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    void loadDetail();
    return () => {
      cancelled = true;
    };
  }, [candidate, jobId]);

  const open = candidate !== null;
  const matchScore = detail?.matchScore ?? candidate?.matchScore ?? null;

  return (
    <Modal open={open} onClose={onClose}>
      <div className="space-y-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="text-lg font-semibold text-slate-900">
              Candidate Match
            </h3>
            <p className="text-sm text-slate-600">
              {candidate?.candidateName ?? "Unknown candidate"}
              {candidate?.originalFilename
                ? " · " + candidate.originalFilename
                : ""}
            </p>
          </div>
          <Button variant="outline" onClick={onClose}>
            Close
          </Button>
        </div>

        {loading ? (
          <div className="flex items-center gap-2 py-8 text-sm text-slate-500">
            <Spinner className="mr-2" />
            Loading candidate match detail...
          </div>
        ) : null}

        {!loading && error ? (
          <p className="rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-600">
            {error}
          </p>
        ) : null}

        {!loading && !error && detail ? (
          <>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
                <p className="text-xs text-slate-500">Match Score</p>
                <p className="text-2xl font-semibold text-slate-900">
                  {matchScore ?? "—"}
                </p>
              </div>
              <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
                <p className="text-xs text-slate-500">Rank</p>
                <p className="text-2xl font-semibold text-slate-900">
                  {detail.recommendationRank ?? "—"}
                </p>
              </div>
              <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
                <p className="text-xs text-slate-500">Evidence Confidence</p>
                <p className="text-2xl font-semibold text-slate-900">
                  {detail.evidenceConfidence ?? "—"}
                </p>
              </div>
              <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
                <p className="text-xs text-slate-500">Status</p>
                <div className="mt-1 flex flex-wrap items-center gap-1.5">
                  {detail.fitBand ? (
                    <FitLevelBadge fitLevel={detail.fitBand} />
                  ) : null}
                  <Badge variant={matchingStatusVariant(detail.scoringStatus)}>
                    {detail.scoringStatus}
                  </Badge>
                  {detail.stale ? (
                    <Badge variant="info">stale</Badge>
                  ) : null}
                </div>
              </div>
            </div>

            <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
              <div className="rounded-md border border-slate-200 bg-white p-3">
                <h4 className="mb-2 text-sm font-semibold text-slate-900">
                  Radar Profile
                </h4>
                <RadarChart
                  dimensions={detail.radarDimensions.map((dimension) => ({
                    id: dimension.dimensionId,
                    label: dimension.label,
                    value: dimension.score,
                  }))}
                  size={360}
                  showLabels
                  showValues
                />
              </div>

              <div className="space-y-4">
                {candidate?.topStrengths?.length ? (
                  <div className="rounded-md border border-slate-200 bg-white p-3">
                    <h4 className="mb-2 text-sm font-semibold text-slate-900">
                      Top Strengths
                    </h4>
                    <ul className="list-inside list-disc space-y-1 text-sm text-slate-600">
                      {candidate.topStrengths.map((strength) => (
                        <li key={strength}>{strength}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}

                {candidate?.keyGaps?.length ? (
                  <div className="rounded-md border border-slate-200 bg-white p-3">
                    <h4 className="mb-2 text-sm font-semibold text-slate-900">
                      Key Gaps
                    </h4>
                    <ul className="list-inside list-disc space-y-1 text-sm text-slate-600">
                      {candidate.keyGaps.map((gap) => (
                        <li key={gap}>{gap}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}

                <div className="rounded-md border border-slate-200 bg-white p-3">
                  <h4 className="mb-2 text-sm font-semibold text-slate-900">
                    Eligibility
                  </h4>
                  <p className="mb-2 text-sm text-slate-700">
                    Status:{" "}
                    <Badge
                      variant={eligibilityStatusVariant(
                        detail.eligibility.status
                      )}
                    >
                      {detail.eligibility.status}
                    </Badge>
                  </p>
                  {detail.eligibility.results.length ? (
                    <ul className="space-y-2 text-sm text-slate-600">
                      {detail.eligibility.results.map((result) => (
                        <li key={result.ruleId}>
                          <span className="font-medium text-slate-900">
                            {result.ruleId}
                          </span>
                          : {result.status}
                          {result.requirement
                            ? " · " + result.requirement
                            : ""}
                          {result.reasonCode
                            ? " (" + result.reasonCode + ")"
                            : ""}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-xs text-slate-500">
                      No eligibility rules returned.
                    </p>
                  )}
                </div>
              </div>
            </div>

            <section className="space-y-3">
              <h4 className="text-sm font-semibold text-slate-900">
                Dimension Details
              </h4>
              {detail.radarDimensions.length ? (
                detail.radarDimensions.map((dimension) => (
                  <div
                    key={dimension.dimensionId}
                    className="rounded-md border border-slate-200 bg-white p-3"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <p className="font-medium text-slate-900">
                        {dimension.label}
                      </p>
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-semibold text-slate-900">
                          {dimension.score ?? "N/A"}
                        </span>
                        <Badge variant="secondary">{dimension.status}</Badge>
                        <span className="text-xs text-slate-500">
                          weight {dimension.normalizedWeight.toFixed(2)}
                        </span>
                      </div>
                    </div>
                    {dimension.reasoning?.summary ? (
                      <p className="mt-2 text-xs leading-relaxed text-slate-600">
                        {dimension.reasoning.summary}
                      </p>
                    ) : null}
                    {dimension.gaps.length ? (
                      <div className="mt-2">
                        <p className="text-xs font-medium text-slate-700">
                          Gaps
                        </p>
                        <ul className="list-inside list-disc text-xs text-slate-500">
                          {dimension.gaps.map((gap) => (
                            <li key={gap.requirementId}>{gap.text}</li>
                          ))}
                        </ul>
                      </div>
                    ) : null}
                  </div>
                ))
              ) : (
                <p className="text-xs text-slate-500">
                  No radar dimension details returned.
                </p>
              )}
            </section>

            <section className="space-y-3">
              <h4 className="text-sm font-semibold text-slate-900">
                Suggested Interview Questions
              </h4>
              {detail.interviewQuestions.length ? (
                <ul className="space-y-2">
                  {detail.interviewQuestions.map((question) => (
                    <li
                      key={question.questionId}
                      className="rounded-md border border-slate-200 bg-white p-3"
                    >
                      <p className="text-sm text-slate-800">
                        {question.question}
                      </p>
                      <p className="mt-1 text-xs text-slate-500">
                        Priority: {question.priority} · Template:{" "}
                        {question.templateId}
                      </p>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-xs text-slate-500">
                  No suggested interview questions.
                </p>
              )}
            </section>
          </>
        ) : null}
      </div>
    </Modal>
  );
}
