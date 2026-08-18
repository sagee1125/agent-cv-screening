// Skeleton: shimmering placeholder block used while content loads.
import { cn } from "../../lib/utils";

interface SkeletonProps {
  className?: string;
}

// Renders an animated placeholder box with a subtle pulse.
export function Skeleton({ className }: SkeletonProps) {
  return (
    <div
      className={cn(
        "animate-pulse rounded-md bg-slate-200/80",
        className
      )}
    />
  );
}
