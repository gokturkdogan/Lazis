<script setup lang="ts">
/**
 * Voice controls (Phase 13): push-to-talk, a hands-free session the user starts and ends,
 * "read replies aloud", stop speaking, and a plain statement of whether the microphone is on.
 * Nothing here opens the microphone by itself.
 */
import { computed, onBeforeUnmount, onMounted } from "vue";
import { useI18n } from "vue-i18n";
import { useAssistantStore } from "@/stores/assistant";
import { useVoiceStore } from "@/stores/voice";

const { t } = useI18n();
const voice = useVoiceStore();
const assistant = useAssistantStore();

const unavailable = computed(() => {
  const reason = voice.status?.stt_reason;
  if (voice.status === null) return t("voice.unavailable");
  return reason ? t(`voice.reason.${reason}`) : null;
});

const state = computed(() => {
  if (voice.micOpen) return voice.mode === "session" ? t(`voice.phase.${voice.phase}`) : t("voice.phase.recording");
  if (voice.phase === "transcribing" || voice.phase === "thinking" || voice.phase === "speaking") {
    return t(`voice.phase.${voice.phase}`);
  }
  return t("voice.micOff");
});

const errorText = computed(() => {
  const code = voice.error;
  if (!code) return null;
  const key = `voice.error.${code}`;
  return t(key) === key ? t("voice.error.stt_failed") : t(key);
});

function holdStart(event: PointerEvent) {
  (event.target as HTMLElement).setPointerCapture?.(event.pointerId);
  void voice.pttStart();
}

function holdEnd() {
  void voice.pttEnd();
}

onMounted(() => void voice.refresh());
// Leaving the conversation view ends a session and releases the microphone.
onBeforeUnmount(() => {
  void voice.endSession();
  void voice.stopSpeaking();
});
</script>

<template>
  <section class="panel voice" data-testid="voice">
    <span class="mic" :class="{ on: voice.micOpen }" data-testid="voice-mic" role="status" aria-live="polite">
      <span class="dot" aria-hidden="true" />{{ state }}
    </span>
    <template v-if="voice.canListen">
      <button
        class="btn"
        type="button"
        data-testid="voice-ptt"
        :disabled="voice.mode === 'session' || !assistant.canSend"
        @pointerdown.prevent="holdStart"
        @pointerup="holdEnd"
        @pointercancel="holdEnd"
        @keydown.space.prevent="voice.pttStart()"
        @keyup.space.prevent="voice.pttEnd()"
      >
        {{ voice.mode === "ptt" ? t("voice.release") : t("voice.hold") }}
      </button>
      <button
        v-if="voice.mode !== 'session'"
        class="btn"
        type="button"
        data-testid="voice-session-start"
        :disabled="voice.mode !== 'off'"
        @click="voice.startSession()"
      >
        {{ t("voice.startSession") }}
      </button>
      <button v-else class="btn btn-primary" type="button" data-testid="voice-session-end" @click="voice.endSession()">
        {{ t("voice.endSession") }}
      </button>
    </template>
    <span v-else class="muted small" data-testid="voice-unavailable">{{ unavailable }}</span>
    <button v-if="voice.phase === 'speaking'" class="btn" type="button" data-testid="voice-stop" @click="voice.stopSpeaking()">
      {{ t("voice.stop") }}
    </button>
    <label v-if="voice.status?.tts_available" class="small speak">
      <input type="checkbox" :checked="voice.speakReplies" data-testid="voice-speak" @change="voice.setSpeakReplies(($event.target as HTMLInputElement).checked)" />
      {{ t("voice.speakReplies") }}
    </label>
    <p v-if="voice.heard && voice.phase !== 'idle'" class="muted small heard" data-testid="voice-heard">{{ t("voice.heard", { text: voice.heard }) }}</p>
    <p v-if="errorText" class="error small" role="alert" data-testid="voice-error">{{ errorText }}</p>
  </section>
</template>

<style scoped>
.voice {
  padding: 8px 14px;
  margin-bottom: 10px;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.mic {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-muted);
  margin-right: auto;
}
.dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--text-muted);
  opacity: 0.5;
}
.mic.on {
  color: var(--danger);
  font-weight: 600;
}
.mic.on .dot {
  background: var(--danger);
  opacity: 1;
}
.speak {
  display: inline-flex;
  gap: 4px;
  align-items: center;
}
.small {
  font-size: 12px;
}
.heard,
.error {
  flex-basis: 100%;
  margin: 0;
}
.error {
  color: var(--danger);
}
</style>
