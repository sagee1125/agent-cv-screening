import { useMemo, useState } from "react";

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

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
  inferredSchema: JsonValue | null;
  error: string | null;
}

interface UploadResponse {
  id: string;
  extracted_id: string;
  error?: string;
  detail?: string;
}

interface CandidateDetailResponse {
  extracted_data?: JsonValue | null;
  error?: string;
  detail?: string;
}

const PRD_SCHEMA_TEMPLATE: JsonValue = {
  name: "string",
  email: "string",
  phone: "string | null",
  education: [
    {
      school: "string",
      degree: "string",
      major: "string",
      year: "number",
    },
  ],
  experience: [
    {
      company: "string",
      title: "string",
      start_date: "string",
      end_date: "string",
      description: "string",
    },
  ],
  skills: ["string"],
  publications: [
    {
      title: "string",
      journal: "string",
      year: "number",
    },
  ],
};

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
  inferredSchema: null,
  error: null,
});

function inferSchema(value: JsonValue): JsonValue {
  if (value === null) return "null";
  if (Array.isArray(value))
    return value.length > 0 ? [inferSchema(value[0])] : ["unknown"];
  if (typeof value === "object") {
    const schema: { [key: string]: JsonValue } = {};
    for (const [key, nestedValue] of Object.entries(value)) {
      schema[key] = inferSchema(nestedValue);
    }
    return schema;
  }
  return typeof value;
}

function prettyFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function statusTagClass(status: UploadStatus): string {
  if (status === "success") return "bg-emerald-100 text-emerald-700";
  if (status === "uploading") return "bg-sky-100 text-sky-700";
  if (status === "failed") return "bg-rose-100 text-rose-700";
  return "bg-slate-200 text-slate-700";
}

function App() {
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [selectedFileEntries, setSelectedFileEntries] = useState<
    SelectedFileEntry[]
  >([]);
  const [uploads, setUploads] = useState<UploadItem[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [globalError, setGlobalError] = useState("");

  const hasFiles = selectedFiles.length > 0;
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

    setSelectedFiles(files);
    setSelectedFileEntries(entries);
    setUploads(
      entries.map((entry) => createUploadItem(entry.file, entry.localId))
    );
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

    const uploadResponse = await fetch(`${API_BASE_URL}/candidates/upload`, {
      method: "POST",
      body: formData,
    });
    const uploadJson = (await uploadResponse.json()) as UploadResponse;
    if (!uploadResponse.ok) {
      throw new Error(uploadJson.error ?? uploadJson.detail ?? "上传失败");
    }

    const detailResponse = await fetch(
      `${API_BASE_URL}/candidates/${uploadJson.id}`
    );
    const detailJson = (await detailResponse.json()) as CandidateDetailResponse;
    if (!detailResponse.ok) {
      throw new Error(
        detailJson.error ?? detailJson.detail ?? "获取解析详情失败"
      );
    }

    const extractedData = detailJson.extracted_data ?? {};
    updateUpload(localId, () => ({
      status: "success",
      candidateId: uploadJson.id,
      extractedId: uploadJson.extracted_id,
      extractedData,
      inferredSchema: inferSchema(extractedData),
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
            error: error instanceof Error ? error.message : "未知错误",
          }));
        }
      }
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <main className="min-h-screen bg-slate-50 py-8">
      <div className="mx-auto w-full max-w-6xl space-y-4 px-4">
        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h1 className="text-2xl font-semibold text-slate-900">
            Batch PDF Parser
          </h1>
          <p className="mt-2 text-slate-600">
            Upload multiple PDFs at once, and display the structured parsing
            results and automatically inferred schema.
          </p>

          <div className="mt-4 space-y-2">
            <label
              htmlFor="pdf-input"
              className="block text-sm font-medium text-slate-800"
            >
              Select PDFs (multiple files allowed)
            </label>
            <input
              id="pdf-input"
              type="file"
              accept=".pdf,application/pdf"
              multiple
              onChange={onPickFiles}
              className="block w-full rounded-lg border border-slate-300 p-2 text-sm"
            />
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={onStartUpload}
              disabled={!hasFiles || isUploading}
              className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isUploading ? "Uploading..." : "Start Uploading and Parsing"}
            </button>
            <span className="text-sm text-slate-600">
              API:{" "}
              <code className="rounded bg-slate-100 px-1 py-0.5">
                {API_BASE_URL}
              </code>
            </span>
          </div>

          {globalError ? (
            <p className="mt-3 text-sm font-medium text-rose-600">
              {globalError}
            </p>
          ) : null}
          <p className="mt-3 text-sm text-slate-600">
            {selectedFiles.length} files selected, {successCount} files uploaded
            successfully.
          </p>
        </section>

        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="text-lg font-semibold text-slate-900">
            PRD Target Parsing Schema
          </h2>
          <pre className="mt-3 overflow-x-auto rounded-lg bg-slate-900 p-3 text-xs text-slate-100">
            {JSON.stringify(PRD_SCHEMA_TEMPLATE, null, 2)}
          </pre>
        </section>

        <section className="grid gap-3">
          {uploads.map((item) => (
            <article
              key={item.localId}
              className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
            >
              <header className="flex items-center justify-between gap-2">
                <h3 className="text-base font-semibold text-slate-900">
                  {item.fileName}
                </h3>
                <span
                  className={`rounded-full px-2 py-1 text-xs font-semibold uppercase tracking-wide ${statusTagClass(
                    item.status
                  )}`}
                >
                  {item.status}
                </span>
              </header>

              <p className="mt-2 text-sm text-slate-600">
                File size: {prettyFileSize(item.fileSize)}
              </p>
              {item.candidateId ? (
                <p className="mt-1 text-xs text-slate-500">
                  Candidate ID: {item.candidateId}
                </p>
              ) : null}
              {item.extractedId ? (
                <p className="mt-1 text-xs text-slate-500">
                  Extracted ID: {item.extractedId}
                </p>
              ) : null}
              {item.error ? (
                <p className="mt-2 text-sm font-medium text-rose-600">
                  {item.error}
                </p>
              ) : null}

              <h4 className="mt-4 text-sm font-semibold text-slate-800">
                Parsed Result JSON
              </h4>
              <pre className="mt-2 overflow-x-auto rounded-lg bg-slate-900 p-3 text-xs text-slate-100">
                {JSON.stringify(item.extractedData, null, 2)}
              </pre>

              <h4 className="mt-2 text-sm font-semibold text-slate-800">
                Inferred Schema from the Result
              </h4>
              <pre className="mt-2 overflow-x-auto rounded-lg bg-slate-900 p-3 text-xs text-slate-100">
                {JSON.stringify(item.inferredSchema, null, 2)}
              </pre>
            </article>
          ))}
        </section>
      </div>
    </main>
  );
}

export default App;
