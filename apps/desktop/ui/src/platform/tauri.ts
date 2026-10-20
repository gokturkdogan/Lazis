/**
 * Bridge to the Rust shell (Tauri commands/events). Everything security-sensitive — the
 * Keychain, the database key, backend process management — lives in Rust. The UI only
 * receives the backend port and the per-launch session token.
 */
import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";

export type BackendPhase = "starting" | "ready" | "failed" | "needs_recovery" | "stopped";

export interface BackendConnection {
  phase: BackendPhase;
  port: number | null;
  token: string | null;
  errorCode: string | null;
  /** True until the user confirms the recovery code has been stored safely. */
  recoveryPending: boolean;
  profile: string;
  dataDir: string;
  logDir: string;
  /** FileVault disk encryption as reported by `fdesetup isactive`. */
  fileVault: "on" | "off" | "unknown";
  /** Automatic restart after an unexpected exit: attempt (1-based) while one is pending. */
  restartAttempt: number;
  restartLimit: number;
}

/** Desktop preferences, stored by the shell (desktop-state.json; no secrets). */
export interface Preferences {
  /** Closing the window keeps LAZIS in the menu bar (true) or quits it (false). */
  closeToMenuBar: boolean;
  startHidden: boolean;
  /** "system" follows macOS Reduce Motion; "on" always reduces. */
  reduceMotion: "system" | "on";
}

export type TrayStatus = "starting" | "idle" | "thinking" | "speaking" | "error" | "offline";

/** Per-process memory (phys_footprint, as in Activity Monitor), read on demand. */
export interface ProcessMetrics {
  source: "phys_footprint";
  processes: {
    role: "shell" | "backend" | "ollama_server" | "ollama_runner";
    pid: number;
    footprint_bytes: number | null;
  }[];
  ollama_found: boolean;
}

export type View = "conversation" | "memory" | "overview" | "settings" | "diagnostics";

export interface Platform {
  getConnection(): Promise<BackendConnection>;
  onConnectionChanged(callback: (connection: BackendConnection) => void): Promise<UnlistenFn>;
  retryBackend(): Promise<BackendConnection>;
  revealRecoveryCode(): Promise<string>;
  acknowledgeRecovery(): Promise<BackendConnection>;
  restoreFromRecoveryCode(code: string): Promise<BackendConnection>;
  getPreferences(): Promise<Preferences>;
  setPreferences(preferences: Preferences): Promise<Preferences>;
  setTrayStatus(status: TrayStatus): Promise<void>;
  /** Only after the user confirmed; the shell accepts http(s) URLs only. */
  openExternalUrl(url: string): Promise<void>;
  processMetrics(): Promise<ProcessMetrics>;
  /** The Mac woke from sleep (payload: seconds the wall clock moved). */
  onSystemWoke(callback: () => void): Promise<UnlistenFn>;
  /** The menu bar or a second launch (`--show=<view>`) asked for a view. */
  onNavigate(callback: (view: View) => void): Promise<UnlistenFn>;
  /** A view requested at launch (`--show=<view>`), if any. */
  initialView(): View | null;
}

export const CONNECTION_EVENT = "lazis://backend-connection";
export const WAKE_EVENT = "lazis://system-woke";
export const NAVIGATE_EVENT = "lazis://navigate";
const VIEWS: readonly View[] = ["conversation", "memory", "overview", "settings", "diagnostics"];

function asView(value: unknown): View | null {
  return VIEWS.find((v) => v === value) ?? null;
}

export const tauriPlatform: Platform = {
  getConnection: () => invoke<BackendConnection>("backend_connection"),
  onConnectionChanged: (callback) =>
    listen<BackendConnection>(CONNECTION_EVENT, (event) => callback(event.payload)),
  retryBackend: () => invoke<BackendConnection>("retry_backend"),
  revealRecoveryCode: () => invoke<string>("reveal_recovery_code"),
  acknowledgeRecovery: () => invoke<BackendConnection>("acknowledge_recovery"),
  restoreFromRecoveryCode: (code: string) =>
    invoke<BackendConnection>("restore_from_recovery_code", { code }),
  getPreferences: () => invoke<Preferences>("get_preferences"),
  setPreferences: (preferences) => invoke<Preferences>("set_preferences", { preferences }),
  setTrayStatus: (status) => invoke<void>("set_tray_status", { status }),
  openExternalUrl: (url) => invoke<void>("open_external_url", { url }),
  processMetrics: () => invoke<ProcessMetrics>("process_metrics"),
  onSystemWoke: (callback) => listen(WAKE_EVENT, () => callback()),
  onNavigate: (callback) =>
    listen<string>(NAVIGATE_EVENT, (event) => {
      const view = asView(event.payload);
      if (view) callback(view);
    }),
  initialView: () => asView((window as { __LAZIS_INITIAL_VIEW__?: unknown }).__LAZIS_INITIAL_VIEW__),
};

/** Tauri rejects command promises with the serialized Rust error: { code, message }. */
export function platformErrorCode(error: unknown): string {
  if (typeof error === "object" && error !== null && "code" in error) {
    const code = (error as { code: unknown }).code;
    if (typeof code === "string") return code;
  }
  return "internal_error";
}
