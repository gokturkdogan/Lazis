<script setup lang="ts">
/**
 * A document to talk about (Phase 11, first version). The user picks a TXT, PDF or DOCX file;
 * the app reads it here and sends its bytes, the backend extracts the text and keeps it in
 * memory for this session only. While it is open, messages are about it: "Özetle" is an
 * ordinary message, and every question is answered from the document. Nothing is learned
 * from it, and closing it (or quitting the app) drops it.
 */
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { ApiError } from "@/api/client";
import { errorKey } from "@/i18n";
import { useAssistantStore } from "@/stores/assistant";
import { currentApiClient } from "@/stores/connection";

const MAX_BYTES = 10_000_000;
const ACCEPT = ".txt,.pdf,.docx";

const { t } = useI18n();
const store = useAssistantStore();
const busy = ref(false);
const error = ref<string | null>(null);
const doc = computed(() => store.document);

function base64Of(bytes: Uint8Array): string {
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  }
  return btoa(binary);
}

async function guarded(action: () => Promise<void>) {
  const client = currentApiClient();
  if (client === null) {
    error.value = t(errorKey("backend_unreachable"));
    return;
  }
  busy.value = true;
  error.value = null;
  try {
    await action();
  } catch (e) {
    error.value = t(errorKey(e instanceof ApiError ? e.code : null));
  } finally {
    busy.value = false;
  }
}

async function pick(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (!file) return;
  if (file.size > MAX_BYTES) {
    error.value = t("errors.document_too_large");
    return;
  }
  await guarded(async () => {
    const bytes = new Uint8Array(await file.arrayBuffer());
    const opened = await currentApiClient()!.addDocument(file.name, base64Of(bytes));
    const previous = store.document;
    store.setDocument(opened);
    // One document at a time in this version: the one it replaces is closed.
    if (previous !== null) await currentApiClient()!.removeDocument(previous.id).catch(() => false);
  });
}

async function close() {
  const open = store.document;
  if (open === null) return;
  await guarded(async () => {
    store.setDocument(null);
    await currentApiClient()!
      .removeDocument(open.id)
      .catch((e: unknown) => {
        // Already gone on the backend: closed is closed.
        if (!(e instanceof ApiError && e.code === "document_not_found")) throw e;
      });
  });
}

async function summarize() {
  if (!store.canSend) return;
  await store.send(t("documents.summaryMessage"));
}

const details = computed(() => {
  const d = doc.value;
  if (d === null) return "";
  const kind = d.kind.toUpperCase();
  return d.pages !== null ? t("documents.detailsPages", { kind, pages: d.pages }) : kind;
});
</script>

<template>
  <section class="panel documents" data-testid="documents">
    <template v-if="doc === null">
      <label class="btn" :class="{ disabled: busy }">
        {{ busy ? t("documents.reading") : t("documents.add") }}
        <input type="file" :accept="ACCEPT" :disabled="busy" data-testid="document-file" @change="pick" />
      </label>
      <span class="muted small">{{ t("documents.hint") }}</span>
    </template>
    <template v-else>
      <div class="open">
        <strong data-testid="document-name">{{ doc.name }}</strong>
        <small class="muted">{{ details }} · {{ t("documents.active") }}</small>
        <small v-if="doc.truncated" class="muted">{{ t("documents.truncated") }}</small>
      </div>
      <button class="btn" type="button" data-testid="document-summary" :disabled="busy || !store.canSend" @click="summarize">
        {{ t("documents.summarize") }}
      </button>
      <button class="btn" type="button" data-testid="document-close" :disabled="busy" @click="close">
        {{ t("documents.close") }}
      </button>
    </template>
    <p v-if="error" class="error small" role="alert">{{ error }}</p>
  </section>
</template>

<style scoped>
.documents {
  padding: 10px 14px;
  margin-bottom: 10px;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
input[type="file"] {
  display: none;
}
.open {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.open strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.small,
small {
  font-size: 12px;
}
.error {
  flex-basis: 100%;
  margin: 0;
  color: var(--danger);
}
.disabled {
  opacity: 0.6;
  pointer-events: none;
}
</style>
