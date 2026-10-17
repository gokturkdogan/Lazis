<script setup lang="ts">
import { onBeforeUnmount, onMounted } from "vue";
import AssistantThread from "@/components/AssistantThread.vue";
import { useAssistantStore } from "@/stores/assistant";
import { onSystemWoke } from "@/stores/connection";

const store = useAssistantStore();

// Window shown again: re-check an unreachable runtime, or re-warm the active session (the
// model may have been unloaded after keep_alive while the app was in the background).
function onVisible() {
  if (document.visibilityState === "visible") store.onVisible();
}
let offWake: (() => void) | null = null;

onMounted(() => {
  void store.resume();
  document.addEventListener("visibilitychange", onVisible);
  offWake = onSystemWoke(() => void store.onWake());
});
onBeforeUnmount(() => {
  document.removeEventListener("visibilitychange", onVisible);
  offWake?.();
});
</script>

<template>
  <div class="assistant" data-testid="assistant-view">
    <AssistantThread />
  </div>
</template>

<style scoped>
.assistant {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  width: 100%;
  max-width: 980px;
  margin: 0 auto;
}
</style>
