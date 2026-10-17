<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import StatusCard from "@/components/StatusCard.vue";
import type { StatusRow } from "@/components/types";
import { formatTime } from "@/format";
import { errorKey } from "@/i18n";
import { useConnectionStore } from "@/stores/connection";

const store = useConnectionStore();
const { t } = useI18n();

const rows = computed<StatusRow[]>(() => {
  const c = store.connection;
  return [
    { label: t("diagnostics.profile"), value: c?.profile ?? "—", mono: true },
    { label: t("diagnostics.port"), value: c?.port ? `127.0.0.1:${c.port}` : "—", mono: true },
    { label: t("diagnostics.lastCheck"), value: formatTime(store.lastCheckedAt) },
    { label: t("settings.dataDir"), value: c?.dataDir ?? "—", mono: true },
    { label: t("settings.logDir"), value: c?.logDir ?? "—", mono: true },
  ];
});

function eventText(code: string): string {
  if (code === "connected") return t("connection.connected");
  if (code === "recovery_acknowledged") return t("settings.recoveryDone");
  return t(errorKey(code));
}
</script>

<template>
  <div class="diagnostics" data-testid="diagnostics-view">
    <StatusCard :title="t('diagnostics.title')" :rows="rows" />
    <section class="panel events">
      <header>
        <h3>{{ t("diagnostics.events") }}</h3>
        <button class="btn" type="button" @click="store.retry()">{{ t("diagnostics.reconnect") }}</button>
      </header>
      <p v-if="store.events.length === 0" class="muted">{{ t("diagnostics.noEvents") }}</p>
      <ul v-else>
        <li v-for="event in store.events" :key="event.at + event.code" :class="`level-${event.level}`">
          <span class="mono time">{{ formatTime(event.at) }}</span>
          <span class="mono code">{{ event.code }}</span>
          <span>{{ eventText(event.code) }}</span>
        </li>
      </ul>
      <p class="muted hint">{{ t("diagnostics.logsHint") }} <span class="mono">{{ store.connection?.logDir }}</span></p>
    </section>
  </div>
</template>

<style scoped>
.diagnostics {
  display: flex;
  flex-direction: column;
  gap: 14px;
  max-width: 860px;
}
.events {
  padding: 16px 18px;
}
header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
h3 {
  margin: 0;
  font-size: 12px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-muted);
}
ul {
  list-style: none;
  margin: 12px 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 280px;
  overflow: auto;
}
li {
  display: grid;
  grid-template-columns: 76px 190px 1fr;
  gap: 10px;
}
.level-error .code {
  color: var(--danger);
}
.level-info .code {
  color: var(--ok);
}
.time {
  color: var(--text-faint);
}
.hint {
  margin: 14px 0 0;
  font-size: 12.5px;
}
</style>
