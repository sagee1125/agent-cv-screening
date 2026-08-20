// JD parser panel: shows JD text, parse/save actions, and skill tags/weights for one job.
import { useState } from "react";
import { toast } from "sonner";
import { JDPasteArea } from "../JDParser/JDPasteArea";
import { SkillTagList } from "../JDParser/SkillTagList";
// import { SkillWeightDrag } from "../JDParser/SkillWeightDrag";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { Button } from "../ui/button";
import {
  parseJobJD,
  permanentlyDeleteJobPost,
  updateJobPost,
} from "../../services/jobService";
import { useConfirm } from "../Common/ConfirmProvider";
import type { JobPost } from "../../types";
import { formatDate } from "../../utils";
import { useCandidates } from "../../hooks/useCandidates";
import { BatchCVUpload } from "./BatchCVUpload";
import { CandidateHistoryGrid } from "./CandidateHistoryGrid";

interface JDParserPanelProps {
  job: JobPost;
  onSaved: () => Promise<void> | void;
  onDeleted: (jobId: string) => Promise<void> | void;
}

// Build the initial flat skill list (must + preferred) from a parsed JD payload.
// function buildInitialSkills(job: JobPost): SkillItem[] {
//   if (!job.jdParsedJson) return [];
//   return [...job.jdParsedJson.mustSkills, ...job.jdParsedJson.preferredSkills];
// }

// Renders the right-side JD parser card; remounts via key when the job changes.
export function JDParserPanel({ job, onSaved, onDeleted }: JDParserPanelProps) {
  // useState lazy initializers read from props once at mount; key=job.id resets them.
  const [jdText, setJdText] = useState(job.description);
  const [parsing, setParsing] = useState(false);
  const [savingJD, setSavingJD] = useState(false);
  const [parseError, setParseError] = useState<string | null>(null);
  const [parsedJD, setParsedJD] = useState(job.jdParsedJson);
  const [deleting, setDeleting] = useState(false);
  const confirm = useConfirm();
  // Historical CVs uploaded for this job, refreshed after each batch upload.
  const candidates = useCandidates(job.id);
  // const [weightedSkills, setWeightedSkills] = useState<SkillItem[]>(() =>
  //   buildInitialSkills(job)
  // );

  const handleParseJD = async (nextJDText: string) => {
    setParsing(true);
    setParseError(null);
    setJdText(nextJDText);
    try {
      const response = await parseJobJD(job.id, nextJDText);
      setParsedJD(response.jdParsedJson);
      // setWeightedSkills([
      //   ...response.jdParsedJson.mustSkills,
      //   ...response.jdParsedJson.preferredSkills,
      // ]);
      await onSaved();
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

  const handleSaveJD = async (nextJDText: string) => {
    setSavingJD(true);
    setJdText(nextJDText);
    try {
      await updateJobPost(job.id, { description: nextJDText });
      await onSaved();
    } catch (saveError) {
      toast.error(
        saveError instanceof Error ? saveError.message : "Failed to save JD.",
        {
          position: "top-center",
        }
      );
    } finally {
      setSavingJD(false);
    }
  };

  // Confirm then permanently delete the current job post and notify the parent page.
  const handleDeleteJob = async () => {
    const confirmed = await confirm({
      title: "Delete job post?",
      description: `This permanently deletes "${job.title}" and all uploaded CVs, scores, and related data. This cannot be undone.`,
      confirmLabel: "Delete",
      cancelLabel: "Cancel",
    });
    if (!confirmed) return;

    setDeleting(true);
    try {
      await permanentlyDeleteJobPost(job.id);
      toast.success("Job post deleted.", { position: "top-center" });
      await onDeleted(job.id);
    } catch (deleteError) {
      toast.error(
        deleteError instanceof Error
          ? deleteError.message
          : "Failed to delete job post.",
        { position: "top-center" }
      );
    } finally {
      setDeleting(false);
    }
  };

  return (
    <Card className="flex h-full flex-col">
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <CardTitle className="text-base">Job: {job.title}</CardTitle>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="border-rose-200 text-rose-600 hover:bg-rose-50 hover:text-rose-700"
            onClick={() => void handleDeleteJob()}
            disabled={deleting}
          >
            {deleting ? "Deleting..." : "Delete"}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="flex min-h-0 flex-1 flex-col space-y-5 overflow-y-auto">
        <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
          <p>Status: {job.status}</p>
          <p>Headcount: {job.headCount}</p>
          <p>Start Date: {formatDate(new Date(job.startDate))}</p>
        </div>

        <JDPasteArea
          value={jdText}
          onParse={handleParseJD}
          onSave={handleSaveJD}
          parsing={parsing}
          saving={savingJD}
        />
        {parseError ? (
          <p className="text-sm text-rose-600">{parseError}</p>
        ) : null}

        <section className="space-y-2">
          <h3 className="text-base font-semibold text-slate-900">Skill Tags</h3>
          <SkillTagList jdParsed={parsedJD} />
        </section>

        <BatchCVUpload jobId={job.id} onUploaded={candidates.refresh} />

        <section className="space-y-2">
          <h3 className="text-base font-semibold text-slate-900">
            Uploaded CVs ({candidates.total})
          </h3>
          <CandidateHistoryGrid
            jobId={job.id}
            candidates={candidates.items}
            loading={candidates.loading}
          />
        </section>

        {/* <SkillWeightDrag skills={weightedSkills} onChange={setWeightedSkills} /> */}
      </CardContent>
    </Card>
  );
}
