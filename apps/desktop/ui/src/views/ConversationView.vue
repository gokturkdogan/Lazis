<script setup lang="ts">
import { onBeforeUnmount, onMounted } from "vue";
import ConversationSidebar from "@/components/ConversationSidebar.vue";
import ConversationThread from "@/components/ConversationThread.vue";
import { useConversationsStore } from "@/stores/conversations";

const store = useConversationsStore();

// Re-warm the open conversation when the window comes back (the model may have been
// unloaded after keep_alive while the app was in the background).
function onVisible() {
  if (document.visibilityState === "visible") void store.prepare();
}

onMounted(() => {
  if (!store.listLoaded) void store.init();
  else void store.refreshRuntime();
  document.addEventListener("visibilitychange", onVisible);
});
onBeforeUnmount(() => document.removeEventListener("visibilitychange", onVisible));
</script>

<template>
  <div class="conversations" data-testid="conversation-view">
    <ConversationSidebar />
    <ConversationThread />
  </div>
</template>

<style scoped>
.conversations {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(220px, 280px) 1fr;
  gap: 14px;
}
@media (max-width: 760px) {
  .conversations {
    grid-template-columns: 1fr;
    grid-template-rows: auto 1fr;
  }
}
</style>
