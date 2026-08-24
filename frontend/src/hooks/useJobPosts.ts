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

/** Fetch and paginate Job Posts from URL-driven status and page. */
export function useJobPosts(status: JobPostStatus | "all", page: number) {
  const [state, setState] = useState<UseJobPostsState>({
    items: [],
    total: 0,
    page,
    limit: INITIAL_LIMIT,
    status,
    loading: true,
    error: null,
  });
  // Track the latest fetch so stale responses never overwrite newer ones.
  const requestSeqRef = useRef(0);

  // Stable fetcher: takes explicit params and uses functional setState, so it has no state deps.
  const fetchJobPosts = useCallback(
    async (
      nextStatus: JobPostStatus | "all",
      nextPage: number,
      silent = false
    ) => {
      const seq = ++requestSeqRef.current;
      if (!silent) {
        setState((prev) => ({ ...prev, loading: true, error: null }));
      }
      try {
        const response = await getJobPosts({
          status: nextStatus,
          page: nextPage,
          limit: INITIAL_LIMIT,
        });
        if (seq !== requestSeqRef.current) return;
        setState((prev) => ({
          ...prev,
          items: response.items,
          total: response.total,
          page: response.page,
          limit: response.limit,
          status: nextStatus,
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

  // Reload whenever the URL-driven filter or page changes.
  useEffect(() => {
    void fetchJobPosts(status, page);
  }, [fetchJobPosts, page, status]);

  // Reload Job Posts using optional silent/page/status overrides.
  const refresh = useCallback(
    (options?: {
      silent?: boolean;
      page?: number;
      status?: JobPostStatus | "all";
    }) => {
      return fetchJobPosts(
        options?.status ?? status,
        options?.page ?? page,
        options?.silent ?? false
      );
    },
    [fetchJobPosts, page, status]
  );

  return {
    ...state,
    refresh,
  };
}
