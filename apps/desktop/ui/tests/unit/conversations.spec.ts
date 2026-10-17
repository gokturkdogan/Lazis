import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, type ApiClient, type TurnEvent, type TurnSubmitRequest } from "@/api/client";
import { createAppI18n } from "@/i18n";
import { useConnectionStore } from "@/stores/connection";
import { useConversationsStore } from "@/stores/conversations";
import ConversationView from "@/views/ConversationView.vue";
import {
  connection,
  conversationFixture,
  detailFixture,
  fakeClient,
  fakePlatform,
  llmStatusFixture,
  messageFixture,
  MODEL,
} from "./fixtures";

type TurnImpl = (body: TurnSubmitRequest, onEvent: (e: TurnEvent) => void, signal?: AbortSignal) => Promise<void>;

const A = conversationFixture();
const B = conversationFixture({ id: "01M558Q8A5R4V2Y7K0J3H6N9TC", title: "Tatil", updated_at: "2026-10-16T09:00:00.000Z" });

async function mountView(overrides: Partial<ApiClient> = {}, conn = connection()) {
  const pinia = createPinia();
  setActivePinia(pinia);
  const client = fakeClient(overrides);
  await useConnectionStore().start({ platform: fakePlatform(conn), clientFactory: () => client });
  const wrapper = mount(ConversationView, { global: { plugins: [pinia, createAppI18n()] } });
  await flushPromises();
  return { wrapper, client, store: useConversationsStore() };
}

function startEvent(conversation = A, seq = 3, created = false): TurnEvent {
  return {
    type: "start",
    conversation,
    created,
    user_message: messageFixture(seq, "user", "Yarın ne yapalım?", { conversation_id: conversation.id }),
    assistant_message: messageFixture(seq + 1, "assistant", "", {
      conversation_id: conversation.id,
      status: "streaming",
      metrics: null,
    }),
  };
}

async function send(wrapper: ReturnType<typeof mount>, text: string) {
  await wrapper.get('[data-testid="composer"]').setValue(text);
  await wrapper.get("form").trigger("submit");
}

