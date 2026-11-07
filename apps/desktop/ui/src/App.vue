<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import PresenceIndicator from "@/components/PresenceIndicator.vue";
import RecoveryCodeDialog from "@/components/RecoveryCodeDialog.vue";
import RestorePanel from "@/components/RestorePanel.vue";
import StartupError from "@/components/StartupError.vue";
import StatusPill from "@/components/StatusPill.vue";
import { useCore } from "@/core/useCore";
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
// Phase 14: the accent colour of the whole UI follows the core's state.
const core = useCore();
const coreLabel = computed(() => t(`core.state.${core.state.value}`));
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
      <div class="chip" data-testid="core-chip">
        <span class="chip-dot pulse-soft" aria-hidden="true" />
        <span class="chip-label">{{ coreLabel }}</span>
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

    <main :class="{ stage: tab === 'conversation' && store.phase === 'connected' }">
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
  position: relative;
  z-index: 30;
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 8px 18px;
  border-bottom: 1px solid rgb(255 255 255 / 0.05);
  background: rgb(2 5 11 / 0.6);
  backdrop-filter: blur(24px);
}
.chip {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 5px 14px;
  border-radius: 999px;
  border: 1px solid rgb(255 255 255 / 0.06);
  background: rgb(255 255 255 / 0.02);
}
.chip-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent);
  box-shadow: 0 0 10px var(--accent);
}
.chip-label {
  font-family: var(--font-display);
  font-size: 10.5px;
  font-weight: 500;
  letter-spacing: 0.3em;
  color: var(--accent);
}
.identity {
  display: flex;
  align-items: center;
  gap: 14px;
  min-width: 0;
}
h1 {
  margin: 0;
  font-family: var(--font-display);
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 0.42em;
  color: #fff;
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
.tab {
  font-family: var(--font-display);
  font-size: 11px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}
.tab.active {
  color: #fff;
  border-color: color-mix(in srgb, var(--accent) 40%, transparent);
  background: rgb(255 255 255 / 0.06);
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
/* The conversation view is a full-bleed stage (the core, its HUD and the chat panel). */
main.stage {
  padding: 0;
  overflow: hidden;
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
