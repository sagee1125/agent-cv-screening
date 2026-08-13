import { useCallback, useEffect, useState } from "react";
import { getJobCandidates } from "../services/jobService";
import type { CandidateSummary } from "../types";

interface UseCandidatesState {
  items: CandidateSummary[];
  total: number;
  page: number;
  limit: number;
  loading: boolean;
  error: string | null;
}

export function useCandidates(jobId: string | undefined, initialPage = 1, initialLimit = 20) {
  const [state, setState] = useState<UseCandidatesState>({
    items: [],
    total: 0,
    page: initialPage,
    limit: initialLimit,
    loading: false,
    error: null,
  });

  const fetchCandidates = useCallback(
    async (page = state.page) => {
      if (!jobId) {
        return;
      }
      setState((prev) => ({ ...prev, loading: true, error: null }));
      try {
        const response = await getJobCandidates(jobId, page, state.limit);
        setState((prev) => ({
          ...prev,
          items: response.items,
          total: response.total,
          page: response.page,
          limit: response.limit,
          loading: false,
        }));
      } catch (error) {
        const message = error instanceof Error ? error.message : "Failed to load candidates.";
        setState((prev) => ({ ...prev, loading: false, error: message }));
      }
    },
    [jobId, state.limit, state.page]
  );

  useEffect(() => {
    if (jobId) {
      void fetchCandidates(initialPage);
    }
  }, [fetchCandidates, initialPage, jobId]);

  const setPage = useCallback(
    (page: number) => {
      void fetchCandidates(page);
    },
    [fetchCandidates]
  );

  return { ...state, setPage, refresh: fetchCandidates };
}
