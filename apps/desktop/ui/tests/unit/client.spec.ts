import { describe, expect, it, vi } from "vitest";
import { ApiError, createApiClient } from "@/api/client";
import { TOKEN } from "./fixtures";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

describe("api client", () => {
  it("calls the loopback API with the bearer token", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(200, { status: "ok" }));
    await createApiClient({ port: 4000, token: TOKEN }, fetchImpl).health();
    const [url, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://127.0.0.1:4000/api/v1/health");
    expect((init.headers as Record<string, string>).Authorization).toBe(`Bearer ${TOKEN}`);
    expect(init.cache).toBe("no-store");
  });

  it("normalizes backend error bodies", async () => {
    const body = { error: { code: "unauthorized", message: "Yetkisiz istek.", recoverable: true, request_id: "x" } };
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(401, body));
    const error = await createApiClient({ port: 1, token: TOKEN }, fetchImpl).health().catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(401);
    expect((error as ApiError).code).toBe("unauthorized");
    expect((error as ApiError).userMessage).toBe("Yetkisiz istek.");
  });

  it("maps network failures to backend_unreachable", async () => {
    const fetchImpl = vi.fn().mockRejectedValue(new TypeError("Load failed"));
    const error = await createApiClient({ port: 1, token: TOKEN }, fetchImpl).health().catch((e: unknown) => e);
    expect((error as ApiError).code).toBe("backend_unreachable");
  });

  it("aborts slow requests", async () => {
    const fetchImpl = vi.fn((_url: string, init: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        init.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
      }),
    );
    const error = await createApiClient({ port: 1, token: TOKEN }, fetchImpl as typeof fetch, 20)
      .health()
      .catch((e: unknown) => e);
    expect((error as ApiError).code).toBe("backend_unreachable");
  });
});
