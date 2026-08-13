import { useEffect, useMemo, useState } from "react";
import { JDPasteArea } from "../components/JDParser/JDPasteArea";
import { SkillTagList } from "../components/JDParser/SkillTagList";
import { SkillWeightDrag } from "../components/JDParser/SkillWeightDrag";
import { JobCard } from "../components/JobCard";
import { JobPostDetail } from "../components/JobPostDetail";
import { Button } from "../components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "../components/ui/card";
import { useJobPosts } from "../hooks/useJobPosts";
import {
  deleteJobPost,
  duplicateJobPost,
  parseJobJD,
  patchJobStatus,
} from "../services/jobService";
import type { JDParsedPayload, JobPostStatus, SkillItem } from "../types";
import { formatDate } from "../utils";

const statusOptions: Array<{ label: string; value: JobPostStatus | "all" }> = [
  { label: "All", value: "all" },
  { label: "Draft", value: "draft" },
  { label: "Active", value: "active" },
  { label: "Closed", value: "closed" },
];

export function JobPostList() {
  const {
    items,
    total,
    page,
    limit,
    status,
    loading,
    error,
    setStatus,
    setPage,
    refresh,
  } = useJobPosts("all");
  const [workingJobId, setWorkingJobId] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [jdText, setJdText] = useState("");
  const [parsing, setParsing] = useState(false);
  const [parseError, setParseError] = useState<string | null>(null);
  const [parsedJD, setParsedJD] = useState<JDParsedPayload | null>(null);
  const [weightedSkills, setWeightedSkills] = useState<SkillItem[]>([]);
  const totalPages = useMemo(
    () => Math.max(1, Math.ceil(total / limit)),
    [limit, total]
  );
  const selectedJob = useMemo(
    () => items.find((job) => job.id === selectedJobId) ?? null,
    [items, selectedJobId]
  );

  useEffect(() => {
    if (items.length === 0) {
      setSelectedJobId(null);
      return;
    }
    const selectedStillExists = selectedJobId
      ? items.some((job) => job.id === selectedJobId)
      : false;
    if (!selectedStillExists) {
      setSelectedJobId(items[0].id);
    }
  }, [items, selectedJobId]);

  useEffect(() => {
    if (!selectedJob) {
      setJdText("");
      setParseError(null);
      setParsedJD(null);
      setWeightedSkills([]);
      return;
    }
    setJdText(selectedJob.description);
    setParseError(null);
    setParsedJD(selectedJob.jdParsedJson);
    const initialSkills = selectedJob.jdParsedJson
      ? [
          ...selectedJob.jdParsedJson.mustSkills,
          ...selectedJob.jdParsedJson.preferredSkills,
        ]
      : [];
    setWeightedSkills(initialSkills);
  }, [selectedJob]);

  const handleDuplicate = async (jobId: string) => {
    setWorkingJobId(jobId);
    try {
      await duplicateJobPost(jobId);
      refresh();
    } catch (duplicateError) {
      window.alert(
        duplicateError instanceof Error
          ? duplicateError.message
          : "Failed to duplicate"
      );
    } finally {
      setWorkingJobId(null);
    }
  };

  const handleArchive = async (jobId: string) => {
    setWorkingJobId(jobId);
    try {
      await deleteJobPost(jobId);
      refresh();
    } catch (archiveError) {
      window.alert(
        archiveError instanceof Error
          ? archiveError.message
          : "Failed to archive"
      );
    } finally {
      setWorkingJobId(null);
    }
  };

  const handleToggleStatus = async (
    jobId: string,
    statusValue: JobPostStatus
  ) => {
    setWorkingJobId(jobId);
    try {
      await patchJobStatus(jobId, { status: statusValue });
      refresh();
    } catch (statusError) {
      window.alert(
        statusError instanceof Error
          ? statusError.message
          : "Failed to update status"
      );
    } finally {
      setWorkingJobId(null);
    }
  };

  const handleParseJD = async () => {
    if (!selectedJob) return;
    setParsing(true);
    setParseError(null);
    try {
      const response = await parseJobJD(selectedJob.id, jdText);
      setParsedJD(response.jdParsedJson);
      setWeightedSkills([
        ...response.jdParsedJson.mustSkills,
        ...response.jdParsedJson.preferredSkills,
      ]);
      refresh();
    } catch (parseJDError) {
      const message =
        parseJDError instanceof Error
          ? parseJDError.message
          : "Failed to parse JD.";
      setParseError(message);
    } finally {
      setParsing(false);
    }
  };

  return (
    <main className="min-h-screen bg-slate-50 py-6">
      <div className="mx-auto w-full max-w-7xl space-y-5 px-4">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-semibold text-slate-900">Job Posts</h1>
          <Button onClick={() => setCreateOpen(true)}>New Job Post</Button>
        </div>

        <div className="grid grid-cols-1 gap-5 xl:grid-cols-[420px_minmax(0,1fr)]">
          <Card className="h-[calc(100vh-160px)]">
            <CardHeader className="space-y-4">
              <CardTitle className="text-base">Job List</CardTitle>
              <div className="flex flex-wrap gap-2">
                {statusOptions.map((option) => (
                  <Button
                    key={option.value}
                    size="sm"
                    variant={status === option.value ? "default" : "outline"}
                    onClick={() => setStatus(option.value)}
                  >
                    {option.label}
                  </Button>
                ))}
              </div>
            </CardHeader>
            <CardContent className="flex h-[calc(100%-120px)] flex-col gap-4">
              {loading ? (
                <p className="text-sm text-slate-500">Loading job posts...</p>
              ) : null}
              {error ? <p className="text-sm text-rose-600">{error}</p> : null}

              {!loading && !error ? (
                <div className="space-y-3 overflow-y-auto pr-1">
                  {items.map((job) => (
                    <div
                      key={job.id}
                      role="button"
                      tabIndex={0}
                      onClick={() => setSelectedJobId(job.id)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          setSelectedJobId(job.id);
                        }
                      }}
                      className={`cursor-pointer rounded-xl transition ${
                        selectedJobId === job.id
                          ? "ring-2 ring-sky-500"
                          : "hover:ring-1 hover:ring-slate-300"
                      } ${workingJobId === job.id ? "opacity-60" : ""}`}
                    >
                      <JobCard
                        job={job}
                        onViewDetail={setSelectedJobId}
                        onDuplicate={handleDuplicate}
                        onArchive={handleArchive}
                        onToggleStatus={handleToggleStatus}
                      />
                    </div>
                  ))}
                </div>
              ) : null}

              <div className="mt-auto flex items-center justify-between border-t border-slate-100 pt-3">
                <p className="text-xs text-slate-500">
                  Page {page} / {totalPages} · Total {total}
                </p>
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setPage(Math.max(1, page - 1))}
                    disabled={page <= 1}
                  >
                    Prev
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setPage(Math.min(totalPages, page + 1))}
                    disabled={page >= totalPages}
                  >
                    Next
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>

          <Card className="h-[calc(100vh-160px)]">
            <CardHeader>
              <CardTitle className="text-base">
                {selectedJob ? `JD Parser · ${selectedJob.title}` : "JD Parser"}
              </CardTitle>
            </CardHeader>
            <CardContent className="h-[calc(100%-88px)] overflow-y-auto space-y-5">
              {!selectedJob ? (
                <p className="text-sm text-slate-500">
                  Select a job card from the left list to view JD parser
                  details.
                </p>
              ) : (
                <>
                  <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
                    <p>Status: {selectedJob.status}</p>
                    <p>Headcount: {selectedJob.headCount}</p>
                    <p>
                      Start Date: {formatDate(new Date(selectedJob.startDate))}
                    </p>
                  </div>

                  <JDPasteArea
                    value={jdText}
                    onChange={setJdText}
                    onParse={handleParseJD}
                    parsing={parsing}
                  />
                  {parseError ? (
                    <p className="text-sm text-rose-600">{parseError}</p>
                  ) : null}

                  <section className="space-y-2">
                    <h3 className="text-base font-semibold text-slate-900">
                      Skill Tags
                    </h3>
                    <SkillTagList jdParsed={parsedJD} />
                  </section>

                  <SkillWeightDrag
                    skills={weightedSkills}
                    onChange={setWeightedSkills}
                  />
                </>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
      {createOpen && (
        <JobPostDetail
          editable
          onClose={() => setCreateOpen(false)}
          onSaved={refresh}
        />
      )}
    </main>
  );
}
