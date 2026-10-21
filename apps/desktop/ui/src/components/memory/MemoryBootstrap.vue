<script setup lang="ts">
/**
 * Personal knowledge import (Phase 8, "Hafıza → Kişisel Bilgi Aktarımı"): pick a profile file →
 * the backend validates it and (Markdown/text) the local model reads it section by section →
 * the preview, decided item by item → a final confirmation → the result with the real counts
 * and the import id → an undo that shows its plan first.
 *
 * The file is read here (the backend never sees a path) and sent once. Nothing is approved by
 * default; every number shown after writing comes from the backend's transaction.
 */
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import type {
  ApiClient,
  BootstrapBatch,
  BootstrapDecisions,
  BootstrapPreview as Preview,
  BootstrapUndoPlan,
} from "@/api/client";
import { ApiError } from "@/api/client";
import { errorKey } from "@/i18n";
import { currentApiClient } from "@/stores/connection";
import BootstrapPreview from "./BootstrapPreview.vue";
import "./memory.css";

const emit = defineEmits<{ changed: [] }>();
const { t } = useI18n();
const MAX_BYTES = 1_000_000;
const POLL_MS = 700;

type Screen = "select" | "progress" | "preview" | "confirm" | "result" | "undo";
const screen = ref<Screen>("select");
const history = ref<BootstrapBatch[]>([]);
const batch = ref<BootstrapBatch | null>(null);
const preview = ref<Preview | null>(null);
const plan = ref<BootstrapUndoPlan | null>(null);
const restore = ref<Set<string>>(new Set());
const working = ref(false);
const error = ref<string | null>(null);
const notice = ref<string | null>(null);
let timer: ReturnType<typeof setInterval> | null = null;

function client(): ApiClient {
  const c = currentApiClient();
  if (c === null) throw new ApiError(0, "backend_unreachable", "", true);
  return c;
}

function show(e: unknown) {
  if (e instanceof ApiError && e.code === "import_profile_invalid_json" && e.details?.line) {
    error.value = `${t(errorKey(e.code))} (${t("memory.bootstrap.line", { n: e.details.line })})`;
    return;
  }
  error.value = t(errorKey(e instanceof ApiError ? e.code : null));
}

async function guarded(fn: () => Promise<void>) {
  working.value = true;
  error.value = null;
  try {
    await fn();
  } catch (e) {
    show(e);
  } finally {
    working.value = false;
  }
}

async function loadHistory() {
  try {
    history.value = await client().bootstrapHistory();
  } catch {
    history.value = [];
  }
}

function base64Of(bytes: Uint8Array): string {
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  }
  return btoa(binary);
}

async function pick(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (!file) return;
  notice.value = null;
  if (file.size > MAX_BYTES) {
    error.value = t("errors.import_file_too_large");
    return;
  }
  await guarded(async () => {
    const bytes = new Uint8Array(await file.arrayBuffer());
    const b = await client().bootstrapAnalyze(file.name, base64Of(bytes));
    await follow(b);
  });
}

async function follow(b: BootstrapBatch) {
  batch.value = b;
  if (b.status === "analyzing") {
    screen.value = "progress";
    startPolling();
  } else if (b.status === "ready") {
    await openPreview(b.id);
  } else if (b.status === "applied" || b.status === "undone") {
    screen.value = "result";
  } else {
    screen.value = "progress"; // failed / cancelled: shown with its reason
  }
}

function startPolling() {
  stopPolling();
  timer = setInterval(() => void poll(), POLL_MS);
}

function stopPolling() {
  if (timer !== null) clearInterval(timer);
  timer = null;
}

async function poll() {
  if (batch.value === null) return;
  try {
    const p = await client().bootstrapImport(batch.value.id);
    batch.value = p.batch;
    if (p.batch.status !== "analyzing") {
      stopPolling();
      if (p.batch.status === "ready") {
        preview.value = p;
        screen.value = "preview";
      }
    }
  } catch (e) {
    stopPolling();
    show(e);
  }
}

async function openPreview(id: string) {
  const p = await client().bootstrapImport(id);
  preview.value = p;
  batch.value = p.batch;
  screen.value = "preview";
}

