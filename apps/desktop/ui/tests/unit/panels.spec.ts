import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "@/App.vue";
import type { ApiClient } from "@/api/client";
import { createAppI18n } from "@/i18n";
import type { Platform, View } from "@/platform/tauri";
import { useAssistantStore } from "@/stores/assistant";
import { useConnectionStore } from "@/stores/connection";
import DiagnosticsView from "@/views/DiagnosticsView.vue";
import SettingsView from "@/views/SettingsView.vue";
import { connection, diagnosticsFixture, fakeClient, fakePlatform } from "./fixtures";

async function mountView(
  component: typeof DiagnosticsView | typeof SettingsView | typeof App,
  client: ApiClient = fakeClient(),
  platformOverrides: Partial<Platform> = {},
) {
  const pinia = createPinia();
  setActivePinia(pinia);
  const platform = fakePlatform(connection(), platformOverrides);
  await useConnectionStore().start({ platform, clientFactory: () => client });
  const wrapper = mount(component, { global: { plugins: [pinia, createAppI18n()] } });
  await flushPromises();
  return { wrapper, platform, client };
}

describe("Diagnostics panel", () => {
  beforeEach(() => setActivePinia(createPinia()));
  afterEach(() => {
    useAssistantStore().stop();
    useConnectionStore().stop();
    vi.useRealTimers();
  });

  it("shows model, backend, performance, context preparation and memory with its source", async () => {
    const { wrapper } = await mountView(DiagnosticsView);
    const text = wrapper.text();
    expect(wrapper.get('[data-testid="diag-model"]').text()).toContain("gemma4:12b-it-qat");
    expect(text).toContain("qwen3.5:9b-q4_K_M (yüklü değil)");
    expect(text).toContain("Yok — model değişikliği yalnızca sizin seçiminizle");
    expect(wrapper.get('[data-testid="diag-backend"]').text()).toContain("Bağlı");
    const perf = wrapper.get('[data-testid="diag-performance"]').text();
    expect(perf).toContain("0.82 sn"); // TTFT
    expect(perf).toContain("4.10 sn"); // total, reported separately
    expect(perf).toContain("38.4 token/sn");
    const prewarm = wrapper.get('[data-testid="diag-prewarm"]').text();
    expect(prewarm).toContain("Bağlam hazırlandı");
    expect(prewarm).toContain("Ollama bunu doğrulamaz");
    expect(text).not.toMatch(/kesinlikle/i);
    const memory = wrapper.get('[data-testid="diag-memory"]').text();
    expect(memory).toContain("LAZIS arka ucu (Python) (pid 11)");
    expect(memory).toContain("70 MB");
    expect(memory).toContain("Okunamadı"); // unknown is unknown, never estimated
    expect(memory).toContain("phys_footprint");
    expect(memory).toContain("toplam RAM kullanımı değildir");
  });

  it("a model-only pre-warm is not presented as a prepared conversation", async () => {
    const client = fakeClient({
      diagnostics: vi.fn().mockResolvedValue(
        diagnosticsFixture({
          prewarm: { state: "done", scope: "model_only", at: "2026-10-18T09:59:00.000Z", duration_ms: 3100 },
          cache_expected_warm: false,
        }),
      ),
    });
    const { wrapper } = await mountView(DiagnosticsView, client);
    const prewarm = wrapper.get('[data-testid="diag-prewarm"]').text();
    expect(prewarm).toContain("Model belleğe yüklendi");
    expect(prewarm).not.toContain("Bağlam hazırlandı");
    expect(prewarm).toContain("Bağlam baştan işlenecek");
  });

  it("measures only while open and visible", async () => {
    vi.useFakeTimers();
    const { wrapper, client, platform } = await mountView(DiagnosticsView);
    expect(client.diagnostics).toHaveBeenCalledTimes(1);
    expect(platform.processMetrics).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(5000);
    expect(client.diagnostics).toHaveBeenCalledTimes(2);
    Object.defineProperty(document, "visibilityState", { value: "hidden", configurable: true });
    await vi.advanceTimersByTimeAsync(20_000);
    expect(client.diagnostics).toHaveBeenCalledTimes(2);
    Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
    wrapper.unmount();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(client.diagnostics).toHaveBeenCalledTimes(2);
    expect(platform.processMetrics).toHaveBeenCalledTimes(2);
  });
});

