<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { errorKey } from "@/i18n";
import { useConnectionStore } from "@/stores/connection";

const store = useConnectionStore();
const { t } = useI18n();
const restartAttempt = computed(() => (store.phase === "backend_failed" ? (store.connection?.restartAttempt ?? 0) : 0));
</script>

<template>
  <section class="startup-error panel" role="alert" data-testid="startup-error">
    <h2>{{ t(`connection.${store.phase}`) }}</h2>
    <p>{{ t(errorKey(store.errorCode)) }}</p>
    <p v-if="restartAttempt > 0" class="restarting" role="status" data-testid="restarting">
      {{ t("presence.restarting", { attempt: restartAttempt, limit: store.connection?.restartLimit ?? 0 }) }}…
    </p>
    <p class="mono muted code">{{ store.errorCode ?? "internal_error" }}</p>
    <button class="btn btn-primary" type="button" @click="store.retry()">{{ t("connection.retry") }}</button>
  </section>
</template>

<style scoped>
.startup-error {
  max-width: 640px;
  padding: 24px 26px;
  border-color: rgba(255, 90, 90, 0.4);
  display: flex;
  flex-direction: column;
  gap: 10px;
}
h2 {
  margin: 0;
  color: var(--danger);
}
p {
  margin: 0;
}
.code {
  font-size: 12px;
}
.restarting {
  color: var(--state-thinking);
}
button {
  align-self: flex-start;
}
</style>