async function cancel() {
  if (batch.value === null) return;
  const id = batch.value.id;
  stopPolling();
  await guarded(async () => {
    batch.value = await client().bootstrapCancel(id);
    preview.value = null;
    screen.value = "progress";
    notice.value = t("memory.bootstrap.cancelled");
  });
}

async function retry() {
  if (batch.value === null) return;
  const id = batch.value.id;
  await guarded(async () => {
    notice.value = null;
    await follow(await client().bootstrapRetry(id));
  });
}

async function decide(body: BootstrapDecisions) {
  if (batch.value === null) return;
  const id = batch.value.id;
  await guarded(async () => {
    preview.value = await client().bootstrapDecide(id, body);
  });
}

async function apply() {
  if (batch.value === null) return;
  const id = batch.value.id;
  await guarded(async () => {
    try {
      const r = await client().bootstrapApply(id);
      batch.value = r.batch;
      screen.value = "result";
      emit("changed");
      void loadHistory();
    } catch (e) {
      if (e instanceof ApiError && e.code === "import_memory_changed") {
        await openPreview(id);
        notice.value = t("memory.bootstrap.memoryChanged");
        return;
      }
      throw e;
    }
  });
}

async function discard() {
  if (batch.value === null) return;
  const id = batch.value.id;
  await guarded(async () => {
    await client().bootstrapDiscard(id);
    reset();
  });
}

async function showUndo(b?: BootstrapBatch) {
  const target = b ?? batch.value;
  if (!target) return;
  batch.value = target;
  await guarded(async () => {
    plan.value = await client().bootstrapUndoPlan(target.id);
    restore.value = new Set();
    screen.value = "undo";
  });
}

async function undo() {
  if (batch.value === null) return;
  const id = batch.value.id;
  await guarded(async () => {
    const r = await client().bootstrapUndo(id, [...restore.value]);
    batch.value = r.batch;
    plan.value = r.plan;
    const c = r.plan.counts;
    notice.value = r.change_set_id === null
      ? t("memory.bootstrap.undo.already")
      : t("memory.bootstrap.undo.done", { removed: c.remove ?? 0, restored: (c.restore ?? 0) + restore.value.size, kept: c.keep ?? 0 });
    screen.value = "result";
    emit("changed");
    void loadHistory();
  });
}

function toggleRestore(id: string, on: boolean) {
  const next = new Set(restore.value);
  if (on) next.add(id);
  else next.delete(id);
  restore.value = next;
}

function reset() {
  stopPolling();
  batch.value = null;
  preview.value = null;
  plan.value = null;
  screen.value = "select";
  void loadHistory();
}

async function openFromHistory(b: BootstrapBatch) {
  notice.value = null;
  await guarded(() => follow(b));
}

const summary = computed(() => preview.value?.summary ?? null);
const counts = computed(() => batch.value?.counts ?? {});
const stepOrder: Screen[] = ["select", "progress", "preview", "confirm", "result"];
const failReason = computed(() => {
  const code = batch.value?.error ?? "internal_error";
  const key = `memory.bootstrap.failReason.${code}`;
  return t(key) === key ? t("memory.bootstrap.failReason.internal_error") : t(key);
});
const planGroups = computed(() => {
  const order = ["remove", "restore", "remove_evidence", "keep", "decide", "gone"] as const;
  const steps = plan.value?.steps ?? [];
  return order.map((a) => ({ action: a, steps: steps.filter((s) => s.action === a) })).filter((g) => g.steps.length);
});

onMounted(loadHistory);
onUnmounted(stopPolling);
</script>

