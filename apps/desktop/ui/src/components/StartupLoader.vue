<script setup lang="ts">
/**
 * The start screen (Phase 14 polish): the logo, a small neural mark and one line for the real
 * startup step (see composables/startup.ts), with a plain line under it saying what is
 * actually happening. The dots count real steps done, never time. On failure: the real error,
 * a retry, and the way to the details in Tanılama.
 */
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { LOGO } from "@/brand";
import NeuralSpinner from "@/components/NeuralSpinner.vue";
import StartupError from "@/components/StartupError.vue";
import type { StartupStep } from "@/composables/startup";

const props = defineProps<{ step: StartupStep }>();
const emit = defineEmits<{ diagnostics: [] }>();
const { t } = useI18n();

const ORDER: StartupStep[] = ["waking", "systems", "memory", "preparing", "ready"];
const done = computed(() => Math.max(0, ORDER.indexOf(props.step)));
</script>

<template>
  <div class="loader" :class="{ failed: step === 'failed', ready: step === 'ready' }" data-testid="startup-loader" :data-step="step">
    <div class="glow" aria-hidden="true" />
    <div class="glow glow--two" aria-hidden="true" />
    <div class="content">
      <div class="mark">
        <div class="mark-light" aria-hidden="true" />
        <img class="logo" :src="LOGO" alt="LAZIS" width="200" height="200" draggable="false" data-testid="starting-logo" />
      </div>

      <template v-if="step !== 'failed'">
        <div class="line" role="status" aria-live="polite">
          <NeuralSpinner v-if="step !== 'ready'" :size="30" />
          <Transition name="say" mode="out-in">
            <span :key="step" class="say" data-testid="startup-message">{{ t(`startup.${step}`) }}</span>
          </Transition>
        </div>
        <Transition name="say" mode="out-in">
          <p :key="step" class="plain" data-testid="startup-plain">{{ t(`startup.plain.${step}`) }}</p>
        </Transition>
        <ol class="steps" :aria-label="t('startup.progress', { done, total: ORDER.length - 1 })">
          <li v-for="(s, i) in ORDER.slice(0, -1)" :key="s" :class="{ done: i < done, now: i === done }" />
        </ol>
      </template>

      <div v-else class="trouble" data-testid="startup-failed">
        <StartupError />
        <button class="btn" type="button" data-testid="startup-diagnostics" @click="emit('diagnostics')">
          {{ t("startup.diagnostics") }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.loader {
  --brand-cyan: #3fd8ff;
  position: fixed;
  inset: 0;
  z-index: 80;
  display: grid;
  place-items: center;
  overflow: hidden;
  background:
    radial-gradient(ellipse 70% 55% at 50% 45%, rgb(0 70 120 / 0.28), transparent 70%),
    radial-gradient(circle at 50% 120%, rgb(0 40 80 / 0.35), transparent 60%),
    #01040b;
}
.glow {
  position: absolute;
  width: 760px;
  height: 760px;
  left: 50%;
  top: 44%;
  translate: -50% -50%;
  border-radius: 50%;
  background: radial-gradient(circle, rgb(63 216 255 / 0.12), transparent 62%);
  animation: swell 6s ease-in-out infinite;
  pointer-events: none;
}
.glow--two {
  width: 420px;
  height: 420px;
  background: radial-gradient(circle, rgb(0 191 255 / 0.14), transparent 65%);
  animation-duration: 4.2s;
  animation-delay: -1.4s;
}
.content {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 14px;
  padding: 24px;
  max-width: 680px;
}
.mark {
  position: relative;
  width: 200px;
  height: 200px;
  margin-bottom: 6px;
}
.mark-light {
  position: absolute;
  inset: 18%;
  border-radius: 50%;
  background: radial-gradient(circle, rgb(63 216 255 / 0.35), transparent 70%);
  filter: blur(18px);
  animation: swell 3.6s ease-in-out infinite;
}
.logo {
  position: relative;
  width: 200px;
  height: 200px;
  user-select: none;
}
.line {
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 32px;
}
.say {
  font-family: var(--font-display);
  font-size: 15px;
  letter-spacing: 0.16em;
  color: #d9f6ff;
  text-shadow: 0 0 14px rgb(63 216 255 / 0.45);
}
.ready .say {
  color: #fff;
}
.plain {
  margin: 0;
  font-size: 12px;
  color: var(--text-muted);
  letter-spacing: 0.02em;
}
.steps {
  display: flex;
  gap: 8px;
  margin: 8px 0 0;
  padding: 0;
  list-style: none;
}
.steps li {
  width: 22px;
  height: 3px;
  border-radius: 2px;
  background: rgb(63 216 255 / 0.14);
  transition: background 400ms ease, box-shadow 400ms ease;
}
.steps li.done {
  background: rgb(63 216 255 / 0.75);
  box-shadow: 0 0 8px rgb(63 216 255 / 0.5);
}
.steps li.now {
  background: rgb(63 216 255 / 0.35);
  animation: pulse-soft 1.6s ease-in-out infinite;
}
.trouble {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 10px;
  width: min(560px, 90vw);
}
.trouble > .btn {
  align-self: flex-start;
}
.failed .glow {
  background: radial-gradient(circle, rgb(255 23 68 / 0.08), transparent 62%);
}
.say-enter-active,
.say-leave-active {
  transition: opacity 260ms ease, transform 260ms ease;
}
.say-enter-from {
  opacity: 0;
  transform: translateY(4px);
}
.say-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
@keyframes swell {
  0%,
  100% {
    opacity: 0.65;
    scale: 0.97;
  }
  50% {
    opacity: 1;
    scale: 1.03;
  }
}
</style>
