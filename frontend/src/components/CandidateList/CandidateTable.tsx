import type { CandidateSummary } from "../../types";
import { CandidateRow } from "./CandidateRow";

interface CandidateTableProps {
  candidates: CandidateSummary[];
}

export function CandidateTable({ candidates }: CandidateTableProps) {
  if (candidates.length === 0) {
    return <p className="text-sm text-slate-500">No candidates linked yet.</p>;
  }

  return (
    <div className="space-y-2">
      {candidates.map((candidate) => (
        <CandidateRow key={candidate.candidateId} candidate={candidate} />
      ))}
    </div>
  );
}
