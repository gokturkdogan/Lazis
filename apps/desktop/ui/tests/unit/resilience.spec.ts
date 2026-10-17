import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ApiClient } from "@/api/client";
import { createAppI18n } from "@/i18n";
import { useAssistantStore, RUNTIME_RETRY_MS } from "@/stores/assistant";
import { useConnectionStore } from "@/stores/connection";
import AssistantView from "@/views/AssistantView.vue";
import { connection, fakeClient, fakePlatform, llmStatusFixture, messageFixture } from "./fixtures";

function setVisibility(state: "visible" | "hidden") {
  Object.defineProperty(document, "visibilityState", { value: state, configurable: true });
  document.dispatchEvent(new Event("visibilitychange"));
}

describe("Cheap, visibility-aware health checks", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    setVisibility("visible");
  });
  afterEach(() => {
    useConnectionStore().stop();
    setVisibility("visible");
    vi.useRealTimers();
  });

  it("polls only /health, every 15 s by default, and only while visible", async () => {
    vi.useFakeTimers();
    const client = fakeClient();
    const store = useConnectionStore();
    await store.start({ platform: fakePlatform(connection()), clientFactory: () => client });
    expect(client.systemStatus).toHaveBeenCalledTimes(1); // initial load only
    vi.mocked(client.health).mockClear();

    await vi.advanceTimersByTimeAsync(14_000);
    expect(client.health).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1_000);
    expect(client.health).toHaveBeenCalledTimes(1);

    setVisibility("hidden");
    await vi.advanceTimersByTimeAsync(120_000);
    expect(client.health).toHaveBeenCalledTimes(1); // nothing while hidden

    setVisibility("visible");
    await flushPromises();
    expect(client.health).toHaveBeenCalledTimes(2); // immediate re-check when shown
    await vi.advanceTimersByTimeAsync(15_000);
    expect(client.health).toHaveBeenCalledTimes(3);
    expect(client.systemStatus).toHaveBeenCalledTimes(1); // never polled
  });

  it("re-checks health right after the Mac wakes and notifies listeners", async () => {
    let wake: () => void = () => undefined;
    const platform = fakePlatform(connection(), {
      onSystemWoke: vi.fn().mockImplementation((cb: () => void) => {
        wake = cb;
        return Promise.resolve(() => undefined);
      }),
    });
    const client = fakeClient();
    const store = useConnectionStore();
    await store.start({ platform, clientFactory: () => client });
    vi.mocked(client.health).mockClear();
    const { onSystemWoke } = await import("@/stores/connection");
    const handler = vi.fn();
    const off = onSystemWoke(handler);
    wake();
    await flushPromises();
    expect(client.health).toHaveBeenCalledTimes(1);
    expect(handler).toHaveBeenCalledTimes(1);
    expect(store.events[0]?.code).toBe("system_woke");
    off();
  });

  it("reports an automatic restart and the exhausted budget distinctly", async () => {
    let push: (c: ReturnType<typeof connection>) => void = () => undefined;
    const platform = fakePlatform(connection(), {
      onConnectionChanged: vi.fn().mockImplementation((cb: typeof push) => {
        push = cb;
        return Promise.resolve(() => undefined);
      }),
    });
    const store = useConnectionStore();
    await store.start({ platform, clientFactory: () => fakeClient() });
    push(connection({ phase: "failed", token: null, port: null, errorCode: "backend_exited", restartAttempt: 1 }));
    await flushPromises();
    expect(store.phase).toBe("backend_failed");
    expect(store.events.map((e) => e.code).slice(0, 2)).toEqual(["backend_restarting", "backend_exited"]);
    push(connection({ phase: "failed", token: null, port: null, errorCode: "backend_restart_limit" }));
    await flushPromises();
    expect(store.errorCode).toBe("backend_restart_limit");
  });
});

