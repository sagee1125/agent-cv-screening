// Batch CV upload zone: file picker, upload-and-parse button, and candidate card grid.
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { Label } from "../ui/label";
import { Spinner } from "../ui/spinner";
import { uploadCandidateCV } from "../../services/jobService";
import { CandidateCard, type CandidateUploadItem } from "./CandidateCard";

interface BatchCVUploadProps {
  // The job this batch of CVs should be linked to.
  jobId: string;
  // Called after each successful upload so the parent can refresh the historical CV list.
  onUploaded?: () => void | Promise<void>;
}

interface FileEntry {
  file: File;
  localId: string;
}

// Builds a stable local id for a picked file so it can be tracked across renders.
const createLocalId = (file: File): string =>
  `${file.name}-${file.lastModified}-${Math.random().toString(36).slice(2, 8)}`;

// Renders the batch CV upload section with a flex-wrap grid of parsed candidate cards.
export function BatchCVUpload({ jobId, onUploaded }: BatchCVUploadProps) {
  const [files, setFiles] = useState<FileEntry[]>([]);
  const [items, setItems] = useState<CandidateUploadItem[]>([]);
  const [succeededCount, setSucceededCount] = useState(0);
  const [uploading, setUploading] = useState(false);

  const handlePickFiles = (event: React.ChangeEvent<HTMLInputElement>) => {
    const picked = Array.from(event.target.files ?? []).filter((file) =>
      file.name.toLowerCase().endsWith(".pdf")
    );
    const entries = picked.map((file) => ({
      file,
      localId: createLocalId(file),
    }));
    setFiles(entries);
    setItems(
      entries.map(({ file, localId }) => ({
        localId,
        fileName: file.name,
        fileSize: file.size,
        status: "pending" as const,
        candidateId: null,
        extractedData: null,
        error: null,
      }))
    );
    setSucceededCount(0);
  };

  const updateItem = (localId: string, patch: Partial<CandidateUploadItem>) => {
    setItems((current) =>
      current.map((item) =>
        item.localId === localId ? { ...item, ...patch } : item
      )
    );
  };

  // Drop a card from the upload area once it has been persisted to the job's CV list.
  const removeItem = (localId: string) => {
    setItems((current) => current.filter((item) => item.localId !== localId));
  };

  const handleUploadAndParse = async () => {
    if (uploading || files.length === 0) return;
    setUploading(true);
    try {
      for (const entry of files) {
        updateItem(entry.localId, { status: "uploading", error: null });
        try {
          await uploadCandidateCV(entry.file, jobId);
          // Success: the CV now lives in "Uploaded CVs", so retire it from the upload area.
          setSucceededCount((count) => count + 1);
          removeItem(entry.localId);
          await onUploaded?.();
        } catch (error) {
          updateItem(entry.localId, {
            status: "failed",
            error: error instanceof Error ? error.message : "Unknown error",
          });
        }
      }
      toast.success("Batch CV upload complete", { position: "top-center" });
    } finally {
      setUploading(false);
    }
  };

  return (
    <section className="space-y-3">
      <h3 className="text-base font-semibold text-slate-900">Batch Upload</h3>

      <div className="space-y-2">
        <Label htmlFor="batch-cv-input">
          Select PDF resumes/CVs (multiple files)
        </Label>
        <Input
          id="batch-cv-input"
          className="cursor-pointer"
          type="file"
          accept=".pdf,application/pdf"
          multiple
          onChange={handlePickFiles}
        />
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <Button
          type="button"
          onClick={handleUploadAndParse}
          disabled={files.length === 0 || uploading}
        >
          {uploading ? (
            <>
              <Spinner className="mr-2" />
              Uploading and parsing...
            </>
          ) : (
            "Upload and Parse"
          )}
        </Button>
        {files.length > 0 ? (
          <span className="text-xs text-slate-600">
            Selected {files.length}, Succeeded {succeededCount}
          </span>
        ) : null}
      </div>

      {items.length > 0 ? (
        <div className="flex flex-wrap gap-4">
          {items.map((item) => (
            <CandidateCard key={item.localId} item={item} />
          ))}
        </div>
      ) : null}
    </section>
  );
}
