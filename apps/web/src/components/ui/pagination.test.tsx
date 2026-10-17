import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Pagination } from "./pagination";

describe("Pagination", () => {
  it("reports the range, disables unavailable directions and calls back with the new page", async () => {
    const onPage = vi.fn();
    render(
      <Pagination
        meta={{ page: 2, size: 20, total: 45, total_pages: 3, has_next: true, has_previous: true }}
        onPage={onPage}
      />,
    );
    expect(screen.getByText("21–40 of 45")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(onPage).toHaveBeenCalledWith(3);
    await userEvent.click(screen.getByRole("button", { name: "Previous" }));
    expect(onPage).toHaveBeenCalledWith(1);
  });
  it("handles an empty result", () => {
    render(
      <Pagination
        meta={{ page: 1, size: 20, total: 0, total_pages: 0, has_next: false, has_previous: false }}
        onPage={() => undefined}
      />,
    );
    expect(screen.getByText("0–0 of 0")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
  });
});