describe("Runtime (Ollama) reconnect", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    setVisibility("visible");
  });
  afterEach(() => {
    useAssistantStore().stop();
    useConnectionStore().stop();
    setVisibility("visible");
    vi.useRealTimers();
  });

  const down = { ...llmStatusFixture, runtime: { available: false, version: null, error_code: "llm_unavailable" as const } };

  async function mountWith(overrides: Partial<ApiClient>) {
    const pinia = createPinia();
    setActivePinia(pinia);
    const client = fakeClient(overrides);
    await useConnectionStore().start({ platform: fakePlatform(connection()), clientFactory: () => client });
    const wrapper = mount(AssistantView, { global: { plugins: [pinia, createAppI18n()] } });
    await flushPromises();
    return { wrapper, client };
  }

  it("re-checks with a growing delay, pauses while hidden, and re-warms once Ollama is back", async () => {
    vi.useFakeTimers();
    const llmStatus = vi.fn().mockResolvedValue(down);
    const { wrapper, client } = await mountWith({ llmStatus });
    expect(wrapper.find('[data-testid="runtime-down"]').exists()).toBe(true);
    expect(llmStatus).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(RUNTIME_RETRY_MS[0] ?? 0);
    expect(llmStatus).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync((RUNTIME_RETRY_MS[1] ?? 0) - 1);
    expect(llmStatus).toHaveBeenCalledTimes(2); // backoff, not a fixed loop
    await vi.advanceTimersByTimeAsync(1);
    expect(llmStatus).toHaveBeenCalledTimes(3);

    setVisibility("hidden");
    await vi.advanceTimersByTimeAsync(10 * 60_000);
    const whileHidden = llmStatus.mock.calls.length;
    await vi.advanceTimersByTimeAsync(10 * 60_000);
    expect(llmStatus.mock.calls.length).toBe(whileHidden); // nothing scheduled while hidden

    llmStatus.mockResolvedValue(llmStatusFixture);
    vi.mocked(client.prepare).mockClear();
    setVisibility("visible");
    await flushPromises();
    expect(wrapper.find('[data-testid="runtime-down"]').exists()).toBe(false);
    expect(client.prepare).toHaveBeenCalledTimes(1);
    const after = llmStatus.mock.calls.length;
    await vi.advanceTimersByTimeAsync(60_000);
    expect(llmStatus.mock.calls.length).toBe(after); // stops once available
  });

  it("after waking from sleep: re-checks the runtime and re-warms the session", async () => {
    let wake: () => void = () => undefined;
    const pinia = createPinia();
    setActivePinia(pinia);
    const client = fakeClient();
    const platform = fakePlatform(connection(), {
      onSystemWoke: vi.fn().mockImplementation((cb: () => void) => {
        wake = cb;
        return Promise.resolve(() => undefined);
      }),
    });
    await useConnectionStore().start({ platform, clientFactory: () => client });
    mount(AssistantView, { global: { plugins: [pinia, createAppI18n()] } });
    await flushPromises();
    vi.mocked(client.llmStatus).mockClear();
    vi.mocked(client.prepare).mockClear();
    wake();
    await flushPromises();
    expect(client.llmStatus).toHaveBeenCalledTimes(1);
    expect(client.prepare).toHaveBeenCalledTimes(1);
  });
});

