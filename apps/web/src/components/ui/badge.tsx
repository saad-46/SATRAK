import type { HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

const tones = {
  neutral: "bg-secondary text-secondary-foreground border-border",
  info: "bg-accent text-accent-foreground border-primary/40",
  warning: "bg-warning/15 text-warning border-warning/50",
  success: "bg-success/15 text-success border-success/50",
  danger: "bg-destructive/15 text-destructive border-destructive/50",
} as const;
export type Tone = keyof typeof tones;

/** Status is always conveyed by text as well as colour. */
export function Badge({
  tone = "neutral",
  className,
  ...props
}: HTMLAttributes<HTMLSpanElement> & { tone?: Tone }) {
  return (
    <span
      className={cn(
        "inline-flex items-center whitespace-nowrap rounded-full border px-2 py-0.5 text-xs font-medium",
        tones[tone],
        className,
      )}
      {...props}
    />
  );
}
