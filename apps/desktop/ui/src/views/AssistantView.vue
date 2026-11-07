<script setup lang="ts">
/**
 * The conversation view (Phase 14, LAZOS layout): the living core fills the stage with its HUD
 * and the voice controls; the written conversation sits in a glass panel on the right that the
 * user opens and closes. Closed, the core is the focus. Documents, research, the first setup and
 * the whole conversation history live in the panel as before.
 */
import { onBeforeUnmount, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import AssistantThread from "@/components/AssistantThread.vue";
import CoreCanvas from "@/components/core/CoreCanvas.vue";
import HudOverlay from "@/components/core/HudOverlay.vue";
import Icon from "@/components/Icon.vue";
import VoiceDock from "@/components/core/VoiceDock.vue";
import { useAssistantStore } from "@/stores/assistant";
import { onSystemWoke } from "@/stores/connection";

const CHAT_KEY = "lazis.chat.open";
const { t } = useI18n();
const store = useAssistantStore();

function readChat(): boolean {
  try {
    return globalThis.localStorage?.getItem(CHAT_KEY) !== "0";
  } catch {
    return true;
  }
}
const chatOpen = ref(readChat());
function toggleChat() {
  chatOpen.value = !chatOpen.value;
  try {
    globalThis.localStorage?.setItem(CHAT_KEY, chatOpen.value ? "1" : "0");
  } catch {
    // not remembered: open again next time
  }
}

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
    <section class="stage">
      <CoreCanvas />
      <HudOverlay :chat-open="chatOpen" />
      <VoiceDock />
      <button
        class="chat-toggle glass"
        type="button"
        data-testid="chat-toggle"
        :aria-pressed="chatOpen"
        @click="toggleChat"
      >
        <Icon name="panel" :size="15" />
        {{ chatOpen ? t("core.hideChat") : t("core.showChat") }}
      </button>
    </section>
    <Transition name="chat">
      <aside v-if="chatOpen" class="chat glass" data-testid="chat-panel">
        <header class="chat-head">
          <div class="hud-label accent-text">{{ t("core.conversation") }}</div>
        </header>
        <div class="chat-body">
          <AssistantThread />
        </div>
      </aside>
    </Transition>
  </div>
</template>

<style scoped>
.assistant {
  flex: 1;
  min-height: 0;
  display: flex;
  width: 100%;
}
.stage {
  position: relative;
  flex: 1;
  min-width: 0;
  overflow: hidden;
}
.chat-toggle {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  position: absolute;
  right: 20px;
  bottom: 30px;
  z-index: 6;
  padding: 8px 14px;
  border-radius: 999px;
  font-family: var(--font-display);
  font-size: 10.5px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--text);
}
.chat {
  position: relative;
  z-index: 4;
  margin: 12px 12px 12px 0;
  width: 440px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  border-radius: 14px;
  overflow: hidden;
}
.chat-head {
  height: 44px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  padding: 0 16px;
  border-bottom: 1px solid rgb(255 255 255 / 0.06);
}
.chat-body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 12px;
}
.chat-enter-active,
.chat-leave-active {
  transition: opacity 0.35s cubic-bezier(0.2, 0.8, 0.2, 1), transform 0.35s cubic-bezier(0.2, 0.8, 0.2, 1);
}
.chat-enter-from,
.chat-leave-to {
  opacity: 0;
  transform: translateX(24px);
}
@media (max-width: 1100px) {
  .chat {
    width: 380px;
  }
}
</style>
