import { env } from "@/env";
import { getToken } from "@/lib/auth/token-source";
import { ApiError, type ProblemBody } from "./types";

/**
 * Typed fetch wrapper around the SATRAK API: base URL, bearer token, JSON, correlation id, and
 * normalisation of RFC 9457 problem responses (and transport failures) into {@link ApiError}.
 */

function generateRequestId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : Math.random().toString(36).slice(2);
}

type UnauthorizedHandler = (error: ApiError) => void;
const unauthorizedHandlers = new Set<UnauthorizedHandler>();

/** Register a callback fired on every 401 (session expired / token rejected). */
export function onUnauthorized(handler: UnauthorizedHandler): () => void {
  unauthorizedHandlers.add(handler);
  return () => unauthorizedHandlers.delete(handler);
}

export interface RequestOptions extends Omit<RequestInit, "body"> {
  /** Path relative to the API base URL, e.g. "/api/v1/candidates". */
  path: string;
  query?: Record<string, string | number | boolean | null | undefined>;
  json?: unknown;
}

export function buildQuery(query: RequestOptions["query"]): string {
  if (!query) return "";
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === "") continue;
    params.set(key, String(value));
  }
  const text = params.toString();
  return text ? `?${text}` : "";
}

export async function apiFetch<T>({
  path,
  query,
  json,
  headers,
  ...init
}: RequestOptions): Promise<T> {
  const url = `${env.NEXT_PUBLIC_API_URL}${path}${buildQuery(query)}`;
  const token = getToken();
  const requestHeaders: Record<string, string> = {
    Accept: "application/json",
    "X-Request-ID": generateRequestId(),
    ...(json !== undefined ? { "Content-Type": "application/json" } : {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(headers as Record<string, string> | undefined),
  };

  let response: Response;
  try {
    response = await fetch(url, {
      ...init,
      headers: requestHeaders,
      body: json !== undefined ? JSON.stringify(json) : undefined,
    });
  } catch {
    throw new ApiError(0, "network_error", "The API could not be reached.");
  }

  if (!response.ok) {
    let code = `http_${response.status}`;
    let message = response.statusText || `Request failed (${response.status})`;
    let requestId = response.headers.get("X-Request-ID");
    let errors: Array<Record<string, unknown>> = [];
    try {
      const body = (await response.json()) as ProblemBody;
      code = body.code ?? code;
      message = body.detail ?? body.title ?? message;
      requestId = body.request_id ?? requestId;
      errors = body.errors ?? [];
    } catch {
      // Non-JSON error body: keep status-based defaults.
    }
    const error = new ApiError(response.status, code, message, requestId, errors);
    if (response.status === 401) unauthorizedHandlers.forEach((h) => h(error));
    throw error;
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
