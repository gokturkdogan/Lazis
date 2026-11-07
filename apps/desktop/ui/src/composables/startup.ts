/**
 * The start screen's steps (Phase 14 polish), each tied to a real stage; nothing advances on a
 * timer except the short "LAZIS hazır." confirmation after everything is really ready.
 *
 *   waking     the window is up, waiting for the shell's first report         (initializing)
 *   systems    the shell is starting the backend process                       (starting)
 *   memory     the backend is up; its state is read: the encrypted database
 *              that holds memory and history, app info, settings               (verifying)
 *   preparing  connected; the conversation and the model list are loading     (assistant init)
 *   ready      all of the above done; shown briefly, then the screen fades
 *   failed     the backend could not start: the real error and a retry
 *
 * Model warm-up is not a step here: it runs in the background and is shown where it happens.
 */
import { computed, onBeforeUnmount, ref, watch, type Ref } from "vue";
import { useAssistantStore } from "@/stores/assistant";
import { useConnectionStore } from "@/stores/connection";

export type StartupStep = "waking" | "systems" | "memory" | "preparing" | "ready" | "failed";

/** How long "LAZIS hazır." stays before the screen fades (a confirmation, not a wait). */
export const READY_HOLD_MS = 650;

export function useStartup(waitForAssistant: Ref<boolean>) {
  const connection = useConnectionStore();
  const assistant = useAssistantStore();
  const holding = ref(false);
  const dismissed = ref(false);
  let timer: ReturnType<typeof setTimeout> | null = null;

  const live = computed<StartupStep | null>(() => {
    switch (connection.phase) {
      case "initializing":
        return connection.verifying ? "memory" : "waking";
      case "starting":
        return connection.verifying ? "memory" : "systems";
      case "backend_failed":
        return "failed";
      case "connected":
        return waitForAssistant.value && !assistant.ready ? "preparing" : null;
      default:
        return null; // recovery and disconnection have their own screens
    }
  });

  // Once everything is ready, confirm briefly, then step aside.
  watch(
    live,
    (now, before) => {
      if (now !== null) {
        holding.value = false;
        if (timer !== null) clearTimeout(timer);
        timer = null;
        if (now !== "failed") dismissed.value = false;
        return;
      }
      if (before !== null && before !== undefined && before !== "failed" && connection.phase === "connected") {
        holding.value = true;
        timer = setTimeout(() => {
          holding.value = false;
          timer = null;
        }, READY_HOLD_MS);
      }
    },
    { immediate: true },
  );
  onBeforeUnmount(() => {
    if (timer !== null) clearTimeout(timer);
  });

  const step = computed<StartupStep | null>(() => live.value ?? (holding.value ? "ready" : null));
  const visible = computed(() => step.value !== null && !dismissed.value);

  return {
    step,
    visible,
    /** "Tanılama" from the error: step aside so the details can be read. */
    dismiss: () => (dismissed.value = true),
  };
}