describe("Settings", () => {
  beforeEach(() => setActivePinia(createPinia()));
  afterEach(() => {
    useConnectionStore().stop();
    document.documentElement.classList.remove("reduce-motion");
  });

  it("edits desktop preferences through the shell and applies reduce motion", async () => {
    const { wrapper, platform } = await mountView(SettingsView);
    const close = wrapper.get('[data-testid="pref-close-to-menu-bar"]');
    expect((close.element as HTMLInputElement).checked).toBe(true);
    await close.setValue(false);
    await flushPromises();
    expect(platform.setPreferences).toHaveBeenLastCalledWith({
      closeToMenuBar: false,
      startHidden: false,
      reduceMotion: "system",
    });
    await wrapper.get('[data-testid="pref-reduce-motion"]').setValue(true);
    await flushPromises();
    expect(document.documentElement.classList.contains("reduce-motion")).toBe(true);
    expect(wrapper.text()).toContain("bu sürümde LAZIS bildirim göndermez");
  });

  it("shows what is really in effect when saving fails", async () => {
    const { wrapper } = await mountView(SettingsView, fakeClient(), {
      setPreferences: vi.fn().mockRejectedValue({ code: "internal_error", message: "" }),
    });
    const start = wrapper.get('[data-testid="pref-start-hidden"]');
    await start.setValue(true);
    await flushPromises();
    expect((start.element as HTMLInputElement).checked).toBe(false);
    expect(wrapper.find('[role="alert"]').exists()).toBe(true);
  });

  it("explains privacy and FileVault without changing anything", async () => {
    const { wrapper, platform } = await mountView(SettingsView);
    const privacy = wrapper.get('[data-testid="settings-privacy"]').text();
    expect(privacy).toContain("Tamamen yerel");
    expect(privacy).toContain("SQLCipher");
    expect(privacy).toContain("FileVault");
    expect(wrapper.text()).toContain("Yanıt uzunluğu");
    expect(wrapper.text()).toContain("Soruya göre");
    expect(platform.setPreferences).not.toHaveBeenCalled();
  });
});

describe("Menu bar and navigation", () => {
  beforeEach(() => setActivePinia(createPinia()));
  afterEach(() => {
    useAssistantStore().stop();
    useConnectionStore().stop();
  });

  it("keeps the menu-bar status in sync with the assistant state", async () => {
    const { platform } = await mountView(App);
    expect(platform.setTrayStatus).toHaveBeenLastCalledWith("idle");
    const assistant = useAssistantStore();
    assistant.phase = "sending";
    assistant.turn = { clientId: "c", stage: "waiting", cache: null, contextTokens: null, trimmed: null };
    await flushPromises();
    expect(platform.setTrayStatus).toHaveBeenLastCalledWith("thinking");
    assistant.turn.stage = "generating";
    await flushPromises();
    expect(platform.setTrayStatus).toHaveBeenLastCalledWith("speaking");
    const calls = vi.mocked(platform.setTrayStatus).mock.calls.length;
    assistant.turn.cache = "warm"; // no state change → no extra IPC
    await flushPromises();
    expect(vi.mocked(platform.setTrayStatus).mock.calls.length).toBe(calls);
  });

  it("opens the view requested by the menu bar or --show", async () => {
    let navigate: (view: View) => void = () => undefined;
    const { wrapper } = await mountView(App, fakeClient(), {
      initialView: vi.fn().mockReturnValue("diagnostics"),
      onNavigate: vi.fn().mockImplementation((cb: (view: View) => void) => {
        navigate = cb;
        return Promise.resolve(() => undefined);
      }),
    });
    expect(wrapper.find('[data-testid="diagnostics-view"]').exists()).toBe(true);
    navigate("settings");
    await flushPromises();
    expect(wrapper.find('[data-testid="settings-view"]').exists()).toBe(true);
  });

  it("works in main.ts order: store started (not awaited) before the app mounts", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const platform = fakePlatform(connection(), { initialView: vi.fn().mockReturnValue("settings") });
    void useConnectionStore().start({ platform, clientFactory: () => fakeClient() });
    const wrapper = mount(App, { global: { plugins: [pinia, createAppI18n()] } });
    await flushPromises();
    expect(platform.onNavigate).toHaveBeenCalledTimes(1);
    expect(platform.getPreferences).toHaveBeenCalledTimes(1);
    expect(platform.setTrayStatus).toHaveBeenCalled();
    expect(wrapper.find('[data-testid="settings-view"]').exists()).toBe(true);
  });

  it("the state is described in text, not by colour alone", async () => {
    const { wrapper } = await mountView(App);
    expect(wrapper.get('[data-testid="presence"]').attributes("data-state")).toBe("idle");
    const label = wrapper.get('[data-testid="presence-text"]');
    expect(label.text()).toBe("Hazır");
    expect(label.attributes("aria-live")).toBe("polite");
  });
});
