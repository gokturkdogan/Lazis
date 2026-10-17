import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, type ApiClient, type TurnEvent, type TurnSubmitRequest } from "@/api/client";
import { createAppI18n } from "@/i18n";
import { useAssistantStore } from "@/stores/assistant";
import { useConnectionStore } from "@/stores/connection";
import AssistantView from "@/views/AssistantView.vue";
import {
  assistantFixture,
  connection,
  conversationFixture,
  fakeClient,
  fakePlatform,
  llmStatusFixture,
  messageFixture,
  MODEL,
} from "./fixtures";

type TurnImpl = (body: TurnSubmitRequest, onEvent: (e: TurnEvent) => void, signal?: AbortSignal) => Promise<void>;

const SESSION = conversationFixture();
const OLD_SESSION = "01M558Q8A5R4V2Y7K0J3H6N9TC";

async function mountView(overrides: Partial<ApiClient> = {}, conn = connection()) {
  const pinia = createPinia();
  setActivePinia(pinia);
  const client = fakeClient(overrides);
  await useConnectionStore().start({ platform: fakePlatform(conn), clientFactory: () => client });
  const wrapper = mount(AssistantView, { global: { plugins: [pinia, createAppI18n()] } });
  await flushPromises();
  return { wrapper, client, store: useAssistantStore() };
}

function startEvent(seq = 3, created = false): TurnEvent {
  return {
    type: "start",
    conversation: SESSION,
    created,
    user_message: messageFixture(seq, "user", "Yarın ne yapalım?"),
    assistant_message: messageFixture(seq + 1, "assistant", "", { status: "streaming", metrics: null }),
  };
}

async function send(wrapper: ReturnType<typeof mount>, text: string) {
  await wrapper.get('[data-testid="composer"]').setValue(text);
  await wrapper.get("form").trigger("submit");
}

const history = {
  messages: [messageFixture(1, "user", "Merhaba"), messageFixture(2, "assistant", "Merhaba efendim.")],
  has_more: false,
};

