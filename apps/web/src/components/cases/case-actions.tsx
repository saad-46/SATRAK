"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { consoleApi, type CaseDetail, type CaseTarget } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/types";
import { CASE_STATUS, TRANSITION_LABEL } from "@/lib/labels";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function caseErrorMessage(error: unknown): { text: string; stale: boolean } {
  if (error instanceof ApiError) {
    if (
      error.isConflict ||
      error.code === "invalid_state_transition" ||
      error.code === "version_conflict"
    )
      return {
        text: "This case changed since you opened it. The latest state has been loaded; review it and try again if still appropriate.",
        stale: true,
      };
    if (error.isForbidden)
      return { text: "You are not permitted to do this in this jurisdiction.", stale: false };
    if (error.isNetwork)
      return {
        text: "The API could not be reached. Nothing was recorded; try again.",
        stale: false,
      };
    return { text: error.message, stale: false };
  }
  return { text: "The action could not be completed. Try again.", stale: false };
}

function useCaseMutation<T>(caseId: string, fn: () => Promise<T>, onDone: () => void) {
  const qc = useQueryClient();
  const [message, setMessage] = useState<string | null>(null);
  const m = useMutation({
    mutationFn: fn,
    onSuccess: async () => {
      await Promise.all(
        [["case", caseId], ["case-history", caseId], ["cases"], ["dashboard"], ["activity"]].map(
          (queryKey) => qc.invalidateQueries({ queryKey }),
        ),
      );
      setMessage(null);
      onDone();
    },
    onError: async (error) => {
      const { text, stale } = caseErrorMessage(error);
      setMessage(text);
      if (stale) {
        await qc.invalidateQueries({ queryKey: ["case", caseId] });
        await qc.invalidateQueries({ queryKey: ["case-history", caseId] });
      }
    },
  });
  return {
    m,
    message,
    clear: () => {
      setMessage(null);
      m.reset();
    },
  };
}

function Footer({
  onCancel,
  busy,
  children,
}: {
  onCancel: () => void;
  busy: boolean;
  children: ReactNode;
}) {
  return (
    <div className="flex justify-end gap-2">
      <Button type="button" variant="outline" disabled={busy} onClick={onCancel}>
        Cancel
      </Button>
      {children}
    </div>
  );
}

function Alert({ message }: { message: string | null }) {
  return (
    <div aria-live="assertive">
      {message && (
        <p
          role="alert"
          className="bg-destructive/10 text-destructive mb-3 rounded-md border px-3 py-2 text-sm"
        >
          {message}
        </p>
      )}
    </div>
  );
}

export function TransitionDialog({
  c,
  target,
  onClose,
}: {
  c: CaseDetail;
  target: CaseTarget | null;
  onClose: (done?: string) => void;
}) {
  const [reason, setReason] = useState("");
  const { m, message, clear } = useCaseMutation(
    c.id,
    () => consoleApi.transition(c.id, target!, c.version, reason.trim()),
    () => {
      setReason("");
      onClose(`Case moved to ${CASE_STATUS[target!].label}.`);
    },
  );
  if (!target) return null;
  const close = () => {
    if (!m.isPending) {
      clear();
      setReason("");
      onClose();
    }
  };
  return (
    <Modal
      open
      title={TRANSITION_LABEL[target] ?? target}
      description={`The case will move from ${CASE_STATUS[c.status].label} to ${CASE_STATUS[target].label}. The server checks that this transition and your permission are valid.`}
      onClose={close}
      busy={m.isPending}
    >
      <Alert message={message} />
      <label htmlFor="reason" className="mb-1 block text-sm font-medium">
        Reason <span className="text-muted-foreground font-normal">(optional)</span>
      </label>
      <textarea
        id="reason"
        data-autofocus
        rows={3}
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        className="bg-background mb-4 w-full rounded-md border p-2 text-sm"
      />
      <Footer onCancel={close} busy={m.isPending}>
        <Button
          variant={target === "dismissed" ? "destructive" : "default"}
          disabled={m.isPending}
          onClick={() => !m.isPending && m.mutate()}
        >
          {m.isPending ? "Recording…" : "Confirm"}
        </Button>
      </Footer>
    </Modal>
  );
}

