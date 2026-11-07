<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import Icon from "@/components/Icon.vue";
import NavDrawer from "@/components/NavDrawer.vue";
import OnboardingModal from "@/components/OnboardingModal.vue";
import { iconFor } from "@/navigation";
import PresenceIndicator from "@/components/PresenceIndicator.vue";
import RecoveryCodeDialog from "@/components/RecoveryCodeDialog.vue";
import RestorePanel from "@/components/RestorePanel.vue";
import StartupError from "@/components/StartupError.vue";
import StartupLoader from "@/components/StartupLoader.vue";
import { useStartup } from "@/composables/startup";
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
// Phase 14.1: navigation lives in the drawer behind the menu button.
const menuOpen = ref(false);
function go(view: View) {
  tab.value = view;
}

const version = computed(() => store.info?.version ?? "—");
// Phase 14 polish: the start screen follows the real startup steps (composables/startup.ts).
const startup = useStartup(computed(() => tab.value === "conversation"));
function startupDiagnostics() {
  startup.dismiss();
  go("diagnostics");
}
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
      <button
        class="icon-btn menu"
        type="button"
        data-testid="menu-button"
        :aria-label="t('nav.open')"
        :aria-expanded="menuOpen"
        aria-controls="nav-panel"
        @click="menuOpen = true"
      >
        <Icon name="menu" :size="20" />
      </button>
      <div class="identity">
        <PresenceIndicator
          :state="presence.state"
          :label="presence.label"
          :params="presence.params ?? {}"
          compact
          logo
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
      <div class="meta">
        <StatusPill :phase="store.phase" />
        <span class="muted mono version">v{{ version }}</span>
      </div>
    </header>

    <main :class="{ stage: tab === 'conversation' && store.phase === 'connected' }">
      <template v-if="store.phase === 'initializing' || store.phase === 'starting'" />
      <RestorePanel v-else-if="store.phase === 'needs_recovery'" />
      <template v-else>
        <StartupError v-if="showError && !startup.visible.value" />
        <Transition name="view" mode="out-in">
          <div :key="tab" class="view" :class="{ 'view-stage': tab === 'conversation' }" :data-view="tab">
            <header v-if="tab !== 'conversation'" class="page-head" data-testid="page-head">
              <span class="page-icon"><Icon :name="iconFor(tab)" :size="20" /></span>
              <div>
                <h2>{{ t(`nav.${tab}`) }}</h2>
                <p class="muted">{{ t(`nav.sub.${tab}`) }}</p>
              </div>
            </header>
            <AssistantView v-if="tab === 'conversation' && store.phase === 'connected'" />
            <MemoryView v-else-if="tab === 'memory' && store.phase === 'connected'" />
            <OverviewView v-else-if="tab === 'overview' && store.phase === 'connected'" />
            <SettingsView v-else-if="tab === 'settings'" @onboarding="go('conversation')" />
            <DiagnosticsView v-else-if="tab === 'diagnostics'" />
          </div>
        </Transition>
      </template>
    </main>

    <RecoveryCodeDialog v-if="store.phase === 'connected' && store.recoveryPending" />
    <OnboardingModal v-else-if="store.phase === 'connected' && !startup.visible.value" />
    <NavDrawer :open="menuOpen" :current="tab" @close="menuOpen = false" @go="go" />
    <Transition name="loader">
      <StartupLoader v-if="startup.visible.value && startup.step.value" :step="startup.step.value" @diagnostics="startupDiagnostics" />
    </Transition>
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
.menu {
  margin-right: 2px;
}
.meta {
  margin-left: auto;
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
.loader-leave-active {
  transition: opacity 520ms ease;
}
.loader-leave-to {
  opacity: 0;
}

.view {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.view:not(.view-stage) {
  width: 100%;
  max-width: 1080px;
  margin-inline: auto;
}
.view:not(.view-stage) > * {
  max-width: none;
}
.page-head {
  position: relative;
  display: flex;
  align-items: center;
  gap: 14px;
  padding-bottom: 12px;
}
.page-head::after {
  content: "";
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 1px;
  background: linear-gradient(90deg, var(--accent), transparent 60%);
  opacity: 0.45;
}
.page-head h2 {
  margin: 0;
  font-family: var(--font-display);
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 0.32em;
  text-transform: uppercase;
  color: #fff;
}
.page-head p {
  margin: 2px 0 0;
  font-size: 12px;
}
.page-icon {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border-radius: 12px;
  color: var(--accent);
  border: 1px solid color-mix(in srgb, var(--accent) 35%, transparent);
  background: color-mix(in srgb, var(--accent) 8%, transparent);
  box-shadow: 0 0 22px -10px var(--accent);
}
.view-enter-active,
.view-leave-active {
  transition: opacity 220ms ease, transform 220ms ease;
}
.view-enter-from {
  opacity: 0;
  transform: translateY(6px);
}
.view-leave-to {
  opacity: 0;
}
@media (max-width: 760px) {
  .chip {
    display: none;
  }
}
</style>
