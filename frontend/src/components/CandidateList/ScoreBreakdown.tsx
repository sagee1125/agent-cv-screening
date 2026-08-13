import type { CandidateScoreBreakdown } from "../../types";

interface ScoreBreakdownProps {
  breakdown: CandidateScoreBreakdown;
}

export function ScoreBreakdown({ breakdown }: ScoreBreakdownProps) {
  return (
    <div className="grid grid-cols-2 gap-2 text-xs text-slate-600 md:grid-cols-4">
      <p>Skill: {breakdown.skill}</p>
      <p>Experience: {breakdown.experience}</p>
      <p>Education: {breakdown.education}</p>
      <p>Language: {breakdown.language}</p>
    </div>
  );
}
