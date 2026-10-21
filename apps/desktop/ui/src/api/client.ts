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
export type AssistantStateResponse = Schemas["AssistantStateResponse"];
export type Message = Schemas["MessageModel"];
export type TimelinePageResponse = Schemas["TimelinePageResponse"];
export type TurnSubmitRequest = Schemas["TurnSubmitRequest"];
export type PrepareResponse = Schemas["PrepareResponse"];
export type ActivityResponse = Schemas["ActivityResponse"];
export type DiagnosticsResponse = Schemas["DiagnosticsResponse"];
export type MemoryRecord = Schemas["MemoryRecordModel"];
export type MemoryListResponse = Schemas["MemoryListResponse"];
export type MemoryRecordDetail = Schemas["MemoryRecordDetailResponse"];
export type MemoryEntity = Schemas["MemoryEntityModel"];
export type MemoryEntityDetail = Schemas["MemoryEntityDetailResponse"];
export type MemoryInboxItem = Schemas["MemoryInboxItemModel"];
export type MemoryOverview = Schemas["MemoryOverviewResponse"];
export type MemoryPredicate = Schemas["PredicateModel"];
export type MemoryCreateRequest = Schemas["MemoryCreateRequest"];
export type MemoryApplyResult = Schemas["ApplyResultResponse"];
export type MemoryForgetResult = Schemas["ForgetResultResponse"];
export type ImportPreview = Schemas["ImportPreviewResponse"];
export type ImportItem = Schemas["ImportItemModel"];
export type RelationshipType = Schemas["RelationshipTypeModel"];
export type Relationship = Schemas["RelationshipModel"];
export type RelationshipDetail = Schemas["RelationshipDetailResponse"];
export type RelationshipCreateRequest = Schemas["RelationshipCreateRequest"];
export type RelationshipEditRequest = Schemas["RelationshipEditRequest"];
export type RelationshipWriteResult = Schemas["RelationshipWriteResponse"];
export type GraphNeighbourhood = Schemas["GraphNeighbourhoodResponse"];
export type GraphPath = Schemas["GraphPathModel"];
export type BootstrapBatch = Schemas["BootstrapBatchModel"];
export type BootstrapPreview = Schemas["BootstrapPreviewResponse"];
export type BootstrapPerson = Schemas["BootstrapPersonModel"];
export type BootstrapItem = Schemas["BootstrapItemModel"];
export type BootstrapSummary = Schemas["BootstrapSummaryModel"];
export type BootstrapDecisions = Schemas["BootstrapDecisionsRequest"];
export type BootstrapUndoPlan = Schemas["BootstrapUndoPlanResponse"];
export type BootstrapUndoResult = Schemas["BootstrapUndoResponse"];
export type BootstrapApplyResult = Schemas["BootstrapApplyResponse"];

