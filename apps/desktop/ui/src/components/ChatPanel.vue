<script setup lang="ts">
/**
 * Minimal Phase 2 chat with a local model: model choice, streamed answer, stop, Turkish
 * errors. Ephemeral by design (see stores/chat.ts). Not the Phase 3 conversation UI.
 */
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { errorKey } from "@/i18n";
import { formatBytes } from "@/format";
import { useChatStore, type ChatEntry } from "@/stores/chat";

const chat = useChatStore();
const { t } = useI18n();
const draft = ref("");
const list = ref<HTMLElement | null>(null);

onMounted(() => void chat.refresh());

const runtimeDown = computed(() => chat.inventoryLoaded && chat.runtime?.available !== true);
const noModels = computed(
  () => chat.inventoryLoaded && chat.runtime?.available === true && chat.models.length === 0,
);
const loadedLabel = computed(() => {
  const first = chat.loaded[0];
  return first
    ? t("conversation.loaded", { model: first.name, size: formatBytes(first.size_bytes) })
    : t("conversation.notLoaded");
});

function metricsLine(entry: ChatEntry): string {
  const m = entry.metrics;
  if (!m) return "";
  const ttft = m.ttft_ms === null ? "—" : `${(m.ttft_ms / 1000).toFixed(2)} sn`;
  const tps = m.decode_tps === null ? "—" : m.decode_tps.toFixed(1);
  return t("conversation.metrics", { ttft, tps, tokens: m.output_tokens ?? "—" });
}

async function submit() {
  if (!chat.canSend || draft.value.trim() === "") return;
  const text = draft.value;
  draft.value = "";
  await chat.send(text);
}

function onKey(event: KeyboardEvent) {
  if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
    event.preventDefault();
    void submit();
  }
}

watch(
  () => chat.messages.map((m) => m.content.length).join(","),
  async () => {
    await nextTick();
    list.value?.scrollTo({ top: list.value.scrollHeight });
  },
);
</script>

<template>
  <section class="chat panel" data-testid="chat-panel">
    <header>
      <h2>{{ t("conversation.title") }}</h2>
      <span class="badge">{{ t("conversation.ephemeral") }}</span>
      <div class="spacer" />
      <label class="model">
        <span class="muted">{{ t("conversation.model") }}</span>
        <select
          v-model="chat.selectedModel"
          data-testid="model-select"
          :disabled="chat.busy || chat.models.length === 0"
        >
          <option v-for="m in chat.models" :key="m.name" :value="m.name">
            {{ m.name }} · {{ m.parameter_size }} · {{ formatBytes(m.size_bytes) }}
          </option>
        </select>
      </label>
      <button class="btn" type="button" :disabled="chat.busy" @click="chat.refresh()">
        {{ t("conversation.refresh") }}
      </button>
      <button
        class="btn"
        type="button"
        :disabled="chat.busy || chat.messages.length === 0"
        data-testid="chat-clear"
        @click="chat.clear()"
      >
        {{ t("conversation.clear") }}
      </button>
    </header>

    <p class="notice muted" data-testid="chat-notice">{{ t("conversation.notice") }}</p>

    <div v-if="runtimeDown" class="state error" data-testid="chat-runtime-down">
      <strong>{{ t("conversation.runtimeDown") }}</strong>
      <span class="muted">{{ t("conversation.runtimeDownHint") }}</span>
    </div>
    <div v-else-if="noModels" class="state" data-testid="chat-no-models">
      <strong>{{ t("conversation.noModels") }}</strong>
      <span class="muted mono">{{ t("conversation.noModelsHint") }}</span>
    </div>

    <div ref="list" class="messages" data-testid="chat-messages" aria-live="polite">
      <p v-if="chat.messages.length === 0" class="muted empty">{{ t("conversation.empty") }}</p>
      <article
        v-for="m in chat.messages"
        :key="m.id"
        :class="['message', m.role, m.state]"
        :data-testid="`message-${m.role}`"
      >
        <span class="who">{{ m.role === "user" ? t("conversation.you") : t("conversation.lazis") }}</span>
        <p v-if="m.content" class="text">{{ m.content }}</p>
        <p v-else-if="m.state === 'streaming'" class="muted" data-testid="chat-loading">
          {{ t("conversation.loadingModel") }}
        </p>
        <p v-if="m.state === 'cancelled'" class="muted small">{{ t("conversation.cancelled") }}</p>
        <p v-if="m.state === 'error' && m.errorCode" class="error small" data-testid="chat-error">
          {{ t(errorKey(m.errorCode)) }}
        </p>
        <p v-if="m.metrics" class="muted small mono" data-testid="chat-metrics">{{ metricsLine(m) }}</p>
      </article>
    </div>

    <form class="composer" @submit.prevent="submit">
      <textarea
        v-model="draft"
        rows="2"
        data-testid="chat-input"
        :placeholder="t('conversation.placeholder')"
        :disabled="!chat.canSend && !chat.busy"
        @keydown="onKey"
      />
      <button
        v-if="!chat.busy"
        class="btn btn-primary"
        type="submit"
        data-testid="chat-send"
        :disabled="!chat.canSend || draft.trim() === ''"
      >
        {{ t("conversation.send") }}
      </button>
      <button
        v-else
        class="btn"
        type="button"
        data-testid="chat-stop"
        :disabled="chat.phase === 'cancelling'"
        @click="chat.cancel()"
      >
        {{ chat.phase === "cancelling" ? t("conversation.stopping") : t("conversation.stop") }}
      </button>
    </form>
    <p class="muted small mono status-line" data-testid="chat-loaded">{{ loadedLabel }}</p>
  </section>
</template>

<style scoped>
.chat {
  padding: 18px 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
header {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
h2 {
  margin: 0;
  font-size: 16px;
}
.spacer {
  flex: 1;
}
.badge {
  font-size: 11px;
  padding: 2px 10px;
  border-radius: 999px;
  border: 1px solid var(--warn);
  color: var(--warn);
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
.notice {
  margin: 0;
  font-size: 12px;
  max-width: 90ch;
}
.state {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid var(--panel-border);
}
.state.error {
  border-color: var(--danger);
}
.messages {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 46vh;
  min-height: 120px;
  overflow-y: auto;
  padding-right: 4px;
}
.empty {
  margin: 0;
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
.message.error {
  border-color: var(--danger);
}
.who {
  font-size: 11px;
  color: var(--text-muted);
}
.text {
  margin: 4px 0 0;
  white-space: pre-wrap;
  user-select: text;
  line-height: 1.5;
}
.small {
  font-size: 12px;
  margin: 4px 0 0;
}
.error {
  color: var(--danger);
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
.status-line {
  margin: 0;
}
</style>
