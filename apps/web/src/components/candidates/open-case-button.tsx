"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import type { Route } from "next";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { consoleApi } from "@/lib/api/endpoints";
import { describeError } from "@/components/ui/states";

/** Opens an inspection case from a verified candidate. The database release gate still applies. */
export function OpenCaseButton({ candidateId }: { candidateId: string }) {
  const [open, setOpen] = useState(false);
  const router = useRouter();
  const queryClient = useQueryClient();
  const create = useMutation({
    mutationFn: () => consoleApi.openCase(candidateId),
    onSuccess: async (created) => {
      await queryClient.invalidateQueries({ queryKey: ["candidate", candidateId] });
      await queryClient.invalidateQueries({ queryKey: ["cases"] });
      await queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      setOpen(false);
      router.push(`/cases/${created.id}` as Route);
    },
  });
  const err = create.error ? describeError(create.error) : null;
  return (
    <>
      <Button onClick={() => setOpen(true)}>Open inspection case</Button>
      <Modal
        open={open}
        title="Open inspection case"
        description="This creates an inspection case from the officer-verified candidate and records it under your identity."
        onClose={() => !create.isPending && setOpen(false)}
        busy={create.isPending}
      >
        {err && (
          <p
            role="alert"
            className="bg-destructive/10 text-destructive mb-3 rounded-md border px-3 py-2 text-sm"
          >
            {err.title}. {err.detail}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="outline" disabled={create.isPending} onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button
            data-autofocus
            disabled={create.isPending}
            onClick={() => !create.isPending && create.mutate()}
          >
            {create.isPending ? "Opening…" : "Open case"}
          </Button>
        </div>
      </Modal>
    </>
  );
}
