import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ApiClient, TurnSubmitRequest } from "@/api/client";
import VoiceDock from "@/components/core/VoiceDock.vue";
import { createAppI18n } from "@/i18n";
import type { Platform } from "@/platform/tauri";
import { useAssistantStore } from "@/stores/assistant";
import { useConnectionStore } from "@/stores/connection";
import { RESUME_AFTER_SPEECH_MS, useMediaForTests, useVoiceStore } from "@/stores/voice";
import { micLevel } from "@/voice/levels";
import type { AudioOut } from "@/voice/player";
import type { MediaAccess } from "@/voice/recorder";
import { assistantFixture, connection, fakeClient, fakePlatform, messageFixture } from "./fixtures";

type Frame = (level: number) => void;

export function fakeMedia(options: { fail?: string } = {}) {
  const track = { stop: vi.fn() };
  let process: ((e: { inputBuffer: { getChannelData: () => Float32Array } }) => void) | null = null;
  const media: MediaAccess = {
    getUserMedia: vi.fn(async () => {
      if (options.fail) throw new DOMException("", options.fail);
      return { getTracks: () => [track] } as unknown as MediaStream;
    }),
    createContext: () =>
      ({
        sampleRate: 16_000,
        destination: {},
        createMediaStreamSource: () => ({ connect: vi.fn() }),
        createScriptProcessor: () => ({
          connect: vi.fn(),
          disconnect: vi.fn(),
          set onaudioprocess(f: typeof process) {
            process = f;
          },
          get onaudioprocess() {
            return process;
          },
        }),
        close: vi.fn(async () => undefined),
      }) as unknown as AudioContext,
  };
  const frame: Frame = (level) =>
    process?.({ inputBuffer: { getChannelData: () => new Float32Array(1600).fill(level) } }); // 100 ms
  return { media, track, frame };
}

/** A speaker that "plays" instantly, or holds until released. */
export function fakeSpeaker(hold = false) {
  const played: number[] = [];
  let release: () => void = () => undefined;
  const out: AudioOut = {
    createContext: () =>
      ({
        state: "running",
        destination: {},
        resume: vi.fn(async () => undefined),
        close: vi.fn(async () => undefined),
        createAnalyser: () => ({ fftSize: 1024, connect: vi.fn(), getFloatTimeDomainData: (a: Float32Array) => a.fill(0.1) }),
        decodeAudioData: vi.fn(async (b: ArrayBuffer) => ({ length: b.byteLength })),
        createBufferSource: () => {
          const source = {
            buffer: null as unknown,
            onended: null as null | (() => void),
            connect: vi.fn(),
            start: () => {
              played.push((source.buffer as { length: number }).length);
              if (hold) release = () => source.onended?.();
              else queueMicrotask(() => source.onended?.());
            },
            stop: () => source.onended?.(),
          };
          return source;
        },
      }) as unknown as AudioContext,
  };
  return { out, played, release: () => release() };
}

async function setup(platform: Partial<Platform> = {}, client: Partial<ApiClient> = {}, media = fakeMedia(), speaker = fakeSpeaker()) {
  const pinia = createPinia();
  setActivePinia(pinia);
  useMediaForTests(media.media, speaker.out);
  const bodies: TurnSubmitRequest[] = [];
  const api = fakeClient({
    assistantState: vi.fn().mockResolvedValue(assistantFixture({ timeline_messages: 0 })),
    submitTurn: vi.fn(async (body: TurnSubmitRequest, onEvent) => {
      bodies.push(body);
      onEvent({ type: "done", message: messageFixture(2, "assistant", "**Merhaba** efendim. Nasılsınız?"), context: { estimated_tokens: 1, prompt_tokens: 1, strategy: "full" } });
    }),
    ...client,
  });
  const p = fakePlatform(connection(), platform);
  await useConnectionStore().start({ platform: p, clientFactory: () => api });
  await useAssistantStore().init?.();
  const wrapper = mount(VoiceDock, { global: { plugins: [pinia, createAppI18n()] } });
  await flushPromises();
  return { wrapper, platform: p, bodies, media, speaker, voice: useVoiceStore() };
}

async function settle() {
  for (let i = 0; i < 6; i++) await flushPromises();
}