export function AssignDialog({
  c,
  open,
  onClose,
}: {
  c: CaseDetail;
  open: boolean;
  onClose: (done?: string) => void;
}) {
  const [assignee, setAssignee] = useState("");
  const [reason, setReason] = useState("");
  const valid = UUID.test(assignee.trim());
  const { m, message, clear } = useCaseMutation(
    c.id,
    () => consoleApi.assign(c.id, assignee.trim(), c.version, reason.trim()),
    () => {
      setAssignee("");
      setReason("");
      onClose("Case assigned.");
    },
  );
  const close = () => {
    if (!m.isPending) {
      clear();
      onClose();
    }
  };
  return (
    <Modal
      open={open}
      title="Assign case"
      description="The assignee must hold case update permission in this case's jurisdiction; the server rejects anyone who does not."
      onClose={close}
      busy={m.isPending}
    >
      <Alert message={message} />
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (valid && !m.isPending) m.mutate();
        }}
        className="space-y-3"
      >
        <label htmlFor="assignee" className="block text-sm font-medium">
          Assignee user ID
        </label>
        <input
          id="assignee"
          data-autofocus
          value={assignee}
          onChange={(e) => setAssignee(e.target.value)}
          aria-invalid={assignee !== "" && !valid}
          aria-describedby="assignee-hint"
          className="bg-background w-full rounded-md border p-2 font-mono text-sm"
        />
        <p id="assignee-hint" className="text-muted-foreground text-xs">
          A user directory is not available yet, so enter the officer&apos;s user ID (UUID).
        </p>
        <label htmlFor="assign-reason" className="block text-sm font-medium">
          Reason <span className="text-muted-foreground font-normal">(optional)</span>
        </label>
        <input
          id="assign-reason"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          className="bg-background w-full rounded-md border p-2 text-sm"
        />
        <Footer onCancel={close} busy={m.isPending}>
          <Button type="submit" disabled={!valid || m.isPending}>
            {m.isPending ? "Assigning…" : "Assign"}
          </Button>
        </Footer>
      </form>
    </Modal>
  );
}

export function FindingDialog({
  c,
  open,
  onClose,
}: {
  c: CaseDetail;
  open: boolean;
  onClose: (done?: string) => void;
}) {
  const [notes, setNotes] = useState("");
  const [key, setKey] = useState("");
  const [value, setValue] = useState("");
  const measured =
    key.trim() && value.trim() !== ""
      ? { [key.trim()]: Number.isNaN(Number(value)) ? value.trim() : Number(value) }
      : {};
  const { m, message, clear } = useCaseMutation(
    c.id,
    () => consoleApi.addFinding(c.id, { notes: notes.trim(), measurements: measured }),
    () => {
      setNotes("");
      setKey("");
      setValue("");
      onClose("Case finding recorded.");
    },
  );
  const close = () => {
    if (!m.isPending) {
      clear();
      onClose();
    }
  };
  return (
    <Modal
      open={open}
      title="Record case finding"
      description="A case finding is the field inspector's site-visit record. It is separate from the AI candidate and is append-only."
      onClose={close}
      busy={m.isPending}
    >
      <Alert message={message} />
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (notes.trim() && !m.isPending) m.mutate();
        }}
        className="space-y-3"
      >
        <label htmlFor="notes" className="block text-sm font-medium">
          Site-visit notes
        </label>
        <textarea
          id="notes"
          data-autofocus
          rows={5}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          className="bg-background w-full rounded-md border p-2 text-sm"
        />
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label htmlFor="mkey" className="block text-sm font-medium">
              Measurement name <span className="text-muted-foreground font-normal">(optional)</span>
            </label>
            <input
              id="mkey"
              value={key}
              onChange={(e) => setKey(e.target.value)}
              className="bg-background w-full rounded-md border p-2 text-sm"
            />
          </div>
          <div>
            <label htmlFor="mval" className="block text-sm font-medium">
              Value
            </label>
            <input
              id="mval"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              className="bg-background w-full rounded-md border p-2 text-sm"
            />
          </div>
        </div>
        <p className="text-muted-foreground text-xs">
          Evidence file attachment is not available yet (no evidence store).
        </p>
        <Footer onCancel={close} busy={m.isPending}>
          <Button type="submit" disabled={!notes.trim() || m.isPending}>
            {m.isPending ? "Saving…" : "Record finding"}
          </Button>
        </Footer>
      </form>
    </Modal>
  );
}
