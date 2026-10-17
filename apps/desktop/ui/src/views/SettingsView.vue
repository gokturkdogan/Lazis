<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import StatusCard from "@/components/StatusCard.vue";
import type { StatusRow } from "@/components/types";
import { formatBytes } from "@/format";
import { useConnectionStore } from "@/stores/connection";

const store = useConnectionStore();
const { t } = useI18n();

const rows = computed<StatusRow[]>(() => {
  const s = store.settings;
  if (!s) return [{ label: t("settings.title"), value: t("overview.loading"), tone: "muted" }];
  const onOff = (v: boolean) => (v ? t("settings.enabled") : t("settings.disabled"));
  return [
    { label: t("settings.environment"), value: s.environment },
    { label: t("settings.research"), value: t("overview.researchOffline"), tone: "ok" },
    { label: t("settings.network"), value: onOff(s.network_egress_enabled), tone: "ok" },
    { label: t("settings.voice"), value: onOff(s.voice_enabled), tone: "muted" },
    { label: t("settings.voiceMode"), value: s.voice_interaction_mode, mono: true },
    { label: t("settings.modelsProvider"), value: s.models_provider, mono: true },
    { label: t("settings.modelsPrimary"), value: s.models_primary_model ?? t("settings.none"), tone: "muted" },
    { label: t("settings.contextLength"), value: String(s.models_context_length) },
    { label: t("settings.logLevel"), value: s.log_level, mono: true },
    { label: t("settings.backups"), value: String(s.backups_keep) },
    { label: t("settings.requestLimit"), value: formatBytes(s.max_request_bytes) },
    { label: t("settings.dataDir"), value: s.data_dir, mono: true },
    { label: t("settings.logDir"), value: s.log_dir, mono: true },
  ];
});

const recoveryRows = computed<StatusRow[]>(() => [
  {
    label: t("settings.recovery"),
    value: store.recoveryPending ? t("settings.recoveryPending") : t("settings.recoveryDone"),
    tone: store.recoveryPending ? "warn" : "ok",
  },
]);
</script>

<template>
  <div class="settings" data-testid="settings-view">
    <p class="muted note">{{ t("settings.readOnly") }}</p>
    <StatusCard :title="t('settings.title')" :rows="rows" />
    <StatusCard :title="t('settings.recovery')" :rows="recoveryRows" />
  </div>
</template>

<style scoped>
.settings {
  display: flex;
  flex-direction: column;
  gap: 14px;
  max-width: 860px;
}
.note {
  margin: 0;
}
</style>
