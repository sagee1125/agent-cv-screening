// Drives the PolyU catalog fetch + one-by-one import flow with cancellation support.
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { getPolyUJobCatalog, importPolyUJob } from "../services/jobService";
import type { JobPostStatus } from "../types";

export interface PolyUSyncResult {
  created: number;
  skipped: number;
  failed: number;
  parseWarnings: number;
}

interface ConfirmOptions {
  title: string;
  description?: string;
  confirmLabel?: string;
  cancelLabel?: string;
}

interface UsePolyUSyncOptions {
  // Called after each successful import so the list can refresh silently.
  onJobImported?: (jobId: string) => void;
  // Called once at the end so the list reflects the final state.
  onSyncComplete?: (status: JobPostStatus | "all", page: number) => void;
  // Promise-based confirm dialog; falls back to window.confirm when omitted.
  confirm?: (options: ConfirmOptions) => Promise<boolean>;
}

interface UsePolyUSyncReturn {
  syncing: boolean;
  progress: string | null;
  sync: () => Promise<void>;
  cancel: () => void;
}

// Manages the PolyU sync lifecycle, including cancellation via AbortController.
export function usePolyUSync(
  options: UsePolyUSyncOptions = {}
): UsePolyUSyncReturn {
  const { onJobImported, onSyncComplete, confirm } = options;
  const [syncing, setSyncing] = useState(false);
  const [progress, setProgress] = useState<string | null>(null);
  // Keep the latest callbacks in refs so the sync function stays stable.
  const onJobImportedRef = useRef(onJobImported);
  const onSyncCompleteRef = useRef(onSyncComplete);
  const confirmRef = useRef(confirm);
  const abortRef = useRef<AbortController | null>(null);

  onJobImportedRef.current = onJobImported;
  onSyncCompleteRef.current = onSyncComplete;
  confirmRef.current = confirm;

  // Abort any in-flight sync when the host unmounts.
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  const cancel = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const sync = useCallback(async () => {
    if (syncing) return;
    const controller = new AbortController();
    abortRef.current = controller;
    setSyncing(true);
    setProgress("Fetching PolyU jobs...");
    try {
      const catalog = await getPolyUJobCatalog();
      if (controller.signal.aborted) return;

      const pending = catalog.items.filter((item) => !item.alreadyImported);
      if (pending.length === 0) {
        toast.message(
          catalog.total === 0
            ? "No PolyU job listings were found."
            : `All ${catalog.total} PolyU jobs are already synced.`,
          {
            position: "top-center",
          }
        );
        return;
      }

      const confirmFn = confirmRef.current;
      const confirmed = confirmFn
        ? await confirmFn({
            title: "Import PolyU jobs?",
            description: `Found ${catalog.total} PolyU jobs, ${pending.length} new. Import and parse now?`,
            confirmLabel: "Import & Parse",
          })
        : window.confirm(
            `Found ${catalog.total} PolyU jobs, ${pending.length} new. Import and parse now?`
          );
      if (!confirmed) return;

      const result: PolyUSyncResult = {
        created: 0,
        skipped: 0,
        failed: 0,
        parseWarnings: 0,
      };
      for (let index = 0; index < pending.length; index += 1) {
        if (controller.signal.aborted) break;
        const item = pending[index];
        setProgress(`Syncing ${index + 1}/${pending.length} · ${item.title}`);
        try {
          const imported = await importPolyUJob(item);
          if (imported.action === "skipped") {
            result.skipped += 1;
            continue;
          }
          result.created += 1;
          if (imported.parseError) result.parseWarnings += 1;
          onJobImportedRef.current?.(imported.job.id);
        } catch {
          result.failed += 1;
        }
      }
      onSyncCompleteRef.current?.("all", 1);
      toast.success(`Created ${result.created} PolyU jobs`, {
        position: "top-center",
      });
      if (result.skipped)
        toast(`Skipped ${result.skipped}`, {
          position: "top-center",
        });
      if (result.failed)
        toast.error(`Failed ${result.failed}`, {
          position: "top-center",
        });
      if (result.parseWarnings)
        toast.warning(`${result.parseWarnings} parse warnings`, {
          position: "top-center",
        });
    } catch (syncError) {
      if (controller.signal.aborted) return;
      toast.error(
        syncError instanceof Error
          ? syncError.message
          : "Failed to sync PolyU jobs.",
        {
          position: "top-center",
        }
      );
    } finally {
      if (abortRef.current === controller) {
        abortRef.current = null;
      }
      setSyncing(false);
      setProgress(null);
    }
  }, [syncing]);

  return { syncing, progress, sync, cancel };
}
