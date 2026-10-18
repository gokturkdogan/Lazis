<script setup lang="ts">
/**
 * Settings (Phase 4): desktop preferences are editable (stored by the shell, no secrets);
 * model, privacy and the backend configuration are shown read-only. Nothing here changes
 * system settings (FileVault, Ollama) — LAZIS only explains them.
 */
import { computed, onMounted } from "vue";
import { useI18n } from "vue-i18n";
import StatusCard from "@/components/StatusCard.vue";
import type { StatusRow } from "@/components/types";
import { formatBytes } from "@/format";
import { useAssistantStore } from "@/stores/assistant";
import { useConnectionStore } from "@/stores/connection";
import { usePreferencesStore } from "@/stores/preferences";
import { errorKey } from "@/i18n";

const store = useConnectionStore();
const chat = useAssistantStore();
const prefs = usePreferencesStore();
const { t } = useI18n();

onMounted(() => {
  if (!prefs.loaded) void prefs.load();
  if (store.phase === "connected") void chat.refreshRuntime();
});

const modelRows = computed<StatusRow[]>(() => {
  const runtime = chat.runtime;
  return [
    {
      label: t("settings.runtime"),
      value: runtime?.available
        ? t("overview.runtimeOk", { version: runtime.version ?? "?" })
        : t("overview.runtimeDown"),
      tone: runtime?.available ? "ok" : "danger",
    },
    { label: t("settings.modelsPrimary"), value: chat.primaryModel ?? t("settings.none"), mono: true },
    { label: t("settings.modelActive"), value: chat.selectedModel || "—", mono: true },
    { label: t("settings.modelFallback"), value: store.settings?.models_fallback_model ?? t("settings.none"), mono: true },
  ];
});

const privacyRows = computed<StatusRow[]>(() => {
  const fv = store.connection?.fileVault ?? "unknown";
  return [
    { label: t("settings.localOnly"), value: t("settings.localOnlyValue"), tone: "ok" },
    { label: t("overview.encryption"), value: t("settings.encryptionValue"), tone: "ok" },
    { label: t("settings.telemetry"), value: t("settings.telemetryValue"), tone: "ok" },
    {
      label: t("overview.fileVault"),
      value: fv === "on" ? t("overview.fileVaultOn") : fv === "off" ? t("overview.fileVaultOff") : t("overview.fileVaultUnknown"),
      tone: fv === "on" ? "ok" : "warn",
    },
  ];
});

const configRows = computed<StatusRow[]>(() => {
  const s = store.settings;
  if (!s) return [{ label: t("settings.title"), value: t("overview.loading"), tone: "muted" }];
  const onOff = (v: boolean) => (v ? t("settings.enabled") : t("settings.disabled"));
  return [
    { label: t("settings.environment"), value: s.environment },
    { label: t("settings.research"), value: t("overview.researchOffline"), tone: "ok" },
    { label: t("settings.network"), value: onOff(s.network_egress_enabled), tone: "ok" },
    { label: t("settings.voice"), value: onOff(s.voice_enabled), tone: "muted" },
    { label: t("settings.modelsProvider"), value: s.models_provider, mono: true },
    {
      label: t("settings.contextLength"),
      value: `${s.models_context_short} / ${s.models_context_normal} / ${s.models_context_long}`,
      mono: true,
    },
    { label: t("settings.keepAlive"), value: s.models_keep_alive, mono: true },
    { label: t("settings.verbosity"), value: t(`settings.verbosityValue.${s.personality_verbosity}`) },
    { label: t("settings.humor"), value: t(`settings.humorValue.${s.personality_humor}`) },
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
    <section class="panel general" data-testid="settings-general">
      <h3>{{ t("settings.general") }}</h3>
      <label class="toggle">
        <input
          type="checkbox"
          data-testid="pref-close-to-menu-bar"
          :checked="prefs.values.closeToMenuBar"
          :disabled="prefs.saving"
          @change="prefs.update({ closeToMenuBar: ($event.target as HTMLInputElement).checked })"
        />
        <span>
          {{ t("settings.closeToMenuBar") }}
          <small class="muted">{{ t("settings.closeToMenuBarHint") }}</small>
        </span>
      </label>
      <label class="toggle">
        <input
          type="checkbox"
          data-testid="pref-start-hidden"
          :checked="prefs.values.startHidden"
          :disabled="prefs.saving"
          @change="prefs.update({ startHidden: ($event.target as HTMLInputElement).checked })"
        />
        <span>
          {{ t("settings.startHidden") }}
          <small class="muted">{{ t("settings.startHiddenHint") }}</small>
        </span>
      </label>
      <label class="toggle">
        <input
          type="checkbox"
          data-testid="pref-reduce-motion"
          :checked="prefs.values.reduceMotion === 'on'"
          :disabled="prefs.saving"
          @change="prefs.update({ reduceMotion: ($event.target as HTMLInputElement).checked ? 'on' : 'system' })"
        />
        <span>
          {{ t("settings.reduceMotion") }}
          <small class="muted">{{ t("settings.reduceMotionHint") }}</small>
        </span>
      </label>
      <p v-if="prefs.errorCode" class="error small" role="alert">{{ t(errorKey(prefs.errorCode)) }}</p>
      <ul class="muted small notes">
        <li>{{ t("settings.notificationsNote") }}</li>
        <li>{{ t("settings.loginItemNote") }}</li>
      </ul>
    </section>
    <StatusCard :title="t('settings.model')" :rows="modelRows" testid="settings-model" />
    <p class="muted small">{{ t("settings.modelHint") }}</p>
    <StatusCard :title="t('settings.privacy')" :rows="privacyRows" testid="settings-privacy" />
    <StatusCard :title="t('settings.recovery')" :rows="recoveryRows" />
    <StatusCard :title="t('settings.config')" :rows="configRows" />
    <p class="muted small">{{ t("settings.readOnly") }}</p>
  </div>
</template>

<style scoped>
.settings {
  display: flex;
  flex-direction: column;
  gap: 14px;
  max-width: 860px;
}
.general {
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
h3 {
  margin: 0;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-muted);
}
.toggle {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  cursor: pointer;
}
.toggle input {
  margin-top: 3px;
}
.toggle small {
  display: block;
  font-size: 12px;
}
.notes {
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