describe("Voice session (Phase 14: session only, no push-to-talk)", () => {
  afterEach(() => {
    useAssistantStore().stop();
    useConnectionStore().stop();
    vi.useRealTimers();
  });

  it("starts with the microphone off, offers a session and no push-to-talk", async () => {
    const { wrapper, media, voice } = await setup();
    expect(voice.micOpen).toBe(false);
    expect(wrapper.get('[data-testid="voice-mic"]').text()).toBe("Mikrofon kapalı");
    expect(wrapper.find('[data-testid="voice-session-start"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="voice-ptt"]').exists()).toBe(false);
    expect(wrapper.text()).not.toContain("Bas-konuş");
    expect(media.media.getUserMedia).not.toHaveBeenCalled();
  });

  it("listens, sends the turn on the voice channel, speaks the reply with Yelda, then listens again", async () => {
    const { wrapper, platform, bodies, media, speaker, voice } = await setup();
    await wrapper.get('[data-testid="voice-session-start"]').trigger("click");
    await flushPromises();
    expect(voice.micOpen).toBe(true);
    expect(wrapper.get('[data-testid="voice-mic"]').text()).toBe("Mikrofon açık");
    for (let i = 0; i < 5; i++) media.frame(0.001);
    for (let i = 0; i < 10; i++) media.frame(0.2);
    expect(micLevel()).toBeGreaterThan(0.5); // the core follows the real microphone
    for (let i = 0; i < 10; i++) media.frame(0.001);
    await settle();
    expect(platform.voiceTranscribe).toHaveBeenCalledTimes(1);
    expect(bodies[0]).toMatchObject({ content: "Merhaba LAZIS", channel: "voice" });
    expect(vi.mocked(platform.voiceSynthesize).mock.calls.map((c) => c[0])).toEqual(["Merhaba efendim.", "Nasılsınız?"]);
    expect(speaker.played).toHaveLength(2);
    expect(voice.phase).toBe("listening");
    expect(voice.lastSttMs).not.toBeNull();
    expect(voice.lastFirstAudioMs).not.toBeNull();
  });

  it("never turns Yelda's voice into a user turn", async () => {
    const speaker = fakeSpeaker(true);
    const { platform, media, voice } = await setup({}, {}, fakeMedia(), speaker);
    await voice.startSession();
    for (let i = 0; i < 10; i++) media.frame(0.2);
    for (let i = 0; i < 10; i++) media.frame(0.001);
    await settle();
    expect(voice.phase).toBe("speaking");
    // Loud audio while LAZIS speaks (its own voice from the speakers) is ignored.
    for (let i = 0; i < 30; i++) media.frame(0.3);
    speaker.release();
    await settle();
    speaker.release();
    await settle();
    expect(voice.phase).toBe("listening");
    // The tail right after speech is ignored too.
    for (let i = 0; i < 3; i++) media.frame(0.3);
    expect(voice.detector.speaking).toBe(false);
    expect(platform.voiceTranscribe).toHaveBeenCalledTimes(1);
    expect(RESUME_AFTER_SPEECH_MS).toBeGreaterThan(0);
  });

  it("silence is not transcribed and Whisper's noise is not sent", async () => {
    const { platform, bodies, voice } = await setup({ voiceTranscribe: vi.fn().mockResolvedValue("Altyazı M.K.") });
    await voice.handle({ wav: new Uint8Array(100), seconds: 1, peak: 0.0001 });
    expect(platform.voiceTranscribe).not.toHaveBeenCalled();
    expect(voice.error).toBe("heard_nothing");
    await voice.handle({ wav: new Uint8Array(100), seconds: 1, peak: 0.2 });
    expect(platform.voiceTranscribe).toHaveBeenCalledTimes(1);
    expect(bodies).toEqual([]);
  });

  it("a refused microphone is explained and the app carries on", async () => {
    const { wrapper, voice } = await setup({}, {}, fakeMedia({ fail: "NotAllowedError" }));
    await wrapper.get('[data-testid="voice-session-start"]').trigger("click");
    await flushPromises();
    expect(voice.mode).toBe("off");
    expect(voice.micOpen).toBe(false);
    expect(wrapper.get('[data-testid="voice-error"]').text()).toContain("Mikrofon izni verilmedi");
  });

  it("ending the session closes the microphone and frees the speech model", async () => {
    const { wrapper, platform, media, voice } = await setup();
    await voice.startSession();
    await flushPromises();
    await wrapper.get('[data-testid="voice-session-end"]').trigger("click");
    await flushPromises();
    expect(voice.micOpen).toBe(false);
    expect(media.track.stop).toHaveBeenCalled();
    expect(platform.voiceRelease).toHaveBeenCalled();
    expect(micLevel()).toBe(0);
  });

  it("stopping speech stops Yelda at once and skips the rest", async () => {
    const speaker = fakeSpeaker(true);
    const { wrapper, platform, voice } = await setup({}, {}, fakeMedia(), speaker);
    const speaking = voice.speak("Bir. İki. Üç.");
    await settle();
    expect(voice.phase).toBe("speaking");
    await wrapper.get('[data-testid="voice-stop"]').trigger("click");
    await speaking;
    expect(speaker.played).toHaveLength(1);
    expect(platform.voiceStopSpeaking).toHaveBeenCalled();
    expect(voice.phase).toBe("idle");
  });

  it("says why voice is unavailable when the speech model is missing", async () => {
    const { wrapper } = await setup({
      voiceStatus: vi.fn().mockResolvedValue({ stt_available: false, stt_reason: "stt_model_missing", stt_running: false, tts_available: true, tts_voice: "Yelda" }),
    });
    expect(wrapper.find('[data-testid="voice-session-start"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="voice-unavailable"]').text()).toContain("modeli henüz indirilmedi");
  });
});
