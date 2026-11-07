/**
 * Live audio levels for the core and the HUD meters (Phase 14). They live outside Vue state, as
 * in LAZOS: the render loop reads them every frame, so ~60 updates/s cause no re-render.
 *
 * * Microphone: the hands-free recorder reports each frame's loudness (listening only).
 * * Speech: Yelda's audio is played through Web Audio; its analyser is read directly.
 * Nothing is invented: with no audio there is no level.
 */

const mic = { value: 0, at: 0 };
let analyser: AnalyserNode | null = null;
let samples: Float32Array<ArrayBuffer> | null = null;

/** RMS (0…≈0.3 for speech) → 0…1, with a gentle curve so quiet speech still moves. */
export function scaleLevel(rms: number): number {
  return Math.min(1, Math.pow(Math.max(0, rms) * 7, 0.8));
}

export function setMicLevel(rms: number): void {
  mic.value = scaleLevel(rms);
  mic.at = performance.now();
}

/** Decays to zero when frames stop (session ended, microphone closed). */
export function micLevel(): number {
  return performance.now() - mic.at > 400 ? 0 : mic.value;
}

export function setSpeechAnalyser(node: AnalyserNode | null): void {
  analyser = node;
  samples = node ? new Float32Array(new ArrayBuffer(node.fftSize * 4)) : null;
}

export function speechLevel(): number {
  if (!analyser || !samples) return 0;
  analyser.getFloatTimeDomainData(samples);
  let sum = 0;
  for (const s of samples) sum += s * s;
  return scaleLevel(Math.sqrt(sum / samples.length));
}
