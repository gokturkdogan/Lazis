import { createPinia, setActivePinia } from "pinia";
import { afterEach, describe, expect, it, vi } from "vitest";
import { measure, resetMeasureForTests } from "@/measure";
import { useConnectionStore } from "@/stores/connection";
import { connection, fakeClient, fakePlatform } from "./fixtures";

async function withPlatform(enabled: boolean) {
  setActivePinia(createPinia());
  resetMeasureForTests();
  const platform = fakePlatform(connection(), { metricsEnabled: vi.fn().mockResolvedValue(enabled) });
  await useConnectionStore().start({ platform, clientFactory: () => fakeClient() });
  return platform;
}

describe("opt-in measurements (Phase 15B)", () => {
  afterEach(() => {
    useConnectionStore().stop();
    resetMeasureForTests();
  });

  it("records nothing unless LAZIS_METRICS=1 turned them on", async () => {
    const platform = await withPlatform(false);
    measure("fps", 59.7, "focused");
    await new Promise((r) => setTimeout(r, 0));
    expect(platform.metricsRecord).not.toHaveBeenCalled();
  });

  it("when on, sends numbers with a fixed detail only", async () => {
    const platform = await withPlatform(true);
    measure("stt_ms", 812.34);
    measure("fps", 59.71, "unfocused");
    await new Promise((r) => setTimeout(r, 0));
    expect(platform.metricsRecord).toHaveBeenCalledWith("stt_ms", 812.3, "");
    expect(platform.metricsRecord).toHaveBeenCalledWith("fps", 59.7, "unfocused");
  });
});
