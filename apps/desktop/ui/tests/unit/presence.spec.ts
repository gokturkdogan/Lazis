import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { watch } from "vue";
import { ApiError, type ApiClient, type TurnEvent, type TurnSubmitRequest } from "@/api/client";
import { createAppI18n } from "@/i18n";
import type { BackendConnection } from "@/platform/tauri";
import { useAssistantStore } from "@/stores/assistant";
import { useConnectionStore } from "@/stores/connection";
import { derivePresence, usePresence, type PresenceInputs, type PresenceState } from "@/stores/presence";
import AssistantView from "@/views/AssistantView.vue";
import { connection, conversationFixture, fakeClient, fakePlatform, messageFixture } from "./fixtures";

const base: PresenceInputs = {
  connection: "connected",
  restartAttempt: 0,
  restartLimit: 3,
  turnPhase: "idle",
  turnStage: null,
  runtimeDown: false,
  turnError: null,
};

describe("derivePresence", () => {
  it.each<[Partial<PresenceInputs>, PresenceState, string]>([
    [{}, "idle", "idle"],
    [{ turnPhase: "sending", turnStage: "waiting" }, "thinking", "thinking"],
    [{ turnPhase: "sending", turnStage: "loading_model" }, "thinking", "thinking"],
    [{ turnPhase: "sending", turnStage: "processing_context" }, "thinking", "thinking"],
    [{ turnPhase: "streaming", turnStage: "generating" }, "speaking", "speaking"],
    [{ turnPhase: "cancelling", turnStage: "generating" }, "thinking", "stopping"],
    [{ turnError: "llm_timeout" }, "error", "turnFailed"],
    [{ turnError: "llm_cancelled" }, "idle", "idle"],
    [{ runtimeDown: true }, "error", "runtimeDown"],
    [{ connection: "starting" }, "thinking", "starting"],
    [{ connection: "disconnected", turnPhase: "streaming", turnStage: "generating" }, "error", "disconnected"],
    [{ connection: "backend_failed" }, "error", "backendFailed"],
    [{ connection: "backend_failed", restartAttempt: 2 }, "error", "restarting"],
    [{ connection: "needs_recovery" }, "error", "needsRecovery"],
  ])("%o → %s", (inputs, state, label) => {
    const p = derivePresence({ ...base, ...inputs });
    expect([p.state, p.label]).toEqual([state, label]);
  });

  it("never reports listening (no microphone before Phase 13)", () => {
    const phases = ["initializing", "starting", "connected", "disconnected", "backend_failed", "needs_recovery"] as const;
    for (const connection of phases) {
      for (const turnPhase of ["idle", "sending", "streaming", "cancelling"] as const) {
        expect(derivePresence({ ...base, connection, turnPhase }).state).not.toBe("listening");
      }
    }
  });
});

type TurnImpl = (body: TurnSubmitRequest, onEvent: (e: TurnEvent) => void, signal?: AbortSignal) => Promise<void>;

/** Mount the assistant and record every presence state it passes through. */
async function mountRecording(overrides: Partial<ApiClient>, conn: BackendConnection = connection()) {
  const pinia = createPinia();
  setActivePinia(pinia);
  const client = fakeClient(overrides);
  let push: ((c: BackendConnection) => void) | null = null;
  const platform = fakePlatform(conn, {
    onConnectionChanged: vi.fn().mockImplementation((cb: (c: BackendConnection) => void) => {
      push = cb;
      return Promise.resolve(() => undefined);
    }),
  });
  await useConnectionStore().start({ platform, clientFactory: () => client });
  const wrapper = mount(AssistantView, { global: { plugins: [pinia, createAppI18n()] } });
  await flushPromises();
  const presence = usePresence();
  const seen: PresenceState[] = [presence.value.state];
  watch(
    () => presence.value.state,
    (s) => seen.push(s),
    { flush: "sync" },
  );
  return { wrapper, client, seen, presence, push: (c: BackendConnection) => push?.(c) };
}

const SESSION = conversationFixture();
const CTX = { estimated_tokens: 1, prompt_tokens: 1, strategy: "full" } as const;
const start: TurnEvent = {
  type: "start",
  conversation: SESSION,
  created: false,
  user_message: messageFixture(3, "user", "Merhaba"),
  assistant_message: messageFixture(4, "assistant", "", { status: "streaming", metrics: null }),
};

async function send(wrapper: ReturnType<typeof mount>, text: string) {
  await wrapper.get('[data-testid="composer"]').setValue(text);
  await wrapper.get("form").trigger("submit");
}

