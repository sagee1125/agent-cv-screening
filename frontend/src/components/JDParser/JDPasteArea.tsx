// Editable JD textarea with Parse and Save actions.
import { useState } from "react";
import { Textarea } from "../ui/textarea";
import { Button } from "../ui/button";
import { Label } from "../ui/label";
import { Spinner } from "../ui/spinner";
import { Switch } from "../ui/switch";

interface JDPasteAreaProps {
  value: string;
  onParse: (value: string) => void;
  onSave: (value: string) => void | Promise<void>;
  parsing?: boolean;
  saving?: boolean;
}

// Renders the JD textarea, an edit toggle, and Parse/Save buttons with spinners.
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
        <div className="flex items-center gap-2">
          <Switch
            id="jd-enable-edit"
            checked={editable}
            onCheckedChange={setEditable}
          />
          <Label
            htmlFor="jd-enable-edit"
            className="cursor-pointer text-xs font-normal text-slate-700"
          >
            Enable Edit
          </Label>
        </div>
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
          {parsing ? (
            <>
              <Spinner className="mr-2" />
              Parsing...
            </>
          ) : (
            "Parse JD"
          )}
        </Button>
        {editable ? (
          <Button
            variant="outline"
            onClick={() => onSave(draftValue)}
            disabled={saving}
          >
            {saving ? (
              <>
                <Spinner className="mr-2" />
                Saving...
              </>
            ) : (
              "Save JD"
            )}
          </Button>
        ) : null}
      </div>
    </section>
  );
}
