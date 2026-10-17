import Link from "next/link";
import type { Route } from "next";
import { Card } from "@/components/ui/card";

export function StatCard({
  label,
  value,
  href,
  hint,
}: {
  label: string;
  value: number | string;
  href?: string;
  hint?: string;
}) {
  const body = (
    <>
      <p className="text-muted-foreground text-sm">{label}</p>
      <p className="mt-1 text-3xl font-semibold tabular-nums">{value}</p>
      {hint && <p className="text-muted-foreground mt-1 text-xs">{hint}</p>}
    </>
  );
  return (
    <Card className="p-0">
      {href ? (
        <Link href={href as Route} className="hover:bg-accent/40 block rounded-lg p-4">
          {body}
        </Link>
      ) : (
        <div className="p-4">{body}</div>
      )}
    </Card>
  );
}
