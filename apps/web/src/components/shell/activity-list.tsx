import Link from "next/link";
import type { Route } from "next";
import type { ActivityItem } from "@/lib/api/endpoints";
import { formatDateTime, humanize, shortId } from "@/lib/format";

const ENTITY_PATH: Record<string, string> = {
  candidate: "candidates",
  case: "cases",
  permit: "permits",
  parcel: "parcels",
};

/** Workflow history only: kind, summary, actor id and time. No request metadata is shown. */
export function ActivityList({ items }: { items: ActivityItem[] }) {
  return (
    <ul className="divide-y">
      {items.map((item, i) => {
        const path = ENTITY_PATH[item.entity_type];
        return (
          <li
            key={`${item.entity_id}-${item.occurred_at}-${i}`}
            className="flex flex-wrap items-baseline gap-x-3 gap-y-1 py-2 text-sm"
          >
            <time
              dateTime={item.occurred_at}
              className="text-muted-foreground w-44 shrink-0 text-xs"
            >
              {formatDateTime(item.occurred_at)}
            </time>
            <span className="font-medium">{humanize(item.kind.replace(".", " · "))}</span>
            <span className="text-muted-foreground">{item.summary}</span>
            {path && (
              <Link
                href={`/${path}/${item.entity_id}` as Route}
                className="text-primary ml-auto underline-offset-4 hover:underline"
              >
                {humanize(item.entity_type)} {shortId(item.entity_id)}
              </Link>
            )}
          </li>
        );
      })}
    </ul>
  );
}