describe("The one assistant", () => {
  beforeEach(() => setActivePinia(createPinia()));
  afterEach(() => {
    useAssistantStore().stop();
    useConnectionStore().stop();
    vi.useRealTimers();
  });

  it("opens straight into the assistant with the latest history and no conversation controls", async () => {
    const { wrapper, client } = await mountView({
      assistantState: vi.fn().mockResolvedValue(assistantFixture({ timeline_messages: 2 })),
      timeline: vi.fn().mockResolvedValue(history),
    });
    expect(client.timeline).toHaveBeenCalledWith(null, 50);
    expect(wrapper.get('[data-testid="thread-title"]').text()).toBe("LAZIS");
    expect(wrapper.findAll('[data-testid="message-assistant"]')[0]?.text()).toContain("Merhaba efendim.");
    for (const control of ["new-conversation", "conversation-item", "rename-conversation", "delete-conversation", "conversation-sidebar"]) {
      expect(wrapper.find(`[data-testid="${control}"]`).exists()).toBe(false);
    }
    expect(client.prepare).toHaveBeenCalledWith(MODEL); // warms the active session only
    expect(client.prepare).toHaveBeenCalledTimes(1);
  });

  it("sends without choosing anything and continues the same timeline", async () => {
    const turn: TurnImpl = async (body, onEvent) => {
      expect(Object.keys(body).sort()).toEqual(["client_id", "content", "model"]);
      onEvent(startEvent(3));
      onEvent({ type: "delta", text: "Bir plan " });
      onEvent({ type: "delta", text: "yapalım." });
      onEvent({
        type: "done",
        message: messageFixture(4, "assistant", "Bir plan yapalım."),
        context: { estimated_tokens: 700, prompt_tokens: 690, strategy: "full" },
      });
    };
    const { wrapper } = await mountView({
      timeline: vi.fn().mockResolvedValue(history),
      assistantState: vi.fn().mockResolvedValue(assistantFixture({ timeline_messages: 2 })),
      submitTurn: vi.fn(turn),
    });
    await send(wrapper, "Yarın ne yapalım?");
    await flushPromises();
    const seqs = wrapper.findAll("article").map((a) => Number(a.attributes("data-timeline")));
    expect(seqs).toEqual([1, 2, 3, 4]);
    expect(wrapper.findAll('[data-testid="message-assistant"]').at(-1)?.text()).toContain("Bir plan yapalım.");
    expect((wrapper.get('[data-testid="composer"]').element as HTMLTextAreaElement).value).toBe("");
  });

  it("works for a first-ever user (no session yet)", async () => {
    const turn: TurnImpl = async (_b, onEvent) => {
      onEvent(startEvent(1, true));
      onEvent({ type: "done", message: messageFixture(2, "assistant", "Merhaba!"), context: { estimated_tokens: 1, prompt_tokens: 1, strategy: "full" } });
    };
    const assistantState = vi
      .fn()
      .mockResolvedValueOnce(assistantFixture({ session: null, context: null, active_from_timeline_seq: null }))
      .mockResolvedValue(assistantFixture({ timeline_messages: 2, active_from_timeline_seq: 1 }));
    const { wrapper, store } = await mountView({ submitTurn: vi.fn(turn), assistantState });
    expect(wrapper.get('[data-testid="empty-thread"]').text()).toContain("tek bir konuşma geçmişinde");
    await send(wrapper, "Merhaba");
    await flushPromises();
    expect(store.session?.id).toBe(SESSION.id);
    expect(store.activeFrom).toBe(1);
    expect(wrapper.find('[data-testid="context-boundary"]').exists()).toBe(false);
  });

  it("marks where the model's current context starts (older sessions are not remembered)", async () => {
    const { wrapper } = await mountView({
      assistantState: vi.fn().mockResolvedValue(assistantFixture({ timeline_messages: 4, active_from_timeline_seq: 3 })),
      timeline: vi.fn().mockResolvedValue({
        messages: [
          messageFixture(1, "user", "Eski konu", { conversation_id: OLD_SESSION }),
          messageFixture(2, "assistant", "Eski yanıt", { conversation_id: OLD_SESSION }),
          messageFixture(3, "user", "Yeni konu"),
          messageFixture(4, "assistant", "Yeni yanıt"),
        ],
        has_more: false,
      }),
    });
    const items = wrapper.get('[data-testid="messages"]').element.children;
    const texts = Array.from(items).map((el) => el.textContent ?? "");
    const boundary = texts.findIndex((x) => x.includes("güncel bağlamında değil"));
    expect(boundary).toBeGreaterThan(0);
    expect(texts.slice(0, boundary).join(" ")).toContain("Eski yanıt");
    expect(texts.slice(boundary).join(" ")).toContain("Yeni konu");
  });

  it("pages older history without duplicates or gaps", async () => {
    const timeline = vi
      .fn()
      .mockResolvedValueOnce({ messages: [messageFixture(51, "user", "yeni"), messageFixture(52, "assistant", "yanıt")], has_more: true })
      .mockResolvedValueOnce({ messages: [messageFixture(50, "assistant", "eski"), messageFixture(51, "user", "yeni")], has_more: false });
    const { wrapper, client } = await mountView({ timeline, assistantState: vi.fn().mockResolvedValue(assistantFixture({ active_from_timeline_seq: 1 })) });
    await wrapper.get('[data-testid="load-older"]').trigger("click");
    await flushPromises();
    expect(client.timeline).toHaveBeenLastCalledWith(51, 50);
    const seqs = wrapper.findAll("article").map((a) => Number(a.attributes("data-timeline")));
    expect(seqs).toEqual([50, 51, 52]);
    expect(wrapper.find('[data-testid="load-older"]').exists()).toBe(false);
  });

  it("shows real backend stages, stops, and keeps the partial reply", async () => {
    let release: (() => void) | null = null;
    const turn: TurnImpl = async (_body, onEvent) => {
      onEvent(startEvent());
      onEvent({ type: "status", stage: "loading_model", model: MODEL });
      await new Promise<void>((r) => (release = r));
      onEvent({ type: "status", stage: "processing_context", context_tokens: 8200, cache: "cold" });
      await new Promise<void>((r) => (release = r));
      onEvent({ type: "delta", text: "Kısmi" });
      await new Promise<void>((r) => (release = r));
      onEvent({ type: "cancelled", message: messageFixture(4, "assistant", "Kısmi", { status: "cancelled" }) });
    };
    const cancelTurn = vi.fn().mockResolvedValue(true);
    const { wrapper } = await mountView({ submitTurn: vi.fn(turn), cancelTurn });
    await send(wrapper, "Yarın ne yapalım?");
    await flushPromises();
    expect(wrapper.get('[data-testid="turn-status"]').text()).toContain("Model hazırlanıyor");
    (release as unknown as () => void)();
    await flushPromises();
    expect(wrapper.get('[data-testid="turn-status"]').text()).toContain("yaklaşık 8200 token");
    (release as unknown as () => void)();
    await flushPromises();
    expect(wrapper.get('[data-testid="turn-status"]').text()).toContain("Yanıt oluşturuluyor");
    await wrapper.get('[data-testid="stop"]').trigger("click");
    await flushPromises();
    expect(cancelTurn).toHaveBeenCalledTimes(1);
    (release as unknown as () => void)();
    await flushPromises();
    const reply = wrapper.findAll('[data-testid="message-assistant"]').at(-1);
    expect(reply?.attributes("data-status")).toBe("cancelled");
    expect(reply?.text()).toContain("Kısmi");
    expect(reply?.text()).toContain("Yanıt durduruldu");
    expect(wrapper.find('[data-testid="send"]').exists()).toBe(true);
  });

  it("keeps the typed message when the backend refuses it before storing", async () => {
    const { wrapper } = await mountView({
      submitTurn: vi.fn().mockRejectedValue(new ApiError(503, "llm_unavailable", "", true)),
    });
    await send(wrapper, "Bunu kaybetme");
    await flushPromises();
    expect((wrapper.get('[data-testid="composer"]').element as HTMLTextAreaElement).value).toBe("Bunu kaybetme");
    expect(wrapper.get('[data-testid="thread-error"]').text()).toContain("Ollama");
  });

  it.each([
    ["database_busy", "meşgul"],
    ["message_save_failed", "kaydedilemedi"],
    ["context_failed", "bağlamı hazırlanamadı"],
    ["llm_model_not_found", "yüklü değil"],
  ])("shows a Turkish error for %s", async (code, text) => {
    const { wrapper } = await mountView({
      submitTurn: vi.fn().mockRejectedValue(new ApiError(503, code, "", true)),
    });
    await send(wrapper, "Merhaba");
    await flushPromises();
    expect(wrapper.get('[data-testid="thread-error"]').text()).toContain(text);
  });

  it("marks interrupted and failed replies instead of showing them as complete", async () => {
    const { wrapper } = await mountView({
      timeline: vi.fn().mockResolvedValue({
        messages: [
          messageFixture(1, "user", "Soru"),
          messageFixture(2, "assistant", "Yarım", { status: "interrupted", metrics: null }),
          messageFixture(3, "user", "Tekrar"),
          messageFixture(4, "assistant", "", { status: "failed", error_code: "llm_load_failed", metrics: null }),
        ],
        has_more: false,
      }),
    });
    expect(wrapper.get('[data-testid="interrupted-note"]').text()).toContain("yarım kaldı");
    expect(wrapper.get('[data-testid="failed-note"]').text()).toContain("Model yüklenemedi");
  });

  it("explains summarized context and a down runtime", async () => {
    const base = assistantFixture();
    const summarized = await mountView({
      assistantState: vi.fn().mockResolvedValue({
        ...base,
        context: { ...base.context!, strategy: "summary_window", summary: { version: 1, to_seq: 40, kept_items: 9, dropped_items: 1, created_at: "t" } },
      }),
    });
    expect(summarized.wrapper.get('[data-testid="context-notice"]').text()).toContain("özet olarak");
    useAssistantStore().stop();
    useConnectionStore().stop();
    const down = await mountView({
      llmStatus: vi.fn().mockResolvedValue({
        ...llmStatusFixture,
        runtime: { available: false, runtime: "ollama", version: null, error_code: "llm_unavailable" },
      }),
    });
    expect(down.wrapper.get('[data-testid="runtime-down"]').text()).toContain("Ollama");
    expect(down.wrapper.get('[data-testid="composer"]').attributes("disabled")).toBeDefined();
  });

  it("never writes conversation text to browser storage", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const turn: TurnImpl = async (_b, onEvent) => {
      onEvent(startEvent());
      onEvent({ type: "delta", text: "gizli yanıt" });
      onEvent({ type: "done", message: messageFixture(4, "assistant", "gizli yanıt"), context: { estimated_tokens: 1, prompt_tokens: 1, strategy: "full" } });
    };
    const { wrapper } = await mountView({ submitTurn: vi.fn(turn) });
    await send(wrapper, "gizli soru");
    await flushPromises();
    expect(setItem).not.toHaveBeenCalled();
    setItem.mockRestore();
  });
});
