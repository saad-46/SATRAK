import type { PageMeta } from "@/lib/api/types";
import { Button } from "@/components/ui/button";

export function Pagination({ meta, onPage }: { meta: PageMeta; onPage: (page: number) => void }) {
  const from = meta.total === 0 ? 0 : (meta.page - 1) * meta.size + 1;
  const to = Math.min(meta.page * meta.size, meta.total);
  return (
    <nav aria-label="Pagination" className="flex items-center justify-between gap-3 text-sm">
      <p aria-live="polite" className="text-muted-foreground">
        {from}–{to} of {meta.total}
      </p>
      <div className="flex gap-2">
        <Button
          variant="outline"
          size="sm"
          disabled={!meta.has_previous}
          onClick={() => onPage(meta.page - 1)}
        >
          Previous
        </Button>
        <span className="text-muted-foreground self-center">
          Page {meta.page} of {Math.max(meta.total_pages, 1)}
        </span>
        <Button
          variant="outline"
          size="sm"
          disabled={!meta.has_next}
          onClick={() => onPage(meta.page + 1)}
        >
          Next
        </Button>
      </div>
    </nav>
  );
}
