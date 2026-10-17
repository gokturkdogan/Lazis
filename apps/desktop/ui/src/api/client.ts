/**
 * Typed client for the local LAZIS API (types generated from the backend's OpenAPI schema).
 * Every request carries the per-launch bearer token; errors are normalized to ApiError.
 */
import type { components } from "./schema";

type Schemas = components["schemas"];
export type HealthResponse = Schemas["HealthResponse"];
export type AppInfoResponse = Schemas["AppInfoResponse"];
export type SystemStatusResponse = Schemas["SystemStatusResponse"];
export type EffectiveSettingsResponse = Schemas["EffectiveSettingsResponse"];
export type LlmStatusResponse = Schemas["LlmStatusResponse"];
export type ModelListResponse = Schemas["ModelListResponse"];
export type ChatStreamRequest = Schemas["ChatStreamRequest"];
export type Conversation = Schemas["ConversationModel"];
export type ConversationListResponse = Schemas["ConversationListResponse"];
export type ConversationDetailResponse = Schemas["ConversationDetailResponse"];
export type Message = Schemas["MessageModel"];
export type MessagePageResponse = Schemas["MessagePageResponse"];
export type TurnSubmitRequest = Schemas["TurnSubmitRequest"];
export type PrepareResponse = Schemas["PrepareResponse"];
export type ActivityResponse = Schemas["ActivityResponse"];
export type DeleteConversationResponse = Schemas["DeleteConversationResponse"];
type ErrorResponse = Schemas["ErrorResponse"];

export interface ChatMetrics {
  ttft_ms: number | null;
  total_ms: number | null;
  load_ms: number | null;
  prompt_tokens: number | null;
  output_tokens: number | null;
  prefill_tps: number | null;
  decode_tps: number | null;
  done_reason: string | null;
}

/** One line of the NDJSON stream from POST /chat/stream. */
export type ChatEvent =
  | { type: "start"; request_id: string; model: string }
  | { type: "delta"; text: string }
  | { type: "done"; metrics: ChatMetrics }
  | { type: "error"; code: string; message: string };

/** Turn stages reported by the backend (real states, no synthetic progress). */
export type TurnStage =
  | "waiting"
  | "compacting"
  | "context_trimmed"
  | "loading_model"
  | "processing_context";

/** One line of the NDJSON stream from POST /turns. */
export type TurnEvent =
  | {
      type: "start";
      conversation: Conversation;
      created: boolean;
      user_message: Message;
      assistant_message: Message;
    }
  | {
      type: "status";
      stage: TurnStage;
      context_tokens?: number;
      cache?: "warm" | "cold";
      model?: string;
      omitted?: number[] | null;
    }
  | { type: "delta"; text: string }
  | {
      type: "done";
      message: Message;
      context: { estimated_tokens: number; prompt_tokens: number | null; strategy: string };
    }
  | { type: "cancelled"; message: Message | null }
  | { type: "error"; code: string; message: string; assistant_message: Message | null };

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    readonly userMessage: string,
    readonly recoverable: boolean,
  ) {
    super(code);
    this.name = "ApiError";
  }
}

export interface ApiConnection {
  port: number;
  token: string;
}

export interface ApiClient {
  health(): Promise<HealthResponse>;
  appInfo(): Promise<AppInfoResponse>;
  systemStatus(): Promise<SystemStatusResponse>;
  settings(): Promise<EffectiveSettingsResponse>;
  llmStatus(): Promise<LlmStatusResponse>;
  models(): Promise<ModelListResponse>;
  /** Streams events until done/error. Rejects with ApiError before the stream starts. */
  chatStream(
    body: ChatStreamRequest,
    onEvent: (event: ChatEvent) => void,
    signal?: AbortSignal,
  ): Promise<void>;
  cancelChat(requestId: string): Promise<boolean>;
  listConversations(cursor?: string | null): Promise<ConversationListResponse>;
  getConversation(id: string): Promise<ConversationDetailResponse>;
  listMessages(id: string, beforeSeq?: number | null, limit?: number): Promise<MessagePageResponse>;
  renameConversation(id: string, title: string): Promise<Conversation>;
  deleteConversation(id: string): Promise<DeleteConversationResponse>;
  /** Streams turn events until done/cancelled/error. Rejects with ApiError before the
   *  stream starts (busy, duplicate, model missing, runtime down, validation). */
  submitTurn(
    body: TurnSubmitRequest,
    onEvent: (event: TurnEvent) => void,
    signal?: AbortSignal,
  ): Promise<void>;
  cancelTurn(clientId: string): Promise<boolean>;
  prepare(conversationId: string | null, model: string): Promise<PrepareResponse>;
  activity(): Promise<ActivityResponse>;
}

function isErrorResponse(value: unknown): value is ErrorResponse {
  return (
    typeof value === "object" &&
    value !== null &&
    "error" in value &&
    typeof (value as { error: unknown }).error === "object"
  );
}