describe("Presence follows real turn events", () => {
  beforeEach(() => setActivePinia(createPinia()));
  afterEach(() => {
    useAssistantStore().stop();
    useConnectionStore().stop();
  });

  it("idle → thinking → speaking → idle for a normal reply", async () => {
    let release: () => void = () => undefined;
    const turn: TurnImpl = async (_b, onEvent) => {
      onEvent(structuredClone(start));
      onEvent({ type: "status", stage: "processing_context", cache: "warm" });
      await new Promise<void>((r) => (release = r));
      onEvent({ type: "delta", text: "Merhaba efendim." });
      onEvent({ type: "done", message: messageFixture(4, "assistant", "Merhaba efendim."), context: CTX });
    };
    const { wrapper, seen, presence } = await mountRecording({ submitTurn: vi.fn().mockImplementation(turn) });
    await send(wrapper, "Merhaba");
    await flushPromises();
    expect(presence.value.state).toBe("thinking"); // waiting for the first token: no timer involved
    release();
    await flushPromises();
    expect(seen).toEqual(["idle", "thinking", "speaking", "idle"]);
  });

  it("a failed reply goes to error and the next good turn back to idle", async () => {
    const failing: TurnImpl = async (_b, onEvent) => {
      onEvent(structuredClone(start));
      onEvent({ type: "error", code: "llm_timeout", message: "", assistant_message: null });
    };
    const ok: TurnImpl = async (_b, onEvent) => {
      onEvent({ ...start, user_message: messageFixture(5, "user", "Tekrar"), assistant_message: messageFixture(6, "assistant", "", { status: "streaming", metrics: null }) });
      onEvent({ type: "delta", text: "Tamam." });
      onEvent({ type: "done", message: messageFixture(6, "assistant", "Tamam."), context: CTX });
    };
    const submitTurn = vi.fn().mockImplementationOnce(failing).mockImplementationOnce(ok);
    const { wrapper, seen, presence } = await mountRecording({ submitTurn });
    await send(wrapper, "Merhaba");
    await flushPromises();
    expect(presence.value.state).toBe("error");
    await send(wrapper, "Tekrar");
    await flushPromises();
    expect(seen).toEqual(["idle", "thinking", "error", "thinking", "speaking", "idle"]);
  });

  it("stop returns to idle (a cancellation is not an error)", async () => {
    let finish: () => void = () => undefined;
    const turn: TurnImpl = async (_b, onEvent) => {
      onEvent(structuredClone(start));
      onEvent({ type: "delta", text: "Uzun bir" });
      await new Promise<void>((r) => (finish = r));
      onEvent({ type: "cancelled", message: messageFixture(4, "assistant", "Uzun bir", { status: "cancelled" }) });
    };
    const cancelTurn = vi.fn().mockImplementation(async () => {
      finish();
      return true;
    });
    const { wrapper, seen, presence } = await mountRecording({ submitTurn: vi.fn().mockImplementation(turn), cancelTurn });
    await send(wrapper, "Anlat");
    await flushPromises();
    expect(presence.value.state).toBe("speaking");
    await wrapper.get('[data-testid="stop"]').trigger("click");
    await flushPromises();
    expect(presence.value.state).toBe("idle");
    expect(seen).toEqual(["idle", "thinking", "speaking", "thinking", "idle"]);
  });

  it("a backend crash mid-reply shows error, keeps the partial text, and recovers on reconnect", async () => {
    let crash: () => void = () => undefined;
    const turn: TurnImpl = async (_b, onEvent) => {
      onEvent(structuredClone(start));
      onEvent({ type: "delta", text: "Yarım kalan" });
      // The shell reports the exit (with a pending automatic restart) as the stream breaks.
      crash();
      throw new ApiError(0, "backend_unreachable", "", true);
    };
    const { wrapper, presence, push, client } = await mountRecording({ submitTurn: vi.fn().mockImplementation(turn) });
    crash = () =>
      push(connection({ phase: "failed", token: null, port: null, errorCode: "backend_exited", restartAttempt: 1 }));
    await send(wrapper, "Anlat");
    await flushPromises();
    expect(presence.value.state).toBe("error");
    expect(presence.value.label).toBe("restarting");
    const store = useAssistantStore();
    const partial = store.messages.find((m) => m.id === start.assistant_message.id);
    expect(partial?.content).toBe("Yarım kalan");
    expect(partial?.status).toBe("interrupted");
    expect(store.messages.filter((m) => m.role === "assistant")).toHaveLength(1);
    expect(store.phase).toBe("idle"); // nothing stuck

    // The restarted backend reports the saved state; the timeline is reloaded once.
    const saved = messageFixture(4, "assistant", "Yarım kalan", { status: "interrupted" });
    vi.mocked(client.timeline).mockResolvedValue({ messages: [start.user_message, saved], has_more: false });
    push(connection({ port: 51235 }));
    await flushPromises();
    const remount = mount(AssistantView, { global: { plugins: [createAppI18n()] } }); // v-if connected
    await flushPromises();
    expect(presence.value.state).toBe("idle");
    expect(client.timeline).toHaveBeenCalledTimes(2);
    expect(store.messages.map((m) => [m.id, m.status])).toEqual([
      [start.user_message.id, "complete"],
      [saved.id, "interrupted"],
    ]);
    remount.unmount();
  });
});
