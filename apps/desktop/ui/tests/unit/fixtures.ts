import { vi } from "vitest";
import type { ApiClient, AssistantStateResponse, Conversation, Message } from "@/api/client";
import type { BackendConnection, Platform } from "@/platform/tauri";

export const TOKEN = "a".repeat(64);

export function connection(overrides: Partial<BackendConnection> = {}): BackendConnection {
  return {
    phase: "ready",
    port: 51234,
    token: TOKEN,
    errorCode: null,
    recoveryPending: false,
    profile: "dev",
    dataDir: "/tmp/lazis/data.noindex",
    logDir: "/tmp/lazis/logs",
    fileVault: "on",
    ...overrides,
  };
}

export const statusFixture = {
  backend: {
    pid: 4242,
    started_at: "2026-10-17T04:00:00.000Z",
    uptime_seconds: 125,
    peak_rss_bytes: 48 * 1024 * 1024,
    python_version: "3.13.16",
    platform: "macOS-27.0.1",
    machine: "arm64",
  },
  database: {
    state: "ready" as const,
    encrypted: true,
    encryption_verified: true,
    cipher_version: "4.19.0 community",
    cipher_provider: "openssl",
    sqlite_version: "3.53.4",
    schema_version: 2,
    journal_mode: "wal",
    integrity: "ok" as const,
    size_bytes: 4096,
    instance_id: "01M54261R8KT1K0H05YJQSQXJF",
    created_at: "2026-10-17T04:00:00.000Z",
  },
  privacy: {
    network_egress: "disabled" as const,
    research_mode: "offline_only" as const,
    microphone: "off" as const,
    voice_enabled: false,
    os_network_sandbox: "enforced" as const,
  },
  ai: { configured: false, provider: "ollama", available_from_phase: "P2" },
};

export const infoFixture = {
  name: "LAZIS",
  version: "0.1.0",
  api_version: "v1",
  phase: "P3",
  environment: "development",
  python_version: "3.13.16",
};

export const settingsFixture = {
  environment: "development",
  data_dir: "/tmp/lazis/data.noindex",
  log_dir: "/tmp/lazis/logs",
  log_level: "INFO",
  research_mode: "offline_only",
  network_egress_enabled: false,
  voice_enabled: false,
  voice_interaction_mode: "push_to_talk",
  models_provider: "ollama",
  models_primary_model: null,
  models_context_short: 4096,
  models_context_normal: 8192,
  models_context_long: 16384,
  models_keep_alive: "10m",
  backups_keep: 10,
  max_request_bytes: 65536,
};

export const modelFixture = {
  name: "qwen3.5:9b-q4_K_M",
  digest: "56671c2ab938",
  size_bytes: 6_600_000_000,
  family: "qwen35",
  parameter_size: "9.0B",
  quantization: "Q4_K_M",
  format: "gguf",
};

export const llmStatusFixture = {
  runtime: { available: true, runtime: "ollama", version: "0.40.4", error_code: null },
  loaded: [],
  primary_model: null,
  cloud_inference: "disabled" as const,
};

export const MODEL = modelFixture.name;

export function conversationFixture(overrides: Partial<Conversation> = {}): Conversation {
  return {
    id: "01M558Q8A5R4V2Y7K0J3H6N9TB",
    title: "Haftalık plan",
    title_source: "auto",
    model: MODEL,
    status: "active",
    message_count: 2,
    created_at: "2026-10-17T11:00:00.000Z",
    updated_at: "2026-10-17T11:05:00.000Z",
    ...overrides,
  };
}

export function messageFixture(
  seq: number,
  role: "user" | "assistant",
  content: string,
  overrides: Partial<Message> = {},
): Message {
  return {
    id: `01M558Q8A5R4V2Y7K0J3H6M${String(seq).padStart(3, "0")}`,
    conversation_id: conversationFixture().id,
    seq,
    role,
    content,
    status: "complete",
    client_id: null,
    reply_to: null,
    model: MODEL,
    error_code: null,
    created_at: "2026-10-17T11:00:00.000Z",
    completed_at: "2026-10-17T11:00:01.000Z",
    timeline_seq: seq,
    channel: "text",
    metrics: role === "assistant" ? { ttft_ms: 450, total_ms: 2000, prompt_tokens: 600, output_tokens: 40 } : null,
    ...overrides,
  };
}

export function assistantFixture(overrides: Partial<AssistantStateResponse> = {}): AssistantStateResponse {
  return {
    session: conversationFixture(),
    context: {
      strategy: "full",
      context_version: 1,
      window_start_seq: 1,
      estimated_tokens: 700,
      anchored: true,
      omitted: null,
      summary: null,
      num_ctx: 16384,
      hard_limit: 13721,
      compact_at: 6144,
      cache: "warm",
      background: null,
    },
    timeline_messages: 0,
    active_from_timeline_seq: 1,
    ...overrides,
  };
}

export function fakeClient(overrides: Partial<ApiClient> = {}): ApiClient {
  return {
    health: vi.fn().mockResolvedValue({ status: "ok", version: "0.1.0", checks: {} }),
    appInfo: vi.fn().mockResolvedValue(infoFixture),
    systemStatus: vi.fn().mockResolvedValue(statusFixture),
    settings: vi.fn().mockResolvedValue(settingsFixture),
    llmStatus: vi.fn().mockResolvedValue(llmStatusFixture),
    models: vi.fn().mockResolvedValue({ models: [modelFixture] }),
    chatStream: vi.fn().mockResolvedValue(undefined),
    cancelChat: vi.fn().mockResolvedValue(true),
    assistantState: vi.fn().mockResolvedValue(
      assistantFixture({ session: null, context: null, active_from_timeline_seq: null }),
    ),
    timeline: vi.fn().mockResolvedValue({ messages: [], has_more: false }),
    submitTurn: vi.fn().mockResolvedValue(undefined),
    cancelTurn: vi.fn().mockResolvedValue(true),
    prepare: vi.fn().mockResolvedValue({ state: "warm", model_loaded: true, context_tokens: 700 }),
    activity: vi.fn().mockResolvedValue({
      turn: null,
      background: null,
      cached_conversation_id: null,
      pending_compaction: [],
    }),
    ...overrides,
  };
}

export function fakePlatform(initial: BackendConnection, overrides: Partial<Platform> = {}): Platform {
  return {
    getConnection: vi.fn().mockResolvedValue(initial),
    onConnectionChanged: vi.fn().mockResolvedValue(() => undefined),
    retryBackend: vi.fn().mockResolvedValue(connection()),
    revealRecoveryCode: vi.fn().mockResolvedValue("LZR1-TEST0-CODE0"),
    acknowledgeRecovery: vi.fn().mockResolvedValue(connection({ recoveryPending: false })),
    restoreFromRecoveryCode: vi.fn().mockResolvedValue(connection()),
    ...overrides,
  };
}
