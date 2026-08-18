import { useState } from "react";
import type { CandidateSummary } from "../../types";
import { FitLevelBadge } from "./FitLevelBadge";
import { ScoreBreakdown } from "./ScoreBreakdown";
import { Button } from "../ui/button";

interface CandidateRowProps {
  candidate: CandidateSummary;
}

export function CandidateRow({ candidate }: CandidateRowProps) {
  const [expanded, setExpanded] = useState(false);
  const matchScore = candidate.matchScore ?? 0;
  const progressWidth = `${Math.max(0, Math.min(100, matchScore))}%`;

  return (
    <div className="rounded-md border border-slate-200 p-3">
      <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
        <div>
          <p className="font-medium text-slate-900">{candidate.candidateName}</p>
          <p className="text-xs text-slate-500">{candidate.sourceChannel}</p>
        </div>
        <div className="flex items-center gap-3">
          <div className="w-40">
            <p className="mb-1 text-xs text-slate-600">Score: {matchScore}</p>
            <div className="h-2 rounded-full bg-slate-100">
              <div className="h-2 rounded-full bg-sky-500" style={{ width: progressWidth }} />
            </div>
          </div>
          {candidate.fitLevel ? <FitLevelBadge fitLevel={candidate.fitLevel} /> : null}
          <Button size="sm" variant="outline" onClick={() => setExpanded((prev) => !prev)}>
            {expanded ? "Hide" : "Breakdown"}
          </Button>
        </div>
      </div>
      {expanded && candidate.scoreBreakdown ? (
        <div className="mt-3 border-t border-slate-100 pt-3">
          <ScoreBreakdown breakdown={candidate.scoreBreakdown} />
        </div>
      ) : null}
    </div>
  );
}
