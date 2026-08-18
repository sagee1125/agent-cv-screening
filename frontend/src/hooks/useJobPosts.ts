// Loads paginated Job Posts and supports a silent refresh during PolyU sync.
import { useCallback, useEffect, useRef, useState } from "react";
import { getJobPosts } from "../services/jobService";
import type { JobPost, JobPostStatus } from "../types";

interface UseJobPostsState {
  items: JobPost[];
  total: number;
  page: number;
  limit: number;
  status: JobPostStatus | "all";
  loading: boolean;
  error: string | null;
}

const INITIAL_LIMIT = 12;

// Fetch and paginate Job Posts, optionally without flashing the loading state.
export function useJobPosts(initialStatus: JobPostStatus | "all" = "all") {
  const [state, setState] = useState<UseJobPostsState>({
    items: [],
    total: 0,
    page: 1,
    limit: INITIAL_LIMIT,
    status: initialStatus,
    loading: true,
    error: null,
  });
  // Track the latest fetch so stale responses never overwrite newer ones.
  const requestSeqRef = useRef(0);

  // Stable fetcher: takes explicit params and uses functional setState, so it has no state deps.
  const fetchJobPosts = useCallback(
    async (
      status: JobPostStatus | "all",
      page: number,
      silent = false
    ) => {
      const seq = ++requestSeqRef.current;
      if (!silent) {
        setState((prev) => ({ ...prev, loading: true, error: null }));
      }
      try {
        const response = await getJobPosts({
          status,
          page,
          limit: INITIAL_LIMIT,
        });
        if (seq !== requestSeqRef.current) return;
        setState((prev) => ({
          ...prev,
          items: response.items,
          total: response.total,
          page: response.page,
          limit: response.limit,
          status,
          loading: false,
          error: silent ? prev.error : null,
        }));
      } catch (error) {
        if (seq !== requestSeqRef.current) return;
        const message =
          error instanceof Error ? error.message : "Failed to load Job Posts.";
        setState((prev) => ({
          ...prev,
          loading: false,
          error: silent ? prev.error ?? message : message,
        }));
      }
    },
    []
  );

  // Initial mount load only; subsequent loads are driven by user actions.
  useEffect(() => {
    void fetchJobPosts(initialStatus, 1);
  }, [fetchJobPosts, initialStatus]);

  // Switch the status filter and reload page 1.
  const setStatus = useCallback(
    (status: JobPostStatus | "all") => {
      void fetchJobPosts(status, 1);
    },
    [fetchJobPosts]
  );

  // Change the list page without resetting the status filter.
  const setPage = useCallback(
    (page: number) => {
      void fetchJobPosts(state.status, page);
    },
    [fetchJobPosts, state.status]
  );

  // Reload Job Posts using optional silent/page/status overrides.
  const refresh = useCallback(
    (options?: {
      silent?: boolean;
      page?: number;
      status?: JobPostStatus | "all";
    }) => {
      return fetchJobPosts(
        options?.status ?? state.status,
        options?.page ?? state.page,
        options?.silent ?? false
      );
    },
    [fetchJobPosts, state.page, state.status]
  );

  return {
    ...state,
    setStatus,
    setPage,
    refresh,
  };
}
