import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ApiClient, TurnSubmitRequest } from "@/api/client";
import VoicePanel from "@/components/VoicePanel.vue";
import { createAppI18n } from "@/i18n";
import type { Platform } from "@/platform/tauri";
import { useAssistantStore } from "@/stores/assistant";
import { useConnectionStore } from "@/stores/connection";
import { useMediaForTests, useVoiceStore } from "@/stores/voice";
import type { MediaAccess } from "@/voice/recorder";
import { assistantFixture, connection, fakeClient, fakePlatform, messageFixture } from "./fixtures";

type Frame = (level: number) => void;

function fakeMedia(options: { fail?: string } = {}) {
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
        createScriptProcessor: () => {
          const node = {
            connect: vi.fn(),
            disconnect: vi.fn(),
            set onaudioprocess(f: typeof process) {
              process = f;
            },
            get onaudioprocess() {
              return process;
            },
          };
          return node;
        },
        close: vi.fn(async () => undefined),
      }) as unknown as AudioContext,
  };
  const frame: Frame = (level) =>
    process?.({ inputBuffer: { getChannelData: () => new Float32Array(1600).fill(level) } }); // 100 ms
  return { media, track, frame };
}

async function setup(platform: Partial<Platform> = {}, client: Partial<ApiClient> = {}, media = fakeMedia()) {
  const pinia = createPinia();
  setActivePinia(pinia);
  useMediaForTests(media.media);
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
  const wrapper = mount(VoicePanel, { global: { plugins: [pinia, createAppI18n()] } });
  await flushPromises();
  return { wrapper, platform: p, bodies, media, voice: useVoiceStore() };
}

describe("Voice (Phase 13)", () => {
  afterEach(() => {
    useAssistantStore().stop();
    useConnectionStore().stop();
  });

  it("starts with the microphone off and never opens it by itself", async () => {
    const { wrapper, media, voice } = await setup();
    expect(voice.micOpen).toBe(false);
    expect(wrapper.get('[data-testid="voice-mic"]').text()).toBe("Mikrofon kapalı");
    expect(media.media.getUserMedia).not.toHaveBeenCalled();
  });

  it("push-to-talk: mic on while held, off on release, then a voice message and a spoken reply", async () => {
    const { wrapper, platform, bodies, media, voice } = await setup();
    await voice.pttStart();
    expect(voice.micOpen).toBe(true);
    expect(wrapper.get('[data-testid="voice-mic"]').text()).toContain("Mikrofon açık");
    for (let i = 0; i < 10; i++) media.frame(0.2); // one second of speech
    await voice.pttEnd();
    await flushPromises();
    expect(media.track.stop).toHaveBeenCalled(); // the system microphone indicator goes off
    expect(voice.micOpen).toBe(false);
    expect(platform.voiceTranscribe).toHaveBeenCalledTimes(1);
    expect(bodies[0]).toMatchObject({ content: "Merhaba LAZIS", channel: "voice" });
    expect(vi.mocked(platform.voiceSpeak).mock.calls.map((c) => c[0])).toEqual(["Merhaba efendim.", "Nasılsınız?"]);
    expect(voice.phase).toBe("idle");
  });

  it("silence is not transcribed and noise is not sent", async () => {
    const { platform, bodies, media, voice } = await setup({ voiceTranscribe: vi.fn().mockResolvedValue("Altyazı M.K.") });
    await voice.pttStart();
    for (let i = 0; i < 10; i++) media.frame(0.0001);
    await voice.pttEnd();
    expect(platform.voiceTranscribe).not.toHaveBeenCalled();
    expect(voice.error).toBe("heard_nothing");
    await voice.pttStart();
    for (let i = 0; i < 10; i++) media.frame(0.2);
    await voice.pttEnd();
    await flushPromises();
    expect(platform.voiceTranscribe).toHaveBeenCalledTimes(1);
    expect(bodies).toEqual([]);
  });

  it("a refused microphone is explained and the app carries on", async () => {
    const { wrapper, voice } = await setup({}, {}, fakeMedia({ fail: "NotAllowedError" }));
    await voice.pttStart();
    await flushPromises();
    expect(voice.mode).toBe("off");
    expect(voice.micOpen).toBe(false);
    expect(wrapper.get('[data-testid="voice-error"]').text()).toContain("Mikrofon izni verilmedi");
  });

  it("a hands-free session hears a turn, answers, and closes the microphone when ended", async () => {
    const { platform, bodies, media, voice } = await setup();
    await voice.startSession();
    expect(voice.micOpen).toBe(true);
    for (let i = 0; i < 5; i++) media.frame(0.001); // quiet: nothing kept but a short preroll
    for (let i = 0; i < 10; i++) media.frame(0.2); // speech
    for (let i = 0; i < 10; i++) media.frame(0.001); // a pause ends the turn
    await flushPromises();
    await flushPromises();
    expect(bodies).toHaveLength(1);
    expect(bodies[0]?.channel).toBe("voice");
    expect(voice.phase).toBe("listening");
    expect(voice.micOpen).toBe(true);
    await voice.endSession();
    expect(voice.micOpen).toBe(false);
    expect(media.track.stop).toHaveBeenCalled();
    expect(platform.voiceRelease).toHaveBeenCalled();
  });

  it("stopping speech stops the system voice and the remaining sentences", async () => {
    let resolveFirst: () => void = () => undefined;
    const speak = vi.fn(() => new Promise<void>((r) => (resolveFirst = r)));
    const { platform, voice } = await setup({ voiceSpeak: speak });
    const speaking = voice.speak("Bir. İki. Üç.");
    await flushPromises();
    expect(voice.phase).toBe("speaking");
    await voice.stopSpeaking();
    resolveFirst();
    await speaking;
    expect(platform.voiceStopSpeaking).toHaveBeenCalled();
    expect(speak).toHaveBeenCalledTimes(1);
    expect(voice.phase).toBe("idle");
  });

  it("says why voice is unavailable when the speech model is missing", async () => {
    const { wrapper } = await setup({
      voiceStatus: vi.fn().mockResolvedValue({ stt_available: false, stt_reason: "stt_model_missing", stt_running: false, tts_available: true, tts_voice: "Yelda" }),
    });
    expect(wrapper.find('[data-testid="voice-ptt"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="voice-unavailable"]').text()).toContain("modeli henüz indirilmedi");
  });
});
