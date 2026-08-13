import { Button } from "./ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { StatusBadge } from "./Common/StatusBadge";
import type { JobPost } from "../types";
import { formatDate } from "../utils";

interface JobCardProps {
  job: JobPost;
  onViewDetail: (jobId: string) => void;
  onDuplicate: (jobId: string) => void;
  onArchive: (jobId: string) => void;
  onToggleStatus: (jobId: string, status: JobPost["status"]) => void;
}

export function JobCard({
  job,
  onViewDetail,
  onDuplicate,
  // onArchive,
  onToggleStatus,
}: JobCardProps) {
  const nextStatus: JobPost["status"] =
    job.status === "active" ? "closed" : "active";
  return (
    <Card className="h-full">
      <CardHeader className="space-y-3 pb-2">
        <div className="flex items-start justify-between gap-3">
          <CardTitle className="text-lg">{job.title}</CardTitle>
          <StatusBadge status={job.status} />
        </div>
      </CardHeader>
      <CardContent className="space-y-4 text-sm text-slate-600">
        <p className="line-clamp-3 min-h-[60px]">{job.description}</p>
        <div className="grid grid-cols-2 gap-2 text-xs text-slate-500">
          <span>Headcount: {job.headCount}</span>
          <span>Start: {formatDate(new Date(job.startDate))}</span>
        </div>
        <div className="flex gap-2">
          <Button size="sm" onClick={() => onViewDetail(job.id)}>
            View Detail
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => onDuplicate(job.id)}
          >
            Duplicate
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => onToggleStatus(job.id, nextStatus)}
          >
            {job.status === "active" ? "Close" : "Activate"}
          </Button>
          {/* <Button size="sm" variant="outline" onClick={() => onArchive(job.id)}>
            Archive
          </Button> */}
        </div>
      </CardContent>
    </Card>
  );
}
