// Renders the server-side list of CVs previously uploaded for a job as clickable radar cards.
import { useEffect, useState } from "react";
import { Badge } from "../ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { FitLevelBadge } from "../CandidateList/FitLevelBadge";
import { RadarChart } from "../CandidateMatching/RadarChart";
import { CandidateMatchDetailModal } from "../CandidateMatching/CandidateMatchDetailModal";
import { useJobBoardParams } from "../../hooks/useJobBoardParams";
import { toRadarDimensions } from "../../utils/matching";
import type { CandidateSummary } from "../../types";

interface CandidateHistoryGridProps {
  // The current job, used to load the detailed matching payload on card click.
  jobId: string;
  // Candidates (with parsed CV data) attached to the current job.
  candidates: CandidateSummary[];
  loading?: boolean;
}

// Formats an ISO timestamp into a short local date/time string.
function formatUploadedAt(value?: string): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleString();
}

// Maps a CV parse status to a badge color variant.
function statusVariant(
  status: string
): "secondary" | "success" | "info" | "danger" {
  if (status === "success") return "success";
  if (status === "pending") return "info";
  if (status === "failed") return "danger";
  return "secondary";
}

// Renders the historical CV cards for a job in a flex-wrap grid.
export function CandidateHistoryGrid({
  jobId,
  candidates,
  loading = false,
}: CandidateHistoryGridProps) {
  const { candidateId, replaceParams } = useJobBoardParams();
  const [selectedCandidate, setSelectedCandidate] =
    useState<CandidateSummary | null>(null);

  // Open the detail modal when the agent chat sets candidateId in the URL.
  useEffect(() => {
    if (!candidateId) {
      setSelectedCandidate(null);
      return;
    }
    const found = candidates.find(
      (candidate) => candidate.candidateId === candidateId
    );
    if (found) setSelectedCandidate(found);
  }, [candidateId, candidates]);

  if (candidates.length === 0) {
    return (
      <p className="text-sm text-slate-500">
        {loading
          ? "Loading previously uploaded CVs..."
          : "No CVs uploaded for this job yet."}
      </p>
    );
  }

  return (
    <div className="flex flex-wrap gap-4">
      {candidates.map((candidate) => {
        const radarDimensions = toRadarDimensions(candidate.radarSummary);
        const radarReady = radarDimensions.some(
          (dimension) => dimension.value !== null
        );

        return (
          <Card
            key={candidate.resumeId ?? candidate.candidateId}
            className="w-80 shrink-0 cursor-pointer transition-colors hover:border-sky-300"
            role="button"
            tabIndex={0}
            onClick={() => {
              setSelectedCandidate(candidate);
              replaceParams({ candidateId: candidate.candidateId });
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                setSelectedCandidate(candidate);
                replaceParams({ candidateId: candidate.candidateId });
              }
            }}
          >
            <CardHeader className="space-y-2">
              <div className="flex items-start justify-between gap-2">
                <CardTitle className="text-sm break-all">
                  {candidate.originalFilename ?? candidate.candidateName}
                </CardTitle>
                {/* <Badge variant={statusVariant(candidate.cvParseStatus)}>
                  {candidate.cvParseStatus}
                </Badge> */}
              </div>
              <p className="text-xs text-slate-500">
                {candidate.candidateName ?? "Unknown candidate"}
                {candidate.candidateEmail
                  ? " · " + candidate.candidateEmail
                  : ""}
              </p>
            </CardHeader>
            <CardContent className="space-y-3">
              <p className="text-xs text-slate-600">
                Channel: {candidate.sourceChannel}
                {formatUploadedAt(candidate.uploadedAt)
                  ? " · " + formatUploadedAt(candidate.uploadedAt)
                  : ""}
              </p>

              {candidate.matchScore != null ? (
                <div className="flex items-center justify-between gap-2">
                  <div>
                    <p className="text-xs text-slate-500">Match Score</p>
                    <p className="text-lg font-semibold text-slate-900">
                      {candidate.matchScore}
                    </p>
                  </div>
                  <div className="text-right">
                    {candidate.recommendationRank != null ? (
                      <p className="text-xs text-slate-500">
                        Rank #{candidate.recommendationRank}
                      </p>
                    ) : null}
                    {candidate.fitBand ? (
                      <FitLevelBadge fitLevel={candidate.fitBand} />
                    ) : null}
                  </div>
                </div>
              ) : (
                <p className="text-xs text-slate-500">Matching not ready.</p>
              )}

              {radarReady ? (
                <RadarChart dimensions={radarDimensions} size={180} />
              ) : (
                <p className="text-xs text-slate-500">
                  No radar data available.
                </p>
              )}
            </CardContent>
          </Card>
        );
      })}

      <CandidateMatchDetailModal
        jobId={jobId}
        candidate={selectedCandidate}
        onClose={() => {
          setSelectedCandidate(null);
          replaceParams({ candidateId: null });
        }}
      />
    </div>
  );
}
