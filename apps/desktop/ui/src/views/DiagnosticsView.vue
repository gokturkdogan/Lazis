<script setup lang="ts">
/**
 * System health (Phase 4). Measures only while this view is open and the window is visible:
 * backend diagnostics (no message content) and per-process memory from the shell, every
 * REFRESH_MS. Nothing here is estimated: unknown values say so.
 */
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import type { DiagnosticsResponse } from "@/api/client";
import StatusCard from "@/components/StatusCard.vue";
import type { StatusRow } from "@/components/types";
import { formatBytes, formatTime } from "@/format";
import { errorKey } from "@/i18n";
import type { ProcessMetrics } from "@/platform/tauri";
import { currentApiClient, currentPlatform, useConnectionStore } from "@/stores/connection";
import { usePresence } from "@/stores/presence";

const REFRESH_MS = 5000;
const store = useConnectionStore();
const presence = usePresence();
const { t } = useI18n();
const diag = ref<DiagnosticsResponse | null>(null);
const diagError = ref<string | null>(null);
const metrics = ref<ProcessMetrics | null>(null);
const metricsError = ref(false);
let timer: ReturnType<typeof setInterval> | null = null;

async function refresh() {
  if (document.visibilityState === "hidden") return;
  const client = currentApiClient();
  const platform = currentPlatform();
  await Promise.all([
    (async () => {
      if (client === null) {
        diag.value = null;
        return;
      }
      try {
        diag.value = await client.diagnostics();
        diagError.value = null;
      } catch {
        diagError.value = "backend_unreachable";
      }
    })(),
    (async () => {
      try {
        metrics.value = (await platform?.processMetrics()) ?? null;
        metricsError.value = false;
      } catch {
        metricsError.value = true;
      }
    })(),
  ]);
}

onMounted(() => {
  void refresh();
  timer = setInterval(() => void refresh(), REFRESH_MS);
});
onBeforeUnmount(() => {
  if (timer !== null) clearInterval(timer);
});

