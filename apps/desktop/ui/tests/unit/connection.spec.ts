import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/api/client";
import { useConnectionStore } from "@/stores/connection";
import { connection, fakeClient, fakePlatform, TOKEN } from "./fixtures";

describe("connection store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });
  afterEach(() => {
    useConnectionStore().stop();
    vi.useRealTimers();
  });

  it("connects when the shell reports ready and keeps the token out of state", async () => {
    const client = fakeClient();
    const factory = vi.fn().mockReturnValue(client);
    const store = useConnectionStore();
    await store.start({ platform: fakePlatform(connection()), clientFactory: factory });

    expect(factory).toHaveBeenCalledWith({ port: 51234, token: TOKEN });
    expect(store.phase).toBe("connected");
    expect(store.status?.database.encryption_verified).toBe(true);
    expect(JSON.stringify(store.$state)).not.toContain(TOKEN);
  });

  it("shows startup failures with their error code", async () => {
    const store = useConnectionStore();
    await store.start({
      platform: fakePlatform(connection({ phase: "failed", token: null, errorCode: "keychain_denied" })),
    });
    expect(store.phase).toBe("backend_failed");
    expect(store.errorCode).toBe("keychain_denied");
  });

  it("asks for the recovery code when the key is missing", async () => {
    const store = useConnectionStore();
    await store.start({
      platform: fakePlatform(connection({ phase: "needs_recovery", token: null, port: null })),
    });
    expect(store.phase).toBe("needs_recovery");
  });

  it("becomes disconnected after repeated poll failures and re-syncs with the shell", async () => {
    vi.useFakeTimers();
    const client = fakeClient();
    const platform = fakePlatform(connection());
    const store = useConnectionStore();
    await store.start({ platform, clientFactory: () => client, pollMs: 1000 });
    expect(store.phase).toBe("connected");

    const unreachable = new ApiError(0, "backend_unreachable", "", true);
    vi.mocked(client.health).mockRejectedValue(unreachable);
    await vi.advanceTimersByTimeAsync(1000);
    expect(store.phase).toBe("connected"); // one failure is tolerated
    await vi.advanceTimersByTimeAsync(1000);
    expect(store.phase).toBe("disconnected");
    expect(store.errorCode).toBe("backend_unreachable");
    expect(platform.getConnection).toHaveBeenCalledTimes(2);
  });

  it("retries through the shell", async () => {
    const platform = fakePlatform(connection({ phase: "failed", token: null, errorCode: "backend_exited" }));
    const store = useConnectionStore();
    await store.start({ platform, clientFactory: () => fakeClient() });
    await store.retry();
    expect(platform.retryBackend).toHaveBeenCalledOnce();
    expect(store.phase).toBe("connected");
  });

  it("surfaces restore errors as codes for the form", async () => {
    const platform = fakePlatform(connection({ phase: "needs_recovery", token: null }), {
      restoreFromRecoveryCode: vi.fn().mockRejectedValue({ code: "recovery_code_invalid", message: "x" }),
    });
    const store = useConnectionStore();
    await store.start({ platform });
    await expect(store.restore("LZR1-WRONG")).rejects.toThrow("recovery_code_invalid");
    expect(store.phase).toBe("needs_recovery");
  });

  it("clears the pending recovery flag after acknowledgement", async () => {
    const platform = fakePlatform(connection({ recoveryPending: true }));
    const store = useConnectionStore();
    await store.start({ platform, clientFactory: () => fakeClient() });
    expect(store.recoveryPending).toBe(true);
    await store.acknowledgeRecovery();
    expect(store.recoveryPending).toBe(false);
  });
});
