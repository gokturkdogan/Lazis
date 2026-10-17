/**
 * The one assistant (Phase 3, ADR-0011): a single continuous timeline.
 *
 * The user never creates, picks, renames or deletes conversations. Technical sessions exist
 * only in the backend; turns always go to the active one. The timeline shown here spans all
 * sessions, but only the active session is in the model's context — `activeFrom` marks where
 * it starts, so the view can say so honestly.
 *
 * The backend owns everything durable. This store mirrors what is on screen and never writes
 * conversation text to localStorage or any other browser storage. Status shown to the user
 * comes from the backend (stream `status` events, the activity endpoint) — no fake progress.
 *
 * Phase 4 resilience: when the local runtime (Ollama) is unreachable the store re-checks it
 * with a growing delay (only while the window is visible) and re-warms the session once it is
 * back; LAZIS never starts, stops or reconfigures Ollama itself. After the Mac wakes, the
 * runtime is re-checked and the session re-warmed. If a reply stream breaks (backend or
 * runtime gone), the partial text stays on screen, marked as interrupted, and the timeline is
 * reloaded from the backend once it is reachable again (message ids prevent duplicates).
 */
import { defineStore } from "pinia";
import {
  ApiError,
  type ActivityResponse,
  type AssistantStateResponse,
  type LlmStatusResponse,
  type Message,
  type ModelListResponse,
  type TurnEvent,
  type TurnStage,
} from "@/api/client";
import { connectionEpoch, currentApiClient } from "@/stores/connection";

type Runtime = LlmStatusResponse["runtime"];
type Model = ModelListResponse["models"][number];
type Loaded = LlmStatusResponse["loaded"][number];
type Session = AssistantStateResponse["session"];
type ContextInfo = AssistantStateResponse["context"];

export type TurnPhase = "idle" | "sending" | "streaming" | "cancelling";

export interface TurnState {
  clientId: string;
  stage: TurnStage | "generating";
  cache: "warm" | "cold" | null;
  contextTokens: number | null;
  trimmed: number[] | null;
}

const PAGE = 50;
const PREPARE_INTERVAL_MS = 30_000;
const CANCEL_GRACE_MS = 2000;
const ACTIVITY_POLL_MS = 1500;
/** Runtime re-check delays while Ollama is unreachable (then stays at the last one). */
export const RUNTIME_RETRY_MS = [2000, 4000, 8000, 15_000, 30_000];

let controller: AbortController | null = null;
let activityTimer: ReturnType<typeof setTimeout> | null = null;
let runtimeTimer: ReturnType<typeof setTimeout> | null = null;
let runtimeRetry = 0;
let lastPrepared = 0;
let loadedEpoch = -1;

function windowVisible(): boolean {
  return typeof document === "undefined" || document.visibilityState !== "hidden";
}

