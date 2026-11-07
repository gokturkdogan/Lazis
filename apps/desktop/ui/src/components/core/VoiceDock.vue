<script setup lang="ts">
/**
 * Voice controls under the core (Phase 14): one session the user starts and ends — no
 * push-to-talk. While the session is open the microphone is on and says so; "Sesli yanıtı
 * durdur" stops Yelda at once. Nothing here opens the microphone by itself.
 */
import { computed, onBeforeUnmount, onMounted } from "vue";
import { useI18n } from "vue-i18n";
import { useAssistantStore } from "@/stores/assistant";
import { useVoiceStore } from "@/stores/voice";

const { t } = useI18n();
const voice = useVoiceStore();
const assistant = useAssistantStore();

const unavailable = computed(() => {
  if (voice.status === null) return t("voice.unavailable");
  const reason = voice.status.stt_reason;
  return reason ? t(`voice.reason.${reason}`) : null;
});

const errorText = computed(() => {
  const code = voice.error;
  if (!code) return null;
  const key = `voice.error.${code}`;
  return t(key) === key ? t("voice.error.stt_failed") : t(key);
});

onMounted(() => void voice.refresh());
// Leaving the conversation view (or closing the window) ends the session: microphone off.
onBeforeUnmount(() => void voice.endSession());
</script>

<template>
  <div class="dock glass" data-testid="voice">
    <span class="mic" :class="{ on: voice.micOpen }" data-testid="voice-mic" role="status" aria-live="polite">
      <span class="dot" aria-hidden="true" />{{ voice.micOpen ? t("voice.micOn") : t("voice.micOff") }}
    </span>
    <template v-if="voice.canListen">
      <button
        v-if="voice.mode !== 'session'"
        class="session"
        type="button"
        data-testid="voice-session-start"
        :disabled="!assistant.canSend"
        @click="voice.startSession()"
      >
        {{ t("voice.startSession") }}
      </button>
      <button v-else class="session active" type="button" data-testid="voice-session-end" @click="voice.endSession()">
        {{ t("voice.endSession") }}
      </button>
    </template>
    <span v-else class="note" data-testid="voice-unavailable">{{ unavailable }}</span>
    <button v-if="voice.phase === 'speaking'" class="btn stop" type="button" data-testid="voice-stop" @click="voice.stopSpeaking()">
      {{ t("voice.stop") }}
    </button>
    <label v-if="voice.status?.tts_available" class="speak">
      <input type="checkbox" :checked="voice.speakReplies" data-testid="voice-speak" @change="voice.setSpeakReplies(($event.target as HTMLInputElement).checked)" />
      {{ t("voice.speakReplies") }}
    </label>
    <p v-if="errorText" class="error" role="alert" data-testid="voice-error">{{ errorText }}</p>
  </div>
</template>

<style scoped>
.dock {
  position: absolute;
  left: 50%;
  bottom: 24px;
  transform: translateX(-50%);
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 10px 16px;
  border-radius: 999px;
  max-width: calc(100% - 48px);
  z-index: 5;
}
.mic {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-family: var(--font-display);
  font-size: 10.5px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--text-muted);
}
.dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--text-faint);
}
.mic.on {
  color: #fff;
}
.mic.on .dot {
  background: #ff1744;
  box-shadow: 0 0 10px #ff1744;
}
.session {
  font-family: var(--font-display);
  letter-spacing: 0.16em;
  text-transform: uppercase;
  font-size: 11.5px;
  padding: 9px 18px;
  border-radius: 999px;
  border: 1px solid color-mix(in srgb, var(--accent) 55%, transparent);
  background: color-mix(in srgb, var(--accent) 14%, transparent);
  color: #fff;
  box-shadow: 0 0 22px -6px var(--accent);
}
.session.active {
  background: color-mix(in srgb, var(--accent) 26%, transparent);
}
.session:disabled {
  opacity: 0.45;
  cursor: default;
}
.stop {
  border-radius: 999px;
}
.speak {
  display: inline-flex;
  gap: 6px;
  align-items: center;
  font-size: 12px;
  color: var(--text-muted);
}
.note {
  font-size: 12px;
  color: var(--text-muted);
}
.error {
  flex-basis: 100%;
  margin: 0;
  text-align: center;
  font-size: 12px;
  color: #ff4d6a;
}
</style>
