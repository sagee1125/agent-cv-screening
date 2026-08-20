// Job Post list page: container that wires list, JD parser, PolyU sync, and create modal.
import { useCallback, useMemo, useState } from "react";
import { toast } from "sonner";
import { Button } from "../components/ui/button";
import { Spinner } from "../components/ui/spinner";
import { JobListPanel } from "../components/JobBoard/JobListPanel";
import { JDParserPanel } from "../components/JobBoard/JDParserPanel";
import { JobPostCreate } from "../components/JobPostCreate";
import { useConfirm } from "../components/Common/ConfirmProvider";
import { useJobPosts } from "../hooks/useJobPosts";
import { usePolyUSync } from "../hooks/usePolyUSync";
import {
  deleteJobPost,
  duplicateJobPost,
  patchJobStatus,
} from "../services/jobService";
import type { JobPostStatus } from "../types";

// Top-level page that lists Job Posts and orchestrates create/parse/sync actions.
export function JobPostList() {
  const {
    items,
    total,
    page,
    limit,
    status,
    loading,
    error,
    setStatus,
    setPage,
    refresh,
  } = useJobPosts("all");

  const [workingJobId, setWorkingJobId] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const confirm = useConfirm();

  // Derive the selected job from items; fall back to the first item when the
  // selection is missing or stale. No useEffect needed for selection sync.
  const selectedJob = useMemo(() => {
    if (selectedJobId && items.some((job) => job.id === selectedJobId)) {
      return items.find((job) => job.id === selectedJobId) ?? null;
    }
    return items[0] ?? null;
  }, [items, selectedJobId]);

  const totalPages = useMemo(
    () => Math.max(1, Math.ceil(total / limit)),
    [limit, total]
  );

  // PolyU sync: refresh silently after each import, then a final refresh.
  const { syncing, progress, sync } = usePolyUSync({
    confirm,
    onJobImported: (jobId) => {
      setSelectedJobId(jobId);
      // fire-and-forget: don't wait for the refresh to complete
      void refresh({ silent: true, page: 1, status: "all" });
    },
    onSyncComplete: (nextStatus, nextPage) => {
      // fire-and-forget: don't wait for the refresh to complete
      void refresh({ silent: true, page: nextPage, status: nextStatus });
    },
  });

  const runWithWorking = useCallback(
    async (jobId: string, action: () => Promise<unknown>) => {
      setWorkingJobId(jobId);
      try {
        await action();
        await refresh();
      } catch (actionError) {
        toast.error(
          actionError instanceof Error ? actionError.message : "Action failed.",
          {
            position: "top-center",
          }
        );
      } finally {
        setWorkingJobId(null);
      }
    },
    [refresh]
  );

  const handleDuplicate = useCallback(
    (jobId: string) => {
      void runWithWorking(jobId, () => duplicateJobPost(jobId));
    },
    [runWithWorking]
  );

  const handleArchive = useCallback(
    (jobId: string) => {
      void runWithWorking(jobId, () => deleteJobPost(jobId));
    },
    [runWithWorking]
  );

  const handleToggleStatus = useCallback(
    (jobId: string, nextStatus: JobPostStatus) => {
      void runWithWorking(jobId, () =>
        patchJobStatus(jobId, { status: nextStatus })
      );
    },
    [runWithWorking]
  );

  // Reload the current list view, then clear the selected job after a hard delete.
  const handleDeleted = useCallback(
    async (jobId: string) => {
      await refresh();
      if (selectedJobId === jobId) {
        setSelectedJobId(null);
      }
    },
    [refresh, selectedJobId]
  );

  return (
    <main className="flex h-full w-full flex-col overflow-hidden">
      <div className="mx-auto flex h-full w-full max-w-7xl flex-col space-y-5 px-4 py-6">
        <div className="flex items-center justify-between gap-3">
          <h1 className="text-xl font-semibold text-slate-900">Job Posts</h1>
          <div className="flex flex-col items-end gap-1">
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                onClick={() => void sync()}
                disabled={syncing}
              >
                {syncing ? (
                  <>
                    <Spinner className="mr-2" />
                    Syncing PolyU...
                  </>
                ) : (
                  "Sync PolyU Jobs"
                )}
              </Button>
              <Button onClick={() => setCreateOpen(true)} disabled={syncing}>
                New Job Post
              </Button>
            </div>
            {progress ? (
              <p className="max-w-md truncate text-xs text-slate-500">
                {progress}
              </p>
            ) : null}
          </div>
        </div>

        <div className="grid min-h-0 flex-1 auto-rows-fr grid-cols-1 gap-5 xl:grid-cols-[420px_minmax(0,1fr)]">
          <JobListPanel
            items={items}
            total={total}
            page={page}
            totalPages={totalPages}
            status={status}
            loading={loading}
            error={error}
            selectedJobId={selectedJob?.id ?? null}
            workingJobId={workingJobId}
            onSelect={setSelectedJobId}
            onStatusChange={setStatus}
            onPageChange={setPage}
            onDuplicate={handleDuplicate}
            onArchive={handleArchive}
            onToggleStatus={handleToggleStatus}
          />

          {selectedJob ? (
            <JDParserPanel
              key={selectedJob.id}
              job={selectedJob}
              onSaved={refresh}
              onDeleted={handleDeleted}
            />
          ) : (
            <div className="flex h-full items-center justify-center rounded-xl border border-dashed border-slate-200 bg-white text-sm text-slate-500">
              Select a job card from the left list to view JD parser details.
            </div>
          )}
        </div>
      </div>
      {createOpen && (
        <JobPostCreate
          modalTitle="Create Job Post"
          onClose={() => setCreateOpen(false)}
          onSaved={refresh}
        />
      )}
    </main>
  );
}
