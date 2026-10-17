"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { consoleApi, type ReviewDecision } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/types";
import { CANDIDATE_STATUS, DECISION_LABEL } from "@/lib/labels";

/** UX hint only; the server's domain rule (ADR-0014) is authoritative and validated again. */
export const MIN_JUSTIFICATION = 10;
export const MAX_JUSTIFICATION = 4000;

const CONSEQUENCE: Record<ReviewDecision, string> = {
  confirm:
    "Marks this candidate as verified by an officer. It becomes eligible for an inspection case. It does not establish a violation.",
  reject: "Marks this candidate as rejected. It will not proceed to an inspection case.",
  request_evidence: "Keeps this candidate unverified and records that more evidence is needed.",
};

export function reviewErrorMessage(error: unknown): { text: string; stale: boolean } {
  if (error instanceof ApiError) {
    if (error.isConflict || error.code === "invalid_state_transition")
      return {
        text: "This candidate changed since you opened it (it may already have been decided or have a case). The latest state has been loaded; review it and decide again if still appropriate.",
        stale: true,
      };
    if (error.isForbidden)
      return {
        text: "You are not permitted to review candidates in this jurisdiction.",
        stale: false,
      };
    if (error.status === 422 || error.status === 400) return { text: error.message, stale: false };
    if (error.isNetwork)
      return {
        text: "The API could not be reached. Your decision was not recorded; try again.",
        stale: false,
      };
    return { text: error.message, stale: false };
  }
  return { text: "The decision could not be recorded. Try again.", stale: false };
}

export function ReviewDialog({
  candidateId,
  decision,
  onClose,
}: {
  candidateId: string;
  decision: ReviewDecision | null;
  onClose: (result?: { decision: ReviewDecision; status: string }) => void;
}) {
  const queryClient = useQueryClient();
  const [justification, setJustification] = useState("");
  const [step, setStep] = useState<"form" | "confirm">("form");
  const [message, setMessage] = useState<string | null>(null);

  const trimmed = justification.trim();
  const valid = trimmed.length >= MIN_JUSTIFICATION && trimmed.length <= MAX_JUSTIFICATION;

  const submit = useMutation({
    mutationFn: () =>
      consoleApi.submitReview(candidateId, { decision: decision!, justification: trimmed }),
    onSuccess: async (review) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["candidate", candidateId] }),
        queryClient.invalidateQueries({ queryKey: ["candidate-reviews", candidateId] }),
        queryClient.invalidateQueries({ queryKey: ["candidates"] }),
        queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
        queryClient.invalidateQueries({ queryKey: ["activity"] }),
      ]);
      setJustification("");
      setStep("form");
      onClose({ decision: decision!, status: review.resulting_status });
    },
    onError: async (error) => {
      const { text, stale } = reviewErrorMessage(error);
      setMessage(text);
      setStep("form");
      if (stale) {
        await queryClient.invalidateQueries({ queryKey: ["candidate", candidateId] });
        await queryClient.invalidateQueries({ queryKey: ["candidate-reviews", candidateId] });
      }
    },
  });

  function close() {
    if (submit.isPending) return;
    setJustification("");
    setStep("form");
    setMessage(null);
    submit.reset();
    onClose();
  }

  if (!decision) return null;
  const title = DECISION_LABEL[decision];

  return (
    <Modal
      open
      title={title}
      description={CONSEQUENCE[decision]}
      onClose={close}
      busy={submit.isPending}
    >
      <div aria-live="assertive" role="status" className="min-h-0">
        {message && (
          <p
            role="alert"
            className="bg-destructive/10 text-destructive mb-3 rounded-md border px-3 py-2 text-sm"
          >
            {message}
          </p>
        )}
      </div>

      {step === "form" ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (valid) {
              setMessage(null);
              setStep("confirm");
            }
          }}
          className="space-y-3"
        >
          <label htmlFor="justification" className="block text-sm font-medium">
            Justification{" "}
            <span className="text-muted-foreground font-normal">
              (required, at least {MIN_JUSTIFICATION} characters)
            </span>
          </label>
          <textarea
            id="justification"
            data-autofocus
            rows={5}
            value={justification}
            onChange={(e) => setJustification(e.target.value)}
            aria-describedby="justification-count"
            className="bg-background w-full rounded-md border p-2 text-sm"
          />
          <p id="justification-count" className="text-muted-foreground text-xs">
            {trimmed.length} / {MAX_JUSTIFICATION}. State the evidence you relied on, not the model
            score alone.
          </p>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={close}>
              Cancel
            </Button>
            <Button type="submit" disabled={!valid}>
              Continue
            </Button>
          </div>
        </form>
      ) : (
        <div className="space-y-3">
          <p className="text-sm">
            Confirm: <strong>{title}</strong>. The server records your identity and the time;
            neither can be edited. Resulting status:{" "}
            <strong>
              {
                CANDIDATE_STATUS[
                  decision === "confirm"
                    ? "confirmed"
                    : decision === "reject"
                      ? "rejected"
                      : "needs_evidence"
                ].label
              }
            </strong>
            .
          </p>
          <blockquote className="bg-muted whitespace-pre-wrap rounded-md border-l-4 p-3 text-sm">
            {trimmed}
          </blockquote>
          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              disabled={submit.isPending}
              onClick={() => setStep("form")}
            >
              Back
            </Button>
            <Button
              type="button"
              data-autofocus
              variant={decision === "reject" ? "destructive" : "default"}
              disabled={submit.isPending}
              onClick={() => {
                if (!submit.isPending) submit.mutate();
              }}
            >
              {submit.isPending ? "Recording…" : "Record decision"}
            </Button>
          </div>
        </div>
      )}
    </Modal>
  );
}
