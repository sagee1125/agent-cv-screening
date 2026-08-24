// Loads a single Job Post by id so the detail pane is independent of list paging.
import { useCallback, useEffect, useRef, useState } from "react";
import { getJobPostDetail } from "../services/jobService";
import type { JobPost } from "../types";

interface UseJobPostDetailState {
  job: JobPost | null;
  loading: boolean;
  error: string | null;
}

/** Fetches one job for the right-hand JD panel from the URL jobId. */
export function useJobPostDetail(jobId: string | null) {
  const [state, setState] = useState<UseJobPostDetailState>({
    job: null,
    loading: Boolean(jobId),
    error: null,
  });
  const requestSeqRef = useRef(0);

  // Reloads the current job; no-ops when jobId is empty.
  const refresh = useCallback(async () => {
    if (!jobId) {
      requestSeqRef.current += 1;
      setState({ job: null, loading: false, error: null });
      return;
    }
    const seq = ++requestSeqRef.current;
    setState((prev) => ({ ...prev, loading: true, error: null }));
    try {
      const response = await getJobPostDetail(jobId);
      if (seq !== requestSeqRef.current) return;
      setState({ job: response.job, loading: false, error: null });
    } catch (error) {
      if (seq !== requestSeqRef.current) return;
      const message =
        error instanceof Error ? error.message : "Failed to load job.";
      setState({ job: null, loading: false, error: message });
    }
  }, [jobId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { ...state, refresh };
}
