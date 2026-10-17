/**
 * The assistant's visible state (Phase 4), derived only from real events: the shell's backend
 * phase, the runtime check and the turn stream's events. No timers or simulated progress.
 *
 *   idle (blue) → thinking (yellow: sent, context/model being prepared) → speaking (green:
 *   reply tokens arriving) → idle;  any failure → error (red) until it is resolved.
 *
 * "listening" (purple) is reserved for voice (Phase 13); nothing produces it yet.
 */
import { computed } from "vue";
import type { TrayStatus } from "@/platform/tauri";
import { useAssistantStore } from "@/stores/assistant";
import { useConnectionStore, type UiPhase } from "@/stores/connection";
import type { TurnPhase, TurnState } from "@/stores/assistant";

export type PresenceState = "idle" | "thinking" | "speaking" | "listening" | "error";

export interface Presence {
  state: PresenceState;
  /** i18n key (under `presence.`) of the accessible text label. */
  label: string;
  params?: Record<string, number>;
  tray: TrayStatus;
}

export interface PresenceInputs {
  connection: UiPhase;
  restartAttempt: number;
  restartLimit: number;
  turnPhase: TurnPhase;
  turnStage: TurnState["stage"] | null;
  runtimeDown: boolean;
  turnError: string | null;
}

export function derivePresence(i: PresenceInputs): Presence {
  switch (i.connection) {
    case "initializing":
    case "starting":
      return { state: "thinking", label: "starting", tray: "starting" };
    case "needs_recovery":
      return { state: "error", label: "needsRecovery", tray: "error" };
    case "backend_failed":
      return i.restartAttempt > 0
        ? {
            state: "error",
            label: "restarting",
            params: { attempt: i.restartAttempt, limit: i.restartLimit },
            tray: "error",
          }
        : { state: "error", label: "backendFailed", tray: "error" };
    case "disconnected":
      return { state: "error", label: "disconnected", tray: "offline" };
    case "connected":
      break;
  }
  if (i.turnPhase === "cancelling") return { state: "thinking", label: "stopping", tray: "thinking" };
  if (i.turnPhase !== "idle") {
    return i.turnStage === "generating"
      ? { state: "speaking", label: "speaking", tray: "speaking" }
      : { state: "thinking", label: "thinking", tray: "thinking" };
  }
  if (i.runtimeDown) return { state: "error", label: "runtimeDown", tray: "error" };
  if (i.turnError !== null && i.turnError !== "llm_cancelled") {
    return { state: "error", label: "turnFailed", tray: "error" };
  }
  return { state: "idle", label: "idle", tray: "idle" };
}

export function usePresence() {
  const connection = useConnectionStore();
  const assistant = useAssistantStore();
  return computed(() =>
    derivePresence({
      connection: connection.phase,
      restartAttempt: connection.connection?.restartAttempt ?? 0,
      restartLimit: connection.connection?.restartLimit ?? 0,
      turnPhase: assistant.phase,
      turnStage: assistant.turn?.stage ?? null,
      runtimeDown: assistant.runtimeDown,
      turnError: assistant.errorCode,
    }),
  );
}
