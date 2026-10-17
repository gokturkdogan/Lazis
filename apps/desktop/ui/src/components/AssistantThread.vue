<script setup lang="ts">
/** The one assistant: a single timeline (paged), streaming reply, real backend stages, stop.
 *  No conversation list, no "new chat", no renaming: technical sessions are invisible.
 *  Replies render as safe Markdown once complete (plain text while streaming, so partial
 *  syntax never flickers). The view follows new text only while the reader is at the bottom. */
import { computed, nextTick, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import type { Message } from "@/api/client";
import MarkdownContent from "@/components/MarkdownContent.vue";
import { formatBytes, formatWhen } from "@/format";
import { errorKey } from "@/i18n";
import { copyText } from "@/platform/clipboard";
import { useAssistantStore } from "@/stores/assistant";
import { useConnectionStore } from "@/stores/connection";

const store = useAssistantStore();
const connection = useConnectionStore();
const { t } = useI18n();
const draft = ref("");
const list = ref<HTMLElement | null>(null);
/** The reader is at (or near) the newest message; only then does new text scroll the view. */
const atBottom = ref(true);
const unseen = ref(false);
const copiedId = ref<string | null>(null);
const BOTTOM_SLACK_PX = 48;

const fileVaultOff = computed(() => connection.connection?.fileVault === "off");
const turnHere = computed(() => store.turn !== null);

/** Index of the first message of the active session when older messages are on screen:
 *  everything above it is in the timeline but not in LAZIS's current context. */
const contextBoundary = computed(() => {
  const from = store.activeFrom;
  if (from === null) return -1;
  const index = store.messages.findIndex((m) => m.timeline_seq >= from);
  return index > 0 || (index === 0 && store.hasOlder) ? index : -1;
});
const loadedLabel = computed(() => {
  const first = store.loaded[0];
  return first
    ? t("conversation.loaded", { model: first.name, size: formatBytes(first.size_bytes) })
    : t("conversation.notLoaded");
});

const stageLabel = computed(() => {
  const turn = store.turn;
  if (!turnHere.value || turn === null) return "";
  if (store.phase === "cancelling") return t("conversation.stage.cancelling");
  switch (turn.stage) {
    case "loading_model":
      return t("conversation.stage.loading_model");
    case "compacting":
      return t("conversation.stage.compacting");
    case "processing_context":
      return turn.cache === "cold"
        ? t("conversation.stage.processing_cold", { tokens: turn.contextTokens ?? "?" })
        : t("conversation.stage.processing_warm");
    case "generating":
      return t("conversation.stage.generating");
    default:
      return t("conversation.stage.waiting");
  }
});

const contextNotice = computed(() => {
  const ctx = store.context;
  if (ctx === null) return "";
  if (ctx.omitted) return t("conversation.omitted");
  if (ctx.summary) return t("conversation.summarized");
  return "";
});

const backgroundLabel = computed(() => {
  const bg = store.background;
  if (bg === null || bg.conversation_id !== (store.session?.id ?? null)) return "";
  return t(`conversation.background.${bg.kind}`);
});

function metricsLine(m: Message): string {
  const metrics = m.metrics;
  if (!metrics || m.status !== "complete") return "";
  const ttft = metrics.ttft_ms === null ? "—" : `${(metrics.ttft_ms / 1000).toFixed(2)} sn`;
  return t("conversation.metrics", { ttft, tokens: metrics.output_tokens ?? "—" });
}

async function submit() {
  const text = draft.value;
  if (!store.canSend || text.trim() === "") return;
  draft.value = "";
  atBottom.value = true; // sending is an explicit "show me the reply"
  const accepted = await store.send(text);
  if (!accepted && draft.value === "") draft.value = text; // refused before storing: keep it
}

function renderAsMarkdown(m: Message): boolean {
  return m.role === "assistant" && m.status !== "streaming" && m.content !== "";
}

async function copyMessage(m: Message) {
  if (await copyText(m.content)) {
    copiedId.value = m.id;
    setTimeout(() => {
      if (copiedId.value === m.id) copiedId.value = null;
    }, 1500);
  }
}

function onScroll() {
  const el = list.value;
  if (!el) return;
  atBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight <= BOTTOM_SLACK_PX;
  if (atBottom.value) unseen.value = false;
}

function scrollToLatest() {
  const el = list.value;
  if (!el) return;
  el.scrollTo({ top: el.scrollHeight });
  atBottom.value = true;
  unseen.value = false;
}

/** Older messages are prepended: keep what the reader is looking at in place. */
async function loadOlder() {
  const el = list.value;
  const before = el ? el.scrollHeight - el.scrollTop : 0;
  await store.loadOlder();
  await nextTick();
  if (el) el.scrollTop = el.scrollHeight - before;
}

function onKey(event: KeyboardEvent) {
  if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
    event.preventDefault();
    void submit();
  }
}

