/**
 * Pure audio and text helpers for voice (Phase 13). No microphone, no network.
 */

export const STT_RATE = 16_000;
export const MAX_SECONDS = 60;

/** Linear-interpolation resampling to 16 kHz mono (input already mono). */
export function downsample(input: Float32Array, fromRate: number, toRate = STT_RATE): Float32Array {
  if (fromRate === toRate) return input.slice();
  const ratio = fromRate / toRate;
  const length = Math.floor(input.length / ratio);
  const out = new Float32Array(length);
  for (let i = 0; i < length; i++) {
    const pos = i * ratio;
    const left = Math.floor(pos);
    const right = Math.min(left + 1, input.length - 1);
    const frac = pos - left;
    out[i] = (input[left] ?? 0) * (1 - frac) + (input[right] ?? 0) * frac;
  }
  return out;
}

/** 16-bit PCM WAV (mono) — the only format the shell accepts. */
export function encodeWav(samples: Float32Array, rate = STT_RATE): Uint8Array {
  const data = samples.length * 2;
  const buffer = new ArrayBuffer(44 + data);
  const view = new DataView(buffer);
  const text = (offset: number, s: string) => [...s].forEach((c, i) => view.setUint8(offset + i, c.charCodeAt(0)));
  text(0, "RIFF");
  view.setUint32(4, 36 + data, true);
  text(8, "WAVE");
  text(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, rate, true);
  view.setUint32(28, rate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  text(36, "data");
  view.setUint32(40, data, true);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i] ?? 0));
    view.setInt16(44 + i * 2, Math.round(s < 0 ? s * 0x8000 : s * 0x7fff), true);
  }
  return new Uint8Array(buffer);
}

export function rms(frame: Float32Array): number {
  let sum = 0;
  for (const s of frame) sum += s * s;
  return frame.length ? Math.sqrt(sum / frame.length) : 0;
}

export function concat(chunks: readonly Float32Array[]): Float32Array {
  const out = new Float32Array(chunks.reduce((n, c) => n + c.length, 0));
  let at = 0;
  for (const c of chunks) {
    out.set(c, at);
    at += c.length;
  }
  return out;
}

export type TurnEvent = "start" | "end" | null;

/**
 * Hands-free turn taking from loudness alone (no model): speech starts after `startMs` above
 * the threshold and ends after `endMs` below it, or at `maxMs`.
 */
export class TurnDetector {
  private above = 0;
  private below = 0;
  private spoken = 0;
  speaking = false;

  constructor(
    readonly threshold = 0.015,
    readonly startMs = 150,
    readonly endMs = 900,
    readonly maxMs = 30_000,
  ) {}

  feed(level: number, frameMs: number): TurnEvent {
    if (!this.speaking) {
      this.above = level >= this.threshold ? this.above + frameMs : 0;
      if (this.above >= this.startMs) {
        this.speaking = true;
        this.below = 0;
        this.spoken = this.above;
        return "start";
      }
      return null;
    }
    this.spoken += frameMs;
    this.below = level < this.threshold ? this.below + frameMs : 0;
    if (this.below >= this.endMs || this.spoken >= this.maxMs) {
      this.reset();
      return "end";
    }
    return null;
  }

  reset(): void {
    this.speaking = false;
    this.above = 0;
    this.below = 0;
    this.spoken = 0;
  }
}

/** What Whisper writes for silence or noise in Turkish videos; never sent as a message. */
const NOISE = [
  /^altyaz[ıi]/,
  /izledi[gğ]iniz i[cç]in te[sş]ekk[uü]r/,
  /abone ol/,
  /^\[.*\]$/,
  /^\(.*\)$/,
  /^(te[sş]ekk[uü]rler|te[sş]ekk[uü]r ederim)[.!]?$/,
];

export function isNoise(text: string): boolean {
  const t = text.trim().toLocaleLowerCase("tr");
  if (t.replace(/[\s.,!?…-]/g, "").length < 2) return true;
  return NOISE.some((r) => r.test(t));
}

/** Reply text as it should be spoken: no Markdown marks, no code, links by their text. */
export function speakable(markdown: string): string {
  return markdown
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`([^`]*)`/g, "$1")
    .replace(/!\[[^\]]*\]\([^)]*\)/g, " ")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/https?:\/\/\S+/g, " ")
    .replace(/^\s{0,3}#{1,6}\s+/gm, "")
    .replace(/^\s*[-*+]\s+/gm, "")
    .replace(/^\s*\d+[.)]\s+/gm, "")
    .replace(/^\s*>\s?/gm, "")
    .replace(/[*_~]{1,3}([^*_~]+)[*_~]{1,3}/g, "$1")
    .replace(/\|/g, " ")
    .split("\n")
    .map((line) => line.replace(/[ \t]+/g, " ").trim())
    .filter((line) => line !== "")
    .join("\n");
}

/** Sentences, so speech can start before the whole reply is synthesized. */
export function sentences(text: string, max = 400): string[] {
  const out: string[] = [];
  for (const line of text.split(/\n+/)) {
    const parts = line.match(/[^.!?…]+[.!?…]+["'”»)]*|[^.!?…]+$/g) ?? [];
    for (const raw of parts) {
      const s = raw.trim();
      if (!s) continue;
      for (let i = 0; i < s.length; i += max) out.push(s.slice(i, i + max));
    }
  }
  return out;
}
