import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import App from "@/App.vue";
import { createAppI18n } from "@/i18n";
import { NAV_ITEMS } from "@/navigation";
import { useConnectionStore } from "@/stores/connection";
import { connection, fakeClient, fakePlatform } from "./fixtures";

async function mountApp() {
  const pinia = createPinia();
  setActivePinia(pinia);
  await useConnectionStore().start({ platform: fakePlatform(connection()), clientFactory: () => fakeClient() });
  const wrapper = mount(App, { attachTo: document.body, global: { plugins: [pinia, createAppI18n()] } });
  await flushPromises();
  return wrapper;
}

describe("Navigation drawer (Phase 14.1)", () => {
  beforeEach(() => localStorage.setItem("lazis.intake.v1", JSON.stringify({ status: "done", step: 4 })));
  afterEach(() => {
    useConnectionStore().stop();
    document.body.innerHTML = "";
  });

  it("replaces the top tabs: a menu button, and no drawer rendered while closed", async () => {
    const wrapper = await mountApp();
    const button = wrapper.get('[data-testid="menu-button"]');
    expect(button.attributes("aria-expanded")).toBe("false");
    expect(button.attributes("aria-controls")).toBe("nav-panel");
    expect(button.attributes("aria-label")).toBe("Menüyü aç");
    expect(wrapper.find('[data-testid="nav-drawer"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="tab-overview"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("opens with every section, an icon each, and the current one marked and focused", async () => {
    const wrapper = await mountApp();
    await wrapper.get('[data-testid="menu-button"]').trigger("click");
    await flushPromises();
    expect(wrapper.get('[data-testid="menu-button"]').attributes("aria-expanded")).toBe("true");
    const nav = wrapper.get("#nav-panel");
    expect(nav.attributes("role")).toBe("dialog");
    expect(nav.attributes("aria-modal")).toBe("true");
    for (const item of NAV_ITEMS) {
      const el = wrapper.get(`[data-testid="tab-${item.view}"]`);
      expect(el.find("svg").exists()).toBe(true);
    }
    const current = wrapper.get('[data-testid="tab-conversation"]');
    expect(current.classes()).toContain("active");
    expect(current.attributes("aria-current")).toBe("page");
    expect(document.activeElement).toBe(current.element);
    wrapper.unmount();
  });

  it("goes to a section and closes", async () => {
    const wrapper = await mountApp();
    await wrapper.get('[data-testid="menu-button"]').trigger("click");
    await wrapper.get('[data-testid="tab-memory"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-testid="nav-drawer"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="page-head"]').text()).toContain("Hafıza");
    // Hidden screens are not rendered.
    expect(wrapper.find('[data-testid="assistant-view"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("closes on Escape, on the scrim and on the close button, and gives focus back", async () => {
    const wrapper = await mountApp();
    const button = wrapper.get('[data-testid="menu-button"]');
    for (const close of [
      () => document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })),
      () => wrapper.get('[data-testid="nav-scrim"]').trigger("click"),
      () => wrapper.get('[data-testid="nav-close"]').trigger("click"),
    ]) {
      (button.element as HTMLElement).focus();
      await button.trigger("click");
      await flushPromises();
      expect(wrapper.find('[data-testid="nav-drawer"]').exists()).toBe(true);
      await close();
      await flushPromises();
      expect(wrapper.find('[data-testid="nav-drawer"]').exists()).toBe(false);
      expect(document.activeElement).toBe(button.element);
    }
    wrapper.unmount();
  });

  it("uses one SVG icon set and no emoji in the frame", async () => {
    const wrapper = await mountApp();
    await wrapper.get('[data-testid="menu-button"]').trigger("click");
    await flushPromises();
    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/\p{Extended_Pictographic}/u);
    for (const svg of document.querySelectorAll("svg.icon")) {
      expect(svg.getAttribute("viewBox")).toBe("0 0 24 24");
    }
    wrapper.unmount();
  });
});
