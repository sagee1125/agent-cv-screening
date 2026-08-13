import { FormEvent, useState } from "react";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Textarea } from "../components/ui/textarea";
import type { JobPostCreateInput } from "../types";

interface JobPostFormProps {
  initialValue?: Partial<JobPostCreateInput>;
  saveText?: string;
  closeText?: string;
  formTitle?: string;
  onSubmit: (payload: JobPostCreateInput) => Promise<void> | void;
  onClose: () => void;
}

export function JobPostForm({
  initialValue,
  saveText = "Save & Close",
  closeText = "Close",
  formTitle = "Create Job Post",
  onSubmit,
  onClose,
}: JobPostFormProps) {
  const [title, setTitle] = useState(initialValue?.title ?? "");
  const [description, setDescription] = useState(
    initialValue?.description ?? ""
  );
  const [headCount, setHeadCount] = useState(initialValue?.headCount ?? 1);
  const [startDate, setStartDate] = useState(initialValue?.startDate ?? "");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);

    if (!title.trim() || !description.trim() || !startDate) {
      setError("Title, JD description and start date are required.");
      return;
    }

    setLoading(true);
    try {
      await onSubmit({
        title: title.trim(),
        description,
        headCount,
        startDate,
        status: "draft",
      });
    } catch (submitError) {
      const message =
        submitError instanceof Error
          ? submitError.message
          : "Failed to submit form.";
      setError(message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <form className="space-y-4" onSubmit={handleSubmit}>
      <h3 className="text-lg font-semibold text-slate-900">{formTitle}</h3>
      <div className="space-y-2">
        <Label htmlFor="job-title">Job Title</Label>
        <Input
          id="job-title"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="job-description">JD Full Text</Label>
        <Textarea
          id="job-description"
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          rows={10}
          className="min-h-36"
        />
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="head-count">Head Count</Label>
          <Input
            id="head-count"
            type="number"
            min={1}
            value={headCount}
            onChange={(event) => setHeadCount(Number(event.target.value))}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="start-date">Start Date</Label>
          <Input
            id="start-date"
            type="date"
            value={startDate}
            onChange={(event) => setStartDate(event.target.value)}
          />
        </div>
      </div>

      {error ? <p className="text-sm text-rose-600">{error}</p> : null}

      <div className="flex gap-2">
        <Button type="submit" disabled={loading}>
          {loading ? "Saving..." : saveText}
        </Button>
        <Button type="button" variant="outline" onClick={onClose}>
          {closeText}
        </Button>
      </div>
    </form>
  );
}
