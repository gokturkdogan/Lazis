import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import App from "@/App.vue";
import { createAppI18n } from "@/i18n";
import { useConnectionStore } from "@/stores/connection";
import { connection, fakeClient, fakePlatform } from "./fixtures";

async function mountWith(conn = connection()) {
  const pinia = createPinia();
  setActivePinia(pinia);
  const store = useConnectionStore();
  await store.start({ platform: fakePlatform(conn), clientFactory: () => fakeClient() });
  const wrapper = mount(App, { global: { plugins: [pinia, createAppI18n()] } });
  await wrapper.vm.$nextTick();
  return { wrapper, store };
}

describe("App", () => {
  beforeEach(() => setActivePinia(createPinia()));
  afterEach(() => useConnectionStore().stop());

  it("renders identity, connection state and verified encryption in Turkish", async () => {
    const { wrapper } = await mountWith();
    const text = wrapper.text();
    expect(text).toContain("LAZIS");
    expect(wrapper.get('[data-testid="status-pill"]').text()).toBe("Bağlı");
    expect(wrapper.get('[data-testid="card-database"]').text()).toContain("SQLCipher etkin");
    expect(wrapper.get('[data-testid="card-privacy"]').text()).toContain("Yalnızca çevrimdışı");
    expect(text).toContain("v0.1.0");
  });

  it("marks the conversation area as inactive and never shows fake responses", async () => {
    const { wrapper } = await mountWith();
    const placeholder = wrapper.get('[data-testid="conversation-placeholder"]');
    expect(placeholder.text()).toContain("Henüz etkin değil");
    expect(placeholder.text()).toContain("sahte yanıt gösterilmez");
    expect(placeholder.get("input").attributes("disabled")).toBeDefined();
  });

  it("shows a Turkish startup error with a retry action", async () => {
    const { wrapper } = await mountWith(
      connection({ phase: "failed", token: null, port: null, errorCode: "keychain_denied" }),
    );
    const error = wrapper.get('[data-testid="startup-error"]');
    expect(error.text()).toContain("Anahtar Zinciri erişimi reddedildi");
    expect(error.text()).toContain("Yeniden dene");
    expect(wrapper.get('[data-testid="status-pill"]').text()).toBe("Arka uç başlatılamadı");
  });

  it("shows the restore form when recovery is needed", async () => {
    const { wrapper } = await mountWith(connection({ phase: "needs_recovery", token: null, port: null }));
    expect(wrapper.find('[data-testid="restore-panel"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="conversation-placeholder"]').exists()).toBe(false);
  });

  it("asks to store the recovery code on first run", async () => {
    const { wrapper } = await mountWith(connection({ recoveryPending: true }));
    expect(wrapper.find('[data-testid="recovery-dialog"]').exists()).toBe(true);
  });

  it("switches to settings and diagnostics views", async () => {
    const { wrapper } = await mountWith();
    await wrapper.get('[data-testid="tab-settings"]').trigger("click");
    expect(wrapper.get('[data-testid="settings-view"]').text()).toContain("yalnızca görüntülenebilir");
    await wrapper.get('[data-testid="tab-diagnostics"]').trigger("click");
    expect(wrapper.get('[data-testid="diagnostics-view"]').text()).toContain("127.0.0.1:51234");
  });
});
