<script setup lang="ts">
/**
 * First setup as a modal over the living core (Phase 14.1): a few optional questions, one at a
 * time, with a progress indicator. Nothing is saved without the user pressing "Hafızaya kaydet"
 * (memory) or a choice button (style); every step can be skipped; "Sonra devam et" and "Bir
 * daha gösterme" are always there. Keyboard: focus stays inside, Escape = later.
 */
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { ApiError, type MemoryApplyResult } from "@/api/client";
import Icon from "@/components/Icon.vue";
import { useFocusTrap } from "@/composables/focusTrap";
import { errorKey } from "@/i18n";
import { currentApiClient } from "@/stores/connection";
import { LAST_STEP, useOnboardingStore } from "@/stores/onboarding";

const { t } = useI18n();
const onboarding = useOnboardingStore();
const dialog = ref<HTMLElement | null>(null);
const text = ref("");
const busy = ref(false);
const error = ref<string | null>(null);
const open = computed(() => onboarding.visible);

useFocusTrap(dialog, open, () => onboarding.later());

function advance() {
  text.value = "";
  error.value = null;
  onboarding.next();
}

async function save(action: () => Promise<unknown>) {
  if (currentApiClient() === null) {
    error.value = t(errorKey("backend_unreachable"));
    return;
  }
  busy.value = true;
  error.value = null;
  try {
    await action();
    advance();
  } catch (e) {
    error.value = t(errorKey(e instanceof ApiError ? e.code : null));
  } finally {
    busy.value = false;
  }
}

async function saveMemory(predicate: string) {
  const value = text.value.trim();
  if (value === "") return;
  await save(async () => {
    const result: MemoryApplyResult = await currentApiClient()!.addMemory({ predicate, value, statement: "" });
    // Refused or only sent for review: do not move on as if it were saved.
    if (result.created + result.updated + result.superseded === 0) {
      throw new ApiError(0, "memory_invalid", "", false);
    }
  });
}

function saveStyle(dimension: "address" | "verbosity", value: string) {
  return save(() => currentApiClient()!.setStyle(dimension, value));
}
</script>

