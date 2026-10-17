import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { consoleApi } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/types";
import { clearToken, setDevToken } from "@/lib/auth/token-source";
import { FULL_PERMS, jsonResponse, makeMe, newClient } from "@/test/utils";
import { AuthGate } from "./auth-gate";
import { SessionProvider } from "./session-provider";

function ui() {
  return (
    <QueryClientProvider client={newClient()}>
      <SessionProvider>
        <AuthGate>
          <p>console content</p>
        </AuthGate>
      </SessionProvider>
    </QueryClientProvider>
  );
}

beforeEach(() => clearToken());
afterEach(() => vi.restoreAllMocks());

describe("AuthGate", () => {
  it("asks for a token when signed out and shows the console after a valid sign-in", async () => {
    const me = vi.spyOn(consoleApi, "me").mockResolvedValue(makeMe(FULL_PERMS));
    render(ui());
    expect(screen.getByRole("heading", { name: /officer console/i })).toBeInTheDocument();
    expect(screen.queryByText("console content")).not.toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(/access token/i), "a.b.c");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
    expect(await screen.findByText("console content")).toBeInTheDocument();
    expect(me).toHaveBeenCalled();
  });

  it("shows no-access when the user holds no permissions", async () => {
    setDevToken("a.b.c");
    vi.spyOn(consoleApi, "me").mockResolvedValue(makeMe({}));
    render(ui());
    expect(await screen.findByRole("heading", { name: /no access/i })).toBeInTheDocument();
    expect(screen.queryByText("console content")).not.toBeInTheDocument();
  });

  it("shows no-access on 403", async () => {
    setDevToken("a.b.c");
    vi.spyOn(consoleApi, "me").mockRejectedValue(new ApiError(403, "forbidden", "no"));
    render(ui());
    expect(await screen.findByRole("heading", { name: /no access/i })).toBeInTheDocument();
  });

  it("signs the user out with an expiry message when the API rejects the token (401)", async () => {
    setDevToken("a.b.c");
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          jsonResponse(
            { title: "Unauthorized", status: 401, code: "unauthenticated" },
            { status: 401 },
          ),
        ),
    );
    render(ui());
    expect(await screen.findByRole("alert")).toHaveTextContent(/session has expired/i);
    expect(screen.getByLabelText(/access token/i)).toBeInTheDocument();
    expect(sessionStorage.getItem("satrak.dev-token")).toBeNull();
    vi.unstubAllGlobals();
  });

  it("offers a retry on a network failure", async () => {
    setDevToken("a.b.c");
    const me = vi
      .spyOn(consoleApi, "me")
      .mockRejectedValueOnce(new ApiError(0, "network_error", "x"))
      .mockResolvedValue(makeMe(FULL_PERMS));
    render(ui());
    expect(await screen.findByRole("alert")).toHaveTextContent(/offline|unreachable/i);
    await userEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(await screen.findByText("console content")).toBeInTheDocument();
    expect(me).toHaveBeenCalledTimes(2);
  });
});
