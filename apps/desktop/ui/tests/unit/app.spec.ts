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
  if (tab === "overview" && wrapper.find('[data-testid="menu-button"]').exists()) {
    await go(wrapper, "overview");
  }
  return { wrapper, store };
}

/** Navigation is a drawer since Phase 14.1: open it, then pick the section. */
async function go(wrapper: ReturnType<typeof mount>, view: string) {
  await wrapper.get('[data-testid="menu-button"]').trigger("click");
  await flushPromises();
  await wrapper.get(`[data-testid="tab-${view}"]`).trigger("click");
  await flushPromises();
}

describe("App", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    // The first-run questions are covered in onboarding.spec; here they are already done.
    localStorage.setItem("lazis.intake.v1", JSON.stringify({ status: "done", step: 4 }));
  });
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
    expect(wrapper.find('[data-testid="assistant-view"]').exists()).toBe(true);
    await wrapper.get('[data-testid="menu-button"]').trigger("click");
    expect(wrapper.get('[data-testid="tab-conversation"]').classes()).toContain("active");
    await wrapper.get('[data-testid="nav-close"]').trigger("click");
    const thread = wrapper.get('[data-testid="conversation-thread"]');
    // Phase 14 polish: the privacy note left the chat; it is in Ayarlar (asserted below)
    expect(thread.text()).not.toContain("şifreli veritabanında saklanır");
    expect(thread.get('[data-testid="empty-thread"]').text()).toContain("tek bir konuşma geçmişinde");
    expect(wrapper.find('[data-testid="new-conversation"]').exists()).toBe(false);
    expect(thread.findAll('[data-testid="message-assistant"]')).toHaveLength(0);
    expect(wrapper.find('[data-testid="filevault-warning"]').exists()).toBe(false);
  });

  it("keeps the FileVault state out of the chat but in Genel Bakış and Ayarlar (Phase 14.1)", async () => {
    const { wrapper } = await mountWith(connection({ fileVault: "off" }), "conversation");
    expect(wrapper.find('[data-testid="filevault-warning"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="conversation-thread"]').text()).not.toContain("FileVault");
    await go(wrapper, "overview");
    expect(wrapper.get('[data-testid="card-privacy"]').text()).toContain("Kapalı — Sistem Ayarları");
    await go(wrapper, "settings");
    expect(wrapper.get('[data-testid="settings-view"]').text()).toContain("FileVault");
    // and the privacy note that left the chat is here
    expect(wrapper.get('[data-testid="settings-privacy-note"]').text()).toContain("şifreli veritabanında saklanır");
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
    expect(wrapper.find('[data-testid="assistant-view"]').exists()).toBe(false);
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
    await go(wrapper, "settings");
    expect(wrapper.get('[data-testid="settings-view"]').text()).toContain("yalnızca görüntülenebilir");
    await go(wrapper, "diagnostics");
    expect(wrapper.get('[data-testid="diagnostics-view"]').text()).toContain("127.0.0.1:51234");
  });
});
