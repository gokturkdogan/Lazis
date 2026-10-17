import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, type ApiClient, type ChatEvent, type ChatStreamRequest } from "@/api/client";
import ChatPanel from "@/components/ChatPanel.vue";
import { createAppI18n } from "@/i18n";
import { useChatStore } from "@/stores/chat";
import { useConnectionStore } from "@/stores/connection";
import { connection, fakeClient, fakePlatform, llmStatusFixture, modelFixture } from "./fixtures";

type StreamImpl = (
  body: ChatStreamRequest,
  onEvent: (e: ChatEvent) => void,
  signal?: AbortSignal,
) => Promise<void>;

async function mountChat(overrides: Partial<ApiClient> = {}) {
  const pinia = createPinia();
  setActivePinia(pinia);
  const client = fakeClient(overrides);
  await useConnectionStore().start({ platform: fakePlatform(connection()), clientFactory: () => client });
  const wrapper = mount(ChatPanel, { global: { plugins: [pinia, createAppI18n()] } });
  await flushPromises();
  return { wrapper, client, chat: useChatStore() };
}

async function send(wrapper: ReturnType<typeof mount>, text: string) {
  await wrapper.get('[data-testid="chat-input"]').setValue(text);
  await wrapper.get("form").trigger("submit");
}

describe("ChatPanel", () => {
  beforeEach(() => setActivePinia(createPinia()));
  afterEach(() => {
    useConnectionStore().stop();
    vi.useRealTimers();
  });

  it("lists installed models and selects the first one", async () => {
    const second = { ...modelFixture, name: "qwen3:8b-q4_K_M", parameter_size: "8.2B" };
    const { wrapper, chat } = await mountChat({
      models: vi.fn().mockResolvedValue({ models: [modelFixture, second] }),
    });
    const options = wrapper.findAll('[data-testid="model-select"] option');
    expect(options.map((o) => o.attributes("value"))).toEqual([modelFixture.name, second.name]);
    expect(chat.selectedModel).toBe(modelFixture.name);
    await wrapper.get('[data-testid="model-select"]').setValue(second.name);
    expect(chat.selectedModel).toBe(second.name);
  });

  it("prefers the configured primary model", async () => {
    const second = { ...modelFixture, name: "qwen3:8b-q4_K_M" };
    const { chat } = await mountChat({
      models: vi.fn().mockResolvedValue({ models: [modelFixture, second] }),
      llmStatus: vi.fn().mockResolvedValue({ ...llmStatusFixture, primary_model: second.name }),
    });
    expect(chat.selectedModel).toBe(second.name);
  });

  it("streams the answer into the conversation and shows metrics", async () => {
    let captured: ChatStreamRequest | null = null;
    const stream: StreamImpl = async (body, onEvent) => {
      captured = body;
      onEvent({ type: "start", request_id: body.request_id, model: body.model });
      onEvent({ type: "delta", text: "Merhaba" });
      onEvent({ type: "delta", text: " efendim." });
      onEvent({
        type: "done",
        metrics: { ttft_ms: 850, total_ms: 2000, load_ms: 0, prompt_tokens: 40, output_tokens: 12,
          prefill_tps: 900, decode_tps: 31.4, done_reason: "stop" },
      });
    };
    const { wrapper } = await mountChat({ chatStream: vi.fn(stream) });
    await send(wrapper, "  Merhaba LAZIS  ");
    await flushPromises();
    const replies = wrapper.findAll('[data-testid="message-assistant"]');
    expect(replies).toHaveLength(1);
    expect(replies[0]?.text()).toContain("Merhaba efendim.");
    expect(wrapper.get('[data-testid="chat-metrics"]').text()).toContain("31.4 token/sn");
    expect(captured).not.toBeNull();
    const body = captured as unknown as ChatStreamRequest;
    expect(body.messages).toEqual([{ role: "user", content: "Merhaba LAZIS" }]);
    expect(body.model).toBe(modelFixture.name);
    expect(body.request_id.length).toBeGreaterThanOrEqual(8);
    expect((wrapper.get('[data-testid="chat-input"]').element as HTMLTextAreaElement).value).toBe("");
  });

  it("sends earlier turns as history but drops failed answers", async () => {
    const bodies: ChatStreamRequest[] = [];
    let call = 0;
    const stream: StreamImpl = async (body, onEvent) => {
      bodies.push(body);
      call += 1;
      if (call === 1) onEvent({ type: "error", code: "llm_timeout", message: "x" });
      else {
        onEvent({ type: "delta", text: "Tamam." });
        onEvent({ type: "done", metrics: { ttft_ms: 1, total_ms: 1, load_ms: null, prompt_tokens: 1,
          output_tokens: 1, prefill_tps: null, decode_tps: null, done_reason: "stop" } });
      }
    };
    const { wrapper } = await mountChat({ chatStream: vi.fn(stream) });
    await send(wrapper, "Birinci");
    await flushPromises();
    await send(wrapper, "İkinci");
    await flushPromises();
    expect(bodies[1]?.messages).toEqual([
      { role: "user", content: "Birinci" },
      { role: "user", content: "İkinci" },
    ]);
  });

  it("shows a loading state until the first token, then lets the user stop", async () => {
    let release: () => void = () => undefined;
    let emit: (e: ChatEvent) => void = () => undefined;
    const stream: StreamImpl = (_body, onEvent) => {
      emit = onEvent;
      return new Promise<void>((resolve) => {
        release = resolve;
      });
    };
    const cancelChat = vi.fn().mockImplementation(async () => {
      emit({ type: "error", code: "llm_cancelled", message: "x" });
      release();
      return true;
    });
    const { wrapper, chat } = await mountChat({ chatStream: vi.fn(stream), cancelChat });
    await send(wrapper, "Uzun bir hikâye anlat");
    await flushPromises();
    expect(wrapper.find('[data-testid="chat-loading"]').exists()).toBe(true);
    expect(chat.phase).toBe("waiting");
    emit({ type: "delta", text: "Bir varmış" });
    await flushPromises();
    expect(chat.phase).toBe("streaming");
    await wrapper.get('[data-testid="chat-stop"]').trigger("click");
    await flushPromises();
    expect(cancelChat).toHaveBeenCalledOnce();
    expect(chat.phase).toBe("idle");
    expect(chat.messages[1]?.state).toBe("cancelled");
    expect(wrapper.text()).toContain("Yanıt durduruldu.");
    expect(wrapper.text()).toContain("Bir varmış"); // partial text stays visible
  });

  it("aborts the stream if the backend does not stop in time", async () => {
    vi.useFakeTimers();
    let aborted = false;
    const stream: StreamImpl = (_b, _e, signal) =>
      new Promise<void>((_resolve, reject) => {
        signal?.addEventListener("abort", () => {
          aborted = true;
          reject(new ApiError(0, "llm_cancelled", "", true));
        });
      });
    const { wrapper, chat } = await mountChat({
      chatStream: vi.fn(stream),
      cancelChat: vi.fn().mockResolvedValue(false),
    });
    await send(wrapper, "Merhaba");
    await flushPromises();
    await wrapper.get('[data-testid="chat-stop"]').trigger("click");
    await flushPromises();
    vi.advanceTimersByTime(2100);
    await flushPromises();
    expect(aborted).toBe(true);
    expect(chat.messages[1]?.state).toBe("cancelled");
  });

  it.each([
    ["llm_out_of_memory", "Model için yeterli bellek yok"],
    ["llm_model_not_found", "yüklü değil"],
    ["backend_unreachable", ""],
  ])("shows a Turkish error for %s", async (code, text) => {
    const stream: StreamImpl = async () => {
      throw new ApiError(503, code, "", true);
    };
    const { wrapper } = await mountChat({ chatStream: vi.fn(stream) });
    await send(wrapper, "Merhaba");
    await flushPromises();
    const error = wrapper.get('[data-testid="chat-error"]');
    expect(error.text().length).toBeGreaterThan(5);
    if (text) expect(error.text()).toContain(text);
  });

  it("explains an empty model inventory and disables sending", async () => {
    const { wrapper } = await mountChat({ models: vi.fn().mockResolvedValue({ models: [] }) });
    expect(wrapper.get('[data-testid="chat-no-models"]').text()).toContain("make model-pull");
    expect(wrapper.get('[data-testid="chat-input"]').attributes("disabled")).toBeDefined();
  });

  it("explains when the local runtime is down", async () => {
    const { wrapper, client } = await mountChat({
      llmStatus: vi.fn().mockResolvedValue({
        ...llmStatusFixture,
        runtime: { available: false, runtime: "ollama", version: null, error_code: "llm_unavailable" },
      }),
    });
    expect(wrapper.get('[data-testid="chat-runtime-down"]').text()).toContain("Ollama");
    expect(client.models).not.toHaveBeenCalled();
    expect(wrapper.get('[data-testid="chat-input"]').attributes("disabled")).toBeDefined();
  });

  it("keeps the conversation in memory only and can clear it", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const stream: StreamImpl = async (_b, onEvent) => {
      onEvent({ type: "delta", text: "Yanıt" });
      onEvent({ type: "done", metrics: { ttft_ms: 1, total_ms: 1, load_ms: null, prompt_tokens: 1,
        output_tokens: 1, prefill_tps: null, decode_tps: null, done_reason: "stop" } });
    };
    const { wrapper, chat } = await mountChat({ chatStream: vi.fn(stream) });
    await send(wrapper, "Gizli not");
    await flushPromises();
    expect(setItem).not.toHaveBeenCalled();
    await wrapper.get('[data-testid="chat-clear"]').trigger("click");
    expect(chat.messages).toHaveLength(0);
    setItem.mockRestore();
  });
});