describe("Conversation view", () => {
  beforeEach(() => setActivePinia(createPinia()));
  afterEach(() => {
    useConversationsStore().stop();
    useConnectionStore().stop();
    vi.useRealTimers();
  });

  it("reopens the most recently updated conversation with its history", async () => {
    const { wrapper, client, store } = await mountView({
      listConversations: vi.fn().mockResolvedValue({ conversations: [A, B], next_cursor: null }),
      listMessages: vi.fn().mockResolvedValue({
        messages: [messageFixture(1, "user", "Merhaba"), messageFixture(2, "assistant", "Merhaba efendim.")],
        has_more: false,
      }),
    });
    expect(store.activeId).toBe(A.id);
    expect(client.listMessages).toHaveBeenCalledWith(A.id, null);
    const items = wrapper.findAll('[data-testid="conversation-item"]');
    expect(items).toHaveLength(2);
    expect(items[0]?.attributes("aria-current")).toBe("true");
    expect(wrapper.get('[data-testid="thread-title"]').text()).toBe("Haftalık plan");
    expect(wrapper.findAll('[data-testid="message-assistant"]')[0]?.text()).toContain("Merhaba efendim.");
    expect(client.prepare).toHaveBeenCalledWith(A.id, MODEL); // cache warming on open
  });

  it("starts a new conversation that is stored with its first message", async () => {
    const turn: TurnImpl = async (body, onEvent) => {
      expect(body.conversation_id).toBeNull();
      const created = conversationFixture({ title: "Yarın ne yapalım?" });
      onEvent(startEvent(created, 1, true));
      onEvent({ type: "delta", text: "Bir plan " });
      onEvent({ type: "delta", text: "yapalım." });
      onEvent({
        type: "done",
        message: messageFixture(2, "assistant", "Bir plan yapalım."),
        context: { estimated_tokens: 700, prompt_tokens: 690, strategy: "full" },
      });
    };
    const { wrapper, store } = await mountView({ submitTurn: vi.fn(turn) });
    expect(wrapper.find('[data-testid="empty-thread"]').exists()).toBe(true);
    await send(wrapper, "Yarın ne yapalım?");
    await flushPromises();
    expect(store.activeId).toBe(A.id);
    expect(wrapper.findAll('[data-testid="conversation-item"]')).toHaveLength(1);
    expect(wrapper.get('[data-testid="message-assistant"]').text()).toContain("Bir plan yapalım.");
    expect((wrapper.get('[data-testid="composer"]').element as HTMLTextAreaElement).value).toBe("");
  });

  it("switches between conversations and keeps them separate", async () => {
    const listMessages = vi.fn().mockImplementation(async (id: string) => ({
      messages: [messageFixture(1, "user", id === A.id ? "A sohbeti" : "B sohbeti", { conversation_id: id })],
      has_more: false,
    }));
    const { wrapper, store } = await mountView({
      listConversations: vi.fn().mockResolvedValue({ conversations: [A, B], next_cursor: null }),
      listMessages,
      getConversation: vi.fn().mockImplementation(async (id: string) => detailFixture(id === A.id ? A : B)),
    });
    expect(wrapper.get('[data-testid="messages"]').text()).toContain("A sohbeti");
    await wrapper.get(`[data-testid="open-${B.id}"]`).trigger("click");
    await flushPromises();
    expect(store.activeId).toBe(B.id);
    const text = wrapper.get('[data-testid="messages"]').text();
    expect(text).toContain("B sohbeti");
    expect(text).not.toContain("A sohbeti");
  });

  it("shows the real backend stages, then lets the user stop and keeps the partial reply", async () => {
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
    const { wrapper } = await mountView({
      listConversations: vi.fn().mockResolvedValue({ conversations: [A], next_cursor: null }),
      submitTurn: vi.fn(turn),
      cancelTurn,
    });
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
      listConversations: vi.fn().mockResolvedValue({ conversations: [A], next_cursor: null }),
      listMessages: vi.fn().mockResolvedValue({
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

  it("renames inline and deletes only after confirmation", async () => {
    const deleteConversation = vi.fn().mockResolvedValue({ deleted: true, messages: 2, summaries: 0 });
    const { wrapper, client, store } = await mountView({
      listConversations: vi.fn().mockResolvedValue({ conversations: [A, B], next_cursor: null }),
      deleteConversation,
      getConversation: vi.fn().mockImplementation(async (id: string) => detailFixture(id === A.id ? A : B)),
    });
    await wrapper.findAll('[data-testid="rename-conversation"]')[0]?.trigger("click");
    const input = wrapper.get('[data-testid="rename-input"]');
    await input.setValue("Yeni başlık");
    await input.trigger("keydown", { key: "Enter" });
    await flushPromises();
    expect(client.renameConversation).toHaveBeenCalledWith(A.id, "Yeni başlık");
    expect(wrapper.findAll('[data-testid="conversation-item"]')[0]?.text()).toContain("Yeni başlık");

    await wrapper.findAll('[data-testid="delete-conversation"]')[0]?.trigger("click");
    expect(wrapper.get('[data-testid="delete-dialog"]').text()).toContain("geri alınamaz");
    await wrapper.get('[data-testid="delete-cancel"]').trigger("click");
    expect(deleteConversation).not.toHaveBeenCalled();

    await wrapper.findAll('[data-testid="delete-conversation"]')[0]?.trigger("click");
    await wrapper.get('[data-testid="delete-confirm"]').trigger("click");
    await flushPromises();
    expect(deleteConversation).toHaveBeenCalledWith(A.id);
    expect(store.conversations.map((c) => c.id)).toEqual([B.id]);
    expect(store.activeId).toBe(B.id); // the deleted one was open: move to a safe state
    expect(wrapper.find('[data-testid="delete-dialog"]').exists()).toBe(false);
  });

  it("pages older messages on request", async () => {
    const listMessages = vi
      .fn()
      .mockResolvedValueOnce({ messages: [messageFixture(51, "user", "yeni")], has_more: true })
      .mockResolvedValueOnce({ messages: [messageFixture(50, "assistant", "eski")], has_more: false });
    const { wrapper, client } = await mountView({
      listConversations: vi.fn().mockResolvedValue({ conversations: [A], next_cursor: null }),
      listMessages,
    });
    await wrapper.get('[data-testid="load-older"]').trigger("click");
    await flushPromises();
    expect(client.listMessages).toHaveBeenLastCalledWith(A.id, 51);
    const texts = wrapper.findAll("article").map((a) => a.text());
    expect(texts[0]).toContain("eski");
    expect(wrapper.find('[data-testid="load-older"]').exists()).toBe(false);
  });

  it("shows summary and context-limit notices from the backend", async () => {
    const detail = detailFixture();
    const { wrapper } = await mountView({
      listConversations: vi.fn().mockResolvedValue({ conversations: [A], next_cursor: null }),
      getConversation: vi.fn().mockResolvedValue({
        ...detail,
        context: { ...detail.context, strategy: "summary_window", summary: { version: 1, to_seq: 40, kept_items: 9, dropped_items: 1, created_at: "t" } },
      }),
    });
    expect(wrapper.get('[data-testid="context-notice"]').text()).toContain("#1–#40");
  });

  it("explains when the local runtime is down", async () => {
    const { wrapper } = await mountView({
      llmStatus: vi.fn().mockResolvedValue({
        ...llmStatusFixture,
        runtime: { available: false, runtime: "ollama", version: null, error_code: "llm_unavailable" },
      }),
    });
    expect(wrapper.get('[data-testid="runtime-down"]').text()).toContain("Ollama");
    expect(wrapper.get('[data-testid="composer"]').attributes("disabled")).toBeDefined();
  });

  it("never writes conversation text to browser storage", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const turn: TurnImpl = async (_b, onEvent) => {
      onEvent(startEvent());
      onEvent({ type: "delta", text: "gizli yanıt" });
      onEvent({ type: "done", message: messageFixture(4, "assistant", "gizli yanıt"), context: { estimated_tokens: 1, prompt_tokens: 1, strategy: "full" } });
    };
    const { wrapper } = await mountView({
      listConversations: vi.fn().mockResolvedValue({ conversations: [A], next_cursor: null }),
      submitTurn: vi.fn(turn),
    });
    await send(wrapper, "gizli soru");
    await flushPromises();
    expect(setItem).not.toHaveBeenCalled();
    setItem.mockRestore();
  });
});
