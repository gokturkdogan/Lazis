/**
 * Typed client for the local LAZIS API (types generated from the backend's OpenAPI schema).
 * Every request carries the per-launch bearer token; errors are normalized to ApiError.
 */
import type { components } from "./schema";

type Schemas = components["schemas"];
export type HealthResponse = Schemas["HealthResponse"];
export type AppInfoResponse = Schemas["AppInfoResponse"];
export type SystemStatusResponse = Schemas["SystemStatusResponse"];
export type EffectiveSettingsResponse = Schemas["EffectiveSettingsResponse"];
type ErrorResponse = Schemas["ErrorResponse"];

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    readonly userMessage: string,
    readonly recoverable: boolean,
  ) {
    super(code);
    this.name = "ApiError";
  }
}

export interface ApiConnection {
  port: number;
  token: string;
}

export interface ApiClient {
  health(): Promise<HealthResponse>;
  appInfo(): Promise<AppInfoResponse>;
  systemStatus(): Promise<SystemStatusResponse>;
  settings(): Promise<EffectiveSettingsResponse>;
}

function isErrorResponse(value: unknown): value is ErrorResponse {
  return (
    typeof value === "object" &&
    value !== null &&
    "error" in value &&
    typeof (value as { error: unknown }).error === "object"
  );
}

export function createApiClient(
  connection: ApiConnection,
  fetchImpl: typeof fetch = fetch,
  timeoutMs = 5000,
): ApiClient {
  const base = `http://127.0.0.1:${connection.port}/api/v1`;

  async function get<T>(path: string): Promise<T> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    let response: Response;
    try {
      response = await fetchImpl(`${base}${path}`, {
        method: "GET",
        headers: { Authorization: `Bearer ${connection.token}` },
        signal: controller.signal,
        cache: "no-store",
      });
    } catch {
      throw new ApiError(0, "backend_unreachable", "", true);
    } finally {
      clearTimeout(timer);
    }
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      body = null;
    }
    if (!response.ok) {
      if (isErrorResponse(body)) {
        const { code, message, recoverable } = body.error;
        throw new ApiError(response.status, code, message, recoverable);
      }
      throw new ApiError(response.status, "internal_error", "", false);
    }
    return body as T;
  }

  return {
    health: () => get<HealthResponse>("/health"),
    appInfo: () => get<AppInfoResponse>("/app/info"),
    systemStatus: () => get<SystemStatusResponse>("/system/status"),
    settings: () => get<EffectiveSettingsResponse>("/settings"),
  };
}
