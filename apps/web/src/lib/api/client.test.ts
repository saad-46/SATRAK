import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearToken, setDevToken } from "@/lib/auth/token-source";
import { apiFetch, buildQuery, onUnauthorized } from "./client";
import { ApiError } from "./types";
import { jsonResponse } from "@/test/utils";

const fetchMock = vi.fn();

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  clearToken();
});
afterEach(() => {
  fetchMock.mockReset();
  vi.unstubAllGlobals();
});

describe("buildQuery", () => {
  it("drops empty values and encodes the rest", () => {
    expect(buildQuery({ a: 1, b: "", c: undefined, d: null, e: "x y", f: false })).toBe(
      "?a=1&e=x+y&f=false",
    );
    expect(buildQuery(undefined)).toBe("");
  });
});

describe("apiFetch", () => {
  it("sends a bearer token and a request id, never in the URL", async () => {
    setDevToken("Bearer abc.def.ghi");
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }));
    await apiFetch({ path: "/api/v1/me", query: { page: 2 } });
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe("http://api.test/api/v1/me?page=2");
    expect(init.headers.Authorization).toBe("Bearer abc.def.ghi");
    expect(init.headers["X-Request-ID"]).toBeTruthy();
    expect(String(url)).not.toContain("abc.def");
  });

  it("omits Authorization without a token and sends JSON bodies", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }));
    await apiFetch({ path: "/x", method: "POST", json: { a: 1 } });
    const init = fetchMock.mock.calls[0]![1];
    expect(init.headers.Authorization).toBeUndefined();
    expect(init.headers["Content-Type"]).toBe("application/json");
    expect(init.body).toBe('{"a":1}');
  });

  it("parses problem+json into an ApiError", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(
        {
          title: "Conflict",
          status: 409,
          detail: "changed",
          code: "version_conflict",
          request_id: "req-1",
          errors: [{ field: "x" }],
        },
        { status: 409 },
      ),
    );
    const err = (await apiFetch({ path: "/x" }).catch((e: unknown) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({
      status: 409,
      code: "version_conflict",
      message: "changed",
      requestId: "req-1",
    });
    expect(err.isConflict).toBe(true);
    expect(err.errors).toEqual([{ field: "x" }]);
  });

  it("falls back to status text for non-JSON errors", async () => {
    fetchMock.mockResolvedValue(new Response("<html>", { status: 502, statusText: "Bad Gateway" }));
    const err = (await apiFetch({ path: "/x" }).catch((e: unknown) => e)) as ApiError;
    expect(err).toMatchObject({ status: 502, code: "http_502", message: "Bad Gateway" });
  });

  it("reports transport failures as status 0", async () => {
    fetchMock.mockRejectedValue(new TypeError("failed"));
    const err = (await apiFetch({ path: "/x" }).catch((e: unknown) => e)) as ApiError;
    expect(err.isNetwork).toBe(true);
  });

  it("notifies unauthorized handlers on 401", async () => {
    const handler = vi.fn();
    const off = onUnauthorized(handler);
    fetchMock.mockResolvedValue(
      jsonResponse(
        { title: "Unauthorized", status: 401, code: "unauthenticated" },
        { status: 401 },
      ),
    );
    await apiFetch({ path: "/x" }).catch(() => undefined);
    expect(handler).toHaveBeenCalledTimes(1);
    off();
    await apiFetch({ path: "/x" }).catch(() => undefined);
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("returns undefined for 204", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    await expect(apiFetch({ path: "/x" })).resolves.toBeUndefined();
  });
});
