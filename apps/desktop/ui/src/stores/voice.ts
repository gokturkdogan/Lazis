/**
 * Voice conversation (Phase 13, first version).
 *
 * * **Push-to-talk:** the microphone opens while the button is held and closes on release; the
 *   recording is transcribed locally and sent as an ordinary message on the "voice" channel.
 * * **Hands-free session:** started and ended only by the user. While it is open the microphone
 *   listens; a turn ends after a short silence (loudness only, no model). While LAZIS thinks or
 *   speaks, nothing heard is kept (no echo of its own voice). Ending it closes the microphone
 *   and frees the speech model.
 * * Replies may be read aloud with the system voice, sentence by sentence; "Durdur" stops it.
 *
 * Audio lives in memory only, goes to the local shell, and nothing heard is ever stored; the
 * backend never writes memory from a spoken message.
 */
import { defineStore } from "pinia";
import { markRaw } from "vue";
import type { VoiceStatus } from "@/platform/tauri";
import { useAssistantStore } from "@/stores/assistant";
import { currentPlatform } from "@/stores/connection";
import { isNoise, sentences, speakable, TurnDetector } from "@/voice/audio";
import { browserMedia, micError, Recorder, type MediaAccess } from "@/voice/recorder";

export type VoiceMode = "off" | "ptt" | "session";
export type VoicePhase = "idle" | "recording" | "listening" | "transcribing" | "thinking" | "speaking";

const SPEAK_KEY = "lazis.voice.speak";
const PREROLL_FRAMES = 6; // about 0.25 s kept from just before speech started
const MIN_SECONDS = 0.3;
const MIN_PEAK = 0.008; // quieter than this is silence: not even transcribed

let media: MediaAccess = browserMedia;
/** Tests replace the microphone. */
export function useMediaForTests(m: MediaAccess): void {
  media = m;
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
    recorder: markRaw(new Recorder(media)) as Recorder,
    detector: markRaw(new TurnDetector()) as TurnDetector,
    cancelSpeech: false,
  }),

  getters: {
    /** True exactly while the microphone stream is open (the system indicator is on). */
    micOpen: (s) => s.mode === "session" || (s.mode === "ptt" && s.phase === "recording"),
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

    newRecorder() {
      this.recorder.close();
      this.recorder = markRaw(new Recorder(media));
      this.detector = markRaw(new TurnDetector());
    },

    // ----- push-to-talk ----------------------------------------------------------------------
    async pttStart() {
      if (this.mode !== "off" || !this.canListen) return;
      await this.stopSpeaking();
      this.newRecorder();
      this.mode = "ptt";
      this.phase = "recording";
      this.error = null;
      try {
        await this.recorder.start();
      } catch (e) {
        this.recorder.close();
        this.mode = "off";
        this.phase = "idle";
        this.error = micError(e);
      }
    },

    async pttEnd() {
      if (this.mode !== "ptt") return;
      const take = this.recorder.take();
      this.recorder.close(); // the microphone is off before anything else happens
      this.mode = "off";
      await this.handle(take);
      if (this.mode === "off") this.phase = "idle";
    },

    // ----- hands-free session ----------------------------------------------------------------
    async startSession() {
      if (this.mode !== "off" || !this.canListen) return;
      this.newRecorder();
      this.mode = "session";
      this.phase = "listening";
      this.error = null;
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
      this.recorder.close();
      this.detector.reset();
      this.phase = "idle";
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
      try {
        text = await platform.voiceTranscribe(take.wav);
      } catch (e) {
        this.error = (e as { code?: string } | null)?.code ?? "stt_failed";
        return;
      }
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

    async speak(text: string) {
      const platform = currentPlatform();
      if (platform === null) return;
      this.cancelSpeech = false;
      this.phase = "speaking";
      try {
        for (const sentence of sentences(speakable(text))) {
          if (this.cancelSpeech) break;
          await platform.voiceSpeak(sentence);
        }
      } catch (e) {
        this.error = (e as { code?: string } | null)?.code ?? "tts_failed";
      } finally {
        this.phase = this.mode === "session" ? "listening" : "idle";
      }
    },

    async stopSpeaking() {
      this.cancelSpeech = true;
      await currentPlatform()?.voiceStopSpeaking().catch(() => undefined);
    },
  },
});
