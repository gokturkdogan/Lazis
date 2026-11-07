<script setup lang="ts">
/**
 * The open document as a small tag above the message field (Phase 14.1): name, kind, pages,
 * "Özetle", and one-click removal; reading and error states. Rendered only when there is
 * something to show.
 */
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import Icon from "@/components/Icon.vue";
import { errorKey } from "@/i18n";
import { useAssistantStore } from "@/stores/assistant";
import { useDocumentUi } from "@/stores/documentUi";

const { t } = useI18n();
const store = useAssistantStore();
const ui = useDocumentUi();
const doc = computed(() => store.document);

const details = computed(() => {
  const d = doc.value;
  if (d === null) return "";
  const kind = d.kind.toUpperCase();
  return d.pages !== null ? t("documents.detailsPages", { kind, pages: d.pages }) : kind;
});
const errorText = computed(() => {
  const code = ui.error;
  if (!code) return null;
  return code.startsWith("document_") ? t(`errors.${code}`) : t(errorKey(code));
});

async function summarize() {
  if (store.canSend) await store.send(t("documents.summaryMessage"));
}
</script>

<template>
  <div v-if="doc || ui.busy || errorText" class="chips" data-testid="documents">
    <span v-if="ui.busy" class="chip busy" role="status">
      <span class="dot" aria-hidden="true" />{{ t("documents.reading") }}
    </span>
    <span v-else-if="doc" class="chip" :title="doc.truncated ? t('documents.truncated') : t('documents.active')">
      <Icon name="file" :size="14" />
      <strong data-testid="document-name">{{ doc.name }}</strong>
      <small>{{ details }}<template v-if="doc.truncated"> · {{ t("documents.truncatedShort") }}</template></small>
      <button class="mini" type="button" data-testid="document-summary" :disabled="!store.canSend" @click="summarize">
        {{ t("documents.summarize") }}
      </button>
      <button class="mini x" type="button" data-testid="document-close" :aria-label="t('documents.close')" :title="t('documents.close')" @click="ui.close()">
        <Icon name="x" :size="13" />
      </button>
    </span>
    <span v-if="errorText" class="chip error" role="alert" data-testid="document-error">{{ errorText }}</span>
  </div>
</template>

<style scoped>
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}
.chip {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  max-width: 100%;
  padding: 5px 6px 5px 10px;
  border-radius: 999px;
  border: 1px solid color-mix(in srgb, var(--accent) 35%, transparent);
  background: color-mix(in srgb, var(--accent) 10%, rgb(4 10 22 / 0.7));
  font-size: 12px;
  color: var(--text);
  animation: chip-in 220ms ease-out;
}
.chip strong {
  font-weight: 500;
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.chip small {
  color: var(--text-muted);
  font-size: 11px;
}
.chip.busy {
  padding-right: 12px;
  color: var(--text-muted);
}
.chip.error {
  border-color: rgb(255 23 68 / 0.45);
  background: rgb(255 23 68 / 0.08);
  color: #ff8aa0;
  padding-right: 12px;
}
.dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--accent);
  animation: pulse-soft 1.2s ease-in-out infinite;
}
.mini {
  border: 0;
  background: rgb(255 255 255 / 0.06);
  color: var(--text);
  font-size: 11px;
  padding: 3px 8px;
  border-radius: 999px;
  transition: background 150ms;
}
.mini:hover:not(:disabled) {
  background: color-mix(in srgb, var(--accent) 30%, transparent);
}
.mini.x {
  display: grid;
  place-items: center;
  width: 22px;
  height: 22px;
  padding: 0;
}
@keyframes chip-in {
  from {
    opacity: 0;
    transform: translateY(4px);
  }
}
</style>
