// Renders the server-side list of CVs previously uploaded for a job as fixed-width cards.
import { Badge } from "../ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import type { CandidateSummary } from "../../types";

interface CandidateHistoryGridProps {
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
  candidates,
  loading = false,
}: CandidateHistoryGridProps) {
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
      {candidates.map((candidate) => (
        <Card key={candidate.resumeId ?? candidate.candidateId} className="w-80 shrink-0">
          <CardHeader className="space-y-2">
            <div className="flex items-start justify-between gap-2">
              <CardTitle className="text-sm break-all">
                {candidate.originalFilename ?? candidate.candidateName}
              </CardTitle>
              <Badge variant={statusVariant(candidate.cvParseStatus)}>
                {candidate.cvParseStatus}
              </Badge>
            </div>
            <p className="text-xs text-slate-500">
              {candidate.candidateName ?? "Unknown candidate"}
              {candidate.candidateEmail ? ` · ${candidate.candidateEmail}` : ""}
            </p>
          </CardHeader>
          <CardContent className="space-y-2">
            <p className="text-xs text-slate-600">
              Channel: {candidate.sourceChannel}
              {formatUploadedAt(candidate.uploadedAt)
                ? ` · ${formatUploadedAt(candidate.uploadedAt)}`
                : ""}
            </p>
            {candidate.extractedData ? (
              <pre className="max-h-72 overflow-auto rounded-md bg-slate-900 p-3 text-xs text-slate-50">
                {JSON.stringify(candidate.extractedData, null, 2)}
              </pre>
            ) : (
              <p className="text-xs text-slate-500">No parsed data available.</p>
            )}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
