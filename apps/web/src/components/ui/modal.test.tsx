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
