import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import App from "@/App.vue";
import { createAppI18n } from "@/i18n";
import { useConnectionStore } from "@/stores/connection";
import { connection, fakeClient, fakePlatform } from "./fixtures";

async function mountWith(conn = connection(), tab: "conversation" | "overview" = "overview") {
  const pinia = createPinia();
  setActivePinia(pinia);
  const store = useConnectionStore();
  await store.start({ platform: fakePlatform(conn), clientFactory: () => fakeClient() });
  const wrapper = mount(App, { global: { plugins: [pinia, createAppI18n()] } });
  await flushPromises();
  if (tab === "overview" && wrapper.find('[data-testid="tab-overview"]').exists()) {
    await wrapper.get('[data-testid="tab-overview"]').trigger("click");
    await flushPromises();
  }
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

  it("opens on the conversation view and never invents a response", async () => {
    const { wrapper } = await mountWith(connection(), "conversation");
    expect(wrapper.get('[data-testid="tab-conversation"]').classes()).toContain("active");
    const thread = wrapper.get('[data-testid="conversation-thread"]');
    expect(thread.text()).toContain("şifreli veritabanında saklanır");
    expect(thread.get('[data-testid="empty-thread"]').text()).toContain("İlk mesajınızla birlikte kaydedilir");
    expect(thread.findAll('[data-testid="message-assistant"]')).toHaveLength(0);
    expect(wrapper.find('[data-testid="filevault-warning"]').exists()).toBe(false);
  });

  it("warns in the conversation view when FileVault is off", async () => {
    const { wrapper } = await mountWith(connection({ fileVault: "off" }), "conversation");
    expect(wrapper.get('[data-testid="filevault-warning"]').text()).toContain("FileVault kapalı");
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
    expect(wrapper.find('[data-testid="conversation-view"]').exists()).toBe(false);
  });

  it("asks to store the recovery code on first run", async () => {
    const { wrapper } = await mountWith(connection({ recoveryPending: true }));
    expect(wrapper.find('[data-testid="recovery-dialog"]').exists()).toBe(true);
  });

  it("shows the OS network sandbox and FileVault state in the privacy card", async () => {
    const { wrapper } = await mountWith();
    const privacy = wrapper.get('[data-testid="card-privacy"]').text();
    expect(privacy).toContain("İşletim sistemi ağ kısıtı");
    expect(privacy).toContain("Etkin");
    expect(privacy).toContain("FileVault disk şifreleme");
    expect(privacy).toContain("Açık");

    const off = await mountWith(connection({ fileVault: "off" }));
    expect(off.wrapper.get('[data-testid="card-privacy"]').text()).toContain(
      "Kapalı — Sistem Ayarları",
    );
  });

  it("reveals the recovery code only on request and keeps it out of the store", async () => {
    const { wrapper, store } = await mountWith(connection({ recoveryPending: true }));
    const dialog = () => wrapper.get('[data-testid="recovery-dialog"]');
    expect(dialog().find('[data-testid="recovery-code"]').exists()).toBe(false);

    await dialog().get("button.btn:not(.btn-primary)").trigger("click");
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(dialog().get('[data-testid="recovery-code"]').text()).toBe("LZR1-TEST0-CODE0");
    expect(dialog().get('[data-testid="recovery-clipboard"]').text()).toContain("Evrensel Pano");
    expect(JSON.stringify(store.$state)).not.toContain("LZR1-TEST0-CODE0");

    await dialog().get('input[type="checkbox"]').setValue(true);
    await dialog().get("button.btn-primary").trigger("click");
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(wrapper.find('[data-testid="recovery-dialog"]').exists()).toBe(false);
    expect(wrapper.text()).not.toContain("LZR1-TEST0-CODE0");
    expect(JSON.stringify(store.$state)).not.toContain("LZR1-TEST0-CODE0");
  });

  it("switches to settings and diagnostics views", async () => {
    const { wrapper } = await mountWith();
    await wrapper.get('[data-testid="tab-settings"]').trigger("click");
    expect(wrapper.get('[data-testid="settings-view"]').text()).toContain("yalnızca görüntülenebilir");
    await wrapper.get('[data-testid="tab-diagnostics"]').trigger("click");
    expect(wrapper.get('[data-testid="diagnostics-view"]').text()).toContain("127.0.0.1:51234");
  });
});
