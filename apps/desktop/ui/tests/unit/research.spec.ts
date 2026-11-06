import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ApiClient, TurnSubmitRequest } from "@/api/client";
import ResearchPanel from "@/components/ResearchPanel.vue";
import { createAppI18n } from "@/i18n";
import { useAssistantStore } from "@/stores/assistant";
import { useConnectionStore } from "@/stores/connection";
import AssistantView from "@/views/AssistantView.vue";
import { assistantFixture, connection, fakeClient, fakePlatform, messageFixture } from "./fixtures";

const ON = { mode: "ask" as const, available: true, provider: "wikipedia" as const, max_query_chars: 200 };

async function mountWith(component: typeof AssistantView | typeof ResearchPanel, overrides: Partial<ApiClient> = {}) {
  const pinia = createPinia();
  setActivePinia(pinia);
  const client = fakeClient(overrides);
  await useConnectionStore().start({ platform: fakePlatform(connection()), clientFactory: () => client });
  const wrapper = mount(component, { global: { plugins: [pinia, createAppI18n()] } });
  await flushPromises();
  return { wrapper, client };
}

describe("Internet research (Phase 12)", () => {
  afterEach(() => {
    useAssistantStore().stop();
    useConnectionStore().stop();
  });

  it("offers no research button while research is off", async () => {
    const { wrapper } = await mountWith(AssistantView);
    expect(wrapper.find('[data-testid="research-button"]').exists()).toBe(false);
  });

  it("shows exactly what would be sent and sends only after approval", async () => {
    const bodies: TurnSubmitRequest[] = [];
    const { wrapper, client } = await mountWith(AssistantView, {
      researchSettings: vi.fn().mockResolvedValue(ON),
      researchPlan: vi.fn().mockResolvedValue({ query: "Ankara nüfusu", blocked: false, blocked_reason: null, people: ["Derya"], mode: "ask" }),
      assistantState: vi.fn().mockResolvedValue(assistantFixture({ timeline_messages: 0 })),
      submitTurn: vi.fn(async (body: TurnSubmitRequest, onEvent) => {
        bodies.push(body);
        onEvent({ type: "done", message: messageFixture(2, "assistant", "Tamam."), context: { estimated_tokens: 1, prompt_tokens: 1, strategy: "full" } });
      }),
    });
    await wrapper.get('[data-testid="composer"]').setValue("İnternette araştır: Ankara nüfusu");
    await wrapper.get('[data-testid="research-button"]').trigger("click");
    await flushPromises();
    expect(client.researchPlan).toHaveBeenCalledWith("İnternette araştır: Ankara nüfusu");
    expect(client.submitTurn).not.toHaveBeenCalled();
    expect((wrapper.get('[data-testid="research-query"]').element as HTMLInputElement).value).toBe("Ankara nüfusu");
    expect(wrapper.get('[data-testid="research-people"]').text()).toContain("Derya");
    expect(wrapper.get('[data-testid="research-not-general"]').text()).toContain("genel bir internet arama motoru değildir");
    await wrapper.get('[data-testid="research-query"]').setValue("Ankara il nüfusu");
    await wrapper.get('[data-testid="research-approve"]').trigger("click");
    await flushPromises();
    expect(bodies[0]?.research_query).toBe("Ankara il nüfusu");
    expect(bodies[0]?.content).toBe("İnternette araştır: Ankara nüfusu");
    expect(wrapper.find('[data-testid="research-prompt"]').exists()).toBe(false);
  });

  it("cannot send a blocked search, and cancelling sends nothing", async () => {
    const { wrapper, client } = await mountWith(AssistantView, {
      researchSettings: vi.fn().mockResolvedValue(ON),
      researchPlan: vi.fn().mockResolvedValue({ query: "şifrem Kedi-1234", blocked: true, blocked_reason: "restricted", people: [], mode: "ask" }),
    });
    await wrapper.get('[data-testid="composer"]').setValue("Araştır: şifrem Kedi-1234");
    await wrapper.get('[data-testid="research-button"]').trigger("click");
    await flushPromises();
    expect(wrapper.get('[data-testid="research-blocked"]').text()).toContain("gönderilemez");
    expect(wrapper.get('[data-testid="research-approve"]').attributes("disabled")).toBeDefined();
    await wrapper.get('[data-testid="research-cancel"]').trigger("click");
    await flushPromises();
    expect(client.submitTurn).not.toHaveBeenCalled();
    expect(wrapper.find('[data-testid="research-prompt"]').exists()).toBe(false);
  });

  it("Settings turns research on and says when the helper is not running", async () => {
    const { wrapper, client } = await mountWith(ResearchPanel, {
      researchSettings: vi.fn().mockResolvedValue({ ...ON, mode: "offline_only", available: false }),
    });
    expect((wrapper.get('[data-testid="research-mode"]').element as HTMLSelectElement).value).toBe("offline_only");
    expect(wrapper.find('[data-testid="research-unavailable"]').exists()).toBe(true);
    expect(wrapper.get('[data-testid="research-not-general"]').text()).toContain("Haberler, güncel olaylar");
    await wrapper.get('[data-testid="research-mode"]').setValue("ask");
    await flushPromises();
    expect(client.setResearchMode).toHaveBeenCalledWith("ask");
  });
});
