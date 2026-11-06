<script setup lang="ts">
/**
 * Settings → "İnternet araştırması" (Phase 12): off by default; when on, every search is still
 * shown and approved first. Turning it on or off is recorded by the backend.
 */
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { ApiError, type ResearchSettings } from "@/api/client";
import { errorKey } from "@/i18n";
import { currentApiClient } from "@/stores/connection";

const { t } = useI18n();
const settings = ref<ResearchSettings | null>(null);
const busy = ref(false);
const error = ref<string | null>(null);

async function run(action: () => Promise<ResearchSettings>) {
  busy.value = true;
  error.value = null;
  try {
    settings.value = await action();
  } catch (e) {
    error.value = t(errorKey(e instanceof ApiError ? e.code : null));
  } finally {
    busy.value = false;
  }
}

function change(event: Event) {
  const mode = (event.target as HTMLSelectElement).value as ResearchSettings["mode"];
  const client = currentApiClient();
  if (client !== null) void run(() => client.setResearchMode(mode));
}

onMounted(() => {
  const client = currentApiClient();
  if (client !== null) void run(() => client.researchSettings());
});
</script>

<template>
  <section class="panel research" data-testid="settings-research">
    <h3>{{ t("research.title") }}</h3>
    <p class="muted small">{{ t("research.hint") }}</p>
    <select v-if="settings" :value="settings.mode" :disabled="busy" data-testid="research-mode" @change="change">
      <option value="offline_only">{{ t("research.off") }}</option>
      <option value="ask">{{ t("research.ask") }}</option>
    </select>
    <p v-if="settings && !settings.available" class="muted small" data-testid="research-unavailable">
      {{ t("research.unavailable") }}
    </p>
    <ul class="muted small">
      <li data-testid="research-not-general">{{ t("research.notGeneral") }}</li>
      <li>{{ t("research.sends") }}</li>
      <li>{{ t("research.keeps") }}</li>
      <li>{{ t("research.never") }}</li>
    </ul>
    <p v-if="error" class="error small" role="alert">{{ error }}</p>
  </section>
</template>

<style scoped>
.research {
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
h3 {
  margin: 0;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-muted);
}
select {
  align-self: flex-start;
}
ul {
  margin: 0;
  padding-left: 18px;
}
.small {
  font-size: 12px;
  margin: 0;
}
.error {
  color: var(--danger);
}
</style>
