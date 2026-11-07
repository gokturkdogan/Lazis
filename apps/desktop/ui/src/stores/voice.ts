/**
 * Voice conversation (Phase 13, session-only since Phase 14).
 *
 * * **Hands-free session**, started and ended only by the user. While it is open the microphone
 *   listens; a turn ends after a short silence (loudness only, no model). The utterance is
 *   transcribed locally and sent as an ordinary message on the "voice" channel; the reply is
 *   read aloud; then listening resumes. While LAZIS thinks or speaks nothing heard is kept, and
 *   listening resumes only shortly after Yelda has finished, so its own voice never becomes a
 *   user message. Ending the session closes the microphone and frees the speech model.
 * * Replies are read with Yelda, sentence by sentence, through Web Audio so the core follows the
 *   real loudness; "Durdur" stops it at once.
 *
 * Audio lives in memory only; nothing heard is ever stored, and the backend never writes memory
 * from a spoken message.
 */
import { defineStore } from "pinia";
import { markRaw } from "vue";
import type { VoiceStatus } from "@/platform/tauri";
import { useAssistantStore } from "@/stores/assistant";
import { currentPlatform } from "@/stores/connection";
import { isNoise, sentences, speakable, TurnDetector } from "@/voice/audio";
import { setMicLevel } from "@/voice/levels";
import { browserAudio, SpeechPlayer, type AudioOut } from "@/voice/player";
import { browserMedia, micError, Recorder, type MediaAccess } from "@/voice/recorder";

export type VoiceMode = "off" | "session";
export type VoicePhase = "idle" | "listening" | "transcribing" | "thinking" | "speaking";

const SPEAK_KEY = "lazis.voice.speak";
const PREROLL_FRAMES = 6; // about 0.25 s kept from just before speech started
const MIN_SECONDS = 0.3;
const MIN_PEAK = 0.008; // quieter than this is silence: not even transcribed
/** After Yelda stops, wait this long before hearing again (room echo, speaker tail). */
export const RESUME_AFTER_SPEECH_MS = 600;

let media: MediaAccess = browserMedia;
let audio: AudioOut = browserAudio;
/** Tests replace the microphone and the speaker. */
export function useMediaForTests(m: MediaAccess, out?: AudioOut): void {
  media = m;
  if (out) audio = out;
}

function readSpeak(): boolean {
  try {
    return globalThis.localStorage?.getItem(SPEAK_KEY) !== "0";
  } catch {
    return true;
  }
}

