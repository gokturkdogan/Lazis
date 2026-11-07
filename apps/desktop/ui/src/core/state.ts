/**
 * What the core shows, derived only from the app's real state (Phase 14): no state is ever
 * acted out. Thinking covers transcribing and the reply being written (voice or text); speaking
 * is Yelda's audio playing; listening is an open hands-free session waiting for the user.
 */
import type { CoreState } from "@/core/palette";

export interface CoreInputs {
  voiceMode: "off" | "session";
  voicePhase: "idle" | "listening" | "transcribing" | "thinking" | "speaking";
  assistantPhase: "idle" | "sending" | "streaming" | "cancelling";
  /** A real fault shown for a few seconds (microphone refused, turn failed, ...). */
  error: boolean;
}

export function coreState(i: CoreInputs): CoreState {
  if (i.error) return "error";
  if (i.voicePhase === "speaking") return "speaking";
  if (i.voicePhase === "transcribing" || i.voicePhase === "thinking") return "thinking";
  if (i.assistantPhase === "sending" || i.assistantPhase === "streaming") return "thinking";
  if (i.voiceMode === "session" && i.voicePhase === "listening") return "listening";
  return "idle";
}

/** Voice errors that are faults (red), not "I did not catch that". */
export const FAULTS = new Set([
  "mic_denied",
  "mic_missing",
  "mic_unavailable",
  "stt_failed",
  "stt_server_missing",
  "stt_model_missing",
  "audio_invalid",
  "tts_unavailable",
  "tts_failed",
]);

export const ERROR_SHOWN_MS = 6000;
