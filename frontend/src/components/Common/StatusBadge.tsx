import { Badge } from "../ui/badge";
import type { JobPostStatus } from "../../types";

interface StatusBadgeProps {
  status: JobPostStatus;
}

const statusMap: Record<JobPostStatus, { label: string; variant: "secondary" | "success" | "danger" }> = {
  draft: { label: "Draft", variant: "secondary" },
  active: { label: "Active", variant: "success" },
  closed: { label: "Closed", variant: "danger" },
};

export function StatusBadge({ status }: StatusBadgeProps) {
  const config = statusMap[status];
  return <Badge variant={config.variant}>{config.label}</Badge>;
}
