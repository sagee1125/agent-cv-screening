// Spinner: small animated loading icon for inline pending states.
import { Loader2 } from "lucide-react";
import { cn } from "../../lib/utils";

interface SpinnerProps {
  className?: string;
}

// Renders a spinning Loader2 icon sized to match button text.
export function Spinner({ className }: SpinnerProps) {
  return (
    <Loader2 className={cn("h-4 w-4 animate-spin", className)} />
  );
}
