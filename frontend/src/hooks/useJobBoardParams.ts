// Reads and writes Job Board selection/filter state in the URL search string.
import { useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import type { JobPostStatus } from "../types";

interface JobBoardParamsPatch {
  jobId?: string | null;
  status?: JobPostStatus | "all";
  page?: number;
  candidateId?: string | null;
}

const STATUS_VALUES: Array<JobPostStatus | "all"> = [
  "all",
  "draft",
  "active",
  "closed",
];

/** Parses a status query value, defaulting to all when missing or invalid. */
function parseStatus(value: string | null): JobPostStatus | "all" {
  if (value && STATUS_VALUES.includes(value as JobPostStatus | "all")) {
    return value as JobPostStatus | "all";
  }
  return "all";
}

/** Parses a 1-based page query value, defaulting to 1 when missing or invalid. */
function parsePage(value: string | null): number {
  const page = Number(value);
  if (!Number.isInteger(page) || page < 1) return 1;
  return page;
}

/** Keeps selected job, status filter, and list page in the URL as source of truth. */
export function useJobBoardParams() {
  const [searchParams, setSearchParams] = useSearchParams();
  const jobId = searchParams.get("jobId");
  const candidateId = searchParams.get("candidateId");
  const status = parseStatus(searchParams.get("status"));
  const page = parsePage(searchParams.get("page"));

  // Merges a patch into the current search params without stacking history.
  const replaceParams = useCallback(
    (patch: JobBoardParamsPatch) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (patch.jobId !== undefined) {
            if (patch.jobId) next.set("jobId", patch.jobId);
            else next.delete("jobId");
          }
          if (patch.status !== undefined) {
            if (patch.status === "all") next.delete("status");
            else next.set("status", patch.status);
          }
          if (patch.page !== undefined) {
            if (patch.page <= 1) next.delete("page");
            else next.set("page", String(patch.page));
          }
          if (patch.candidateId !== undefined) {
            if (patch.candidateId) next.set("candidateId", patch.candidateId);
            else next.delete("candidateId");
          }
          return next;
        },
        { replace: true }
      );
    },
    [setSearchParams]
  );

  return { jobId, candidateId, status, page, replaceParams };
}
