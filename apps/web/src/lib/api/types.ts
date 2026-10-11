/** RFC 9457 problem+json body emitted by the API (with SATRAK `code`/`request_id` extensions). */
export interface ProblemBody {
  type?: string;
  title?: string;
  status?: number;
  detail?: string | null;
  code?: string | null;
  request_id?: string | null;
  errors?: Array<Record<string, unknown>> | null;
}

/** Thrown by the API client for any non-2xx response or transport failure. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | null;
  readonly errors: Array<Record<string, unknown>>;

  constructor(
    status: number,
    code: string,
    message: string,
    requestId: string | null = null,
    errors: Array<Record<string, unknown>> = [],
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.requestId = requestId;
    this.errors = errors;
  }

  /** Status 0 means the request never reached the API (offline, DNS, CORS, TLS). */
  get isNetwork(): boolean {
    return this.status === 0;
  }
  get isUnauthenticated(): boolean {
    return this.status === 401;
  }
  get isForbidden(): boolean {
    return this.status === 403;
  }
  get isConflict(): boolean {
    return this.status === 409;
  }
}

/** Page envelope returned by every list endpoint. */
export interface PageMeta {
  page: number;
  size: number;
  total: number;
  total_pages: number;
  has_next: boolean;
  has_previous: boolean;
}
export interface PageResponse<T> {
  items: T[];
  meta: PageMeta;
}
