import { env } from "@/env";

/**
 * Bearer-token source for API calls.
 *
 * Production authentication is the platform OIDC flow (ADR-0003): the web tier obtains an access
 * token from the identity provider and hands it to this module. That integration is NOT wired yet
 * — no IdP client configuration exists in this repository — so the only implemented source is a
 * development-only manual token, held in sessionStorage for the tab's lifetime. It needs
 * NEXT_PUBLIC_ENABLE_DEV_TOKEN=true at build time and is refused when
 * NEXT_PUBLIC_APP_ENV is "production"; tokens are never written to localStorage, logged
 * or placed in URLs.
 */
const KEY = "satrak.dev-token";

type Listener = () => void;
const listeners = new Set<Listener>();
let memoryToken: string | null = null;
let epoch = 0;

/**
 * Changes every time the token is set or cleared. Used in cache keys instead of the token itself,
 * so a bearer credential never ends up in a query key (visible to devtools and error reports).
 */
export function tokenEpoch(): number {
  return epoch;
}

/**
 * Fail-closed: the manual token needs an explicit build-time opt-in AND a non-production
 * environment label. An unset or mistyped variable therefore leaves it disabled (an unset
 * NEXT_PUBLIC_APP_ENV defaults to "development", so the label alone is not a safe gate).
 */
export function devTokenAllowed(): boolean {
  return env.NEXT_PUBLIC_ENABLE_DEV_TOKEN === "true" && env.NEXT_PUBLIC_APP_ENV !== "production";
}

function storage(): Storage | null {
  try {
    return typeof window !== "undefined" ? window.sessionStorage : null;
  } catch {
    return null;
  }
}

export function getToken(): string | null {
  if (!devTokenAllowed()) return null;
  if (memoryToken) return memoryToken;
  return storage()?.getItem(KEY) ?? null;
}

export function setDevToken(token: string): void {
  if (!devTokenAllowed()) throw new Error("Manual tokens are disabled in this build.");
  const trimmed = token.trim().replace(/^Bearer\s+/i, "");
  memoryToken = trimmed || null;
  try {
    if (trimmed) storage()?.setItem(KEY, trimmed);
    else storage()?.removeItem(KEY);
  } catch {
    // sessionStorage unavailable: the in-memory copy still serves this page load.
  }
  epoch += 1;
  listeners.forEach((l) => l());
}

export function clearToken(): void {
  memoryToken = null;
  try {
    storage()?.removeItem(KEY);
  } catch {
    // ignore
  }
  epoch += 1;
  listeners.forEach((l) => l());
}

export function subscribeToken(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Decoded `exp` (seconds) for display only; never used for authorisation decisions. */
export function tokenExpiry(token: string | null): number | null {
  if (!token) return null;
  try {
    const payload = token.split(".")[1];
    if (!payload) return null;
    const json = JSON.parse(atob(payload.replace(/-/g, "+").replace(/_/g, "/"))) as {
      exp?: unknown;
    };
    return typeof json.exp === "number" ? json.exp : null;
  } catch {
    return null;
  }
}
