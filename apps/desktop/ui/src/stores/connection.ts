/**
 * Connection state for the desktop UI.
 *
 * The Rust shell owns the backend lifecycle and reports its phase; this store turns that into
 * UI state, polls health while connected, and records diagnostic events. The session token is
 * kept only inside the API client closure — never in reactive (devtools-visible) state.
 */
import { defineStore } from "pinia";
import {
  ApiError,
  createApiClient,
  type ApiClient,
  type ApiConnection,
  type AppInfoResponse,
  type EffectiveSettingsResponse,
  type HealthResponse,
  type SystemStatusResponse,
} from "@/api/client";
import { platformErrorCode, type BackendConnection, type Platform } from "@/platform/tauri";

export type UiPhase =
  | "initializing"
  | "starting"
  | "connected"
  | "disconnected"
  | "backend_failed"
  | "needs_recovery";

export interface DiagnosticEvent {
  at: string;
  level: "info" | "error";
  code: string;
}

export interface ConnectionDeps {
  platform: Platform;
  clientFactory?: (connection: ApiConnection) => ApiClient;
  pollMs?: number;
  now?: () => Date;
}

type PublicConnection = Omit<BackendConnection, "token">;

const MAX_EVENTS = 50;
let deps: Required<ConnectionDeps> | null = null;
let client: ApiClient | null = null;
let pollTimer: ReturnType<typeof setInterval> | null = null;
let unlisten: (() => void) | null = null;

export const useConnectionStore = defineStore("connection", {
  state: () => ({
    phase: "initializing" as UiPhase,
    errorCode: null as string | null,
    connection: null as PublicConnection | null,
    info: null as AppInfoResponse | null,
    status: null as SystemStatusResponse | null,
    settings: null as EffectiveSettingsResponse | null,
    health: null as HealthResponse | null,
    lastCheckedAt: null as string | null,
    consecutiveFailures: 0,
    events: [] as DiagnosticEvent[],
  }),

  getters: {
    recoveryPending: (state) => state.connection?.recoveryPending === true,
  },

  actions: {
    record(level: DiagnosticEvent["level"], code: string) {
      const at = (deps?.now() ?? new Date()).toISOString();
      this.events = [{ at, level, code }, ...this.events].slice(0, MAX_EVENTS);
    },

    async start(options: ConnectionDeps) {
      deps = {
        clientFactory: (c) => createApiClient(c),
        pollMs: 5000,
        now: () => new Date(),
        ...options,
      };
      unlisten = await deps.platform.onConnectionChanged((c) => void this.applyConnection(c));
      try {
        await this.applyConnection(await deps.platform.getConnection());
      } catch (error) {
        this.fail(platformErrorCode(error));
      }
    },

    stop() {
      this.stopPolling();
      unlisten?.();
      unlisten = null;
      client = null;
    },

    fail(code: string) {
      this.stopPolling();
      client = null;
      this.phase = "backend_failed";
      this.errorCode = code;
      this.record("error", code);
    },

    async applyConnection(connection: BackendConnection) {
      const { token, ...visible } = connection;
      this.connection = visible;
      switch (connection.phase) {
        case "starting":
          this.stopPolling();
          this.phase = "starting";
          this.errorCode = null;
          return;
        case "needs_recovery":
          this.stopPolling();
          this.phase = "needs_recovery";
          this.errorCode = connection.errorCode;
          this.record("error", connection.errorCode ?? "database_key_invalid");
          return;
        case "failed":
          this.fail(connection.errorCode ?? "backend_start_failed");
          return;
        case "stopped":
          this.stopPolling();
          this.phase = "disconnected";
          return;
        case "ready": {
          if (connection.port === null || token === null || deps === null) {
            this.fail("backend_start_failed");
            return;
          }
          client = deps.clientFactory({ port: connection.port, token });
          await this.refreshAll();
          return;
        }
      }
    },

    async refreshAll() {
      if (client === null) return;
      try {
        const [info, status, settings, health] = await Promise.all([
          client.appInfo(),
          client.systemStatus(),
          client.settings(),
          client.health(),
        ]);
        this.info = info;
        this.status = status;
        this.settings = settings;
        this.health = health;
        this.markHealthy();
        this.record("info", "connected");
        this.startPolling();
      } catch (error) {
        this.handleRequestFailure(error);
      }
    },

    async poll() {
      if (client === null) return;
      try {
        const [health, status] = await Promise.all([client.health(), client.systemStatus()]);
        this.health = health;
        this.status = status;
        this.markHealthy();
      } catch (error) {
        this.handleRequestFailure(error);
      }
    },

    markHealthy() {
      this.phase = "connected";
      this.errorCode = null;
      this.consecutiveFailures = 0;
      this.lastCheckedAt = (deps?.now() ?? new Date()).toISOString();
    },

    handleRequestFailure(error: unknown) {
      const code = error instanceof ApiError ? error.code : "internal_error";
      this.consecutiveFailures += 1;
      this.record("error", code);
      if (this.consecutiveFailures >= 2 || this.phase !== "connected") {
        this.phase = "disconnected";
        this.errorCode = code;
        void this.syncWithShell();
      }
    },

    /** After repeated failures, ask the shell whether the backend is still alive. */
    async syncWithShell() {
      if (deps === null) return;
      try {
        const connection = await deps.platform.getConnection();
        if (connection.phase !== "ready") await this.applyConnection(connection);
      } catch (error) {
        this.fail(platformErrorCode(error));
      }
    },

    startPolling() {
      if (pollTimer !== null || deps === null) return;
      pollTimer = setInterval(() => void this.poll(), deps.pollMs);
    },

    stopPolling() {
      if (pollTimer !== null) clearInterval(pollTimer);
      pollTimer = null;
    },

    async retry() {
      if (deps === null) return;
      this.phase = "starting";
      this.errorCode = null;
      try {
        await this.applyConnection(await deps.platform.retryBackend());
      } catch (error) {
        this.fail(platformErrorCode(error));
      }
    },

    async revealRecoveryCode(): Promise<string> {
      if (deps === null) throw new Error("not started");
      return deps.platform.revealRecoveryCode();
    },

    async acknowledgeRecovery() {
      if (deps === null) return;
      const connection = await deps.platform.acknowledgeRecovery();
      this.connection = { ...(this.connection ?? connection), recoveryPending: false };
      this.record("info", "recovery_acknowledged");
    },

    /** Throws the shell's error code (e.g. recovery_code_invalid) for the form to display. */
    async restore(code: string) {
      if (deps === null) return;
      try {
        await this.applyConnection(await deps.platform.restoreFromRecoveryCode(code));
      } catch (error) {
        const errorCode = platformErrorCode(error);
        this.record("error", errorCode);
        throw new Error(errorCode);
      }
    },
  },
});
