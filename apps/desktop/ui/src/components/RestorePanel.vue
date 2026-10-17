<script setup lang="ts">
import { ref } from "vue";
import { useI18n } from "vue-i18n";
import { errorKey } from "@/i18n";
import { useConnectionStore } from "@/stores/connection";

const store = useConnectionStore();
const { t } = useI18n();
const code = ref("");
const busy = ref(false);
const error = ref<string | null>(null);

async function submit() {
  busy.value = true;
  error.value = null;
  try {
    await store.restore(code.value);
    code.value = "";
  } catch (e) {
    error.value = e instanceof Error ? e.message : "internal_error";
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <section class="restore panel" data-testid="restore-panel">
    <h2>{{ t("recovery.restoreTitle") }}</h2>
    <p class="muted">{{ t("recovery.restoreIntro") }}</p>
    <form @submit.prevent="submit">
      <label for="recovery-code">{{ t("recovery.restoreLabel") }}</label>
      <input
        id="recovery-code"
        v-model="code"
        class="mono"
        type="text"
        autocomplete="off"
        autocorrect="off"
        autocapitalize="characters"
        spellcheck="false"
        placeholder="LZR1-XXXXX-XXXXX-…"
      />
      <p v-if="error" class="error" data-testid="restore-error">{{ t(errorKey(error)) }}</p>
      <button class="btn btn-primary" type="submit" :disabled="busy || code.trim().length < 20">
        {{ busy ? t("recovery.restoreBusy") : t("recovery.restoreAction") }}
      </button>
    </form>
  </section>
</template>

<style scoped>
.restore {
  max-width: 640px;
  padding: 24px 26px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
h2,
p {
  margin: 0;
}
form {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
input {
  padding: 12px 14px;
  border-radius: 10px;
  border: 1px solid var(--panel-border-strong);
  background: rgba(6, 10, 19, 0.9);
  color: var(--text);
  user-select: text;
}
.error {
  color: var(--danger);
}
button {
  align-self: flex-start;
}
</style>
