<script setup lang="ts">
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import CoreGlyph from "@/components/CoreGlyph.vue";
import RecoveryCodeDialog from "@/components/RecoveryCodeDialog.vue";
import RestorePanel from "@/components/RestorePanel.vue";
import StartupError from "@/components/StartupError.vue";
import StatusPill from "@/components/StatusPill.vue";
import { useConnectionStore } from "@/stores/connection";
import AssistantView from "@/views/AssistantView.vue";
import DiagnosticsView from "@/views/DiagnosticsView.vue";
import OverviewView from "@/views/OverviewView.vue";
import SettingsView from "@/views/SettingsView.vue";

type Tab = "conversation" | "overview" | "settings" | "diagnostics";

const store = useConnectionStore();
const { t } = useI18n();
const tab = ref<Tab>("conversation");
const tabs: Tab[] = ["conversation", "overview", "settings", "diagnostics"];

const version = computed(() => store.info?.version ?? "—");
const showError = computed(
  () =>
    store.phase === "backend_failed" ||
    (store.phase === "disconnected" && (tab.value === "overview" || tab.value === "conversation")),
);
</script>

<template>
  <div class="shell">
    <header class="topbar">
      <div class="identity">
        <CoreGlyph :phase="store.phase" />
        <div>
          <h1>{{ t("app.name") }}</h1>
          <p class="muted">{{ t("app.tagline") }} · {{ t("app.foundation") }}</p>
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
        <CoreGlyph phase="starting" />
        <span>{{ t("connection.starting") }}…</span>
      </div>
      <RestorePanel v-else-if="store.phase === 'needs_recovery'" />
      <template v-else>
        <StartupError v-if="showError" />
        <AssistantView v-if="tab === 'conversation' && store.phase === 'connected'" />
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
