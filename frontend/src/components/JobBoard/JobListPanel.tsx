// Left-side job list panel: status filter, list of job cards, and pagination controls.
import { useLayoutEffect, useRef } from "react";
import { Button } from "../ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { Skeleton } from "../ui/skeleton";
import { JobCard } from "../JobCard";
import type { JobPost, JobPostStatus } from "../../types";

const statusOptions: Array<{ label: string; value: JobPostStatus | "all" }> = [
  { label: "All", value: "all" },
  { label: "Draft", value: "draft" },
  { label: "Active", value: "active" },
  { label: "Closed", value: "closed" },
];

interface JobListPanelProps {
  items: JobPost[];
  total: number;
  page: number;
  totalPages: number;
  status: JobPostStatus | "all";
  loading: boolean;
  error: string | null;
  selectedJobId: string | null;
  workingJobId: string | null;
  onSelect: (jobId: string) => void;
  onStatusChange: (status: JobPostStatus | "all") => void;
  onPageChange: (page: number) => void;
  onDuplicate: (jobId: string) => void;
  onArchive: (jobId: string) => void;
  onToggleStatus: (jobId: string, status: JobPostStatus) => void;
}

// Renders the job list card with status tabs, scrollable cards, and pager.
export function JobListPanel({
  items,
  total,
  page,
  totalPages,
  status,
  loading,
  error,
  selectedJobId,
  workingJobId,
  onSelect,
  onStatusChange,
  onPageChange,
  onDuplicate,
  onArchive,
  onToggleStatus,
}: JobListPanelProps) {
  const listRef = useRef<HTMLDivElement>(null);

  // Keep the selected card in view after refresh or deep-link.
  useLayoutEffect(() => {
    if (!selectedJobId || loading) return;
    const selectedCard = listRef.current?.querySelector(
      `[data-job-id="${CSS.escape(selectedJobId)}"]`
    );
    selectedCard?.scrollIntoView({ block: "nearest", behavior: "auto" });
  }, [items, loading, selectedJobId]);

  return (
    <Card className="flex h-full flex-col">
      <CardHeader className="space-y-4">
        <CardTitle className="text-base">Job List</CardTitle>
        <div className="flex flex-wrap gap-2">
          {statusOptions.map((option) => (
            <Button
              key={option.value}
              size="sm"
              variant={status === option.value ? "default" : "outline"}
              onClick={() => onStatusChange(option.value)}
            >
              {option.label}
            </Button>
          ))}
        </div>
      </CardHeader>
      <CardContent className="flex min-h-0 flex-1 flex-col gap-4">
        {loading ? (
          <div className="min-h-0 flex-1 space-y-3 overflow-y-auto pr-1">
            {Array.from({ length: 4 }).map((_, index) => (
              <div
                key={index}
                className="space-y-3 rounded-xl border border-slate-200 p-4"
              >
                <div className="flex items-start justify-between">
                  <Skeleton className="h-4 w-2/3" />
                  <Skeleton className="h-5 w-16 rounded-full" />
                </div>
                <Skeleton className="h-3 w-full" />
                <Skeleton className="h-3 w-1/2" />
                <div className="flex gap-2">
                  <Skeleton className="h-8 w-24" />
                  <Skeleton className="h-8 w-24" />
                </div>
              </div>
            ))}
          </div>
        ) : null}
        {error ? <p className="text-sm text-rose-600">{error}</p> : null}

        {!loading && !error ? (
          <div
            ref={listRef}
            className="min-h-0 flex-1 space-y-3 overflow-y-auto pr-1"
          >
            {items.map((job) => (
              <div
                key={job.id}
                data-job-id={job.id}
                role="button"
                tabIndex={0}
                onClick={() => onSelect(job.id)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    onSelect(job.id);
                  }
                }}
                className={`scroll-mt-2 cursor-pointer rounded-xl transition ${
                  selectedJobId === job.id
                    ? "ring-2 ring-slate-500"
                    : "hover:ring-2 hover:ring-slate-300"
                } ${workingJobId === job.id ? "opacity-60" : ""}`}
              >
                <JobCard
                  job={job}
                  onViewDetail={onSelect}
                  onDuplicate={onDuplicate}
                  onArchive={onArchive}
                  onToggleStatus={onToggleStatus}
                />
              </div>
            ))}
          </div>
        ) : null}

        <div className="mt-auto flex items-center justify-between border-t border-slate-100 pt-3">
          <p className="text-xs text-slate-500">
            Page {page} / {totalPages} · Total {total}
          </p>
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={() => onPageChange(Math.max(1, page - 1))}
              disabled={page <= 1}
            >
              Prev
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => onPageChange(Math.min(totalPages, page + 1))}
              disabled={page >= totalPages}
            >
              Next
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
