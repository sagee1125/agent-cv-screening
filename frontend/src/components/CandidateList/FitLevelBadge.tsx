import { Badge } from "../ui/badge";
import type { FitLevel } from "../../types";

interface FitLevelBadgeProps {
  fitLevel: FitLevel;
}

const fitLevelConfig: Record<FitLevel, { label: string; variant: "success" | "secondary" | "danger" }> = {
  high: { label: "High", variant: "success" },
  medium: { label: "Medium", variant: "secondary" },
  low: { label: "Low", variant: "danger" },
};

export function FitLevelBadge({ fitLevel }: FitLevelBadgeProps) {
  const config = fitLevelConfig[fitLevel];
  return <Badge variant={config.variant}>{config.label}</Badge>;
}