function newClientId(): string {
  const random = globalThis.crypto?.randomUUID?.();
  return random ?? `c-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

function byTimeline(messages: Message[]): Message[] {
  const unique = new Map(messages.map((m) => [m.id, m]));
  return [...unique.values()].sort((a, b) => a.timeline_seq - b.timeline_seq);
}

export const useAssistantStore = defineStore("assistant", {
  state: () => ({
    runtime: null as Runtime | null,
    loaded: [] as Loaded[],
    models: [] as Model[],
    inventoryLoaded: false,
    primaryModel: null as string | null,
    selectedModel: "",

    ready: false,
    session: null as Session,
    context: null as ContextInfo,
    activeFrom: null as number | null,
    messages: [] as Message[],
    hasOlder: false,
    loadingMessages: false,

    phase: "idle" as TurnPhase,
    turn: null as TurnState | null,
    background: null as ActivityResponse["background"],
    errorCode: null as string | null,
  }),

  getters: {
    busy: (state) => state.phase !== "idle",
    canSend: (state) =>
      state.phase === "idle" && state.runtime?.available === true && state.selectedModel !== "",
    runtimeDown: (state) => state.inventoryLoaded && state.runtime?.available !== true,
    noModels: (state) =>
      state.inventoryLoaded && state.runtime?.available === true && state.models.length === 0,
  },

  actions: {
    /** Opening LAZIS: the same assistant, the latest page of the timeline, then warm the
     *  active session's prompt prefix (only that one). */
    async init() {
      await Promise.all([this.refreshRuntime(), this.loadLatest()]);
      this.ready = true;
      void this.prepare(true);
    },

    /** The view became active again. After a backend restart (new connection) the timeline
     *  is reloaded: an interrupted reply now carries its saved state. */
    async resume() {
      if (!this.ready) return this.init();
      const reload = loadedEpoch !== connectionEpoch() && !this.busy;
      if (reload) this.errorCode = null; // a new backend session: the old stream error is resolved
      await Promise.all([this.refreshRuntime(), reload ? this.loadLatest() : Promise.resolve()]);
      if (reload) void this.prepare(true);
    },

    async refreshRuntime() {
      const client = currentApiClient();
      if (client === null) return;
      const wasDown = this.runtime !== null && !this.runtime.available;
      try {
        const status = await client.llmStatus();
        this.runtime = status.runtime;
        this.loaded = status.loaded;
        this.primaryModel = status.primary_model;
        if (!status.runtime.available) {
          this.models = [];
          this.scheduleRuntimeCheck();
          return;
        }
        this.models = (await client.models()).models;
        this.pickModel(this.session?.model ?? null);
        this.clearRuntimeCheck();
        if (wasDown) {
          if (this.errorCode === "llm_unavailable") this.errorCode = null;
          void this.prepare(true);
        }
      } catch (error) {
        this.errorCode = error instanceof ApiError ? error.code : "internal_error";
      } finally {
        this.inventoryLoaded = true;
      }
    },

    /** Re-check an unreachable runtime with a growing delay, only while the window is visible
     *  (a hidden window re-checks when it is shown again, see `onVisible`). */
    scheduleRuntimeCheck() {
      if (runtimeTimer !== null || !windowVisible()) return;
      const delay = RUNTIME_RETRY_MS[Math.min(runtimeRetry, RUNTIME_RETRY_MS.length - 1)] ?? 30_000;
      runtimeRetry += 1;
      runtimeTimer = setTimeout(() => {
        runtimeTimer = null;
        void this.refreshRuntime();
      }, delay);
    },

    clearRuntimeCheck() {
      if (runtimeTimer !== null) clearTimeout(runtimeTimer);
      runtimeTimer = null;
      runtimeRetry = 0;
    },

    onVisible() {
      if (this.runtime !== null && !this.runtime.available) {
        this.clearRuntimeCheck();
        void this.refreshRuntime();
      } else {
        void this.prepare();
      }
    },

    /** After sleep the model may have been unloaded and Ollama may have restarted. */
    async onWake() {
      this.clearRuntimeCheck();
      await this.refreshRuntime();
      void this.prepare(true);
    },

    pickModel(preferred: string | null) {
      const names = this.models.map((m) => m.name);
      if (preferred && names.includes(preferred)) {
        this.selectedModel = preferred;
      } else if (!names.includes(this.selectedModel)) {
        const primary = this.primaryModel;
        this.selectedModel = primary && names.includes(primary) ? primary : (names[0] ?? "");
      }
    },

    async loadState() {
      const client = currentApiClient();
      if (client === null) return;
      const state = await client.assistantState();
      this.session = state.session;
      this.context = state.context;
      this.activeFrom = state.active_from_timeline_seq;
      if (state.session) this.pickModel(state.session.model);
    },

    async loadLatest() {
      const client = currentApiClient();
      if (client === null) return;
      this.loadingMessages = true;
      try {
        const [page] = await Promise.all([client.timeline(null, PAGE), this.loadState()]);
        this.messages = byTimeline(page.messages);
        this.hasOlder = page.has_more;
        loadedEpoch = connectionEpoch();
      } catch (error) {
        this.errorCode = error instanceof ApiError ? error.code : "internal_error";
      } finally {
        this.loadingMessages = false;
      }
    },

    async loadOlder() {
      const client = currentApiClient();
      const oldest = this.messages[0];
      if (client === null || !oldest || this.loadingMessages) return;
      this.loadingMessages = true;
      try {
        const page = await client.timeline(oldest.timeline_seq, PAGE);
        this.messages = byTimeline([...page.messages, ...this.messages]);
        this.hasOlder = page.has_more;
      } catch (error) {
        this.errorCode = error instanceof ApiError ? error.code : "internal_error";
      } finally {
        this.loadingMessages = false;
      }
    },

    /** Ask the backend to warm the model's prompt cache for the active session. */
    async prepare(force = false) {
      const client = currentApiClient();
      if (client === null || this.runtime?.available !== true || this.selectedModel === "") return;
      if (this.busy) return;
      const now = Date.now();
      if (!force && now - lastPrepared < PREPARE_INTERVAL_MS) return;
      lastPrepared = now;
      try {
        const result = await client.prepare(this.selectedModel);
        if (result.state === "warming" || result.state === "compacting") this.pollActivity();
      } catch {
        /* warming is an optimization; the turn reports real errors */
      }
    },

    /** Called on composer input: re-warm if the cache may have gone cold meanwhile. */
    composerActivity() {
      void this.prepare();
    },

    pollActivity() {
      const client = currentApiClient();
      if (client === null || activityTimer !== null) return;
      const tick = async () => {
        activityTimer = null;
        try {
          const activity = await client.activity();
          this.background = activity.background;
          if (activity.background !== null) {
            activityTimer = setTimeout(() => void tick(), ACTIVITY_POLL_MS);
          }
        } catch {
          this.background = null;
        }
      };
      activityTimer = setTimeout(() => void tick(), 0);
    },

    replaceMessage(message: Message) {
      this.messages = byTimeline([...this.messages.filter((m) => m.id !== message.id), message]);
    },

    /** Returns false if the backend refused the message before storing it (keep the draft). */
    async send(text: string): Promise<boolean> {
      const client = currentApiClient();
      const content = text.trim();
      if (client === null || content === "" || !this.canSend) return false;
      const clientId = newClientId();
      this.phase = "sending";
      this.errorCode = null;
      this.turn = { clientId, stage: "waiting", cache: null, contextTokens: null, trimmed: null };
      controller = new AbortController();
      let started = false;
      let assistantId: string | null = null;
      const onEvent = (event: TurnEvent) => {
        const turn = this.turn;
        if (turn === null || turn.clientId !== clientId) return;
        switch (event.type) {
          case "start":
            started = true;
            assistantId = event.assistant_message.id;
            this.session = event.conversation;
            if (event.created || this.activeFrom === null) {
              this.activeFrom = event.user_message.timeline_seq;
            }
            this.messages = byTimeline([...this.messages, event.user_message, event.assistant_message]);
            break;
          case "status":
            turn.stage = event.stage;
            if (event.cache !== undefined) turn.cache = event.cache;
            if (event.context_tokens !== undefined) turn.contextTokens = event.context_tokens;
            if (event.stage === "context_trimmed") turn.trimmed = event.omitted ?? null;
            break;
          case "delta": {
            turn.stage = "generating";
            this.phase = this.phase === "cancelling" ? "cancelling" : "streaming";
            const reply = this.messages.find((m) => m.id === assistantId);
            if (reply) reply.content += event.text;
            break;
          }
          case "done":
            this.replaceMessage(event.message);
            break;
          case "cancelled":
            if (event.message) this.replaceMessage(event.message);
            break;
          case "error":
            if (event.assistant_message) this.replaceMessage(event.assistant_message);
            this.errorCode = event.code;
            break;
        }
      };
      try {
        await client.submitTurn(
          { client_id: clientId, content, model: this.selectedModel },
          onEvent,
          controller.signal,
        );
        return true;
      } catch (error) {
        const code = error instanceof ApiError ? error.code : "internal_error";
        if (!started) {
          this.errorCode = code;
          return false;
        }
        // The stream broke after the message was stored: keep the partial reply visible as
        // interrupted, then show what the backend saved (if it is reachable).
        if (code !== "llm_cancelled") this.errorCode = code;
        const reply = this.messages.find((m) => m.id === assistantId);
        if (reply && reply.status === "streaming") reply.status = "interrupted";
        if (currentApiClient() === client) await this.loadLatest();
        return true;
      } finally {
        controller = null;
        this.phase = "idle"; // before clearing the turn: no transient state in between
        this.turn = null;
        void this.refreshAfterTurn();
      }
    },

    async cancel() {
      const client = currentApiClient();
      const turn = this.turn;
      if (client === null || turn === null) return;
      this.phase = "cancelling";
      const clientId = turn.clientId;
      try {
        await client.cancelTurn(clientId);
      } catch {
        /* fall back to closing the stream below */
      }
      setTimeout(() => {
        if (this.turn?.clientId === clientId) controller?.abort();
      }, CANCEL_GRACE_MS);
    },

    async refreshAfterTurn() {
      const client = currentApiClient();
      if (client === null) return;
      try {
        const status = await client.llmStatus();
        this.runtime = status.runtime;
        this.loaded = status.loaded;
        await this.loadState();
      } catch {
        /* informative only */
      }
    },

    stop() {
      controller?.abort();
      if (activityTimer !== null) clearTimeout(activityTimer);
      activityTimer = null;
      this.clearRuntimeCheck();
      lastPrepared = 0;
      loadedEpoch = -1;
    },
  },
});
