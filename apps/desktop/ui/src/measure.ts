/**
 * Opt-in local measurements (Phase 15B). Off unless the shell was started with LAZIS_METRICS=1;
 * then a few numbers (frame rate, speech timings) go to the shell's own log. No text, no
 * content, nothing leaves the machine. When off, every call is a no-op.
 */
import { currentPlatform } from "@/stores/connection";

export type MeasureKind = "fps" | "stt_ms" | "first_audio_ms" | "voice_e2e_ms" | "reply_ms";

let enabled: Promise<boolean> | null = null;

export function measuring(): Promise<boolean> {
  if (enabled === null) {
    const platform = currentPlatform();
    enabled = platform ? platform.metricsEnabled().catch(() => false) : Promise.resolve(false);
  }
  return enabled;
}

export function measure(kind: MeasureKind, value: number, detail = ""): void {
  void measuring().then((on) => {
    if (on) void currentPlatform()?.metricsRecord(kind, Math.round(value * 10) / 10, detail).catch(() => undefined);
  });
}

/** Tests: forget the cached answer. */
export function resetMeasureForTests(): void {
  enabled = null;
}
