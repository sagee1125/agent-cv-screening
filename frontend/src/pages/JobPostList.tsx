// Job Post list page: container that wires list, JD parser, PolyU sync, and create modal.
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { AgentChatDrawer } from "../components/AgentChat/AgentChatDrawer";
import { Button } from "../components/ui/button";
import { Spinner } from "../components/ui/spinner";
import { JobListPanel } from "../components/JobBoard/JobListPanel";
import { JDParserPanel } from "../components/JobBoard/JDParserPanel";
import { JobPostCreate } from "../components/JobPostCreate";
import { useConfirm } from "../components/Common/ConfirmProvider";
import { useJobBoardParams } from "../hooks/useJobBoardParams";
import { useJobPostDetail } from "../hooks/useJobPostDetail";
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
  const { jobId, status, page, replaceParams } = useJobBoardParams();
  const {
    items,
    total,
    page: listPage,
    limit,
    status: listStatus,
    loading,
    error,
    refresh,
  } = useJobPosts(status, page);
  const {
    job: detailedJob,
    loading: detailLoading,
    error: detailError,
    refresh: refreshDetail,
  } = useJobPostDetail(jobId);

  const [workingJobId, setWorkingJobId] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);
  const confirm = useConfirm();

  // Prefer the dedicated detail fetch so the right pane still works off-page.
  const selectedJob = useMemo(() => {
    if (detailedJob && detailedJob.id === jobId) return detailedJob;
    return items.find((job) => job.id === jobId) ?? null;
  }, [detailedJob, items, jobId]);

  const totalPages = useMemo(
    () => Math.max(1, Math.ceil(total / limit)),
    [limit, total]
  );

  // When the URL has no jobId, pin the first visible card so refresh stays on it.
  useEffect(() => {
    if (loading || jobId || items.length === 0) return;
    replaceParams({ jobId: items[0].id });
  }, [items, jobId, loading, replaceParams]);

  // PolyU sync: refresh silently after each import, then a final refresh.
  const { syncing, progress, sync } = usePolyUSync({
    confirm,
    onJobImported: (importedJobId) => {
      replaceParams({ jobId: importedJobId, status: "all", page: 1 });
      // fire-and-forget: don't wait for the refresh to complete
      void refresh({ silent: true, page: 1, status: "all" });
    },
    onSyncComplete: (nextStatus, nextPage) => {
      replaceParams({ status: nextStatus, page: nextPage });
      // fire-and-forget: don't wait for the refresh to complete
      void refresh({ silent: true, page: nextPage, status: nextStatus });
    },
  });

  const runWithWorking = useCallback(
    async (targetJobId: string, action: () => Promise<unknown>) => {
      setWorkingJobId(targetJobId);
      try {
        await action();
        await Promise.all([refresh(), refreshDetail()]);
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
    [refresh, refreshDetail]
  );

  const handleDuplicate = useCallback(
    (targetJobId: string) => {
      void runWithWorking(targetJobId, () => duplicateJobPost(targetJobId));
    },
    [runWithWorking]
  );

  const handleArchive = useCallback(
    (targetJobId: string) => {
      void runWithWorking(targetJobId, () => deleteJobPost(targetJobId));
    },
    [runWithWorking]
  );

  const handleToggleStatus = useCallback(
    (targetJobId: string, nextStatus: JobPostStatus) => {
      void runWithWorking(targetJobId, () =>
        patchJobStatus(targetJobId, { status: nextStatus })
      );
    },
    [runWithWorking]
  );

  // Reload list and detail after a JD save so both panes stay in sync.
  const handleSaved = useCallback(async () => {
    await Promise.all([refresh(), refreshDetail()]);
  }, [refresh, refreshDetail]);

  // Reload the current list view, then clear the selected job after a hard delete.
  const handleDeleted = useCallback(
    async (deletedJobId: string) => {
      await refresh();
      if (jobId === deletedJobId) {
        replaceParams({ jobId: null });
      }
    },
    [jobId, refresh, replaceParams]
  );

  // Write the clicked job into the URL without stacking history entries.
  const handleSelect = useCallback(
    (nextJobId: string) => {
      replaceParams({ jobId: nextJobId });
    },
    [replaceParams]
  );

  const agentContext = useMemo(
    () => ({
      jobId,
      jobTitle: selectedJob?.title ?? null,
      jobDescription: selectedJob?.description ?? null,
      jdParsedJson: selectedJob?.jdParsedJson ?? null,
    }),
    [jobId, selectedJob]
  );

  const agentBridge = useMemo(
    () => ({
      refreshJob: async () => {
        await Promise.all([refresh(), refreshDetail()]);
      },
      selectJob: (nextJobId: string) => replaceParams({ jobId: nextJobId }),
      openCandidate: (candidateId: string) => replaceParams({ candidateId }),
    }),
    [refresh, refreshDetail, replaceParams]
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
            page={listPage}
            totalPages={totalPages}
            status={listStatus}
            loading={loading}
            error={error}
            selectedJobId={jobId}
            workingJobId={workingJobId}
            onSelect={handleSelect}
            onStatusChange={(nextStatus) =>
              replaceParams({ status: nextStatus, page: 1 })
            }
            onPageChange={(nextPage) => replaceParams({ page: nextPage })}
            onDuplicate={handleDuplicate}
            onArchive={handleArchive}
            onToggleStatus={handleToggleStatus}
          />

          {selectedJob ? (
            <JDParserPanel
              key={selectedJob.id}
              job={selectedJob}
              onSaved={handleSaved}
              onDeleted={handleDeleted}
            />
          ) : (
            <div className="flex h-full items-center justify-center rounded-xl border border-dashed border-slate-200 bg-white px-6 text-center text-sm text-slate-500">
              {detailLoading
                ? "Loading job details..."
                : detailError
                  ? detailError
                  : "Select a job card from the left list to view JD parser details."}
            </div>
          )}
        </div>
      </div>
      {createOpen && (
        <JobPostCreate
          modalTitle="Create Job Post"
          onClose={() => setCreateOpen(false)}
          onSaved={async (createdJobId) => {
            replaceParams({ jobId: createdJobId });
            await refresh();
          }}
        />
      )}
      <AgentChatDrawer
        open={chatOpen}
        onOpenChange={setChatOpen}
        context={agentContext}
        bridge={agentBridge}
      />
    </main>
  );
}
