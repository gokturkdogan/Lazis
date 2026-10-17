/**
 * Ephemeral Phase 2 chat with a local model.
 *
 * Privacy: the conversation exists only in this store's memory. It is never written to disk,
 * localStorage or the database, never logged, and disappears when the app closes or the user
 * clears it. Persistent conversations arrive with the conversation engine (Phase 3).
 */
import { defineStore } from "pinia";
import { ApiError, type ChatEvent, type ChatMetrics, type LlmStatusResponse, type ModelListResponse } from "@/api/client";
import { currentApiClient } from "@/stores/connection";

export type ChatRole = "user" | "assistant";
export type EntryState = "streaming" | "done" | "cancelled" | "error";

export interface ChatEntry {
  id: number;
  role: ChatRole;
  content: string;
  state: EntryState;
  errorCode: string | null;
  metrics: ChatMetrics | null;
}

export type ChatPhase = "idle" | "waiting" | "streaming" | "cancelling";
type Runtime = LlmStatusResponse["runtime"];
type Model = ModelListResponse["models"][number];
type Loaded = LlmStatusResponse["loaded"][number];

let controller: AbortController | null = null;
let activeRequest: string | null = null;
let nextId = 1;

function newRequestId(): string {
  const random = globalThis.crypto?.randomUUID?.();
  return random ?? `req-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

export const useChatStore = defineStore("chat", {
  state: () => ({
    runtime: null as Runtime | null,
    loaded: [] as Loaded[],
    models: [] as Model[],
    inventoryLoaded: false,
    selectedModel: "",
    messages: [] as ChatEntry[],
    phase: "idle" as ChatPhase,
    errorCode: null as string | null,
  }),

  getters: {
    busy: (state) => state.phase !== "idle",
    canSend: (state) =>
      state.phase === "idle" && state.runtime?.available === true && state.selectedModel !== "",
  },

  actions: {
    async refresh() {
      const client = currentApiClient();
      if (client === null) return;
      try {
        const status = await client.llmStatus();
        this.runtime = status.runtime;
        this.loaded = status.loaded;
        if (!status.runtime.available) {
          this.models = [];
          this.errorCode = status.runtime.error_code ?? "llm_unavailable";
          return;
        }
        this.models = (await client.models()).models;
        this.errorCode = null;
        const names = this.models.map((m) => m.name);
        if (!names.includes(this.selectedModel)) {
          const preferred = status.primary_model;
          this.selectedModel = preferred && names.includes(preferred) ? preferred : (names[0] ?? "");
        }
      } catch (error) {
        this.errorCode = error instanceof ApiError ? error.code : "internal_error";
      } finally {
        this.inventoryLoaded = true;
      }
    },

    async send(text: string) {
      const client = currentApiClient();
      const content = text.trim();
      if (client === null || content === "" || !this.canSend) return;
      const history = this.messages
        .filter((m) => m.role === "user" || (m.state === "done" && m.content !== ""))
        .map((m) => ({ role: m.role, content: m.content }));
      this.messages.push(entry("user", content, "done"));
      this.messages.push(entry("assistant", "", "streaming"));
      const reply = this.messages[this.messages.length - 1] as ChatEntry;
      const requestId = newRequestId();
      activeRequest = requestId;
      controller = new AbortController();
      this.phase = "waiting";
      this.errorCode = null;
      const onEvent = (event: ChatEvent) => {
        if (event.type === "delta") {
          reply.content += event.text;
          if (this.phase === "waiting") this.phase = "streaming";
        } else if (event.type === "done") {
          reply.state = "done";
          reply.metrics = event.metrics;
        } else if (event.type === "error") {
          reply.state = event.code === "llm_cancelled" ? "cancelled" : "error";
          reply.errorCode = event.code;
        }
      };
      try {
        await client.chatStream(
          {
            model: this.selectedModel,
            request_id: requestId,
            messages: [...history, { role: "user", content }],
          },
          onEvent,
          controller.signal,
        );
        if (reply.state === "streaming") {
          reply.state = "error";
          reply.errorCode = "llm_invalid_response";
        }
      } catch (error) {
        const code = error instanceof ApiError ? error.code : "internal_error";
        reply.state = code === "llm_cancelled" ? "cancelled" : "error";
        reply.errorCode = code;
      } finally {
        controller = null;
        activeRequest = null;
        this.phase = "idle";
        void this.refreshLoaded();
      }
    },

    async cancel() {
      const client = currentApiClient();
      if (activeRequest === null || client === null) return;
      this.phase = "cancelling";
      const requestId = activeRequest;
      try {
        await client.cancelChat(requestId);
      } catch {
        /* fall back to aborting the stream below */
      }
      // If the backend did not end the stream promptly, drop the connection: the backend
      // then stops the generation in the local runtime as well.
      setTimeout(() => {
        if (activeRequest === requestId) controller?.abort();
      }, 2000);
    },

    async refreshLoaded() {
      const client = currentApiClient();
      if (client === null) return;
      try {
        const status = await client.llmStatus();
        this.runtime = status.runtime;
        this.loaded = status.loaded;
      } catch {
        /* status is informative only */
      }
    },

    clear() {
      if (this.busy) return;
      this.messages = [];
    },
  },
});

function entry(role: ChatRole, content: string, state: EntryState): ChatEntry {
  return { id: nextId++, role, content, state, errorCode: null, metrics: null };
}