const ms = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${(v / 1000).toFixed(2)} sn`);
const n = (v: number | null | undefined) => (v === null || v === undefined ? "—" : String(v));
const yesNo = (v: boolean) => (v ? t("diagnostics.yes") : t("diagnostics.no"));

const assistantRows = computed<StatusRow[]>(() => [
  {
    label: t("diagnostics.state"),
    value: t(`presence.${presence.value.label}`, presence.value.params ?? {}),
    tone: presence.value.state === "error" ? "danger" : "ok",
  },
]);

const modelRows = computed<StatusRow[]>(() => {
  const d = diag.value;
  if (d === null) return [{ label: t("diagnostics.model"), value: t("overview.loading"), tone: "muted" }];
  const m = d.model;
  const runtime = d.runtime.available
    ? { value: t("diagnostics.ollamaOk", { version: d.runtime.version ?? "?" }), tone: "ok" as const }
    : { value: t(errorKey(d.runtime.error_code)), tone: "danger" as const };
  return [
    { label: t("diagnostics.ollama"), ...runtime },
    { label: t("diagnostics.activeModel"), value: m.active ?? "—", mono: true },
    {
      label: t("diagnostics.modelInstalled"),
      value: yesNo(m.active_installed),
      tone: m.active_installed ? "ok" : "danger",
    },
    {
      label: t("diagnostics.modelLoaded"),
      value: m.loaded
        ? t("diagnostics.loadedValue", {
            name: m.loaded.name,
            size: formatBytes(m.loaded.size_bytes),
            ctx: m.loaded.context_length ?? "?",
          })
        : t("diagnostics.notLoaded"),
      tone: m.loaded ? "ok" : "muted",
      mono: m.loaded !== null,
    },
    { label: t("diagnostics.keepAlive"), value: `${m.keep_alive} · num_ctx ${m.num_ctx}`, mono: true },
    {
      label: t("diagnostics.fallback"),
      value: m.fallback
        ? t("diagnostics.fallbackValue", {
            name: m.fallback,
            installed: m.fallback_installed ? t("diagnostics.installed") : t("diagnostics.notInstalled"),
          })
        : t("settings.none"),
      mono: true,
    },
    { label: t("diagnostics.autoFallback"), value: t("diagnostics.autoFallbackOff"), tone: "muted" },
  ];
});

const backendRows = computed<StatusRow[]>(() => {
  const c = store.connection;
  const lastError = store.events.find((e) => e.level === "error");
  const restarting = (c?.restartAttempt ?? 0) > 0;
  return [
    {
      label: t("diagnostics.connection"),
      value: t(`connection.${store.phase}`),
      tone: store.phase === "connected" ? "ok" : "danger",
    },
    { label: t("diagnostics.lastCheck"), value: formatTime(store.lastCheckedAt) },
    {
      label: t("diagnostics.lastError"),
      value: lastError ? `${lastError.code} · ${formatTime(lastError.at)}` : "—",
      tone: lastError ? "warn" : "muted",
      mono: lastError !== undefined,
    },
    {
      label: t("diagnostics.restart"),
      value: restarting
        ? t("presence.restarting", { attempt: c?.restartAttempt ?? 0, limit: c?.restartLimit ?? 0 })
        : t("diagnostics.restartPolicy", { limit: c?.restartLimit ?? 3 }),
      tone: restarting ? "warn" : "muted",
    },
    { label: t("diagnostics.profile"), value: c?.profile ?? "—", mono: true },
    { label: t("diagnostics.port"), value: c?.port ? `127.0.0.1:${c.port}` : "—", mono: true },
  ];
});

const perfRows = computed<StatusRow[]>(() => {
  const turn = diag.value?.last_turn;
  if (!turn) return [{ label: t("diagnostics.lastTurn"), value: t("diagnostics.noTurn"), tone: "muted" }];
  return [
    { label: t("diagnostics.lastTurn"), value: `${t(`diagnostics.outcome.${turn.outcome}`, turn.outcome)} · ${formatTime(turn.at)}` },
    { label: t("diagnostics.ttft"), value: ms(turn.ttft_ms), mono: true },
    { label: t("diagnostics.total"), value: ms(turn.total_ms), mono: true },
    { label: t("diagnostics.contextPrep"), value: ms(turn.context_prep_ms), mono: true },
    {
      label: t("diagnostics.tps"),
      value: turn.decode_tps === null ? "—" : `${turn.decode_tps.toFixed(1)} token/sn`,
      mono: true,
    },
    {
      label: t("diagnostics.tokens"),
      value: t("diagnostics.tokensValue", { prompt: n(turn.prompt_tokens), output: n(turn.output_tokens) }),
      mono: true,
    },
  ];
});

const prewarmRows = computed<StatusRow[]>(() => {
  const d = diag.value;
  if (d === null) return [];
  const p = d.prewarm;
  let value: string;
  let tone: StatusRow["tone"] = "muted";
  switch (p.state) {
    case "running":
      value = t("diagnostics.prewarm.running");
      tone = "warn";
      break;
    case "done":
      value =
        p.scope === "context"
          ? t("diagnostics.prewarm.doneContext", { duration: ms(p.duration_ms), tokens: n(p.prompt_tokens) })
          : t("diagnostics.prewarm.doneModel", { duration: ms(p.duration_ms) });
      tone = "ok";
      break;
    case "failed":
      value = t("diagnostics.prewarm.failed", { code: p.code ?? "llm_error" });
      tone = "danger";
      break;
    case "cancelled":
      value = t("diagnostics.prewarm.cancelled");
      break;
    default:
      value = t("diagnostics.prewarm.idle");
  }
  return [
    { label: t("diagnostics.prewarmLabel"), value, tone },
    { label: t("diagnostics.prewarmAt"), value: formatTime(p.at ?? null) },
    {
      label: t("diagnostics.nextTurn"),
      value: d.cache_expected_warm ? t("diagnostics.expectWarm") : t("diagnostics.expectCold"),
      tone: "muted",
    },
  ];
});

const learningRows = computed<StatusRow[]>(() => {
  const m = diag.value?.memory;
  if (!m) return [];
  const l = m.learning;
  const jobs = m.jobs;
  let value: string;
  let tone: StatusRow["tone"] = "muted";
  switch (l.state) {
    case "running":
      value = t("diagnostics.learning.running");
      tone = "warn";
      break;
    case "done":
      value = t("diagnostics.learning.done", {
        created: l.created ?? 0,
        inbox: l.inbox ?? 0,
        duration: ms(l.duration_ms ?? null),
      });
      tone = "ok";
      break;
    case "failed":
      value = t("diagnostics.learning.failed", { code: l.code ?? "llm_error" });
      tone = "danger";
      break;
    case "preempted":
      value = t("diagnostics.learning.preempted");
      break;
    default:
      value = t("diagnostics.learning.idle");
  }
  return [
    {
      label: t("diagnostics.learning.auto"),
      value: m.auto_extract ? t("diagnostics.learning.on", { models: m.trusted_models.join(", ") }) : t("settings.disabled"),
      tone: m.auto_extract ? "ok" : "muted",
    },
    { label: t("diagnostics.learning.last"), value, tone },
    {
      label: t("diagnostics.learning.queue"),
      value: t("diagnostics.learning.queueValue", {
        queued: (jobs.queued ?? 0) + (jobs.running ?? 0),
        deferred: jobs.deferred ?? 0,
        failed: jobs.failed ?? 0,
      }),
      tone: (jobs.failed ?? 0) > 0 ? "warn" : "muted",
    },
    {
      label: t("diagnostics.learning.records"),
      value: t("diagnostics.learning.recordsValue", { active: m.memories.active ?? 0, pending: m.inbox_open }),
    },
  ];
});

const memoryRows = computed<StatusRow[]>(() => {
  const m = metrics.value;
  if (metricsError.value || m === null) {
    return [{ label: t("diagnostics.memory"), value: t("diagnostics.memoryUnavailable"), tone: "muted" }];
  }
  const rows: StatusRow[] = m.processes.map((p) => ({
    label: `${t(`diagnostics.process.${p.role}`)} (pid ${p.pid})`,
    value: p.footprint_bytes === null ? t("diagnostics.unreadable") : formatBytes(p.footprint_bytes),
    ...(p.footprint_bytes === null ? { tone: "muted" as const } : {}),
    mono: true,
  }));
  if (!m.ollama_found) rows.push({ label: t("diagnostics.process.ollama_server"), value: t("diagnostics.ollamaNotFound"), tone: "warn" });
  return rows;
});

function eventText(code: string): string {
  if (code === "connected") return t("connection.connected");
  if (code === "recovery_acknowledged") return t("settings.recoveryDone");
  if (code === "system_woke") return t("diagnostics.woke");
  if (code === "backend_restarting") return t("diagnostics.restarting");
  return t(errorKey(code));
}
</script>

<template>
  <div class="diagnostics" data-testid="diagnostics-view">
    <p class="muted note">{{ t("diagnostics.intro") }}</p>
    <p v-if="diagError" class="error small" role="alert">{{ t(errorKey(diagError)) }}</p>
    <div class="grid">
      <StatusCard :title="t('diagnostics.assistant')" :rows="assistantRows" testid="diag-assistant" />
      <StatusCard :title="t('diagnostics.backend')" :rows="backendRows" testid="diag-backend" />
      <StatusCard :title="t('diagnostics.model')" :rows="modelRows" testid="diag-model" />
      <StatusCard :title="t('diagnostics.performance')" :rows="perfRows" testid="diag-performance" />
      <StatusCard
        v-if="learningRows.length"
        :title="t('diagnostics.personalMemory')"
        :rows="learningRows"
        testid="diag-learning"
      />
      <StatusCard
        v-if="prewarmRows.length"
        :title="t('diagnostics.context')"
        :rows="prewarmRows"
        testid="diag-prewarm"
      />
      <section class="panel memory" data-testid="diag-memory">
        <StatusCard :title="t('diagnostics.memory')" :rows="memoryRows" />
        <p class="muted small source">{{ t("diagnostics.memorySource") }}</p>
      </section>
    </div>
    <section class="panel events">
      <header>
        <h3>{{ t("diagnostics.events") }}</h3>
        <div class="buttons">
          <button class="btn" type="button" data-testid="diag-refresh" @click="refresh()">
            {{ t("diagnostics.refresh") }}
          </button>
          <button class="btn" type="button" @click="store.retry()">{{ t("diagnostics.reconnect") }}</button>
        </div>
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
  max-width: 1080px;
}
.note {
  margin: 0;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(420px, 1fr));
  gap: 14px;
}
.memory {
  padding: 0;
  border: 0;
  background: none;
}
.source {
  margin: 6px 4px 0;
}
.events {
  padding: 16px 18px;
}
header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.buttons {
  display: flex;
  gap: 8px;
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
.small {
  font-size: 12px;
}
.error {
  color: var(--danger);
}
</style>
