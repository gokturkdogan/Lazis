/**
 * The microphone (Phase 13). Opened only by an explicit user action (push-to-talk held, or a
 * hands-free session started) and closed — every track stopped, the audio context closed — the
 * moment that ends. Audio stays in memory: nothing is written anywhere.
 */
import { concat, downsample, encodeWav, rms, STT_RATE } from "@/voice/audio";

export type MicError = "mic_denied" | "mic_missing" | "mic_unavailable";

export interface MediaAccess {
  getUserMedia(constraints: MediaStreamConstraints): Promise<MediaStream>;
  createContext(): AudioContext;
}

export const browserMedia: MediaAccess = {
  getUserMedia: (c) => {
    if (!navigator.mediaDevices?.getUserMedia) return Promise.reject(new DOMException("", "NotFoundError"));
    return navigator.mediaDevices.getUserMedia(c);
  },
  createContext: () => new AudioContext(),
};

export function micError(e: unknown): MicError {
  const name = e instanceof DOMException || e instanceof Error ? e.name : "";
  if (name === "NotAllowedError" || name === "SecurityError") return "mic_denied";
  if (name === "NotFoundError" || name === "OverconstrainedError") return "mic_missing";
  return "mic_unavailable";
}

const FRAME = 2048;

export class Recorder {
  private stream: MediaStream | null = null;
  private context: AudioContext | null = null;
  private node: ScriptProcessorNode | null = null;
  private chunks: Float32Array[] = [];
  private keep = true;
  rate = 48_000;

  constructor(private readonly media: MediaAccess = browserMedia) {}

  get open(): boolean {
    return this.stream !== null;
  }

  /** Opens the microphone. `onFrame` gets each frame's level and length (ms). */
  async start(onFrame?: (level: number, ms: number) => void): Promise<void> {
    if (this.stream) return;
    const stream = await this.media.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      video: false,
    });
    this.stream = stream;
    try {
      const context = this.media.createContext();
      this.context = context;
      this.rate = context.sampleRate;
      const source = context.createMediaStreamSource(stream);
      const node = context.createScriptProcessor(FRAME, 1, 1);
      node.onaudioprocess = (event) => {
        const frame = new Float32Array(event.inputBuffer.getChannelData(0));
        if (this.keep) this.chunks.push(frame);
        onFrame?.(rms(frame), (frame.length / this.rate) * 1000);
      };
      source.connect(node);
      node.connect(context.destination);
      this.node = node;
    } catch (e) {
      this.close();
      throw e;
    }
  }

  /** Hands-free: drop what was heard so far, or stop keeping audio while LAZIS speaks. */
  setKeeping(keep: boolean): void {
    this.keep = keep;
    if (!keep) this.chunks = [];
  }

  /** The audio kept since the last take, at 16 kHz, as a WAV; and its loudest frame. */
  take(): { wav: Uint8Array; seconds: number; peak: number } {
    const chunks = this.chunks;
    const samples = downsample(concat(chunks), this.rate, STT_RATE);
    const peak = chunks.reduce((m, c) => Math.max(m, rms(c)), 0);
    this.chunks = [];
    return { wav: encodeWav(samples), seconds: samples.length / STT_RATE, peak };
  }

  /** Keep only the last `frames` frames (the moments just before speech started). */
  trim(frames: number): void {
    if (this.chunks.length > frames) this.chunks = this.chunks.slice(-frames);
  }

  /** Closes the microphone: tracks stopped (the system indicator goes off), context closed. */
  close(): void {
    if (this.node) {
      this.node.onaudioprocess = null;
      this.node.disconnect();
    }
    this.stream?.getTracks().forEach((t) => t.stop());
    void this.context?.close().catch(() => undefined);
    this.node = null;
    this.stream = null;
    this.context = null;
    this.chunks = [];
    this.keep = true;
  }
}
