/**
 * @satrak/shared — cross-cutting TypeScript types and constants shared across
 * apps and packages (nothing app-specific). Kept intentionally small at the
 * foundation stage.
 */

export const SATRAK = {
  name: "SATRAK",
  version: "0.1.0",
} as const;

/** Shape of the API error envelope, shared so web + sdk agree on it. */
export interface ApiErrorEnvelope {
  error: {
    code: string;
    message: string;
    details?: Record<string, unknown>;
    request_id?: string | null;
  };
}
