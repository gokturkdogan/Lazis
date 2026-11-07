/**
 * Plays Yelda's speech (a WAV from the shell) through Web Audio (Phase 14), so the core can
 * follow its real loudness through an analyser. Stopping is immediate. Nothing is stored.
 */
import { setSpeechAnalyser } from "@/voice/levels";

export interface AudioOut {
  createContext(): AudioContext;
}

export const browserAudio: AudioOut = { createContext: () => new AudioContext() };

export class SpeechPlayer {
  private context: AudioContext | null = null;
  private analyser: AnalyserNode | null = null;
  private source: AudioBufferSourceNode | null = null;
  private finish: (() => void) | null = null;

  constructor(private readonly out: AudioOut = browserAudio) {}

  private ensure(): { context: AudioContext; analyser: AnalyserNode } {
    if (!this.context || !this.analyser) {
      this.context = this.out.createContext();
      this.analyser = this.context.createAnalyser();
      this.analyser.fftSize = 1024;
      this.analyser.connect(this.context.destination);
    }
    return { context: this.context, analyser: this.analyser };
  }

  /** Create and resume the audio output inside a user gesture (WebKit may otherwise keep it
   *  suspended): call from the click that starts the voice session. */
  warm(): void {
    try {
      const { context } = this.ensure();
      if (context.state === "suspended") void context.resume().catch(() => undefined);
    } catch {
      // no audio output: speech falls back to an error message, the session still works
    }
  }

  /** Resolves when the audio ended or was stopped. */
  async play(wav: ArrayBuffer): Promise<void> {
    const { context, analyser } = this.ensure();
    if (context.state === "suspended") await context.resume();
    const buffer = await context.decodeAudioData(wav.slice(0));
    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(analyser);
    this.source = source;
    setSpeechAnalyser(analyser);
    await new Promise<void>((resolve) => {
      this.finish = resolve;
      source.onended = () => resolve();
      source.start();
    });
    this.finish = null;
    if (this.source === source) this.source = null;
    setSpeechAnalyser(null);
  }

  stop(): void {
    try {
      this.source?.stop();
    } catch {
      // already stopped
    }
    this.source = null;
    this.finish?.();
    this.finish = null;
    setSpeechAnalyser(null);
  }

  close(): void {
    this.stop();
    void this.context?.close().catch(() => undefined);
    this.context = null;
    this.analyser = null;
  }
}
