import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h, ref } from "vue";
import App from "@/App.vue";
import ModelPanel from "@/components/ModelPanel.vue";
import StartupLoader from "@/components/StartupLoader.vue";
import { READY_HOLD_MS, useStartup } from "@/composables/startup";
import { createAppI18n } from "@/i18n";
import { useAssistantStore } from "@/stores/assistant";
import { useConnectionStore } from "@/stores/connection";
import AssistantView from "@/views/AssistantView.vue";
import { connection, fakeClient, fakePlatform, llmStatusFixture, MODEL, modelFixture } from "./fixtures";

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

describe("Start screen steps (Phase 14 polish)", () => {
  beforeEach(() => setActivePinia(createPinia()));

  function harness(wait = true) {
    let api!: ReturnType<typeof useStartup>;
    const Comp = defineComponent(() => {
      api = useStartup(ref(wait));
      return () => h("i");
    });
    mount(Comp, { global: { plugins: [createAppI18n()] } });
    return () => api;
  }

  it("follows the real stages, one by one, and never moves on by itself", async () => {
    const api = harness();
    const conn = useConnectionStore();
    const chat = useAssistantStore();
    expect(api().step.value).toBe("waking");
    conn.$patch({ phase: "starting" });
    expect(api().step.value).toBe("systems");
    await wait(READY_HOLD_MS * 2); // time alone changes nothing
    expect(api().step.value).toBe("systems");
    conn.$patch({ verifying: true });
    expect(api().step.value).toBe("memory");
    conn.$patch({ verifying: false, phase: "connected" });
    expect(api().step.value).toBe("preparing");
    chat.$patch({ ready: true });
    await flushPromises();
    expect(api().step.value).toBe("ready"); // a short confirmation…
    await wait(READY_HOLD_MS + 30);
    expect(api().step.value).toBeNull(); // …then it steps aside
    expect(api().visible.value).toBe(false);
  });

  it("does not wait for the conversation when another screen is open", () => {
    const api = harness(false);
    useConnectionStore().$patch({ phase: "connected" });
    expect(api().step.value).toBeNull();
  });

  it("shows a failure as it is, and can step aside for the details", () => {
    const api = harness();
    useConnectionStore().$patch({ phase: "backend_failed", errorCode: "backend_start_failed" });
    expect(api().step.value).toBe("failed");
    expect(api().visible.value).toBe(true);
    api().dismiss();
    expect(api().visible.value).toBe(false);
  });

  it("leaves recovery to its own screen", () => {
    const api = harness();
    useConnectionStore().$patch({ phase: "needs_recovery" });
    expect(api().step.value).toBeNull();
  });
});

