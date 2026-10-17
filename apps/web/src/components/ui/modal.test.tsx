import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { Modal } from "./modal";

function Harness({ busy = false }: { busy?: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button onClick={() => setOpen(true)}>open</button>
      <Modal
        open={open}
        title="Title"
        description="Desc"
        onClose={() => setOpen(false)}
        busy={busy}
      >
        <input aria-label="first" />
        <button>last</button>
      </Modal>
    </>
  );
}

describe("Modal", () => {
  it("is labelled and described, focuses inside, traps Tab, closes on Escape and restores focus", async () => {
    render(<Harness />);
    const trigger = screen.getByRole("button", { name: "open" });
    await userEvent.click(trigger);
    const dialog = screen.getByRole("dialog", { name: "Title" });
    expect(dialog).toHaveAccessibleDescription("Desc");
    expect(screen.getByLabelText("first")).toHaveFocus();
    await userEvent.tab();
    expect(screen.getByRole("button", { name: "last" })).toHaveFocus();
    await userEvent.tab();
    expect(screen.getByLabelText("first")).toHaveFocus();
    await userEvent.tab({ shift: true });
    expect(screen.getByRole("button", { name: "last" })).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("ignores Escape while busy", async () => {
    render(<Harness busy />);
    await userEvent.click(screen.getByRole("button", { name: "open" }));
    await userEvent.keyboard("{Escape}");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});

describe("Modal isolation", () => {
  it("renders in a body-level portal and makes the rest of the page inert while open", async () => {
    const { container } = render(<Harness />);
    const trigger = screen.getByRole("button", { name: "open" });
    expect(container).not.toHaveAttribute("inert");
    await userEvent.click(trigger);
    const dialog = screen.getByRole("dialog", { name: "Title" });
    expect(container.contains(dialog)).toBe(false);
    expect(container).toHaveAttribute("inert");
    expect(container).toHaveAttribute("aria-hidden", "true");
    // The portal itself must not be inert, or the dialog would be unreachable.
    expect(dialog.closest("[inert]")).toBeNull();
    expect(screen.queryByRole("button", { name: "open" })).not.toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    expect(container).not.toHaveAttribute("inert");
    expect(container).not.toHaveAttribute("aria-hidden");
    expect(document.body.querySelectorAll("[role=dialog]")).toHaveLength(0);
  });

  it("still closes on Escape and keeps Tab inside when focus has fallen to <body>", async () => {
    render(<Harness />);
    await userEvent.click(screen.getByRole("button", { name: "open" }));
    (document.activeElement as HTMLElement).blur();
    expect(document.body).toHaveFocus();
    await userEvent.tab();
    expect(screen.getByRole("dialog")).toContainElement(document.activeElement as HTMLElement);
    (document.activeElement as HTMLElement).blur();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("restores a pre-existing aria-hidden value instead of clearing it", async () => {
    const { container } = render(<Harness />);
    container.setAttribute("aria-hidden", "false");
    await userEvent.click(screen.getByRole("button", { name: "open", hidden: true }));
    await userEvent.keyboard("{Escape}");
    expect(container).toHaveAttribute("aria-hidden", "false");
  });
});
