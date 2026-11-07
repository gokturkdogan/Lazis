<script setup lang="ts">
/**
 * The conversation view (Phase 14, LAZOS layout): the living core fills the stage with its HUD
 * and the voice controls; the written conversation sits in a glass panel on the right that the
 * user opens and closes. Closed, the core is the focus. Documents, research and the whole
 * conversation history live in the panel as before.
 *
 * Phase 14.1: the panel closes with a small chevron at the right of its header, and a slim
 * chevron tab on the stage's edge brings it back. No text on either; both are labelled for
 * screen readers, and focus moves to the other one so the keyboard is never stranded.
 */
import { nextTick, onBeforeUnmount, onMounted, ref } from "vue";
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
const collapse = ref<HTMLButtonElement | null>(null);
const expand = ref<HTMLButtonElement | null>(null);
async function toggleChat() {
  chatOpen.value = !chatOpen.value;
  try {
    globalThis.localStorage?.setItem(CHAT_KEY, chatOpen.value ? "1" : "0");
  } catch {
    // not remembered: open again next time
  }
  await nextTick();
  (chatOpen.value ? collapse.value : expand.value)?.focus({ preventScroll: true });
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
      <Transition name="tab">
        <button
          v-if="!chatOpen"
          ref="expand"
          class="chat-tab chevron-btn"
          type="button"
          data-testid="chat-toggle"
          aria-controls="chat-panel"
          :aria-expanded="false"
          :aria-label="t('core.showChat')"
          :title="t('core.showChat')"
          @click="toggleChat"
        >
          <Icon name="chevron-left" :size="16" />
        </button>
      </Transition>
    </section>
    <Transition name="chat">
      <aside v-if="chatOpen" id="chat-panel" class="chat glass" data-testid="chat-panel" :aria-label="t('core.conversation')">
        <header class="chat-head">
          <div class="hud-label accent-text">{{ t("core.conversation") }}</div>
          <button
            ref="collapse"
            class="chevron-btn"
            type="button"
            data-testid="chat-toggle"
            aria-controls="chat-panel"
            :aria-expanded="true"
            :aria-label="t('core.hideChat')"
            :title="t('core.hideChat')"
            @click="toggleChat"
          >
            <Icon name="chevron-right" :size="16" />
          </button>
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
/* A small, quiet chevron: no frame until hovered, then the state colour and a soft glow. */
.chevron-btn {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  padding: 0;
  border-radius: 8px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition: color 180ms ease, background 180ms ease, border-color 180ms ease, box-shadow 220ms ease;
}
.chevron-btn:hover,
.chevron-btn:focus-visible {
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 10%, transparent);
  border-color: color-mix(in srgb, var(--accent) 35%, transparent);
  box-shadow: 0 0 14px color-mix(in srgb, var(--accent) 30%, transparent);
}
.chevron-btn :deep(svg) {
  transition: transform 180ms ease;
}
.chat-head .chevron-btn:hover :deep(svg) {
  transform: translateX(2px);
}
/* Closed: a slim glass tab on the stage's right edge, easy to find, never in the way. */
.chat-tab {
  position: absolute;
  right: 0;
  top: 50%;
  z-index: 6;
  width: 26px;
  height: 64px;
  transform: translateY(-50%);
  border-radius: 10px 0 0 10px;
  border: 1px solid rgb(255 255 255 / 0.08);
  border-right: 0;
  background: rgb(4 10 22 / 0.55);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
}
.chat-tab:hover :deep(svg) {
  transform: translateX(-2px);
}
.tab-enter-active {
  transition: opacity 240ms ease 180ms;
}
.tab-leave-active {
  transition: opacity 120ms ease;
}
.tab-enter-from,
.tab-leave-to {
  opacity: 0;
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
  justify-content: space-between;
  padding: 0 10px 0 16px;
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
  transition: opacity 0.38s cubic-bezier(0.2, 0.8, 0.2, 1), transform 0.38s cubic-bezier(0.2, 0.8, 0.2, 1);
}
.chat-enter-from,
.chat-leave-to {
  opacity: 0;
  transform: translateX(calc(100% + 12px));
}
@media (max-width: 1100px) {
  .chat {
    width: 380px;
  }
}
</style>
