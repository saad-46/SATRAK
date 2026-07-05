import { apiFetch } from "./client";

/**
 * Foundation-level API calls. Only the health/version surface exists today;
 * domain endpoints are added by their feature modules as the platform grows.
 */

export interface VersionInfo {
  name: string;
  version: string;
  environment: string;
}

export interface HealthStatus {
  status: string;
}

export const api = {
  health: () => apiFetch<HealthStatus>({ path: "/api/v1/health/live" }),
  version: () => apiFetch<VersionInfo>({ path: "/api/v1/meta/version" }),
};
