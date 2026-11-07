/**
 * The core's state for every part of the UI (Phase 14), from the real app state only. Also
 * drives the `--accent` colour on the document root, so text, HUD frames and the core change
 * together (CSS eases the colour over 900 ms, as in LAZOS).
 */
import { computed, ref, watch, type ComputedRef, type Ref } from "vue";
import { STATE_COLOR, type CoreState } from "@/core/palette";
import { coreState, ERROR_SHOWN_MS, FAULTS } from "@/core/state";
import { useAssistantStore } from "@/stores/assistant";
import { usePreferencesStore } from "@/stores/preferences";
import { useVoiceStore } from "@/stores/voice";

export interface CoreHandle {
  state: ComputedRef<CoreState>;
  reducedMotion: ComputedRef<boolean>;
  error: Ref<boolean>;
}

let handle: CoreHandle | null = null;
let timer: ReturnType<typeof setTimeout> | null = null;

export function useCore(): CoreHandle {
  if (handle) return handle;
  const assistant = useAssistantStore();
  const voice = useVoiceStore();
  const preferences = usePreferencesStore();
  const error = ref(false);
  const flag = () => {
    error.value = true;
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => (error.value = false), ERROR_SHOWN_MS);
  };
  watch(
    () => assistant.errorCode,
    (code) => code !== null && code !== "llm_cancelled" && flag(),
  );
  watch(
    () => voice.error,
    (code) => code !== null && FAULTS.has(code) && flag(),
  );
  const state = computed(() =>
    coreState({
      voiceMode: voice.mode,
      voicePhase: voice.phase,
      assistantPhase: assistant.phase,
      error: error.value,
    }),
  );
  const system = typeof matchMedia === "function" ? matchMedia("(prefers-reduced-motion: reduce)").matches : false;
  const reducedMotion = computed(() => system || preferences.values.reduceMotion === "on");
  watch(
    state,
    (s) => {
      if (typeof document === "undefined") return;
      document.documentElement.style.setProperty("--accent", STATE_COLOR[s]);
      document.documentElement.dataset.coreState = s;
    },
    { immediate: true },
  );
  handle = { state, reducedMotion, error };
  return handle;
}

/** Tests: forget the shared handle (each test has its own Pinia). */
export function resetCoreForTests(): void {
  handle = null;
  if (timer) clearTimeout(timer);
  timer = null;
}
