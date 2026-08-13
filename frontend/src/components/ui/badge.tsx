import * as React from "react";
import { cn } from "../../lib/utils";

type BadgeVariant =
  | "default"
  | "secondary"
  | "outline"
  | "success"
  | "info"
  | "danger";

const badgeVariantClasses: Record<BadgeVariant, string> = {
  default: "border-transparent bg-slate-900 text-slate-50",
  secondary: "border-transparent bg-slate-100 text-slate-900",
  outline: "text-slate-900",
  success: "border-transparent bg-emerald-100 text-emerald-700",
  info: "border-transparent bg-sky-100 text-sky-700",
  danger: "border-transparent bg-rose-100 text-rose-700",
};

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement> {
  variant?: BadgeVariant;
}

function Badge({ className, variant = "default", ...props }: BadgeProps) {
  return (
    <div
      className={cn(
        "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold transition-colors",
        badgeVariantClasses[variant],
        className
      )}
      {...props}
    />
  );
}

export { Badge };
