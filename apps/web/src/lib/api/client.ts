import { env } from "@/env";
import { ApiError, type ApiErrorEnvelope } from "./types";

/**
 * Minimal typed fetch wrapper around the SATRAK API.
 *
 * Responsibilities kept deliberately thin at the foundation stage: base-URL
 * resolution, JSON handling, correlation-id propagation, and normalizing error
 * responses into a typed {@link ApiError}. A generated client (packages/sdk)
 * will supersede hand-written per-endpoint calls once the OpenAPI surface grows.
 */

function generateRequestId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : Math.random().toString(36).slice(2);
}

export interface RequestOptions extends RequestInit {
  /** Path relative to the API base URL, e.g. "/api/v1/health/live". */
  path: string;
}

export async function apiFetch<T>({ path, headers, ...init }: RequestOptions): Promise<T> {
  const url = `${env.NEXT_PUBLIC_API_URL}${path}`;
  const requestId = generateRequestId();

  const response = await fetch(url, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-Request-ID": requestId,
      ...headers,
    },
  });

  if (!response.ok) {
    let code = `http_${response.status}`;
    let message = response.statusText;
    let serverRequestId: string | null = response.headers.get("X-Request-ID");
    let details: Record<string, unknown> = {};
    try {
      const body = (await response.json()) as ApiErrorEnvelope;
      if (body.error) {
        code = body.error.code ?? code;
        message = body.error.message ?? message;
        serverRequestId = body.error.request_id ?? serverRequestId;
        details = body.error.details ?? {};
      }
    } catch {
      // Non-JSON error body — keep the status-based defaults.
    }
    throw new ApiError(response.status, code, message, serverRequestId, details);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}
