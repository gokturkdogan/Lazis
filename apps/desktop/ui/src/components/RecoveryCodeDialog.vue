<script setup lang="ts">
/**
 * First-run recovery code (SECURITY_MODEL §5.1). The code is fetched from the Rust shell only
 * on explicit request, kept in component memory only, and cleared once acknowledged.
 */
import { onBeforeUnmount, ref } from "vue";
import { useI18n } from "vue-i18n";
import { errorKey } from "@/i18n";
import { platformErrorCode } from "@/platform/tauri";
import { useConnectionStore } from "@/stores/connection";

const store = useConnectionStore();
const { t } = useI18n();
const code = ref<string | null>(null);
const confirmed = ref(false);
const error = ref<string | null>(null);

async function reveal() {
  error.value = null;
  try {
    code.value = await store.revealRecoveryCode();
  } catch (e) {
    error.value = platformErrorCode(e);
  }
}

async function finish() {
  error.value = null;
  try {
    await store.acknowledgeRecovery();
    code.value = null;
  } catch (e) {
    error.value = platformErrorCode(e);
  }
}

onBeforeUnmount(() => {
  code.value = null;
});
</script>

<template>
  <div class="overlay" role="dialog" aria-modal="true" data-testid="recovery-dialog">
    <div class="dialog panel">
      <h2>{{ t("recovery.title") }}</h2>
      <p>{{ t("recovery.intro") }}</p>
      <p class="warning">{{ t("recovery.warning") }}</p>
      <div v-if="code" class="code mono" data-testid="recovery-code">{{ code }}</div>
      <button v-else class="btn" type="button" @click="reveal">{{ t("recovery.reveal") }}</button>
      <label v-if="code" class="confirm">
        <input v-model="confirmed" type="checkbox" />
        {{ t("recovery.confirm") }}
      </label>
      <p v-if="error" class="error">{{ t(errorKey(error)) }}</p>
      <div class="actions">
        <button class="btn btn-primary" type="button" :disabled="!code || !confirmed" @click="finish">
          {{ t("recovery.done") }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  display: grid;
  place-items: center;
  background: rgba(3, 6, 12, 0.72);
  backdrop-filter: blur(6px);
  z-index: 10;
}
.dialog {
  width: min(620px, calc(100vw - 48px));
  padding: 26px 28px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
h2 {
  margin: 0;
}
p {
  margin: 0;
}
.warning {
  color: var(--warn);
}
.code {
  padding: 16px;
  border-radius: 10px;
  border: 1px solid var(--panel-border-strong);
  background: rgba(6, 10, 19, 0.9);
  font-size: 15px;
  letter-spacing: 0.04em;
  word-break: break-all;
}
.confirm {
  display: flex;
  gap: 10px;
  align-items: center;
}
.error {
  color: var(--danger);
}
.actions {
  display: flex;
  justify-content: flex-end;
}
</style>
