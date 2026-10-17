/**
 * Connection state for the desktop UI.
 *
 * The Rust shell owns the backend lifecycle and reports its phase; this store turns that into
 * UI state, checks health while connected, and records diagnostic events. The session token is
 * kept only inside the API client closure — never in reactive (devtools-visible) state.
 *
 * Polling is deliberately cheap (Phase 4): only `/health`, every `pollMs` while the window is
 * visible, paused while it is hidden and re-checked at once when it becomes visible again or
 * the Mac wakes from sleep. A backend crash does not wait for a poll: the shell notices the
 * exit immediately and pushes the new phase. The heavier system status (database integrity,
 * size) is refreshed only when a view that shows it asks for it.
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
  /** Visibility source (tests inject one); defaults to the document. */
  isVisible?: () => boolean;
}

type PublicConnection = Omit<BackendConnection, "token">;

const MAX_EVENTS = 50;
let deps: Required<ConnectionDeps> | null = null;
let client: ApiClient | null = null;
let pollTimer: ReturnType<typeof setInterval> | null = null;
let unlisten: (() => void) | null = null;
let unlistenWake: (() => void) | null = null;
let epoch = 0;
let onVisibility: (() => void) | null = null;
const wakeHandlers = new Set<() => void>();

/** The API client for the current backend session (null while not connected). Not reactive:
 * it holds the session token, which must never enter devtools-visible state. */
export function currentApiClient(): ApiClient | null {
  return client;
}

/** Increments with every new backend session (start, restart, retry). */
export function connectionEpoch(): number {
  return epoch;
}

/** The shell bridge (null before start). */
export function currentPlatform(): Platform | null {
  return deps?.platform ?? null;
}

/** Run `handler` after the Mac woke from sleep (and the backend health was re-checked). */
export function onSystemWoke(handler: () => void): () => void {
  wakeHandlers.add(handler);
  return () => wakeHandlers.delete(handler);
}

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
        pollMs: 15_000,
        now: () => new Date(),
        isVisible: () => typeof document === "undefined" || document.visibilityState !== "hidden",
        ...options,
      };
      unlisten = await deps.platform.onConnectionChanged((c) => void this.applyConnection(c));
      unlistenWake = await deps.platform.onSystemWoke(() => void this.onWake());
      if (typeof document !== "undefined") {
        onVisibility = () => this.onVisibilityChange();
        document.addEventListener("visibilitychange", onVisibility);
      }
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
      unlistenWake?.();
      unlistenWake = null;
      wakeHandlers.clear();
      if (onVisibility !== null) document.removeEventListener("visibilitychange", onVisibility);
      onVisibility = null;
      client = null;
    },

    /** Hidden window: no polling at all. Visible again: check at once, then resume. */
    onVisibilityChange() {
      if (deps === null || client === null) return;
      if (deps.isVisible()) {
        void this.poll();
        this.startPolling();
      } else {
        this.stopPolling();
      }
    },

    async onWake() {
      this.record("info", "system_woke");
      if (client !== null) await this.poll();
      for (const handler of wakeHandlers) handler();
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
          if (connection.restartAttempt > 0) this.record("info", "backend_restarting");
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
          epoch += 1;
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
        this.health = await client.health();
        this.markHealthy();
      } catch (error) {
        this.handleRequestFailure(error);
      }
    },

    /** System status (integrity, database size, uptime) for the views that show it. */
    async refreshStatus() {
      if (client === null) return;
      try {
        this.status = await client.systemStatus();
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
      if (pollTimer !== null || deps === null || !deps.isVisible()) return;
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
