<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import ConversationPlaceholder from "@/components/ConversationPlaceholder.vue";
import StatusCard from "@/components/StatusCard.vue";
import type { StatusRow } from "@/components/types";
import { formatBytes, formatDuration } from "@/format";
import { useConnectionStore } from "@/stores/connection";

const store = useConnectionStore();
const { t } = useI18n();

const loading = (label: string): StatusRow[] => [{ label, value: t("overview.loading"), tone: "muted" }];

const backendRows = computed<StatusRow[]>(() => {
  const s = store.status;
  const info = store.info;
  if (!s || !info) return loading(t("overview.backend"));
  return [
    { label: t("overview.version"), value: `${info.version} · API ${info.api_version}` },
    { label: t("overview.uptime"), value: formatDuration(s.backend.uptime_seconds) },
    { label: t("overview.process"), value: `PID ${s.backend.pid}`, mono: true },
    { label: t("overview.memory"), value: formatBytes(s.backend.peak_rss_bytes) },
  ];
});

const databaseRows = computed<StatusRow[]>(() => {
  const db = store.status?.database;
  if (!db) return loading(t("overview.database"));
  return [
    {
      label: t("overview.encryption"),
      value: db.encryption_verified ? t("overview.encryptionActive") : t("overview.encryptionUnverified"),
      tone: db.encryption_verified ? "ok" : "warn",
    },
    { label: "SQLCipher", value: `${db.cipher_version} · SQLite ${db.sqlite_version}`, mono: true },
    { label: t("overview.schema"), value: String(db.schema_version) },
    {
      label: t("overview.integrity"),
      value: db.integrity === "ok" ? t("overview.integrityOk") : t("overview.integrityFailed"),
      tone: db.integrity === "ok" ? "ok" : "danger",
    },
    { label: t("overview.size"), value: formatBytes(db.size_bytes) },
  ];
});

const systemRows = computed<StatusRow[]>(() => {
  const b = store.status?.backend;
  if (!b) return loading(t("overview.system"));
  return [
    { label: t("overview.platform"), value: `${b.platform} · ${b.machine}` },
    { label: t("overview.python"), value: b.python_version, mono: true },
  ];
});

function sandboxRow(status: "enforced" | "not_enforced" | "unknown"): StatusRow {
  const label = t("overview.osSandbox");
  if (status === "enforced") return { label, value: t("overview.osSandboxOn"), tone: "ok" };
  if (status === "not_enforced") return { label, value: t("overview.osSandboxOff"), tone: "warn" };
  return { label, value: t("overview.osSandboxUnknown"), tone: "warn" };
}

function fileVaultRow(state: "on" | "off" | "unknown"): StatusRow {
  const label = t("overview.fileVault");
  if (state === "on") return { label, value: t("overview.fileVaultOn"), tone: "ok" };
  if (state === "off") return { label, value: t("overview.fileVaultOff"), tone: "warn" };
  return { label, value: t("overview.fileVaultUnknown"), tone: "muted" };
}

const privacyRows = computed<StatusRow[]>(() => {
  const p = store.status?.privacy;
  if (!p) return loading(t("overview.privacy"));
  return [
    { label: t("overview.network"), value: t("overview.networkOff"), tone: "ok" },
    sandboxRow(p.os_network_sandbox),
    { label: t("overview.research"), value: t("overview.researchOffline"), tone: "ok" },
    { label: t("overview.microphone"), value: t("overview.microphoneOff"), tone: "ok" },
    { label: t("overview.voice"), value: t("overview.voiceOff"), tone: "muted" },
    fileVaultRow(store.connection?.fileVault ?? "unknown"),
  ];
});

const aiRows = computed<StatusRow[]>(() => [
  { label: t("overview.model"), value: t("overview.modelNone"), tone: "muted" },
  { label: "", value: t("overview.modelPhase"), tone: "muted" },
]);
</script>

<template>
  <div class="overview">
    <div class="grid">
      <StatusCard :title="t('overview.backend')" :rows="backendRows" testid="card-backend" />
      <StatusCard :title="t('overview.database')" :rows="databaseRows" testid="card-database" />
      <StatusCard :title="t('overview.privacy')" :rows="privacyRows" testid="card-privacy" />
      <StatusCard :title="t('overview.system')" :rows="systemRows" testid="card-system" />
      <StatusCard :title="t('overview.ai')" :rows="aiRows" testid="card-ai" />
    </div>
    <ConversationPlaceholder />
  </div>
</template>

<style scoped>
.overview {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 14px;
}
</style>
