import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  vi.resetModules();
  vi.doUnmock("@/env");
  sessionStorage.clear();
});

describe("token source", () => {
  it("stores a dev token in sessionStorage only, strips Bearer, and clears", async () => {
    const t = await import("./token-source");
    t.setDevToken("  Bearer a.b.c ");
    expect(t.getToken()).toBe("a.b.c");
    expect(sessionStorage.getItem("satrak.dev-token")).toBe("a.b.c");
    expect(localStorage.length).toBe(0);
    t.clearToken();
    expect(t.getToken()).toBeNull();
  });

  it("notifies subscribers", async () => {
    const t = await import("./token-source");
    const fn = vi.fn();
    const off = t.subscribeToken(fn);
    t.setDevToken("x.y.z");
    t.clearToken();
    off();
    t.setDevToken("x.y.z");
    expect(fn).toHaveBeenCalledTimes(2);
    t.clearToken();
  });

  it("is disabled in this build", async () => {
    vi.doMock("@/env", () => ({
      env: { NEXT_PUBLIC_API_URL: "http://api.test", NEXT_PUBLIC_APP_ENV: "production" },
    }));
    const t = await import("./token-source");
    expect(t.devTokenAllowed()).toBe(false);
    expect(() => t.setDevToken("a.b.c")).toThrow(/disabled in this build/);
    sessionStorage.setItem("satrak.dev-token", "leftover");
    expect(t.getToken()).toBeNull();
  });

  it.each([
    ["opt-in unset (APP_ENV defaults to development)", "development", "false"],
    ["opt-in set but APP_ENV is production", "production", "true"],
    ["staging without opt-in", "staging", "false"],
  ])("is disabled when %s", async (_name, appEnv, optIn) => {
    vi.doMock("@/env", () => ({
      env: {
        NEXT_PUBLIC_API_URL: "http://api.test",
        NEXT_PUBLIC_APP_ENV: appEnv,
        NEXT_PUBLIC_ENABLE_DEV_TOKEN: optIn,
      },
    }));
    const t = await import("./token-source");
    expect(t.devTokenAllowed()).toBe(false);
    expect(t.getToken()).toBeNull();
  });

  it("is enabled only with the explicit opt-in outside production", async () => {
    vi.doMock("@/env", () => ({
      env: {
        NEXT_PUBLIC_API_URL: "http://api.test",
        NEXT_PUBLIC_APP_ENV: "development",
        NEXT_PUBLIC_ENABLE_DEV_TOKEN: "true",
      },
    }));
    const t = await import("./token-source");
    expect(t.devTokenAllowed()).toBe(true);
  });

  it("reads the display-only expiry from a JWT payload", async () => {
    const t = await import("./token-source");
    const payload = btoa(JSON.stringify({ exp: 1893456000 })).replace(/=/g, "");
    expect(t.tokenExpiry(`h.${payload}.s`)).toBe(1893456000);
    expect(t.tokenExpiry("garbage")).toBeNull();
    expect(t.tokenExpiry(null)).toBeNull();
  });
});

describe("token epoch", () => {
  it("changes on set and clear so cache keys never need the token itself", async () => {
    const t = await import("./token-source");
    const e0 = t.tokenEpoch();
    t.setDevToken("a.b.c");
    const e1 = t.tokenEpoch();
    t.clearToken();
    expect(e1).toBeGreaterThan(e0);
    expect(t.tokenEpoch()).toBeGreaterThan(e1);
  });
});
