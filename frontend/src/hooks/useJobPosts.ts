import { useCallback, useEffect, useState } from "react";
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

export function useJobPosts(initialStatus: JobPostStatus | "all" = "all") {
  const [state, setState] = useState<UseJobPostsState>({
    items: [],
    total: 0,
    page: 1,
    limit: 12,
    status: initialStatus,
    loading: true,
    error: null,
  });

  const fetchJobPosts = useCallback(
    async (status = state.status, page = state.page) => {
      setState((prev) => ({ ...prev, loading: true, error: null }));
      try {
        const response = await getJobPosts({
          status,
          page,
          limit: state.limit,
        });
        setState((prev) => ({
          ...prev,
          items: response.items,
          total: response.total,
          page: response.page,
          limit: response.limit,
          status,
          loading: false,
        }));
      } catch (error) {
        const message =
          error instanceof Error ? error.message : "Failed to load Job Posts.";
        setState((prev) => ({ ...prev, loading: false, error: message }));
      }
    },
    [state.limit, state.page, state.status]
  );

  useEffect(() => {
    void fetchJobPosts(state.status, 1);
  }, [fetchJobPosts, state.status]);

  const setStatus = (status: JobPostStatus | "all") => {
    void fetchJobPosts(status, 1);
  };

  const setPage = useCallback(
    (page: number) => {
      void fetchJobPosts(state.status, page);
    },
    [fetchJobPosts, state.status]
  );

  const refresh = useCallback(() => {
    void fetchJobPosts(state.status, state.page);
  }, [fetchJobPosts, state.page, state.status]);

  return {
    ...state,
    setStatus,
    setPage,
    refresh,
  };
}