describe("Start screen (Phase 14 polish)", () => {
  beforeEach(() => setActivePinia(createPinia()));

  it("shows the logo, a neural mark and the step's line with a plain explanation", () => {
    const wrapper = mount(StartupLoader, { props: { step: "memory" }, global: { plugins: [createAppI18n()] } });
    expect(wrapper.get('[data-testid="starting-logo"]').attributes("alt")).toBe("LAZIS");
    expect(wrapper.find('[data-testid="neural-spinner"]').exists()).toBe(true);
    expect(wrapper.get('[data-testid="startup-message"]').text()).toBe("Hafıza bağlantısı kuruluyor…");
    expect(wrapper.get('[data-testid="startup-plain"]').text()).toContain("Şifreli veritabanı");
    expect(wrapper.findAll(".steps li.done")).toHaveLength(2);
    expect(wrapper.text()).not.toMatch(/bilinç|bilinçli/i);
  });

  it("says ready without a spinner", () => {
    const wrapper = mount(StartupLoader, { props: { step: "ready" }, global: { plugins: [createAppI18n()] } });
    expect(wrapper.get('[data-testid="startup-message"]').text()).toBe("LAZIS hazır.");
    expect(wrapper.find('[data-testid="neural-spinner"]').exists()).toBe(false);
  });

  it("on failure shows the real error, a retry, and the way to Tanılama", async () => {
    useConnectionStore().$patch({ phase: "backend_failed", errorCode: "keychain_denied" });
    const wrapper = mount(StartupLoader, { props: { step: "failed" }, global: { plugins: [createAppI18n()] } });
    expect(wrapper.get('[data-testid="startup-error"]').text()).toContain("Anahtar Zinciri erişimi reddedildi");
    expect(wrapper.get('[data-testid="startup-error"]').text()).toContain("Yeniden dene");
    await wrapper.get('[data-testid="startup-diagnostics"]').trigger("click");
    expect(wrapper.emitted("diagnostics")).toHaveLength(1);
  });

  it("covers the app while starting and fades away once LAZIS is ready", async () => {
    localStorage.setItem("lazis.intake.v1", JSON.stringify({ status: "done", step: 4 }));
    const pinia = createPinia();
    setActivePinia(pinia);
    await useConnectionStore().start({ platform: fakePlatform(connection()), clientFactory: () => fakeClient() });
    const app = mount(App, { global: { plugins: [pinia, createAppI18n()] } });
    await flushPromises();
    expect(app.get('[data-testid="startup-loader"]').attributes("data-step")).toBe("ready");
    await wait(READY_HOLD_MS + 30);
    await flushPromises();
    expect(app.find('[data-testid="startup-loader"]').exists()).toBe(false);
    app.unmount();
    useConnectionStore().stop();
  });
});

describe("Minimal chat (Phase 14 polish)", () => {
  afterEach(() => {
    useAssistantStore().stop();
    useConnectionStore().stop();
  });

  async function mountChat(client = fakeClient()) {
    const pinia = createPinia();
    setActivePinia(pinia);
    localStorage.setItem("lazis.chat.open", "1");
    await useConnectionStore().start({ platform: fakePlatform(connection()), clientFactory: () => client });
    const wrapper = mount(AssistantView, { attachTo: document.body, global: { plugins: [createAppI18n()] } });
    await flushPromises();
    return { wrapper, client, store: useAssistantStore() };
  }

  it("keeps only the essentials: messages, a short field, paperclip and an icon send", async () => {
    const { wrapper } = await mountChat();
    const thread = wrapper.get('[data-testid="conversation-thread"]');
    const field = thread.get('[data-testid="composer"]');
    expect(field.attributes("placeholder")).toBe("LAZIS'e yaz…");
    expect(field.attributes("rows")).toBe("3");
    const send = thread.get('[data-testid="send"]');
    expect(send.text()).toBe("");
    expect(send.attributes("aria-label")).toBe("Gönder (⌘↵)");
    expect(thread.find('[data-testid="document-attach"]').exists()).toBe(true);
    for (const gone of ["model-select", "loaded-model", "thread-title"]) {
      expect(thread.find(`[data-testid="${gone}"]`).exists()).toBe(false);
    }
    expect(thread.text()).not.toMatch(/Bellekte|şifreli veritabanında|İlk token|qwen3\.5/);
    wrapper.unmount();
  });

  it("keeps the keys: Enter writes a new line, ⌘↵ sends", async () => {
    const { wrapper, client } = await mountChat();
    const field = wrapper.get('[data-testid="composer"]');
    await field.setValue("Merhaba");
    await field.trigger("keydown", { key: "Enter" });
    await field.trigger("keydown", { key: "Enter", shiftKey: true });
    await flushPromises();
    expect(client.submitTurn).not.toHaveBeenCalled();
    await field.trigger("keydown", { key: "Enter", metaKey: true });
    await flushPromises();
    expect(client.submitTurn).toHaveBeenCalled();
    wrapper.unmount();
  });

  it("shows the real model warm-up as a small neural mark, only while it runs", async () => {
    const { wrapper, store } = await mountChat();
    expect(wrapper.find('[data-testid="background-status"]').exists()).toBe(false);
    store.$patch({ background: { kind: "prewarm", conversation_id: store.session?.id ?? null } as never });
    await flushPromises();
    const status = wrapper.get('[data-testid="background-status"]');
    expect(status.text()).toContain("Sinir ağları hazırlanıyor");
    expect(status.find('[data-testid="neural-spinner"]').exists()).toBe(true);
    wrapper.unmount();
  });
});

