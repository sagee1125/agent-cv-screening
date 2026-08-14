import type { CandidateSummary, JobPost } from "../types";
import { formatDate } from "../utils";
import { CandidateTable } from "./CandidateList/CandidateTable";
import { Modal } from "./Common/Modal";
import { StatusBadge } from "./Common/StatusBadge";
import { SkillTagList } from "./JDParser/SkillTagList";
import { Button } from "./ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";

interface JobPostDetailViewProps {
  job?: JobPost | null;
  candidates?: CandidateSummary[];
  loading?: boolean;
  error?: string | null;
  onClose: () => void;
}

export function JobPostDetailView({
  job = null,
  candidates = [],
  loading = false,
  error = null,
  onClose,
}: JobPostDetailViewProps) {
  const modalTitle = job ? `Job Detail - ${job.title}` : "Job Detail";

  return (
    <Modal open onClose={onClose}>
      <div className="space-y-4">
        <div className="flex items-start justify-between gap-3">
          <h3 className="text-lg font-semibold text-slate-900">{modalTitle}</h3>
          <Button variant="outline" onClick={onClose}>
            Close
          </Button>
        </div>

        {loading ? (
          <p className="text-sm text-slate-500">Loading job detail...</p>
        ) : null}
        {error ? <p className="text-sm text-rose-600">{error}</p> : null}

        {!loading && !error && job ? (
          <>
            <Card>
              <CardHeader className="flex items-start justify-between">
                <CardTitle className="text-base">{job.title}</CardTitle>
                <StatusBadge status={job.status} />
              </CardHeader>
              <CardContent className="space-y-2 text-sm text-slate-600">
                <p className="whitespace-pre-wrap">{job.description}</p>
                <p>Headcount: {job.headCount}</p>
                <p>Start Date: {formatDate(new Date(job.startDate))}</p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle className="text-base">JD Parsed Skills</CardTitle>
              </CardHeader>
              <CardContent>
                <SkillTagList jdParsed={job.jdParsedJson} />
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Candidates</CardTitle>
              </CardHeader>
              <CardContent>
                <CandidateTable candidates={candidates} />
              </CardContent>
            </Card>
          </>
        ) : null}
      </div>
    </Modal>
  );
}

export { JobPostDetailView as jobPostDetail };