<template>
  <Transition name="modal">
    <div v-if="open" class="backdrop" data-testid="onboarding">
      <div
        ref="dialog"
        class="dialog glass brackets"
        role="dialog"
        aria-modal="true"
        aria-labelledby="onboarding-title"
        tabindex="-1"
      >
        <header>
          <div class="hud-label accent-text" id="onboarding-title">{{ t("intake.title") }}</div>
          <ol class="progress" :aria-label="t('intake.intro', { step: Math.min(onboarding.step + 1, LAST_STEP), total: LAST_STEP })">
            <li v-for="i in LAST_STEP" :key="i" :class="{ done: i <= onboarding.step, current: i === onboarding.step + 1 }" />
          </ol>
          <button class="icon-btn" type="button" :aria-label="t('intake.pause')" data-testid="intake-close" @click="onboarding.later()">
            <Icon name="x" />
          </button>
        </header>

        <Transition name="step" mode="out-in">
          <section v-if="!onboarding.finished" :key="onboarding.step" class="step">
            <p class="muted small">{{ t("intake.intro", { step: onboarding.step + 1, total: LAST_STEP }) }}</p>
            <template v-if="onboarding.step === 0">
              <label for="intake-name" class="question">{{ t("intake.name") }}</label>
              <input id="intake-name" v-model="text" maxlength="60" data-testid="intake-name" data-autofocus @keydown.enter.prevent="saveMemory('preferred_name')" />
              <div class="choices">
                <button class="btn btn-primary" type="button" :disabled="busy || text.trim() === ''" @click="saveMemory('preferred_name')">{{ t("intake.save") }}</button>
              </div>
            </template>
            <template v-else-if="onboarding.step === 1">
              <p class="question">{{ t("intake.address") }}</p>
              <div class="choices">
                <button class="btn" type="button" :disabled="busy" data-autofocus @click="saveStyle('address', 'siz')">{{ t("style.option.address.siz") }}</button>
                <button class="btn" type="button" :disabled="busy" @click="saveStyle('address', 'sen')">{{ t("style.option.address.sen") }}</button>
              </div>
            </template>
            <template v-else-if="onboarding.step === 2">
              <p class="question">{{ t("intake.length") }}</p>
              <div class="choices">
                <button class="btn" type="button" :disabled="busy" data-autofocus @click="saveStyle('verbosity', '3')">{{ t("style.option.verbosity.3") }}</button>
                <button class="btn" type="button" :disabled="busy" @click="saveStyle('verbosity', '7')">{{ t("style.option.verbosity.7") }}</button>
              </div>
            </template>
            <template v-else>
              <label for="intake-topic" class="question">{{ t("intake.topic") }}</label>
              <input id="intake-topic" v-model="text" maxlength="200" data-testid="intake-topic" data-autofocus />
              <div class="choices">
                <button class="btn" type="button" :disabled="busy || text.trim() === ''" @click="saveMemory('goal')">{{ t("intake.asGoal") }}</button>
                <button class="btn" type="button" :disabled="busy || text.trim() === ''" @click="saveMemory('interest')">{{ t("intake.asInterest") }}</button>
              </div>
            </template>
            <p v-if="error" class="error small" role="alert">{{ error }}</p>
          </section>
          <section v-else key="done" class="step">
            <p class="question">{{ t("intake.done") }}</p>
            <ul class="muted small notes">
              <li>{{ t("intake.doneMemory") }}</li>
              <li>{{ t("intake.doneReminder") }}</li>
            </ul>
          </section>
        </Transition>

        <footer>
          <template v-if="!onboarding.finished">
            <button class="link" type="button" :disabled="busy" data-testid="intake-never" @click="onboarding.close()">{{ t("intake.never") }}</button>
            <span class="spacer" />
            <button class="btn" type="button" :disabled="busy" data-testid="intake-pause" @click="onboarding.later()">{{ t("intake.pause") }}</button>
            <button class="btn" type="button" :disabled="busy" data-testid="intake-skip" @click="advance">{{ t("intake.skip") }}</button>
          </template>
          <template v-else>
            <span class="spacer" />
            <button class="btn btn-primary" type="button" data-testid="intake-finish" data-autofocus @click="onboarding.close()">{{ t("intake.finish") }}</button>
          </template>
        </footer>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.backdrop {
  position: fixed;
  inset: 0;
  z-index: 60;
  display: grid;
  place-items: center;
  padding: 24px;
  background: rgb(2 5 11 / 0.35);
  backdrop-filter: blur(3px);
}
.dialog {
  width: min(520px, 100%);
  border-radius: 16px;
  padding: 18px 22px 16px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  outline: none;
}
header {
  display: flex;
  align-items: center;
  gap: 12px;
}
.progress {
  flex: 1;
  display: flex;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.progress li {
  flex: 1;
  height: 3px;
  border-radius: 2px;
  background: rgb(255 255 255 / 0.1);
  transition: background 400ms, box-shadow 400ms;
}
.progress li.done {
  background: color-mix(in srgb, var(--accent) 70%, transparent);
}
.progress li.current {
  background: var(--accent);
  box-shadow: 0 0 10px var(--accent);
}
.step {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 150px;
}
.question {
  margin: 0;
  font-size: 17px;
  color: #fff;
}
input {
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid var(--panel-border-strong);
  background: rgb(4 10 22 / 0.8);
  color: var(--text);
  font: inherit;
  user-select: text;
}
.choices {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.notes {
  margin: 0;
  padding-left: 18px;
}
footer {
  display: flex;
  align-items: center;
  gap: 8px;
}
.spacer {
  flex: 1;
}
.link {
  background: none;
  border: 0;
  padding: 4px 0;
  color: var(--text-muted);
  font-size: 12.5px;
}
.link:hover {
  color: var(--text);
}
.small {
  font-size: 12.5px;
  margin: 0;
}
.error {
  color: var(--danger);
}
.modal-enter-active,
.modal-leave-active {
  transition: opacity 260ms ease;
}
.modal-enter-active .dialog,
.modal-leave-active .dialog {
  transition: transform 320ms cubic-bezier(0.2, 0.8, 0.2, 1), opacity 320ms;
}
.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}
.modal-enter-from .dialog,
.modal-leave-to .dialog {
  transform: translateY(14px) scale(0.98);
  opacity: 0;
}
.step-enter-active,
.step-leave-active {
  transition: opacity 220ms, transform 220ms;
}
.step-enter-from {
  opacity: 0;
  transform: translateX(16px);
}
.step-leave-to {
  opacity: 0;
  transform: translateX(-16px);
}
</style>