describe("Thread scrolling", () => {
  beforeEach(() => setActivePinia(createPinia()));
  afterEach(() => {
    useAssistantStore().stop();
    useConnectionStore().stop();
  });

  /** happy-dom has no layout: give the list a fake geometry. */
  function geometry(el: HTMLElement, g: { scrollHeight: number; clientHeight: number; scrollTop: number }) {
    Object.defineProperty(el, "scrollHeight", { configurable: true, get: () => g.scrollHeight });
    Object.defineProperty(el, "clientHeight", { configurable: true, get: () => g.clientHeight });
    Object.defineProperty(el, "scrollTop", {
      configurable: true,
      get: () => g.scrollTop,
      set: (v: number) => (g.scrollTop = v),
    });
    const scrollTo = vi.fn((o: ScrollToOptions) => (g.scrollTop = o.top ?? g.scrollTop));
    Object.defineProperty(el, "scrollTo", { configurable: true, value: scrollTo });
    return scrollTo;
  }

  const many = Array.from({ length: 50 }, (_, i) =>
    messageFixture(i + 51, i % 2 === 0 ? "user" : "assistant", `Mesaj ${i + 51}`),
  );

  async function mountThread(overrides: Partial<ApiClient> = {}) {
    const pinia = createPinia();
    setActivePinia(pinia);
    const client = fakeClient({
      timeline: vi.fn().mockResolvedValue({ messages: structuredClone(many), has_more: true }),
      ...overrides,
    });
    await useConnectionStore().start({ platform: fakePlatform(connection()), clientFactory: () => client });
    const wrapper = mount(AssistantView, { global: { plugins: [pinia, createAppI18n()] } });
    await flushPromises();
    return { wrapper, client, store: useAssistantStore() };
  }

  it("does not pull a reader back down while they read older messages", async () => {
    const { wrapper, store } = await mountThread();
    const list = wrapper.get('[data-testid="messages"]').element as HTMLElement;
    const g = { scrollHeight: 5000, clientHeight: 500, scrollTop: 1200 };
    const scrollTo = geometry(list, g);
    await wrapper.get('[data-testid="messages"]').trigger("scroll");
    // New text arrives at the end (e.g. a streaming reply).
    const last = store.messages[store.messages.length - 1];
    if (last) last.content += " ve devamı";
    await flushPromises();
    expect(scrollTo).not.toHaveBeenCalled();
    expect(g.scrollTop).toBe(1200);
    expect(wrapper.find('[data-testid="jump-latest"]').exists()).toBe(true);
    await wrapper.get('[data-testid="jump-latest"]').trigger("click");
    expect(scrollTo).toHaveBeenCalledWith({ top: 5000 });
    expect(wrapper.find('[data-testid="jump-latest"]').exists()).toBe(false);
  });

  it("follows new text while the reader is at the bottom", async () => {
    const { wrapper, store } = await mountThread();
    const list = wrapper.get('[data-testid="messages"]').element as HTMLElement;
    const g = { scrollHeight: 5000, clientHeight: 500, scrollTop: 4480 }; // within the slack
    const scrollTo = geometry(list, g);
    await wrapper.get('[data-testid="messages"]').trigger("scroll");
    const last = store.messages[store.messages.length - 1];
    if (last) last.content += " ve devamı";
    await flushPromises();
    expect(scrollTo).toHaveBeenCalledWith({ top: 5000 });
  });

  it("keeps the reading position when older messages are prepended", async () => {
    const older = Array.from({ length: 50 }, (_, i) => messageFixture(i + 1, "user", `Eski ${i + 1}`));
    const { wrapper } = await mountThread();
    const list = wrapper.get('[data-testid="messages"]').element as HTMLElement;
    const g = { scrollHeight: 5000, clientHeight: 500, scrollTop: 0 };
    geometry(list, g);
    const store = useAssistantStore();
    const client = (await import("@/stores/connection")).currentApiClient();
    vi.mocked(client!.timeline).mockImplementation(async () => {
      g.scrollHeight = 9000; // the prepended page adds 4000 px above
      return { messages: older, has_more: false };
    });
    await wrapper.get('[data-testid="load-older"]').trigger("click");
    await flushPromises();
    expect(store.messages).toHaveLength(100);
    expect(g.scrollTop).toBe(4000); // the same message stays in view
  });

  it("copies a whole message", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    const { wrapper } = await mountThread();
    const button = wrapper.findAll('[data-testid="copy-assistant"]').at(-1);
    await button?.trigger("click");
    await flushPromises();
    expect(writeText).toHaveBeenCalledWith("Mesaj 100");
    expect(button?.text()).toBe("Kopyalandı");
  });

  it("renders a completed reply as Markdown and a streaming one as plain text", async () => {
    const { wrapper } = await mountThread({
      timeline: vi.fn().mockResolvedValue({
        messages: [
          messageFixture(1, "assistant", "**kalın** <b>ham</b>"),
          messageFixture(2, "user", "**olduğu gibi**"),
          messageFixture(3, "assistant", "**yarım", { status: "streaming", metrics: null }),
        ],
        has_more: false,
      }),
    });
    const replies = wrapper.findAll('[data-testid="message-assistant"]');
    expect(replies[0]?.find("strong").text()).toBe("kalın");
    expect(replies[0]?.find("b").exists()).toBe(false);
    expect(replies[0]?.text()).toContain("<b>ham</b>");
    expect(wrapper.get('[data-testid="message-user"]').find("strong").exists()).toBe(false);
    expect(replies[1]?.find('[data-testid="markdown"]').exists()).toBe(false);
    expect(replies[1]?.text()).toContain("**yarım");
  });
});
