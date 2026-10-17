import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { newClient } from "@/test/utils";

vi.mock("@/lib/auth/token-source", async (orig) => ({
  ...(await orig<typeof import("@/lib/auth/token-source")>()),
  devTokenAllowed: () => false,
  getToken: () => null,
}));

import { AuthGate } from "./auth-gate";
import { SessionProvider } from "./session-provider";

describe("AuthGate in production mode", () => {
  it("offers no manual token entry and says SSO is not configured", () => {
    render(
      <QueryClientProvider client={newClient()}>
        <SessionProvider>
          <AuthGate>
            <p>secret</p>
          </AuthGate>
        </SessionProvider>
      </QueryClientProvider>,
    );
    expect(screen.queryByLabelText(/access token/i)).not.toBeInTheDocument();
    expect(screen.getByText(/not configured in this build/i)).toBeInTheDocument();
    expect(screen.queryByText("secret")).not.toBeInTheDocument();
  });
});
