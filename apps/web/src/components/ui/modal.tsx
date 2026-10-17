"use client";

import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

const FOCUSABLE =
  'a[href],button:not([disabled]),textarea:not([disabled]),input:not([disabled]),select:not([disabled]),[tabindex]:not([tabindex="-1"])';

// Elements that must stay reachable while a dialog is open (live regions announce route changes).
const KEEP_LIVE = "next-route-announcer,[aria-live],script,style";

/**
 * Makes everything outside `portal` inert (unfocusable, unclickable, hidden from assistive tech)
 * and returns a restore function. `aria-modal` alone is not honoured by every screen reader, and
 * a focus trap does not stop a virtual cursor from reading the page behind the dialog.
 */
function isolate(portal: HTMLElement): () => void {
  const restored: Array<() => void> = [];
  for (const el of Array.from(document.body.children)) {
    if (el === portal || el.matches(KEEP_LIVE)) continue;
    const hadInert = el.hasAttribute("inert");
    const ariaHidden = el.getAttribute("aria-hidden");
    el.setAttribute("inert", "");
    el.setAttribute("aria-hidden", "true");
    restored.push(() => {
      if (!hadInert) el.removeAttribute("inert");
      if (ariaHidden === null) el.removeAttribute("aria-hidden");
      else el.setAttribute("aria-hidden", ariaHidden);
    });
  }
  return () => restored.reverse().forEach((r) => r());
}

/**
 * Accessible modal dialog: rendered in a portal on <body>; role=dialog + aria-modal,
 * labelled/described; the rest of the page is made inert while it is open; focus moves in and is
 * trapped, Escape closes (unless busy), and focus returns to the trigger on close.
 */
export function Modal({
  open,
  title,
  description,
  onClose,
  busy = false,
  children,
}: {
  open: boolean;
  title: string;
  description?: string;
  onClose: () => void;
  busy?: boolean;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const descId = useId();
  const [portal, setPortal] = useState<HTMLElement | null>(null);
  const trigger = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;
    // Capture before the page goes inert: inert content drops focus to <body>.
    trigger.current = document.activeElement as HTMLElement | null;
    const root = document.createElement("div");
    document.body.appendChild(root);
    const release = isolate(root);
    setPortal(root);
    return () => {
      release();
      root.remove();
      setPortal(null);
      trigger.current?.focus?.();
    };
  }, [open]);

  useEffect(() => {
    if (!open || !portal) return;
    const node = ref.current;
    const first =
      node?.querySelector<HTMLElement>("[data-autofocus]") ??
      node?.querySelector<HTMLElement>(FOCUSABLE);
    first?.focus();
  }, [open, portal]);

  // Keyboard handling lives on the document so it still works if focus ever lands outside the
  // dialog (for example on <body> after a pointer click): Escape closes, Tab is kept inside.
  useEffect(() => {
    if (!open || !portal) return;
    function onKeyDown(event: KeyboardEvent) {
      const node = ref.current;
      if (!node) return;
      if (event.key === "Escape" && !busy) {
        event.stopPropagation();
        onClose();
        return;
      }
      if (event.key !== "Tab") return;
      const items = Array.from(node.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (items.length === 0) {
        event.preventDefault();
        node.focus();
        return;
      }
      const firstEl = items[0]!;
      const lastEl = items[items.length - 1]!;
      const active = document.activeElement;
      if (!node.contains(active)) {
        event.preventDefault();
        (event.shiftKey ? lastEl : firstEl).focus();
      } else if (event.shiftKey && active === firstEl) {
        event.preventDefault();
        lastEl.focus();
      } else if (!event.shiftKey && active === lastEl) {
        event.preventDefault();
        firstEl.focus();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, portal, busy, onClose]);

  if (!open || !portal) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 p-0 sm:items-center sm:p-4"
      // A click on the backdrop must not drop focus to <body>, where Escape/Tab handling is lost.
      onMouseDown={(e) => e.target === e.currentTarget && e.preventDefault()}
    >
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descId : undefined}
        tabIndex={-1}
        className="bg-popover text-popover-foreground max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-t-xl border p-5 shadow-xl sm:rounded-xl"
      >
        <h2 id={titleId} className="text-lg font-semibold">
          {title}
        </h2>
        {description && (
          <p id={descId} className="text-muted-foreground mt-1 text-sm">
            {description}
          </p>
        )}
        <div className="mt-4">{children}</div>
      </div>
    </div>,
    portal,
  );
}