export const useVoiceStore = defineStore("voice", {
  state: () => ({
    status: null as VoiceStatus | null,
    mode: "off" as VoiceMode,
    phase: "idle" as VoicePhase,
    speakReplies: readSpeak(),
    error: null as string | null,
    heard: null as string | null,
    /** The sentence Yelda is saying now (the HUD caption). */
    saying: null as string | null,
    /** Real timings of the last voice turn (ms), for the HUD. */
    lastSttMs: null as number | null,
    lastFirstAudioMs: null as number | null,
    recorder: markRaw(new Recorder(media)) as Recorder,
    detector: markRaw(new TurnDetector()) as TurnDetector,
    player: markRaw(new SpeechPlayer(audio)) as SpeechPlayer,
    cancelSpeech: false,
    resumeAt: 0,
  }),

  getters: {
    /** True exactly while the microphone stream is open (the system indicator is on). */
    micOpen: (s) => s.mode === "session",
    canListen: (s) => s.status?.stt_available === true,
  },

  actions: {
    async refresh() {
      const platform = currentPlatform();
      if (platform === null) return;
      try {
        this.status = await platform.voiceStatus();
      } catch {
        this.status = null;
      }
    },

    setSpeakReplies(on: boolean) {
      this.speakReplies = on;
      try {
        globalThis.localStorage?.setItem(SPEAK_KEY, on ? "1" : "0");
      } catch {
        // Not remembered: the default (on) comes back next time.
      }
      if (!on) void this.stopSpeaking();
    },

    // ----- hands-free session ----------------------------------------------------------------
    async startSession() {
      if (this.mode !== "off" || !this.canListen) return;
      this.player.warm(); // inside the user's click: the speaker may play later
      this.recorder.close();
      this.recorder = markRaw(new Recorder(media));
      this.detector = markRaw(new TurnDetector());
      this.mode = "session";
      this.phase = "listening";
      this.error = null;
      this.resumeAt = 0;
      try {
        await this.recorder.start((level, ms) => this.onFrame(level, ms));
      } catch (e) {
        this.recorder.close();
        this.mode = "off";
        this.phase = "idle";
        this.error = micError(e);
      }
    },

    onFrame(level: number, ms: number) {
      if (this.mode !== "session" || this.phase !== "listening") return;
      if (performance.now() < this.resumeAt) {
        this.recorder.trim(0); // the tail of Yelda's voice is never heard as the user
        return;
      }
      setMicLevel(level);
      const event = this.detector.feed(level, ms);
      if (event === null && !this.detector.speaking) this.recorder.trim(PREROLL_FRAMES);
      if (event === "end") {
        const take = this.recorder.take();
        this.recorder.setKeeping(false); // nothing is kept while LAZIS works or speaks
        void this.handle(take).finally(() => {
          if (this.mode === "session") {
            this.detector.reset();
            this.recorder.setKeeping(true);
            this.phase = "listening";
          }
        });
      }
    },

    async endSession() {
      if (this.mode !== "session") return;
      this.mode = "off";
      this.recorder.close(); // tracks stopped: the system microphone indicator goes off
      this.detector.reset();
      this.phase = "idle";
      setMicLevel(0);
      await this.stopSpeaking();
      await currentPlatform()?.voiceRelease().catch(() => undefined);
    },

    // ----- one utterance ---------------------------------------------------------------------
    async handle(take: { wav: Uint8Array; seconds: number; peak: number }) {
      const platform = currentPlatform();
      if (platform === null) return;
      if (take.seconds < MIN_SECONDS || take.peak < MIN_PEAK) {
        this.error = "heard_nothing";
        return;
      }
      this.phase = "transcribing";
      let text: string;
      const started = performance.now();
      try {
        text = await platform.voiceTranscribe(take.wav);
      } catch (e) {
        this.error = (e as { code?: string } | null)?.code ?? "stt_failed";
        return;
      }
      this.lastSttMs = Math.round(performance.now() - started);
      if (isNoise(text)) {
        this.error = "heard_nothing";
        return;
      }
      this.heard = text;
      this.error = null;
      const assistant = useAssistantStore();
      if (!assistant.canSend) {
        this.error = "busy";
        return;
      }
      this.phase = "thinking";
      const before = assistant.messages.length;
      const sent = await assistant.send(text, { channel: "voice" });
      if (!sent || !this.speakReplies || this.status?.tts_available !== true) return;
      const reply = [...assistant.messages.slice(before)].reverse().find((m) => m.role === "assistant");
      if (reply && reply.content.trim()) await this.speak(reply.content);
    },

    /** Sentence by sentence; the next one is synthesized while the current one plays. */
    async speak(text: string) {
      const platform = currentPlatform();
      if (platform === null) return;
      const parts = sentences(speakable(text));
      if (parts.length === 0) return;
      this.cancelSpeech = false;
      this.phase = "speaking";
      const started = performance.now();
      let first = true;
      try {
        let next: Promise<ArrayBuffer> | null = platform.voiceSynthesize(parts[0]!);
        for (let i = 0; i < parts.length && next !== null; i++) {
          const wav = await next;
          next = i + 1 < parts.length ? platform.voiceSynthesize(parts[i + 1]!) : null;
          if (this.cancelSpeech) break;
          this.saying = parts[i]!;
          if (first) {
            this.lastFirstAudioMs = Math.round(performance.now() - started);
            first = false;
          }
          await this.player.play(wav);
          if (this.cancelSpeech) break;
        }
        next?.catch(() => undefined);
      } catch (e) {
        this.error = (e as { code?: string } | null)?.code ?? "tts_failed";
      } finally {
        this.saying = null;
        this.resumeAt = performance.now() + RESUME_AFTER_SPEECH_MS;
        this.phase = this.mode === "session" ? "listening" : "idle";
      }
    },

    async stopSpeaking() {
      this.cancelSpeech = true;
      this.player.stop();
      await currentPlatform()?.voiceStopSpeaking().catch(() => undefined);
    },
  },
});
