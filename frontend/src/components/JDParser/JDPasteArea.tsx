// import { Textarea } from "../ui/textarea";
import { Button } from "../ui/button";

interface JDPasteAreaProps {
  value: string;
  onChange: (value: string) => void;
  onParse: () => void;
  parsing?: boolean;
}

export function JDPasteArea({
  value,
  // onChange,
  onParse,
  parsing = false,
}: JDPasteAreaProps) {
  return (
    <section className="space-y-3">
      <h3 className="text-base font-semibold text-slate-900">
        Job Description
      </h3>
      <textarea
        value={value}
        disabled
        // onChange={(event) => onChange(event.target.value)}
        // placeholder="Paste JD content here..."
        className="min-h-60 w-full border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600"
      />
      <Button onClick={onParse} disabled={parsing}>
        {parsing ? "Parsing..." : "Parse JD"}
      </Button>
    </section>
  );
}