export function createApiClient(
  connection: ApiConnection,
  fetchImpl: typeof fetch = fetch,
  timeoutMs = 5000,
): ApiClient {
  const base = `http://127.0.0.1:${connection.port}/api/v1`;

  async function errorFrom(response: Response): Promise<ApiError> {
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      body = null;
    }
    if (isErrorResponse(body)) {
      const { code, message, recoverable } = body.error;
      return new ApiError(response.status, code, message, recoverable);
    }
    return new ApiError(response.status, "internal_error", "", false);
  }

  async function streamNdjson<E>(
    path: string,
    body: unknown,
    onEvent: (event: E) => void,
    signal?: AbortSignal,
  ): Promise<void> {
    let response: Response;
    try {
      response = await fetchImpl(`${base}${path}`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${connection.token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(body),
        signal: signal ?? null,
        cache: "no-store",
      });
    } catch {
      if (signal?.aborted) throw new ApiError(0, "llm_cancelled", "", true);
      throw new ApiError(0, "backend_unreachable", "", true);
    }
    if (!response.ok) throw await errorFrom(response);
    if (response.body === null) throw new ApiError(response.status, "llm_invalid_response", "", true);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    const emit = (line: string) => {
      if (!line.trim()) return;
      let event: E;
      try {
        event = JSON.parse(line) as E;
      } catch {
        throw new ApiError(response.status, "llm_invalid_response", "", true);
      }
      onEvent(event);
    };
    try {
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let index = buffer.indexOf("\n");
        while (index >= 0) {
          emit(buffer.slice(0, index));
          buffer = buffer.slice(index + 1);
          index = buffer.indexOf("\n");
        }
      }
      emit(buffer + decoder.decode());
    } catch (error) {
      if (error instanceof ApiError) throw error;
      if (signal?.aborted) throw new ApiError(0, "llm_cancelled", "", true);
      throw new ApiError(0, "backend_unreachable", "", true);
    }
  }

  async function send<T>(method: "POST" | "PATCH" | "DELETE", path: string, payload?: unknown): Promise<T> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    let response: Response;
    try {
      response = await fetchImpl(`${base}${path}`, {
        method,
        headers: {
          Authorization: `Bearer ${connection.token}`,
          "Content-Type": "application/json",
        },
        body: payload === undefined ? null : JSON.stringify(payload),
        signal: controller.signal,
        cache: "no-store",
      });
    } catch {
      throw new ApiError(0, "backend_unreachable", "", true);
    } finally {
      clearTimeout(timer);
    }
    if (!response.ok) throw await errorFrom(response);
    return (await response.json()) as T;
  }

  const post = <T>(path: string, payload: unknown) => send<T>("POST", path, payload);
  const id = (value: string) => encodeURIComponent(value);

  async function get<T>(path: string): Promise<T> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    let response: Response;
    try {
      response = await fetchImpl(`${base}${path}`, {
        method: "GET",
        headers: { Authorization: `Bearer ${connection.token}` },
        signal: controller.signal,
        cache: "no-store",
      });
    } catch {
      throw new ApiError(0, "backend_unreachable", "", true);
    } finally {
      clearTimeout(timer);
    }
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      body = null;
    }
    if (!response.ok) {
      if (isErrorResponse(body)) {
        const { code, message, recoverable } = body.error;
        throw new ApiError(response.status, code, message, recoverable);
      }
      throw new ApiError(response.status, "internal_error", "", false);
    }
    return body as T;
  }

  return {
    health: () => get<HealthResponse>("/health"),
    appInfo: () => get<AppInfoResponse>("/app/info"),
    systemStatus: () => get<SystemStatusResponse>("/system/status"),
    settings: () => get<EffectiveSettingsResponse>("/settings"),
    llmStatus: () => get<LlmStatusResponse>("/llm/status"),
    models: () => get<ModelListResponse>("/llm/models"),
    chatStream: (body, onEvent, signal) =>
      streamNdjson<ChatEvent>("/chat/stream", body, onEvent, signal),
    cancelChat: async (requestId: string) =>
      (await post<{ cancelled: boolean }>("/chat/cancel", { request_id: requestId })).cancelled,
    listConversations: (cursor) =>
      get<ConversationListResponse>(
        cursor ? `/conversations?limit=50&cursor=${encodeURIComponent(cursor)}` : "/conversations?limit=50",
      ),
    getConversation: (cid) => get<ConversationDetailResponse>(`/conversations/${id(cid)}`),
    listMessages: (cid, beforeSeq, limit = 50) =>
      get<MessagePageResponse>(
        `/conversations/${id(cid)}/messages?limit=${limit}` + (beforeSeq ? `&before_seq=${beforeSeq}` : ""),
      ),
    renameConversation: (cid, title) => send<Conversation>("PATCH", `/conversations/${id(cid)}`, { title }),
    deleteConversation: (cid) => send<DeleteConversationResponse>("DELETE", `/conversations/${id(cid)}`),
    submitTurn: (body, onEvent, signal) => streamNdjson<TurnEvent>("/turns", body, onEvent, signal),
    cancelTurn: async (clientId: string) =>
      (await post<{ cancelled: boolean }>("/turns/cancel", { client_id: clientId })).cancelled,
    prepare: (conversationId, model) =>
      post<PrepareResponse>("/chat/prepare", { conversation_id: conversationId, model }),
    activity: () => get<ActivityResponse>("/chat/activity"),
  };
}
