// Displays one uploaded candidate's parse result as a fixed-width card.
import { Badge } from "../ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";

export type CandidateUploadStatus =
  | "pending"
  | "uploading"
  | "success"
  | "failed";

export interface CandidateUploadItem {
  localId: string;
  fileName: string;
  fileSize: number;
  status: CandidateUploadStatus;
  candidateId: string | null;
  extractedData: unknown | null;
  error: string | null;
}

interface CandidateCardProps {
  item: CandidateUploadItem;
}

// Formats a byte count into a human-readable file size string.
function prettyFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// Maps an upload status to the matching badge color variant.
function statusToVariant(
  status: CandidateUploadStatus
): "secondary" | "success" | "info" | "danger" {
  if (status === "success") return "success";
  if (status === "uploading") return "info";
  if (status === "failed") return "danger";
  return "secondary";
}

// Renders a single candidate upload card with status badge and parsed JSON preview.
export function CandidateCard({ item }: CandidateCardProps) {
  return (
    <Card className="w-80 shrink-0">
      <CardHeader className="space-y-2">
        <div className="flex items-start justify-between gap-2">
          <CardTitle className="text-sm break-all">{item.fileName}</CardTitle>
          <Badge variant={statusToVariant(item.status)}>{item.status}</Badge>
        </div>
        <p className="text-xs text-slate-500">
          File size: {prettyFileSize(item.fileSize)}
        </p>
      </CardHeader>
      <CardContent className="space-y-2">
        {item.candidateId ? (
          <p className="text-xs text-slate-600">
            Candidate ID: {item.candidateId}
          </p>
        ) : null}
        {item.error ? (
          <p className="text-sm font-medium text-rose-600">{item.error}</p>
        ) : null}
        {item.extractedData ? (
          <pre className="max-h-72 overflow-auto rounded-md bg-slate-900 p-3 text-xs text-slate-50">
            {JSON.stringify(item.extractedData, null, 2)}
          </pre>
        ) : null}
      </CardContent>
    </Card>
  );
}
