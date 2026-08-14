import { useState } from "react";
import { Textarea } from "../ui/textarea";
import { Button } from "../ui/button";

interface JDPasteAreaProps {
  value: string;
  onParse: (value: string) => void;
  onSave: (value: string) => void | Promise<void>;
  parsing?: boolean;
  saving?: boolean;
}

export function JDPasteArea({
  value,
  onParse,
  onSave,
  parsing = false,
  saving = false,
}: JDPasteAreaProps) {
  const [editable, setEditable] = useState(false);
  const [draftValue, setDraftValue] = useState(value);

  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-base font-semibold text-slate-900">
          Job Description
        </h3>
        <label className="flex items-center gap-2 text-xs text-slate-700">
          <input
            type="checkbox"
            checked={editable}
            onChange={(event) => setEditable(event.target.checked)}
            className="h-4 w-4 accent-slate-700"
          />
          Enable Edit
        </label>
      </div>
      {editable ? (
        <Textarea
          value={draftValue}
          onChange={(event) => setDraftValue(event.target.value)}
          className="min-h-60 text-xs text-slate-700"
        />
      ) : (
        <textarea
          value={value}
          disabled
          className="min-h-60 w-full rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600"
        />
      )}
      <div className="flex gap-2">
        <Button
          onClick={() => onParse(editable ? draftValue : value)}
          disabled={parsing || saving}
        >
          {parsing ? "Parsing..." : "Parse JD"}
        </Button>
        {editable ? (
          <Button
            variant="outline"
            onClick={() => onSave(draftValue)}
            disabled={saving}
          >
            {saving ? "Saving..." : "Save JD"}
          </Button>
        ) : null}
      </div>
    </section>
  );
}
