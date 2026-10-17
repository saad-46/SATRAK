import type { HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

export function Card({ className, ...props }: HTMLAttributes<HTMLElement>) {
  return (
    <section
      className={cn("bg-card text-card-foreground rounded-lg border p-4 shadow-sm", className)}
      {...props}
    />
  );
}