describe("Ayarlar → Yapay Zekâ Modeli (Phase 14 polish)", () => {
  const other = { ...modelFixture, name: "gemma4:12b-it-qat", parameter_size: "12B", quantization: "Q4_0", size_bytes: 8 * 1024 ** 3 };

  async function mountPanel(overrides = {}) {
    const pinia = createPinia();
    setActivePinia(pinia);
    const client = fakeClient({
      models: vi.fn().mockResolvedValue({ models: [modelFixture, other] }),
      llmStatus: vi.fn().mockResolvedValue({
        ...llmStatusFixture,
        primary_model: MODEL,
        loaded: [{ name: MODEL, size_bytes: 7.2 * 1024 ** 3, vram_bytes: 0, expires_at: "2026-11-07T12:00:00Z" }],
      }),
      ...overrides,
    });
    await useConnectionStore().start({ platform: fakePlatform(connection()), clientFactory: () => client });
    await useAssistantStore().refreshRuntime();
    const wrapper = mount(ModelPanel, { global: { plugins: [createAppI18n()] } });
    await flushPromises();
    return { wrapper, client, store: useAssistantStore() };
  }
  afterEach(() => useConnectionStore().stop());

  it("lists the local models, marks the active one, and shows size and memory as secondary text", async () => {
    const { wrapper } = await mountPanel();
    expect(wrapper.get("h3").text()).toBe("Yapay Zekâ Modeli");
    const active = wrapper.get(`[data-testid="ai-model-${MODEL}"]`);
    expect(active.classes()).toContain("active");
    expect(active.get('[data-testid="ai-active"]').text()).toBe("Etkin");
    expect(active.text()).toContain("Bellekte · ");
    expect(active.text()).toContain("Varsayılan");
    expect(wrapper.get(`[data-testid="ai-model-${other.name}"]`).text()).toContain("12B · Q4_0");
    expect(wrapper.text()).toContain("LAZIS model indirmez");
  });

  it("switches only on an explicit choice, the same way the old chooser did", async () => {
    const { wrapper, client, store } = await mountPanel();
    (client.prepare as ReturnType<typeof vi.fn>).mockClear();
    await wrapper.get(`[data-testid="ai-use-${other.name}"]`).trigger("click");
    await flushPromises();
    expect(store.selectedModel).toBe(other.name);
    expect(client.prepare).toHaveBeenCalledWith(other.name);
    expect(wrapper.get('[data-testid="ai-changed"]').text()).toContain(other.name);
    expect(wrapper.get(`[data-testid="ai-model-${other.name}"]`).classes()).toContain("active");
  });

  it("cannot switch while a reply is running", async () => {
    const { wrapper, store } = await mountPanel();
    store.$patch({ phase: "streaming" as never });
    await flushPromises();
    expect(wrapper.get(`[data-testid="ai-use-${other.name}"]`).attributes("disabled")).toBeDefined();
  });

  it("explains when the local runtime is down or no model is installed", async () => {
    const down = await mountPanel({
      llmStatus: vi.fn().mockResolvedValue({ ...llmStatusFixture, runtime: { ...llmStatusFixture.runtime, available: false } }),
    });
    expect(down.wrapper.find('[data-testid="ai-runtime-down"]').exists()).toBe(true);
    useConnectionStore().stop();
    const none = await mountPanel({ models: vi.fn().mockResolvedValue({ models: [] }) });
    expect(none.wrapper.find('[data-testid="ai-no-models"]').exists()).toBe(true);
  });
});