<template>
  <section class="panel mem-panel" data-testid="memory-bootstrap">
    <ol class="mem-steps" :aria-label="t('memory.tabs.import')">
      <li v-for="s in stepOrder" :key="s" :class="{ active: screen === s || (screen === 'undo' && s === 'result') }">
        {{ t(`memory.bootstrap.steps.${s}`) }}
      </li>
    </ol>

    <!-- 1. File selection -->
    <template v-if="screen === 'select'">
      <p class="muted mem-small">{{ t("memory.bootstrap.intro") }}</p>
      <p class="muted mem-small">{{ t("memory.bootstrap.privacy") }}</p>
      <label class="btn mem-btn-small mem-file" :class="{ disabled: working }">
        {{ t("memory.bootstrap.choose") }}
        <input type="file" accept=".md,.markdown,.txt,.json" :disabled="working" data-testid="bootstrap-file" @change="pick" />
      </label>
      <span class="muted mem-small">{{ t("memory.bootstrap.accepted") }}</span>
      <span v-if="working" class="muted mem-small" role="status">{{ t("memory.bootstrap.reading") }}</span>
      <h3 class="mem-heading">{{ t("memory.bootstrap.history") }}</h3>
      <p v-if="history.length === 0" class="muted mem-small">{{ t("memory.bootstrap.noHistory") }}</p>
      <ul class="mem-list">
        <li v-for="b in history" :key="b.id" class="mem-item" data-testid="bootstrap-history-item">
          <div class="mem-row">
            <span class="mem-text">{{ b.file_name }}</span>
            <span class="mem-badge">{{ t(`memory.bootstrap.status.${b.status}`) }}</span>
            <span class="muted mem-small">{{ b.created_at.slice(0, 16).replace("T", " ") }}</span>
            <button v-if="b.status !== 'cancelled'" type="button" class="btn mem-btn-small" :disabled="working" @click="openFromHistory(b)">
              {{ t("memory.bootstrap.open") }}
            </button>
            <button v-if="b.status === 'applied'" type="button" class="btn mem-btn-small" :disabled="working" data-testid="bootstrap-history-undo" @click="showUndo(b)">
              {{ t("memory.bootstrap.undo.button") }}
            </button>
          </div>
        </li>
      </ul>
    </template>

    <!-- 2. Progress (cancel stops the model now and deletes the draft) -->
    <template v-else-if="screen === 'progress' && batch">
      <p class="mem-text">{{ batch.file_name }} · {{ t(`memory.bootstrap.status.${batch.status}`) }}</p>
      <template v-if="batch.status === 'analyzing'">
        <progress class="mem-progress" :max="Math.max(batch.sections_total, 1)" :value="batch.sections_done + batch.sections_failed" />
        <p class="mem-small" role="status" data-testid="bootstrap-progress">
          {{ t("memory.bootstrap.progress", { done: batch.sections_done, total: batch.sections_total }) }}
          <template v-if="batch.sections_failed"> · {{ t("memory.bootstrap.progressFailed", { n: batch.sections_failed }) }}</template>
        </p>
        <p class="muted mem-small">{{ t("memory.bootstrap.progressNote") }}</p>
        <button type="button" class="btn mem-btn-small" :disabled="working" data-testid="bootstrap-cancel" @click="cancel">{{ t("memory.bootstrap.cancel") }}</button>
      </template>
      <template v-else-if="batch.status === 'failed'">
        <p class="mem-error" role="alert" data-testid="bootstrap-failed">{{ t("memory.bootstrap.failed", { reason: failReason }) }}</p>
        <p class="muted mem-small">{{ t("memory.bootstrap.retryNote") }}</p>
        <div class="mem-actions">
          <button type="button" class="btn mem-btn-small" :disabled="working" data-testid="bootstrap-retry" @click="retry">{{ t("memory.bootstrap.retry") }}</button>
          <button type="button" class="btn mem-btn-small" :disabled="working" @click="discard">{{ t("memory.bootstrap.discard") }}</button>
        </div>
      </template>
      <button v-if="batch.status !== 'analyzing'" type="button" class="btn mem-btn-small" @click="reset">{{ t("memory.bootstrap.newImport") }}</button>
    </template>

    <!-- 3 + 4. Preview, people and conflicts -->
    <template v-else-if="screen === 'preview' && preview && summary">
      <p class="mem-text">{{ preview.batch.file_name }}</p>
      <details v-if="preview.batch.warnings.length" class="mem-small">
        <summary>{{ t("memory.bootstrap.warnings") }} ({{ preview.batch.warnings.length }})</summary>
        <span v-for="w in preview.batch.warnings" :key="w" class="muted">{{ w }}<br /></span>
      </details>
      <div v-if="preview.batch.sections_failed" class="mem-row">
        <span class="mem-warn">{{ t("memory.bootstrap.progressFailed", { n: preview.batch.sections_failed }) }}</span>
        <button type="button" class="btn mem-btn-small" :disabled="working" data-testid="bootstrap-retry" @click="retry">{{ t("memory.bootstrap.retry") }}</button>
      </div>
      <BootstrapPreview :preview="preview" :working="working" @decide="decide" />
      <div class="mem-actions">
        <button type="button" class="btn mem-btn-small" :disabled="working" data-testid="bootstrap-to-confirm" @click="screen = 'confirm'">
          {{ t("memory.bootstrap.toConfirm") }}
        </button>
        <button type="button" class="btn mem-btn-small" :disabled="working" data-testid="bootstrap-discard" @click="discard">{{ t("memory.bootstrap.discard") }}</button>
      </div>
    </template>

    <!-- 5. Final confirmation: counted from the decisions, nothing written yet -->
    <template v-else-if="screen === 'confirm' && summary">
      <h3 class="mem-heading">{{ t("memory.bootstrap.summary.title") }}</h3>
      <ul class="mem-summary" data-testid="bootstrap-summary">
        <li><strong>{{ t("memory.bootstrap.summary.writable", { n: summary.writable }) }}</strong></li>
        <li v-if="summary.updates">{{ t("memory.bootstrap.summary.updates", { n: summary.updates }) }}</li>
        <li v-if="summary.people_new">{{ t("memory.bootstrap.summary.peopleNew", { n: summary.people_new }) }}</li>
        <li v-if="summary.people_linked">{{ t("memory.bootstrap.summary.peopleLinked", { n: summary.people_linked }) }}</li>
        <li v-if="summary.rejected">{{ t("memory.bootstrap.summary.rejected", { n: summary.rejected }) }}</li>
        <li v-if="summary.held">{{ t("memory.bootstrap.summary.held", { n: summary.held }) }}</li>
        <li v-if="summary.pending" class="mem-warn">{{ t("memory.bootstrap.summary.pending", { n: summary.pending }) }}</li>
        <li v-if="summary.blocked" class="mem-warn">{{ t("memory.bootstrap.summary.blocked", { n: summary.blocked }) }}</li>
        <li v-if="summary.excluded">{{ t("memory.bootstrap.summary.excluded", { n: summary.excluded }) }}</li>
      </ul>
      <template v-if="Object.keys(summary.by_category).length">
        <p class="muted mem-small">{{ t("memory.bootstrap.summary.byCategory") }}</p>
        <ul class="mem-summary">
          <li v-for="(n, c) in summary.by_category" :key="c">{{ t(`memory.bootstrap.category.${c}`) }}: {{ n }}</li>
        </ul>
      </template>
      <div class="mem-actions">
        <button type="button" class="btn mem-btn-small" :disabled="working || summary.writable === 0" data-testid="bootstrap-apply" @click="apply">
          {{ working ? t("memory.bootstrap.applying") : t("memory.bootstrap.apply") }}
        </button>
        <button type="button" class="btn mem-btn-small" :disabled="working" @click="screen = 'preview'">{{ t("memory.bootstrap.back") }}</button>
      </div>
    </template>

    <!-- 6. Result: the real counts, the import id, undo -->
    <template v-else-if="screen === 'result' && batch">
      <h3 class="mem-heading">{{ t("memory.bootstrap.result.title") }} · {{ t(`memory.bootstrap.status.${batch.status}`) }}</h3>
      <p class="muted mem-small" data-testid="bootstrap-import-id">{{ t("memory.bootstrap.result.id", { id: batch.id }) }}</p>
      <ul class="mem-summary" data-testid="bootstrap-result">
        <li><strong>{{ t("memory.bootstrap.result.written", { n: counts.written ?? 0 }) }}</strong></li>
        <li v-if="counts.updated">{{ t("memory.bootstrap.result.updated", { n: counts.updated }) }}</li>
        <li v-if="counts.evidence_added">{{ t("memory.bootstrap.result.evidenceAdded", { n: counts.evidence_added }) }}</li>
        <li v-if="counts.kept_old">{{ t("memory.bootstrap.result.keptOld", { n: counts.kept_old }) }}</li>
        <li v-if="counts.people_created">{{ t("memory.bootstrap.result.peopleCreated", { n: counts.people_created }) }}</li>
        <li v-if="counts.people_linked">{{ t("memory.bootstrap.result.peopleLinked", { n: counts.people_linked }) }}</li>
        <li v-if="counts.rejected">{{ t("memory.bootstrap.result.rejected", { n: counts.rejected }) }}</li>
        <li v-if="counts.held">{{ t("memory.bootstrap.result.held", { n: counts.held }) }}</li>
        <li v-if="counts.pending">{{ t("memory.bootstrap.result.pending", { n: counts.pending }) }}</li>
        <li v-if="counts.blocked" class="mem-warn">{{ t("memory.bootstrap.result.blocked", { n: counts.blocked }) }}</li>
        <li v-if="counts.failed" class="mem-warn">{{ t("memory.bootstrap.result.failed", { n: counts.failed }) }}</li>
        <li v-if="counts.excluded">{{ t("memory.bootstrap.result.excluded", { n: counts.excluded }) }}</li>
      </ul>
      <div class="mem-actions">
        <button v-if="batch.status === 'applied'" type="button" class="btn mem-btn-small" :disabled="working" data-testid="bootstrap-undo" @click="showUndo()">
          {{ t("memory.bootstrap.undo.button") }}
        </button>
        <button type="button" class="btn mem-btn-small" @click="reset">{{ t("memory.bootstrap.newImport") }}</button>
      </div>
    </template>

    <!-- Undo: the plan first -->
    <template v-else-if="screen === 'undo' && plan">
      <h3 class="mem-heading">{{ t("memory.bootstrap.undo.title") }}</h3>
      <p class="muted mem-small">{{ t("memory.bootstrap.undo.note") }}</p>
      <p v-if="plan.steps.length === 0" class="muted mem-small">{{ t("memory.bootstrap.undo.nothing") }}</p>
      <section v-for="g in planGroups" :key="g.action" class="mem-group" data-testid="bootstrap-undo-group">
        <h4 class="mem-heading">{{ t(`memory.bootstrap.undo.action.${g.action}`) }} · {{ g.steps.length }}</h4>
        <ul class="mem-list">
          <li v-for="s in g.steps" :key="`${s.action}-${s.target_id}`" class="mem-item">
            <span class="mem-text">{{ s.label }}</span>
            <div class="mem-meta">
              <span class="mem-badge">{{ t(`memory.bootstrap.table.${s.table}`) }}</span>
              <span v-if="s.reason && s.reason !== 'already_deleted'">{{ t(`memory.bootstrap.undo.reason.${s.reason}`) }}</span>
            </div>
            <label v-if="s.action === 'decide'" class="mem-row mem-small">
              <input type="checkbox" :checked="restore.has(s.target_id)" data-testid="bootstrap-undo-restore" @change="toggleRestore(s.target_id, ($event.target as HTMLInputElement).checked)" />
              {{ t("memory.bootstrap.undo.restoreAnyway") }}
            </label>
          </li>
        </ul>
      </section>
      <div class="mem-actions">
        <button type="button" class="btn mem-btn-small" :disabled="working || plan.already_undone" data-testid="bootstrap-undo-confirm" @click="undo">
          {{ working ? t("memory.bootstrap.undo.working") : t("memory.bootstrap.undo.confirm") }}
        </button>
        <button type="button" class="btn mem-btn-small" :disabled="working" @click="screen = 'result'">{{ t("memory.bootstrap.back") }}</button>
      </div>
    </template>

    <p v-if="error" class="mem-error" role="alert" data-testid="bootstrap-error">{{ error }}</p>
    <p v-if="notice" class="mem-ok" role="status" data-testid="bootstrap-notice">{{ notice }}</p>
  </section>
</template>
