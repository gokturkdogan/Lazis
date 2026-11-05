<script setup lang="ts">
/**
 * First setup (Phase 10D): a few optional questions in a fixed form. No model call. Only what the
 * user types or picks is saved, through the existing endpoints, and any step can be skipped. Where
 * the user is stays in this window's local storage, so it holds no personal text.
 */
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { ApiError, type MemoryApplyResult } from "@/api/client";
import { errorKey } from "@/i18n";
import { currentApiClient } from "@/stores/connection";

type Status = "open" | "paused" | "done";
const KEY = "lazis.intake.v1";
const LAST_STEP = 4;

function read(): { status: Status; step: number } {
  try {
    const raw = JSON.parse(globalThis.localStorage?.getItem(KEY) ?? "null") as {
      status?: Status;
      step?: number;
    } | null;
    if (raw?.status && typeof raw.step === "number") return { status: raw.status, step: raw.step };
  } catch {
    // Unreadable state: start over; nothing was lost, the answers are saved apart.
  }
  return { status: "open", step: 0 };
}

const { t } = useI18n();
const saved = read();
const status = ref<Status>(saved.status);
const step = ref(saved.step);
const text = ref("");
const busy = ref(false);
const error = ref<string | null>(null);
const finished = computed(() => step.value >= LAST_STEP);

function remember() {
  try {
    globalThis.localStorage?.setItem(KEY, JSON.stringify({ status: status.value, step: step.value }));
  } catch {
    // Not stored: the form opens again next time. Nothing else depends on it.
  }
}

function next() {
  step.value += 1;
  text.value = "";
  error.value = null;
  remember();
}

function setStatus(value: Status) {
  status.value = value;
  remember();
}

async function save(action: () => Promise<unknown>) {
  const client = currentApiClient();
  if (client === null) {
    error.value = t(errorKey("backend_unreachable"));
    return;
  }
  busy.value = true;
  error.value = null;
  try {
    await action();
    next();
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
  <section v-if="status === 'open'" class="panel intake" data-testid="intake">
    <template v-if="!finished">
      <p class="muted small">{{ t("intake.intro", { step: step + 1, total: LAST_STEP }) }}</p>
      <template v-if="step === 0">
        <label for="intake-name">{{ t("intake.name") }}</label>
        <input id="intake-name" v-model="text" maxlength="60" data-testid="intake-name" />
        <button class="btn btn-primary" type="button" :disabled="busy || text.trim() === ''" @click="saveMemory('preferred_name')">
          {{ t("intake.save") }}
        </button>
      </template>
      <template v-else-if="step === 1">
        <p>{{ t("intake.address") }}</p>
        <button class="btn" type="button" :disabled="busy" @click="saveStyle('address', 'siz')">{{ t("style.option.address.siz") }}</button>
        <button class="btn" type="button" :disabled="busy" @click="saveStyle('address', 'sen')">{{ t("style.option.address.sen") }}</button>
      </template>
      <template v-else-if="step === 2">
        <p>{{ t("intake.length") }}</p>
        <button class="btn" type="button" :disabled="busy" @click="saveStyle('verbosity', '3')">{{ t("style.option.verbosity.3") }}</button>
        <button class="btn" type="button" :disabled="busy" @click="saveStyle('verbosity', '7')">{{ t("style.option.verbosity.7") }}</button>
      </template>
      <template v-else>
        <label for="intake-topic">{{ t("intake.topic") }}</label>
        <input id="intake-topic" v-model="text" maxlength="200" data-testid="intake-topic" />
        <button class="btn" type="button" :disabled="busy || text.trim() === ''" @click="saveMemory('goal')">{{ t("intake.asGoal") }}</button>
        <button class="btn" type="button" :disabled="busy || text.trim() === ''" @click="saveMemory('interest')">{{ t("intake.asInterest") }}</button>
      </template>
      <p v-if="error" class="error small" role="alert">{{ error }}</p>
      <div class="actions">
        <button class="btn" type="button" :disabled="busy" data-testid="intake-skip" @click="next">{{ t("intake.skip") }}</button>
        <button class="btn" type="button" :disabled="busy" data-testid="intake-pause" @click="setStatus('paused')">{{ t("intake.pause") }}</button>
        <button class="btn" type="button" :disabled="busy" data-testid="intake-never" @click="setStatus('done')">{{ t("intake.never") }}</button>
      </div>
    </template>
    <template v-else>
      <p>{{ t("intake.done") }}</p>
      <ul class="muted small">
        <li>{{ t("intake.doneMemory") }}</li>
        <li>{{ t("intake.doneReminder") }}</li>
      </ul>
      <button class="btn btn-primary" type="button" data-testid="intake-finish" @click="setStatus('done')">{{ t("intake.finish") }}</button>
    </template>
  </section>
  <p v-else-if="status === 'paused'" class="muted small resume">
    <button class="btn" type="button" data-testid="intake-resume" @click="setStatus('open')">{{ t("intake.resume") }}</button>
  </p>
</template>

<style scoped>
.intake {
  padding: 14px 16px;
  margin-bottom: 10px;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.intake > p,
.intake > label,
.intake > ul {
  flex-basis: 100%;
  margin: 0;
}
input {
  flex: 1;
  min-width: 220px;
  padding: 8px 10px;
  border-radius: 8px;
  border: 1px solid var(--panel-border-strong);
  background: rgba(6, 10, 19, 0.9);
  color: var(--text);
  font: inherit;
  user-select: text;
}
.actions {
  flex-basis: 100%;
  display: flex;
  gap: 8px;
}
.small {
  font-size: 12px;
}
.resume {
  margin: 0 0 8px;
}
.error {
  color: var(--danger);
}
</style>
