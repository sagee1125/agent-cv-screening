import { JobPostForm } from "../pages/JobPostForm";
import { createJobPost } from "../services/jobService";
import { CandidateTable } from "./CandidateList/CandidateTable";
import { Modal } from "./Common/Modal";
import { SkillTagList } from "./JDParser/SkillTagList";
import { StatusBadge } from "./Common/StatusBadge";
import { Button } from "./ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import type { CandidateSummary, JobPost } from "../types";
import { formatDate } from "../utils";

interface JobPostDetailProps {
  editable: boolean;
  job?: JobPost | null;
  candidates?: CandidateSummary[];
  loading?: boolean;
  error?: string | null;
  onClose: () => void;
  onSaved?: () => Promise<void> | void;
}

export function JobPostDetail({
  editable,
  job = null,
  candidates = [],
  loading = false,
  error = null,
  onClose,
  onSaved,
}: JobPostDetailProps) {
  const modalTitle = editable
    ? "Create Job Post"
    : job
    ? `Job Detail - ${job.title}`
    : "Job Detail";

  return (
    <Modal open onClose={onClose}>
      {editable ? (
        <JobPostForm
          formTitle={modalTitle}
          saveText="Save & Close"
          closeText="Close"
          onSubmit={async (payload) => {
            await createJobPost(payload);
            await onSaved?.();
            onClose();
          }}
          onClose={onClose}
        />
      ) : (
        <div className="space-y-4">
          <div className="flex items-start justify-between gap-3">
            <h3 className="text-lg font-semibold text-slate-900">
              {modalTitle}
            </h3>
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
      )}
    </Modal>
  );
}
