import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ApiClient } from "@/api/client";
import App from "@/App.vue";
import OnboardingModal from "@/components/OnboardingModal.vue";
import { READY_HOLD_MS } from "@/composables/startup";
import { createAppI18n } from "@/i18n";
import { useConnectionStore } from "@/stores/connection";
import { useOnboardingStore } from "@/stores/onboarding";
import { connection, fakeClient, fakePlatform } from "./fixtures";

const KEY = "lazis.intake.v1";
const saved = { created: 1, updated: 0, superseded: 0, refused: 0, review: 0 };

async function mountModal(client: ApiClient = fakeClient({ addMemory: vi.fn().mockResolvedValue(saved) })) {
  const pinia = createPinia();
  setActivePinia(pinia);
  await useConnectionStore().start({ platform: fakePlatform(connection()), clientFactory: () => client });
  const wrapper = mount(OnboardingModal, { attachTo: document.body, global: { plugins: [pinia, createAppI18n()] } });
  await flushPromises();
  return { wrapper, client, onboarding: useOnboardingStore() };
}

const stored = () => JSON.parse(localStorage.getItem(KEY) ?? "null");

describe("First setup modal (Phase 14.1)", () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
  });
  afterEach(() => {
    useConnectionStore().stop();
    document.body.innerHTML = "";
  });

  it("opens by itself on first run as an accessible dialog with progress", async () => {
    const { wrapper } = await mountModal();
    const dialog = wrapper.get('[role="dialog"]');
    expect(dialog.attributes("aria-modal")).toBe("true");
    expect(dialog.attributes("aria-labelledby")).toBe("onboarding-title");
    expect(wrapper.get("#onboarding-title").text()).toBe("İlk kurulum");
    expect(wrapper.findAll(".progress li")).toHaveLength(4);
    expect(wrapper.findAll(".progress li.current")).toHaveLength(1);
    expect(document.activeElement).toBe(wrapper.get('[data-testid="intake-name"]').element);
  });

  it("does not open when finished or told never to show", async () => {
    localStorage.setItem(KEY, JSON.stringify({ status: "done", step: 2 }));
    const { wrapper } = await mountModal();
    expect(wrapper.find('[data-testid="onboarding"]').exists()).toBe(false);
  });

  it("saves the name only on the explicit button, then moves on", async () => {
    const { wrapper, client, onboarding } = await mountModal();
    await wrapper.get('[data-testid="intake-name"]').setValue("Göktürk");
    expect(client.addMemory).not.toHaveBeenCalled();
    await wrapper.get(".choices .btn-primary").trigger("click");
    await flushPromises();
    expect(client.addMemory).toHaveBeenCalledWith({ predicate: "preferred_name", value: "Göktürk", statement: "" });
    expect(onboarding.step).toBe(1);
    expect(stored()).toEqual({ status: "open", step: 1 });
  });

  it("does not move on when memory refused the answer", async () => {
    const client = fakeClient({ addMemory: vi.fn().mockResolvedValue({ ...saved, created: 0, refused: 1 }) });
    const { wrapper, onboarding } = await mountModal(client);
    await wrapper.get('[data-testid="intake-name"]').setValue("x");
    await wrapper.get(".choices .btn-primary").trigger("click");
    await flushPromises();
    expect(onboarding.step).toBe(0);
    expect(wrapper.find('[role="alert"]').exists()).toBe(true);
  });

  it("skips steps without saving anything and finishes", async () => {
    const { wrapper, client, onboarding } = await mountModal();
    for (let i = 0; i < 4; i++) {
      await wrapper.get('[data-testid="intake-skip"]').trigger("click");
      await flushPromises();
    }
    expect(client.addMemory).not.toHaveBeenCalled();
    expect(client.setStyle).not.toHaveBeenCalled();
    await wrapper.get('[data-testid="intake-finish"]').trigger("click");
    await flushPromises();
    expect(onboarding.status).toBe("done");
    expect(wrapper.find('[data-testid="onboarding"]').exists()).toBe(false);
  });

  it("sets the address style with a choice button", async () => {
    localStorage.setItem(KEY, JSON.stringify({ status: "open", step: 1 }));
    const { wrapper, client } = await mountModal();
    await wrapper.findAll(".choices .btn")[1]!.trigger("click");
    await flushPromises();
    expect(client.setStyle).toHaveBeenCalledWith("address", "sen");
  });

  it("'Sonra devam et' closes it for this run and keeps the step for next time", async () => {
    localStorage.setItem(KEY, JSON.stringify({ status: "open", step: 2 }));
    const { wrapper } = await mountModal();
    await wrapper.get('[data-testid="intake-pause"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-testid="onboarding"]').exists()).toBe(false);
    expect(stored()).toEqual({ status: "paused", step: 2 });

    // Same run (session flag set): stays closed.
    const again = await mountModal();
    expect(again.wrapper.find('[data-testid="onboarding"]').exists()).toBe(false);
    // Next launch: back at the same step.
    sessionStorage.clear();
    const next = await mountModal();
    expect(next.wrapper.find('[data-testid="onboarding"]').exists()).toBe(true);
    expect(next.onboarding.step).toBe(2);
  });

  it("Escape and the close icon mean 'later', not 'never'", async () => {
    const { wrapper, onboarding } = await mountModal();
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    await flushPromises();
    expect(onboarding.status).toBe("paused");
    expect(wrapper.find('[data-testid="onboarding"]').exists()).toBe(false);
  });

  it("'Bir daha gösterme' closes it for good", async () => {
    const { wrapper } = await mountModal();
    await wrapper.get('[data-testid="intake-never"]').trigger("click");
    await flushPromises();
    expect(stored()).toEqual({ status: "done", step: 0 });
    sessionStorage.clear();
    const next = await mountModal();
    expect(next.wrapper.find('[data-testid="onboarding"]').exists()).toBe(false);
  });

  it("can be opened again from Ayarlar, and the chat holds no setup cards", async () => {
    localStorage.setItem(KEY, JSON.stringify({ status: "done", step: 4 }));
    const pinia = createPinia();
    setActivePinia(pinia);
    await useConnectionStore().start({ platform: fakePlatform(connection()), clientFactory: () => fakeClient() });
    const wrapper = mount(App, { attachTo: document.body, global: { plugins: [pinia, createAppI18n()] } });
    await flushPromises();
    expect(wrapper.find('[data-testid="onboarding"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="intake"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="assistant-view"]').text()).not.toContain("hitap");

    await wrapper.get('[data-testid="menu-button"]').trigger("click");
    await wrapper.get('[data-testid="tab-settings"]').trigger("click");
    await flushPromises();
    await wrapper.get('[data-testid="open-onboarding"]').trigger("click");
    await flushPromises();
    // the setup window waits for the start screen's short "LAZIS hazır." to finish
    await new Promise((r) => setTimeout(r, READY_HOLD_MS + 50));
    await flushPromises();
    expect(wrapper.find('[data-testid="onboarding"]').exists()).toBe(true);
    expect(useOnboardingStore().step).toBe(0);
    expect(wrapper.find('[data-testid="assistant-view"]').exists()).toBe(true);
    wrapper.unmount();
  });
});
