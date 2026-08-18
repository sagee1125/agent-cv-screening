// JD parser panel: shows JD text, parse/save actions, and skill tags/weights for one job.
import { useState } from "react";
import { toast } from "sonner";
import { JDPasteArea } from "../JDParser/JDPasteArea";
import { SkillTagList } from "../JDParser/SkillTagList";
// import { SkillWeightDrag } from "../JDParser/SkillWeightDrag";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { parseJobJD, updateJobPost } from "../../services/jobService";
import type { JobPost } from "../../types";
import { formatDate } from "../../utils";
import { useCandidates } from "../../hooks/useCandidates";
import { BatchCVUpload } from "./BatchCVUpload";
import { CandidateHistoryGrid } from "./CandidateHistoryGrid";

interface JDParserPanelProps {
  job: JobPost;
  onSaved: () => Promise<void> | void;
}

// Build the initial flat skill list (must + preferred) from a parsed JD payload.
// function buildInitialSkills(job: JobPost): SkillItem[] {
//   if (!job.jdParsedJson) return [];
//   return [...job.jdParsedJson.mustSkills, ...job.jdParsedJson.preferredSkills];
// }

// Renders the right-side JD parser card; remounts via key when the job changes.
export function JDParserPanel({ job, onSaved }: JDParserPanelProps) {
  // useState lazy initializers read from props once at mount; key=job.id resets them.
  const [jdText, setJdText] = useState(job.description);
  const [parsing, setParsing] = useState(false);
  const [savingJD, setSavingJD] = useState(false);
  const [parseError, setParseError] = useState<string | null>(null);
  const [parsedJD, setParsedJD] = useState(job.jdParsedJson);
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

  return (
    <Card className="h-[calc(100vh-160px)]">
      <CardHeader>
        <CardTitle className="text-base">JD Parser · {job.title}</CardTitle>
      </CardHeader>
      <CardContent className="h-[calc(100%-88px)] space-y-5 overflow-y-auto">
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
            candidates={candidates.items}
            loading={candidates.loading}
          />
        </section>

        {/* <SkillWeightDrag skills={weightedSkills} onChange={setWeightedSkills} /> */}
      </CardContent>
    </Card>
  );
}
