<script setup lang="ts">
import { useI18n } from "vue-i18n";
import { errorKey } from "@/i18n";
import { useConnectionStore } from "@/stores/connection";

const store = useConnectionStore();
const { t } = useI18n();
</script>

<template>
  <section class="startup-error panel" role="alert" data-testid="startup-error">
    <h2>{{ t(`connection.${store.phase}`) }}</h2>
    <p>{{ t(errorKey(store.errorCode)) }}</p>
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
button {
  align-self: flex-start;
}
</style>
