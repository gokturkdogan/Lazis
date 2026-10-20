<script setup lang="ts">
/** Starting-profile import: JSON or plain text → preview → apply only the selected items. */
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import type { ImportItem, ImportPreview } from "@/api/client";
import { ApiError } from "@/api/client";
import { errorKey } from "@/i18n";
import { currentApiClient } from "@/stores/connection";
import "./memory.css";

const emit = defineEmits<{ changed: [] }>();
// Example of the import format (code, not translatable prose; see lazis.memory.importer).
const JSON_EXAMPLE =
  '{ "user": { "occupation": "…", "technology": ["…"] }, "people": [ { "name": "…", "relation": "…", "facts": { "occupation": "…" } } ] }';
const { t } = useI18n();

const format = ref<"json" | "text">("json");
const content = ref("");
const preview = ref<ImportPreview | null>(null);
const choices = ref<Record<number, string>>({});
const working = ref(false);
const error = ref<string | null>(null);
const notice = ref<string | null>(null);

function client() {
  const c = currentApiClient();
  if (c === null) throw new ApiError(0, "backend_unreachable", "", true);
  return c;
}

function defaultChoice(item: ImportItem): string {
  // Sensitive items, duplicates and items needing a decision start unselected.
  if (item.sensitive || item.status === "duplicate" || item.status === "excluded") return "";
  if (item.status === "ambiguous" || item.status === "conflict") return "";
  return "apply";
}

async function runPreview() {
  working.value = true;
  error.value = null;
  notice.value = null;
  try {
    const result = await client().importPreview(format.value, content.value);
    preview.value = result;
    choices.value = Object.fromEntries(result.items.map((i) => [i.index, defaultChoice(i)]));
  } catch (e) {
    error.value = t(errorKey(e instanceof ApiError ? e.code : null));
  } finally {
    working.value = false;
  }
}

const selected = computed(() =>
  Object.fromEntries(Object.entries(choices.value).filter(([, v]) => v !== "")),
);

async function apply() {
  if (preview.value === null) return;
  working.value = true;
  try {
    const result = await client().importApply(preview.value.batch_id, selected.value);
    notice.value = t("memory.import.applied", { n: result.created + result.superseded });
    preview.value = null;
    content.value = "";
    emit("changed");
  } catch (e) {
    error.value = t(errorKey(e instanceof ApiError ? e.code : null));
  } finally {
    working.value = false;
  }
}

async function discard() {
  if (preview.value === null) return;
  try {
    await client().importDiscard(preview.value.batch_id);
  } catch {
    // The preview is closed either way; an orphan batch holds nothing beyond the preview.
  }
  preview.value = null;
}

function toggle(item: ImportItem, on: boolean) {
  choices.value = { ...choices.value, [item.index]: on ? "apply" : "" };
}
</script>

<template>
  <section class="panel mem-panel" data-testid="memory-import">
    <p class="muted mem-small">{{ t("memory.import.intro") }}</p>
    <template v-if="preview === null">
      <div class="mem-row">
        <label v-for="f in ['json', 'text'] as const" :key="f" class="mem-row mem-small">
          <input v-model="format" type="radio" :value="f" :data-testid="`import-format-${f}`" />
          {{ t(`memory.import.format.${f}`) }}
        </label>
      </div>
      <textarea
        v-model="content"
        class="mem-textarea"
        maxlength="60000"
        :placeholder="format === 'json' ? JSON_EXAMPLE : t('memory.import.placeholderText')"
        data-testid="import-content"
      />
      <div class="mem-actions">
        <button type="button" class="btn mem-btn-small" :disabled="working || content.trim() === ''" data-testid="import-preview" @click="runPreview">
          {{ t("memory.import.preview") }}
        </button>
        <span v-if="working" class="muted mem-small" role="status">{{ t("memory.import.previewing") }}</span>
      </div>
    </template>
    <template v-else>
      <p v-if="preview.items.length === 0" class="muted mem-small">{{ t("memory.import.nothing") }}</p>
      <ul class="mem-list">
        <li v-for="item in preview.items" :key="item.index" class="mem-item" :class="{ old: item.status === 'excluded' }" data-testid="import-item">
          <label class="mem-row">
            <input
              v-if="item.status !== 'ambiguous' && item.status !== 'conflict'"
              type="checkbox"
              :disabled="item.status === 'excluded'"
              :checked="choices[item.index] === 'apply'"
              :data-testid="`import-check-${item.index}`"
              @change="toggle(item, ($event.target as HTMLInputElement).checked)"
            />
            <span class="mem-text">{{ item.statement }}</span>
          </label>
          <div class="mem-meta">
            <span>{{ item.predicate_label }} · {{ item.subject }}</span>
            <span class="mem-badge" :class="{ warn: item.status === 'conflict' || item.status === 'ambiguous', danger: item.status === 'excluded' }">
              {{ t(`memory.import.status.${item.status}`) }}
            </span>
            <span v-if="item.sensitive" class="mem-badge danger">{{ t("memory.badge.sensitive") }}</span>
            <span v-if="item.reason">{{ t(`memory.import.reason.${item.reason}`) }}</span>
            <span v-for="v in item.existing" :key="v">· {{ t("memory.inbox.current", { value: v }) }}</span>
          </div>
          <select v-if="item.status === 'ambiguous'" v-model="choices[item.index]" class="mem-select">
            <option value="">{{ t("memory.import.choose") }}</option>
            <option v-for="o in item.options" :key="o.id" :value="o.id">{{ o.label }}</option>
            <option value="new">{{ t("memory.inbox.newPerson") }}</option>
          </select>
          <select v-if="item.status === 'conflict'" v-model="choices[item.index]" class="mem-select">
            <option value="">{{ t("memory.import.choose") }}</option>
            <option value="replace">{{ t("memory.import.replace") }}</option>
            <option value="both">{{ t("memory.import.both") }}</option>
          </select>
        </li>
      </ul>
      <details v-if="preview.errors.length" class="mem-small">
        <summary>{{ t("memory.import.warnings") }}</summary>
        <span v-for="e in preview.errors" :key="e" class="muted">{{ e }}<br /></span>
      </details>
      <div class="mem-actions">
        <button type="button" class="btn mem-btn-small" :disabled="working || Object.keys(selected).length === 0" data-testid="import-apply" @click="apply">
          {{ t("memory.import.apply") }}
        </button>
        <button type="button" class="btn mem-btn-small" @click="discard">{{ t("memory.import.discard") }}</button>
      </div>
    </template>
    <p v-if="error" class="mem-error" role="alert">{{ error }}</p>
    <p v-if="notice" class="mem-ok" role="status">{{ notice }}</p>
  </section>
</template>