function onInput() {
  store.composerActivity();
}

// New text at the end (a new turn, streaming, the Markdown re-render when a reply completes):
// follow it only if the reader is at the bottom; otherwise offer a "new message" button.
watch(
  () => {
    const last = store.messages[store.messages.length - 1];
    return `${last?.id ?? ""}|${last?.content.length ?? 0}|${last?.status ?? ""}`;
  },
  async () => {
    if (!atBottom.value) {
      unseen.value = true;
      return;
    }
    await nextTick();
    list.value?.scrollTo({ top: list.value.scrollHeight });
  },
);
</script>

<template>
  <section class="thread panel" data-testid="conversation-thread">
    <header>
      <div class="heading">
        <h2 data-testid="thread-title">{{ t("conversation.title") }}</h2>
        <span class="muted small">{{ t("conversation.subtitle") }}</span>
      </div>
      <label class="model">
        <span class="muted">{{ t("conversation.model") }}</span>
        <select
          v-model="store.selectedModel"
          data-testid="model-select"
          :disabled="store.busy || store.models.length === 0"
          @change="store.prepare(true)"
        >
          <option v-for="m in store.models" :key="m.name" :value="m.name">
            {{ m.name }} · {{ m.parameter_size }} · {{ formatBytes(m.size_bytes) }}
          </option>
        </select>
      </label>
    </header>

    <p v-if="fileVaultOff" class="banner warn" data-testid="filevault-warning">
      {{ t("conversation.fileVaultOff") }}
    </p>
    <div v-if="store.runtimeDown" class="banner danger" data-testid="runtime-down">
      <strong>{{ t("conversation.runtimeDown") }}</strong>
      <span class="muted">{{ t("conversation.runtimeDownHint") }}</span>
    </div>
    <div v-else-if="store.noModels" class="banner" data-testid="no-models">
      <strong>{{ t("conversation.noModels") }}</strong>
      <span class="muted mono">{{ t("conversation.noModelsHint") }}</span>
    </div>
    <p v-if="contextNotice" class="muted small notice" data-testid="context-notice">{{ contextNotice }}</p>

    <div ref="list" class="messages" data-testid="messages" @scroll.passive="onScroll">
      <button
        v-if="store.hasOlder"
        class="btn older"
        type="button"
        data-testid="load-older"
        :disabled="store.loadingMessages"
        @click="loadOlder()"
      >
        {{ t("conversation.loadOlder") }}
      </button>
      <p v-if="store.loadingMessages && store.messages.length === 0" class="muted">
        {{ t("conversation.loadingMessages") }}
      </p>
      <p v-else-if="store.ready && store.messages.length === 0" class="muted empty" data-testid="empty-thread">
        {{ t("conversation.empty") }}
      </p>
      <template v-for="(m, index) in store.messages" :key="m.id">
        <p v-if="index === contextBoundary" class="boundary" role="separator" data-testid="context-boundary">
          <span>{{ t("conversation.boundary") }}</span>
        </p>
      <article
        :class="['message', m.role, m.status]"
        :data-testid="`message-${m.role}`"
        :data-status="m.status"
        :data-timeline="m.timeline_seq"
      >
        <span class="who">
          {{ m.role === "user" ? t("conversation.you") : t("conversation.lazis") }}
          <span class="when">· {{ formatWhen(m.created_at) }}</span>
          <button
            v-if="m.content && m.status !== 'streaming'"
            class="copy"
            type="button"
            :data-testid="`copy-${m.role}`"
            :aria-label="t('conversation.copyMessage')"
            @click="copyMessage(m)"
          >
            {{ copiedId === m.id ? t("conversation.copied") : t("conversation.copy") }}
          </button>
        </span>
        <MarkdownContent v-if="renderAsMarkdown(m)" :source="m.content" />
        <p v-else-if="m.content" class="text">{{ m.content }}</p>
        <p v-if="m.status === 'cancelled'" class="muted small">{{ t("conversation.cancelled") }}</p>
        <p v-else-if="m.status === 'interrupted'" class="warn-text small" data-testid="interrupted-note">
          {{ t("conversation.interrupted") }}
        </p>
        <p v-else-if="m.status === 'failed'" class="error small" data-testid="failed-note">
          {{ t(errorKey(m.error_code)) }}
        </p>
        <p v-if="metricsLine(m)" class="muted small mono">{{ metricsLine(m) }}</p>
      </article>
      </template>
    </div>

    <button v-if="unseen" class="btn latest" type="button" data-testid="jump-latest" @click="scrollToLatest">
      {{ t("conversation.jumpLatest") }} ↓
    </button>
    <p v-if="stageLabel" class="stage" role="status" data-testid="turn-status">{{ stageLabel }}</p>
    <p v-if="turnHere && store.turn?.trimmed" class="warn-text small" data-testid="trimmed-notice">
      {{ t("conversation.trimmed", { from: store.turn.trimmed[0], to: store.turn.trimmed[1] }) }}
    </p>
    <p v-if="backgroundLabel && !store.busy" class="muted small" data-testid="background-status">
      {{ backgroundLabel }}…
    </p>
    <p v-if="store.errorCode && !store.busy" class="error small" role="alert" data-testid="thread-error">
      {{ t(errorKey(store.errorCode)) }}
    </p>

    <form class="composer" @submit.prevent="submit">
      <textarea
        v-model="draft"
        rows="3"
        data-testid="composer"
        maxlength="16000"
        :placeholder="t('conversation.placeholder')"
        :disabled="store.runtimeDown || store.noModels"
        @keydown="onKey"
        @input="onInput"
      />
      <button
        v-if="!turnHere"
        class="btn btn-primary"
        type="submit"
        data-testid="send"
        :disabled="!store.canSend || draft.trim() === ''"
      >
        {{ t("conversation.send") }}
      </button>
      <button
        v-else
        class="btn"
        type="button"
        data-testid="stop"
        :disabled="store.phase === 'cancelling'"
        @click="store.cancel()"
      >
        {{ store.phase === "cancelling" ? t("conversation.stopping") : t("conversation.stop") }}
      </button>
    </form>
    <p class="muted small footer">
      <span>{{ t("conversation.storedNotice") }}</span>
      <span class="mono" data-testid="loaded-model">{{ loadedLabel }}</span>
    </p>
  </section>
