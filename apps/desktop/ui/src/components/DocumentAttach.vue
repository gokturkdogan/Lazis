<script setup lang="ts">
/** The paperclip next to the message field (Phase 14.1): opens the system file picker. */
import { ref } from "vue";
import { useI18n } from "vue-i18n";
import Icon from "@/components/Icon.vue";
import { DOCUMENT_ACCEPT, useDocumentUi } from "@/stores/documentUi";

const { t } = useI18n();
const ui = useDocumentUi();
const input = ref<HTMLInputElement | null>(null);

async function pick(event: Event) {
  const el = event.target as HTMLInputElement;
  const file = el.files?.[0];
  el.value = "";
  if (file) await ui.open(file);
}
</script>

<template>
  <button
    class="icon-btn attach"
    type="button"
    data-testid="document-attach"
    :aria-label="t('documents.add')"
    :title="t('documents.add')"
    :disabled="ui.busy"
    :aria-busy="ui.busy"
    @click="input?.click()"
  >
    <Icon name="paperclip" :size="19" />
  </button>
  <input ref="input" class="file" type="file" :accept="DOCUMENT_ACCEPT" data-testid="document-file" tabindex="-1" aria-hidden="true" @change="pick" />
</template>

<style scoped>
.attach {
  width: 40px;
  height: 40px;
  border-radius: 12px;
}
.attach[aria-busy="true"] {
  animation: pulse-soft 1.2s ease-in-out infinite;
}
.file {
  display: none;
}
</style>
