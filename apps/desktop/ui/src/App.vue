<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import PresenceIndicator from "@/components/PresenceIndicator.vue";
import RecoveryCodeDialog from "@/components/RecoveryCodeDialog.vue";
import RestorePanel from "@/components/RestorePanel.vue";
import StartupError from "@/components/StartupError.vue";
import StatusPill from "@/components/StatusPill.vue";
import type { View } from "@/platform/tauri";
import { currentPlatform, useConnectionStore } from "@/stores/connection";
import { usePreferencesStore } from "@/stores/preferences";
import { usePresence } from "@/stores/presence";
import AssistantView from "@/views/AssistantView.vue";
import DiagnosticsView from "@/views/DiagnosticsView.vue";
import MemoryView from "@/views/MemoryView.vue";
import OverviewView from "@/views/OverviewView.vue";
import SettingsView from "@/views/SettingsView.vue";

const store = useConnectionStore();
const preferences = usePreferencesStore();
const presence = usePresence();
const { t } = useI18n();
const tab = ref<View>("conversation");
const tabs: View[] = ["conversation", "memory", "overview", "settings", "diagnostics"];

const version = computed(() => store.info?.version ?? "—");
const showError = computed(
  () =>
    store.phase === "backend_failed" ||
    (store.phase === "disconnected" && (tab.value === "overview" || tab.value === "conversation")),
);

// The menu-bar status line follows the same derived state (only on change).
watch(
  () => presence.value.tray,
  (status) => void currentPlatform()?.setTrayStatus(status).catch(() => undefined),
  { immediate: true },
);

let offNavigate: (() => void) | null = null;
onMounted(async () => {
  const platform = currentPlatform();
  if (platform === null) return;
  tab.value = platform.initialView() ?? tab.value;
  void preferences.load();
  offNavigate = await platform.onNavigate((view) => (tab.value = view));
});
onBeforeUnmount(() => offNavigate?.());
</script>

<template>
  <div class="shell">
    <header class="topbar">
      <div class="identity">
        <PresenceIndicator
          :state="presence.state"
          :label="presence.label"
          :params="presence.params ?? {}"
          compact
        />
        <div>
          <h1>{{ t("app.name") }}</h1>
          <p class="muted" data-testid="presence-text" role="status" aria-live="polite">
            {{ t(`presence.${presence.label}`, presence.params ?? {}) }}
          </p>
        </div>
      </div>
      <nav :aria-label="t('app.name')">
        <button
          v-for="item in tabs"
          :key="item"
          type="button"
          class="tab"
          :class="{ active: tab === item }"
          :data-testid="`tab-${item}`"
          @click="tab = item"
        >
          {{ t(`nav.${item}`) }}
        </button>
      </nav>
      <div class="meta">
        <StatusPill :phase="store.phase" />
        <span class="muted mono version">v{{ version }}</span>
      </div>
    </header>

    <main>
      <div v-if="store.phase === 'initializing' || store.phase === 'starting'" class="starting" role="status">
        <PresenceIndicator state="thinking" label="starting" compact />
        <span>{{ t("connection.starting") }}…</span>
      </div>
      <RestorePanel v-else-if="store.phase === 'needs_recovery'" />
      <template v-else>
        <StartupError v-if="showError" />
        <AssistantView v-if="tab === 'conversation' && store.phase === 'connected'" />
        <MemoryView v-else-if="tab === 'memory' && store.phase === 'connected'" />
        <OverviewView v-else-if="tab === 'overview' && store.phase === 'connected'" />
        <SettingsView v-else-if="tab === 'settings'" />
        <DiagnosticsView v-else-if="tab === 'diagnostics'" />
      </template>
    </main>

    <RecoveryCodeDialog v-if="store.phase === 'connected' && store.recoveryPending" />
  </div>
</template>

<style scoped>
.shell {
  height: 100%;
  display: flex;
  flex-direction: column;
}
.topbar {
  display: flex;
  align-items: center;
  gap: 24px;
  padding: 16px 24px;
  border-bottom: 1px solid var(--panel-border);
  background: rgba(6, 10, 19, 0.65);
  backdrop-filter: blur(10px);
}
.identity {
  display: flex;
  align-items: center;
  gap: 14px;
  min-width: 0;
}
h1 {
  margin: 0;
  font-size: 18px;
  letter-spacing: 0.32em;
}
.identity p {
  margin: 0;
  font-size: 12px;
}
nav {
  display: flex;
  gap: 4px;
  margin-left: auto;
}
.tab {
  border: 1px solid transparent;
  background: transparent;
  padding: 7px 14px;
  border-radius: 9px;
  color: var(--text-muted);
}
.tab.active {
  color: var(--text);
  border-color: var(--panel-border);
  background: rgba(58, 160, 255, 0.10);
}
.meta {
  display: flex;
  align-items: center;
  gap: 12px;
}
.version {
  font-size: 12px;
}
main {
  flex: 1;
  overflow: auto;
  padding: 22px 24px 28px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.starting {
  margin: auto;
  display: flex;
  align-items: center;
  gap: 14px;
  color: var(--text-muted);
}
@media (max-width: 980px) {
  .topbar {
    flex-wrap: wrap;
  }
  nav {
    order: 3;
    margin-left: 0;
    width: 100%;
  }
}
</style>