</template>

<style scoped>
.thread {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 16px 18px;
  min-height: 0;
  min-width: 0;
}
header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.heading {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
h2 {
  margin: 0;
  font-size: 16px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.model {
  display: flex;
  align-items: center;
  gap: 8px;
}
select {
  background: var(--bg-elevated);
  color: var(--text);
  border: 1px solid var(--panel-border-strong);
  border-radius: 8px;
  padding: 6px 8px;
  max-width: 340px;
}
.banner {
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 9px 12px;
  border-radius: 10px;
  border: 1px solid var(--panel-border);
  font-size: 13px;
}
.banner.warn {
  border-color: var(--warn);
  color: var(--warn);
}
.banner.danger {
  border-color: var(--danger);
}
.notice {
  margin: 0;
}
.messages {
  flex: 1;
  min-height: 160px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding-right: 4px;
}
.older {
  align-self: center;
}
.empty {
  margin: auto;
}
.boundary {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 6px 0;
  font-size: 11px;
  color: var(--text-faint);
}
.boundary::before,
.boundary::after {
  content: "";
  flex: 1;
  border-top: 1px dashed var(--panel-border);
}
.message {
  padding: 10px 12px;
  border-radius: 12px;
  border: 1px solid var(--panel-border);
  background: rgba(6, 10, 19, 0.55);
  max-width: 85%;
}
.message.user {
  align-self: flex-end;
  background: rgba(58, 160, 255, 0.12);
}
.message.failed {
  border-color: var(--danger);
}
.message.interrupted {
  border-color: var(--warn);
}
.who {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: var(--text-muted);
}
.copy {
  margin-left: auto;
  font: inherit;
  color: var(--text-faint);
  background: transparent;
  border: 0;
  padding: 0 2px;
  cursor: pointer;
  opacity: 0;
}
.message:hover .copy,
.copy:focus-visible {
  opacity: 1;
}
.latest {
  align-self: center;
  margin-top: -4px;
}
.when {
  color: var(--text-faint);
}
.text {
  margin: 4px 0 0;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  user-select: text;
  line-height: 1.55;
}
.small {
  font-size: 12px;
  margin: 4px 0 0;
}
.error {
  color: var(--danger);
}
.warn-text {
  color: var(--warn);
}
.stage {
  margin: 0;
  font-size: 13px;
  color: var(--state-thinking);
}
.composer {
  display: flex;
  gap: 10px;
  align-items: flex-end;
}
textarea {
  flex: 1;
  resize: vertical;
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid var(--panel-border-strong);
  background: rgba(6, 10, 19, 0.9);
  color: var(--text);
  font: inherit;
  user-select: text;
}
.footer {
  margin: 0;
  display: flex;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
</style>
