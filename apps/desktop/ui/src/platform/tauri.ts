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
}

export interface Platform {
  getConnection(): Promise<BackendConnection>;
  onConnectionChanged(callback: (connection: BackendConnection) => void): Promise<UnlistenFn>;
  retryBackend(): Promise<BackendConnection>;
  revealRecoveryCode(): Promise<string>;
  acknowledgeRecovery(): Promise<BackendConnection>;
  restoreFromRecoveryCode(code: string): Promise<BackendConnection>;
}

export const CONNECTION_EVENT = "lazis://backend-connection";

export const tauriPlatform: Platform = {
  getConnection: () => invoke<BackendConnection>("backend_connection"),
  onConnectionChanged: (callback) =>
    listen<BackendConnection>(CONNECTION_EVENT, (event) => callback(event.payload)),
  retryBackend: () => invoke<BackendConnection>("retry_backend"),
  revealRecoveryCode: () => invoke<string>("reveal_recovery_code"),
  acknowledgeRecovery: () => invoke<BackendConnection>("acknowledge_recovery"),
  restoreFromRecoveryCode: (code: string) =>
    invoke<BackendConnection>("restore_from_recovery_code", { code }),
};

/** Tauri rejects command promises with the serialized Rust error: { code, message }. */
export function platformErrorCode(error: unknown): string {
  if (typeof error === "object" && error !== null && "code" in error) {
    const code = (error as { code: unknown }).code;
    if (typeof code === "string") return code;
  }
  return "internal_error";
}
