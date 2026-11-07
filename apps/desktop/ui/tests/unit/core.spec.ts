import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import CoreCanvas from "@/components/core/CoreCanvas.vue";
import { LOOKS, STATE_COLOR } from "@/core/palette";
import { coreState, FAULTS } from "@/core/state";
import { resetCoreForTests, useCore } from "@/core/useCore";
import { createAppI18n } from "@/i18n";
import { useAssistantStore } from "@/stores/assistant";
import { useConnectionStore } from "@/stores/connection";
import { useVoiceStore } from "@/stores/voice";
import AssistantView from "@/views/AssistantView.vue";
import { micLevel, scaleLevel, setMicLevel, setSpeechAnalyser, speechLevel } from "@/voice/levels";
import { assistantFixture, connection, fakeClient, fakePlatform } from "./fixtures";

describe("the living core (Phase 14)", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    resetCoreForTests();
  });
  afterEach(() => {
    useAssistantStore().stop();
    useConnectionStore().stop();
    vi.useRealTimers();
  });

  it("uses exactly the owner's five colours", () => {
    expect(STATE_COLOR).toEqual({
      idle: "#00BFFF",
      listening: "#A855F7",
      thinking: "#FFD600",
      speaking: "#00E676",
      error: "#FF1744",
    });
    expect(Object.keys(LOOKS)).toHaveLength(5);
  });

  it("shows only the real state", () => {
    const base = { voiceMode: "off", voicePhase: "idle", assistantPhase: "idle", error: false } as const;
    expect(coreState(base)).toBe("idle");
    expect(coreState({ ...base, voiceMode: "session", voicePhase: "listening" })).toBe("listening");
    expect(coreState({ ...base, voiceMode: "session", voicePhase: "transcribing" })).toBe("thinking");
    expect(coreState({ ...base, voiceMode: "session", voicePhase: "thinking" })).toBe("thinking");
    expect(coreState({ ...base, assistantPhase: "streaming" })).toBe("thinking"); // a typed message
    expect(coreState({ ...base, voiceMode: "session", voicePhase: "speaking" })).toBe("speaking");
    expect(coreState({ ...base, voicePhase: "speaking", error: true })).toBe("error");
    expect(coreState({ ...base, voicePhase: "listening" })).toBe("idle"); // no session, no listening
    expect(FAULTS.has("heard_nothing")).toBe(false);
  });

  it("sets the accent colour from the state, and a fault turns red for a while", async () => {
    vi.useFakeTimers();
    const core = useCore();
    const voice = useVoiceStore();
    expect(document.documentElement.style.getPropertyValue("--accent")).toBe("#00BFFF");
    voice.mode = "session";
    voice.phase = "listening";
    await flushPromises();
    expect(core.state.value).toBe("listening");
    expect(document.documentElement.style.getPropertyValue("--accent")).toBe("#A855F7");
    voice.error = "mic_denied";
    await flushPromises();
    expect(core.state.value).toBe("error");
    vi.advanceTimersByTime(6100);
    await flushPromises();
    expect(core.state.value).toBe("listening");
    voice.error = "heard_nothing"; // not a fault
    await flushPromises();
    expect(core.state.value).toBe("listening");
  });

  it("audio levels come from real sources and decay when they stop", () => {
    vi.useFakeTimers();
    expect(scaleLevel(0)).toBe(0);
    expect(scaleLevel(1)).toBe(1);
    setMicLevel(0.1);
    expect(micLevel()).toBeGreaterThan(0.5);
    vi.advanceTimersByTime(500);
    expect(micLevel()).toBe(0);
    expect(speechLevel()).toBe(0);
    setSpeechAnalyser({ fftSize: 32, getFloatTimeDomainData: (a: Float32Array) => a.fill(0.05) } as unknown as AnalyserNode);
    expect(speechLevel()).toBeCloseTo(scaleLevel(0.05));
    setSpeechAnalyser(null);
    expect(speechLevel()).toBe(0);
  });

  it("falls back to a still glow without WebGL", async () => {
    const wrapper = mount(CoreCanvas, { global: { plugins: [createAppI18n()] } });
    await vi.waitFor(() => expect(wrapper.find('[data-testid="core-fallback"]').exists()).toBe(true), { timeout: 4000 });
    wrapper.unmount();
  });

  it("the conversation view: core, HUD, voice dock, and a chat panel that opens and closes", async () => {
    const client = fakeClient({ assistantState: vi.fn().mockResolvedValue(assistantFixture({ timeline_messages: 0 })) });
    await useConnectionStore().start({ platform: fakePlatform(connection()), clientFactory: () => client });
    const wrapper = mount(AssistantView, { global: { plugins: [createAppI18n()] } });
    await flushPromises();
    expect(wrapper.find('[data-testid="core"]').exists()).toBe(true);
    expect(wrapper.get('[data-testid="core-label"]').text()).toBe("BEKLEMEDE");
    expect(wrapper.find('[data-testid="voice-session-start"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="voice-ptt"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="chat-panel"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="composer"]').exists()).toBe(true); // typing still works
    expect(wrapper.find('[data-testid="documents"]').exists()).toBe(true);
    await wrapper.get('[data-testid="chat-toggle"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-testid="chat-panel"]').exists()).toBe(false);
    await wrapper.get('[data-testid="chat-toggle"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-testid="chat-panel"]').exists()).toBe(true);
    wrapper.unmount();
  });
});