export interface MemoryQuery {
  q?: string | undefined;
  kind?: string | undefined;
  subject_id?: string | undefined;
  user_only?: boolean | undefined;
  status?: "active" | "superseded" | "all";
  limit?: number;
  offset?: number;
}
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
  | "memory"
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
    /** What the backend may show about the refusal (a JSON file's broken line). */
    readonly details: Record<string, number | string | string[]> | null = null,
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
  /** The one assistant: active technical session, its context, where it starts in the timeline. */
  assistantState(): Promise<AssistantStateResponse>;
  /** A page of the single timeline (all sessions), oldest first; `before` = timeline_seq. */
  timeline(before?: number | null, limit?: number): Promise<TimelinePageResponse>;
  /** Streams turn events until done/cancelled/error. Rejects with ApiError before the
   *  stream starts (busy, duplicate, model missing, runtime down, validation). */
  submitTurn(
    body: TurnSubmitRequest,
    onEvent: (event: TurnEvent) => void,
    signal?: AbortSignal,
  ): Promise<void>;
  cancelTurn(clientId: string): Promise<boolean>;
  // ----- personal memory (Phase 6) -----
  memoryOverview(): Promise<MemoryOverview>;
  memoryPredicates(): Promise<MemoryPredicate[]>;
  memoryRecords(query?: MemoryQuery): Promise<MemoryListResponse>;
  memoryRecord(id: string): Promise<MemoryRecordDetail>;
  addMemory(body: MemoryCreateRequest): Promise<MemoryApplyResult>;
  editMemory(id: string, value: string, statement: string): Promise<MemoryRecord>;
  forgetMemory(id: string): Promise<MemoryForgetResult>;
  memoryEntities(kind?: string, q?: string): Promise<MemoryEntity[]>;
  memoryEntity(id: string): Promise<MemoryEntityDetail>;
  editEntity(id: string, body: { name?: string; relation?: string | null; description?: string | null }): Promise<MemoryEntity>;
  mergeEntities(keepId: string, otherId: string): Promise<MemoryEntity>;
  forgetEntity(id: string): Promise<MemoryForgetResult>;
  memoryInbox(): Promise<MemoryInboxItem[]>;
  // ----- relationship graph (Phase 7) -----
  relationshipTypes(): Promise<RelationshipType[]>;
  entityRelationships(entityId: string): Promise<Relationship[]>;
  relationship(id: string): Promise<RelationshipDetail>;
  addRelationship(body: RelationshipCreateRequest): Promise<RelationshipWriteResult>;
  editRelationship(id: string, body: RelationshipEditRequest): Promise<Relationship>;
  forgetRelationship(id: string): Promise<MemoryForgetResult>;
  graphNeighbourhood(entityId: string, depth: number, past?: boolean): Promise<GraphNeighbourhood>;
  graphPaths(fromId: string, toId: string): Promise<GraphPath[]>;
  resolveInbox(id: string, choice: string): Promise<MemoryApplyResult>;
  importPreview(format: "json" | "text", content: string): Promise<ImportPreview>;
  importApply(batchId: string, selections: Record<string, string>): Promise<MemoryApplyResult>;
  importDiscard(batchId: string): Promise<void>;
  // ----- personal knowledge import (Phase 8): nothing is approved until the user says so -----
  bootstrapAnalyze(fileName: string, contentBase64: string): Promise<BootstrapBatch>;
  bootstrapHistory(): Promise<BootstrapBatch[]>;
  bootstrapImport(importId: string): Promise<BootstrapPreview>;
  bootstrapCancel(importId: string): Promise<BootstrapBatch>;
  bootstrapRetry(importId: string): Promise<BootstrapBatch>;
  bootstrapDecide(importId: string, body: BootstrapDecisions): Promise<BootstrapPreview>;
  bootstrapApply(importId: string): Promise<BootstrapApplyResult>;
  bootstrapUndoPlan(importId: string): Promise<BootstrapUndoPlan>;
  bootstrapUndo(importId: string, restore: string[]): Promise<BootstrapUndoResult>;
  bootstrapDiscard(importId: string): Promise<BootstrapBatch>;
  prepare(model: string): Promise<PrepareResponse>;
  activity(): Promise<ActivityResponse>;
  /** Model, runtime, last-turn timings and pre-warm state; never message content. */
  diagnostics(): Promise<DiagnosticsResponse>;
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
      const { code, message, recoverable, details } = body.error;
      return new ApiError(response.status, code, message, recoverable, details ?? null);
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

  async function send<T>(
    method: "POST" | "PATCH" | "DELETE",
    path: string,
    payload?: unknown,
    timeout = timeoutMs,
  ): Promise<T> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
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
  const enc = encodeURIComponent;
  const queryString = (params: Record<string, string | number | boolean | undefined>) => {
    const parts = Object.entries(params)
      .filter(([, v]) => v !== undefined && v !== "")
      .map(([k, v]) => `${k}=${enc(String(v))}`);
    return parts.length ? `?${parts.join("&")}` : "";
  };

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
        const { code, message, recoverable, details } = body.error;
        throw new ApiError(response.status, code, message, recoverable, details ?? null);
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
    assistantState: () => get<AssistantStateResponse>("/assistant"),
    timeline: (before, limit = 50) =>
      get<TimelinePageResponse>(`/timeline?limit=${limit}` + (before ? `&before=${before}` : "")),
    submitTurn: (body, onEvent, signal) => streamNdjson<TurnEvent>("/turns", body, onEvent, signal),
    cancelTurn: async (clientId: string) =>
      (await post<{ cancelled: boolean }>("/turns/cancel", { client_id: clientId })).cancelled,
    prepare: (model) => post<PrepareResponse>("/chat/prepare", { model }),
    activity: () => get<ActivityResponse>("/chat/activity"),
    diagnostics: () => get<DiagnosticsResponse>("/diagnostics"),
    memoryOverview: () => get<MemoryOverview>("/memory/overview"),
    memoryPredicates: async () =>
      (await get<{ predicates: MemoryPredicate[] }>("/memory/predicates")).predicates,
    memoryRecords: (query = {}) => get<MemoryListResponse>(`/memory/records${queryString({ ...query })}`),
    memoryRecord: (id) => get<MemoryRecordDetail>(`/memory/records/${enc(id)}`),
    addMemory: (body) => post<MemoryApplyResult>("/memory/records", body),
    editMemory: (id, value, statement) =>
      send<MemoryRecord>("PATCH", `/memory/records/${enc(id)}`, { value, statement }),
    forgetMemory: (id) => send<MemoryForgetResult>("DELETE", `/memory/records/${enc(id)}`),
    memoryEntities: async (kind, q) =>
      (await get<{ entities: MemoryEntity[] }>(`/memory/entities${queryString({ kind, q })}`)).entities,
    memoryEntity: (id) => get<MemoryEntityDetail>(`/memory/entities/${enc(id)}`),
    editEntity: (id, body) => send<MemoryEntity>("PATCH", `/memory/entities/${enc(id)}`, body),
    mergeEntities: (keepId, otherId) =>
      post<MemoryEntity>(`/memory/entities/${enc(keepId)}/merge`, { other_id: otherId }),
    forgetEntity: (id) => send<MemoryForgetResult>("DELETE", `/memory/entities/${enc(id)}?confirm=true`),
    memoryInbox: async () => (await get<{ items: MemoryInboxItem[] }>("/memory/inbox")).items,
    relationshipTypes: async () =>
      (await get<{ types: RelationshipType[] }>("/memory/relationship-types")).types,
    entityRelationships: async (entityId) =>
      (await get<{ relationships: Relationship[] }>(`/memory/entities/${enc(entityId)}/relationships`))
        .relationships,
    relationship: (id) => get<RelationshipDetail>(`/memory/relationships/${enc(id)}`),
    addRelationship: (body) => post<RelationshipWriteResult>("/memory/relationships", body),
    editRelationship: (id, body) => send<Relationship>("PATCH", `/memory/relationships/${enc(id)}`, body),
    forgetRelationship: (id) => send<MemoryForgetResult>("DELETE", `/memory/relationships/${enc(id)}`),
    graphNeighbourhood: (entityId, depth, past = false) =>
      get<GraphNeighbourhood>(
        `/memory/graph/neighbourhood/${enc(entityId)}${queryString({ depth, past: past || undefined })}`,
      ),
    graphPaths: async (fromId, toId) =>
      (await get<{ paths: GraphPath[] }>(`/memory/graph/paths${queryString({ from: fromId, to: toId })}`)).paths,
    resolveInbox: (id, choice) => post<MemoryApplyResult>(`/memory/inbox/${enc(id)}/resolve`, { choice }),
    // A text import runs the local model over the text: allow it minutes, not seconds.
    importPreview: (format, content) =>
      send<ImportPreview>("POST", "/memory/import/preview", { format, content }, 300_000),
    importApply: (batchId, selections) =>
      post<MemoryApplyResult>(`/memory/import/${enc(batchId)}/apply`, { selections }),
    importDiscard: async (batchId) => {
      await send<unknown>("DELETE", `/memory/import/${enc(batchId)}`);
    },
    // The file (up to 1 MB) goes up once; the model reads it in the background afterwards.
    bootstrapAnalyze: (fileName, contentBase64) =>
      send<BootstrapBatch>("POST", "/memory/bootstrap/analyze",
        { file_name: fileName, content_base64: contentBase64 }, 60_000),
    bootstrapHistory: async () =>
      (await get<{ batches: BootstrapBatch[] }>("/memory/bootstrap")).batches,
    bootstrapImport: (importId) => get<BootstrapPreview>(`/memory/bootstrap/${enc(importId)}`),
    bootstrapCancel: (importId) =>
      send<BootstrapBatch>("POST", `/memory/bootstrap/${enc(importId)}/cancel`, undefined, 20_000),
    bootstrapRetry: (importId) =>
      post<BootstrapBatch>(`/memory/bootstrap/${enc(importId)}/retry`, undefined),
    bootstrapDecide: (importId, body) =>
      post<BootstrapPreview>(`/memory/bootstrap/${enc(importId)}/decisions`, body),
    // One transaction; a large import may take a few seconds.
    bootstrapApply: (importId) =>
      send<BootstrapApplyResult>("POST", `/memory/bootstrap/${enc(importId)}/apply`, undefined, 60_000),
    bootstrapUndoPlan: (importId) =>
      get<BootstrapUndoPlan>(`/memory/bootstrap/${enc(importId)}/undo-plan`),
    bootstrapUndo: (importId, restore) =>
      send<BootstrapUndoResult>("POST", `/memory/bootstrap/${enc(importId)}/undo`, { restore }, 60_000),
    bootstrapDiscard: (importId) =>
      send<BootstrapBatch>("DELETE", `/memory/bootstrap/${enc(importId)}`),
  };
}
