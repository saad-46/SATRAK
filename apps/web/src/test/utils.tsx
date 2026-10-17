import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderResult } from "@testing-library/react";
import { Suspense, type ReactElement } from "react";
import { vi } from "vitest";
import type { Me } from "@/lib/api/endpoints";
import { can as canPermission } from "@/lib/permissions";

export const J1 = "11111111-1111-4111-8111-111111111111";
export const J2 = "22222222-2222-4222-8222-222222222222";
export const USER = "99999999-9999-4999-8999-999999999999";

export function makeMe(permissions: Record<string, string[]>, jurisdictions = [J1]): Me {
  return {
    user_id: USER,
    status: "active",
    permissions,
    jurisdictions: jurisdictions.map((id, i) => ({
      id,
      code: `J${i + 1}`,
      name: `Ward ${i + 1}`,
      level: "ward",
    })),
  };
}

export const FULL_PERMS = Object.fromEntries(
  [
    "parcel:read",
    "property:read",
    "permit:read",
    "candidate:read",
    "finding:verify",
    "case:read",
    "case:create",
    "case:assign",
    "case:update",
  ].map((p) => [p, [J1]]),
);

export function newClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
}

export function renderWithClient(
  ui: ReactElement,
  client = newClient(),
): RenderResult & { client: QueryClient } {
  const result = render(
    <QueryClientProvider client={client}>
      <Suspense fallback={<p>suspended</p>}>{ui}</Suspense>
    </QueryClientProvider>,
  );
  return Object.assign(result, { client });
}

/** A promise React's `use()` can read synchronously. */
export function resolved<T>(value: T): Promise<T> {
  return Object.assign(Promise.resolve(value), { status: "fulfilled" as const, value });
}

export function sessionFor(me: Me | undefined) {
  return {
    status: "authenticated" as const,
    me,
    error: undefined,
    can: (p: string, j?: string) => canPermission(me, p, j),
    signOut: vi.fn(),
    retry: vi.fn(),
  };
}

export function jsonResponse(
  body: unknown,
  init: { status?: number; headers?: Record<string, string> } = {},
) {
  return new Response(JSON.stringify(body), {
    status: init.status ?? 200,
    headers: {
      "Content-Type":
        init.status && init.status >= 400 ? "application/problem+json" : "application/json",
      ...init.headers,
    },
  });
}

/** Current fake session for tests that mock `useSession`. */
export const session: { current: ReturnType<typeof sessionFor> } = {
  current: sessionFor(makeMe({})),
};
export function asUser(permissions: Record<string, string[]>, jurisdictions = [J1]) {
  session.current = sessionFor(makeMe(permissions, jurisdictions));
  return session.current;
}
