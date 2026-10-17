<script setup lang="ts">
import { onBeforeUnmount, onMounted } from "vue";
import AssistantThread from "@/components/AssistantThread.vue";
import { useAssistantStore } from "@/stores/assistant";

const store = useAssistantStore();

// Re-warm the active session when the window comes back (the model may have been
// unloaded after keep_alive while the app was in the background).
function onVisible() {
  if (document.visibilityState === "visible") void store.prepare();
}

onMounted(() => {
  if (!store.ready) void store.init();
  else void store.refreshRuntime();
  document.addEventListener("visibilitychange", onVisible);
});
onBeforeUnmount(() => document.removeEventListener("visibilitychange", onVisible));
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
