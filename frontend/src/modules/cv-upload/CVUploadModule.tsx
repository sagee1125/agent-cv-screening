import { useMemo, useState } from "react";
import { get, post } from "../../utils";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";

type UploadStatus = "pending" | "uploading" | "success" | "failed";
type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };

interface SelectedFileEntry {
  file: File;
  localId: string;
}

interface UploadItem {
  localId: string;
  fileName: string;
  fileSize: number;
  status: UploadStatus;
  candidateId: string | null;
  extractedId: string | null;
  extractedData: JsonValue | null;
  error: string | null;
}

interface UploadResponse {
  id: string;
  extracted_id: string;
}

interface CandidateDetailResponse {
  extracted_data?: JsonValue | null;
}

const createLocalId = (file: File): string =>
  `${file.name}-${file.lastModified}-${Math.random().toString(36).slice(2, 8)}`;

const createUploadItem = (file: File, localId: string): UploadItem => ({
  localId,
  fileName: file.name,
  fileSize: file.size,
  status: "pending",
  candidateId: null,
  extractedId: null,
  extractedData: null,
  error: null,
});

function prettyFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function statusToVariant(status: UploadStatus): "secondary" | "success" | "info" | "danger" {
  if (status === "success") return "success";
  if (status === "uploading") return "info";
  if (status === "failed") return "danger";
  return "secondary";
}

export function CVUploadModule() {
  const [selectedFileEntries, setSelectedFileEntries] = useState<
    SelectedFileEntry[]
  >([]);
  const [uploads, setUploads] = useState<UploadItem[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [globalError, setGlobalError] = useState("");

  const hasFiles = selectedFileEntries.length > 0;
  const successCount = useMemo(
    () => uploads.filter((item) => item.status === "success").length,
    [uploads]
  );

  const onPickFiles = (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []).filter((file) =>
      file.name.toLowerCase().endsWith(".pdf")
    );
    const entries = files.map((file) => ({
      file,
      localId: createLocalId(file),
    }));

    setSelectedFileEntries(entries);
    setUploads(entries.map((entry) => createUploadItem(entry.file, entry.localId)));
    setGlobalError("");
  };

  const updateUpload = (
    localId: string,
    updater: (item: UploadItem) => Partial<UploadItem>
  ) => {
    setUploads((current) =>
      current.map((item) =>
        item.localId === localId ? { ...item, ...updater(item) } : item
      )
    );
  };

  const uploadSingleFile = async (file: File, localId: string) => {
    updateUpload(localId, () => ({ status: "uploading", error: null }));

    const formData = new FormData();
    formData.append("file", file);

    const uploadJson = await post<UploadResponse>("/candidates/upload", formData);
    const detailJson = await get<CandidateDetailResponse>(
      `/candidates/${uploadJson.id}`
    );

    updateUpload(localId, () => ({
      status: "success",
      candidateId: uploadJson.id,
      extractedId: uploadJson.extracted_id,
      extractedData: detailJson.extracted_data ?? {},
      error: null,
    }));
  };

  const onStartUpload = async () => {
    if (!hasFiles || isUploading) return;
    setIsUploading(true);
    setGlobalError("");

    try {
      for (const entry of selectedFileEntries) {
        try {
          await uploadSingleFile(entry.file, entry.localId);
        } catch (error) {
          updateUpload(entry.localId, () => ({
            status: "failed",
            error: error instanceof Error ? error.message : "Unknown error",
          }));
        }
      }
    } catch (error) {
      setGlobalError(
        error instanceof Error ? error.message : "Batch upload failed"
      );
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-xl">CV Batch Upload and Parsing</CardTitle>
          <CardDescription>
            Upload multiple PDF resumes at once and view the structured parsing
            result for each file.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="pdf-input">Select PDF resumes (multiple files)</Label>
            <Input
              id="pdf-input"
              type="file"
              accept=".pdf,application/pdf"
              multiple
              onChange={onPickFiles}
            />
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <Button type="button" onClick={onStartUpload} disabled={!hasFiles || isUploading}>
              {isUploading ? "Uploading and parsing..." : "Start upload and parsing"}
            </Button>
            <Badge variant="secondary">
              Selected {selectedFileEntries.length}, Succeeded {successCount}
            </Badge>
          </div>

          {globalError ? (
            <p className="text-sm font-medium text-rose-600">{globalError}</p>
          ) : null}
        </CardContent>
      </Card>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {uploads.map((item) => (
          <Card key={item.localId}>
            <CardHeader className="space-y-2">
              <div className="flex items-start justify-between gap-2">
                <CardTitle className="text-base break-all">{item.fileName}</CardTitle>
                <Badge variant={statusToVariant(item.status)}>{item.status}</Badge>
              </div>
              <CardDescription>File size: {prettyFileSize(item.fileSize)}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              {item.candidateId ? (
                <p className="text-xs text-slate-600">Candidate ID: {item.candidateId}</p>
              ) : null}
              {item.extractedId ? (
                <p className="text-xs text-slate-600">Extracted ID: {item.extractedId}</p>
              ) : null}
              {item.error ? (
                <p className="text-sm font-medium text-rose-600">{item.error}</p>
              ) : null}

              <div>
                <p className="mb-2 text-sm font-medium text-slate-700">
                  Parsed Result JSON
                </p>
                <pre className="max-h-72 overflow-auto rounded-md bg-slate-900 p-3 text-xs text-slate-50">
                  {JSON.stringify(item.extractedData, null, 2)}
                </pre>
              </div>
            </CardContent>
          </Card>
        ))}
      </section>
    </div>
  );
}
