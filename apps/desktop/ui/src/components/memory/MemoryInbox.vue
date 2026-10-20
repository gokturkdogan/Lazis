<script setup lang="ts">
/** Decisions LAZIS does not take alone: which person, contradictions, sensitive facts,
 * deleting everything about someone. */
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import type { MemoryInboxItem } from "@/api/client";
import { ApiError } from "@/api/client";
import { errorKey } from "@/i18n";
import { currentApiClient } from "@/stores/connection";
import "./memory.css";

const emit = defineEmits<{ changed: [] }>();
const { t } = useI18n();
const items = ref<MemoryInboxItem[]>([]);
const loading = ref(true);
const error = ref<string | null>(null);
const busy = ref<string | null>(null);

function client() {
  const c = currentApiClient();
  if (c === null) throw new ApiError(0, "backend_unreachable", "", true);
  return c;
}

async function load() {
  loading.value = true;
  try {
    items.value = await client().memoryInbox();
  } catch (e) {
    error.value = t(errorKey(e instanceof ApiError ? e.code : null));
  } finally {
    loading.value = false;
  }
}

onMounted(load);

async function decide(item: MemoryInboxItem, choice: string) {
  busy.value = item.id;
  error.value = null;
  try {
    await client().resolveInbox(item.id, choice);
    items.value = items.value.filter((x) => x.id !== item.id);
    emit("changed");
  } catch (e) {
    error.value = t(errorKey(e instanceof ApiError ? e.code : null));
  } finally {
    busy.value = null;
  }
}
</script>

<template>
  <section class="panel mem-panel" data-testid="memory-inbox">
    <p v-if="error" class="mem-error" role="alert">{{ error }}</p>
    <p v-if="loading" class="muted mem-small">{{ t("memory.loading") }}</p>
    <p v-else-if="items.length === 0" class="muted mem-small" data-testid="inbox-empty">{{ t("memory.inbox.empty") }}</p>
    <ul class="mem-list">
      <li v-for="item in items" :key="item.id" class="mem-item" data-testid="inbox-item">
        <div class="mem-meta">
          <span class="mem-badge warn">{{ t(`memory.inbox.type.${item.type}`) }}</span>
          <span v-if="item.subject">{{ item.subject }}</span>
          <span v-if="item.predicate_label">· {{ item.predicate_label }}</span>
        </div>
        <span class="mem-text">{{ item.summary }}</span>
        <span v-for="v in item.existing" :key="v" class="mem-small muted">{{ t("memory.inbox.current", { value: v }) }}</span>
        <div class="mem-actions">
          <template v-if="item.type === 'ambiguous_entity'">
            <button
              v-for="o in item.options"
              :key="o.id"
              type="button"
              class="btn mem-btn-small"
              :disabled="busy === item.id"
              data-testid="inbox-option"
              @click="decide(item, o.id)"
            >
              {{ o.label }}
            </button>
            <button type="button" class="btn mem-btn-small" :disabled="busy === item.id" @click="decide(item, 'new')">
              {{ t("memory.inbox.newPerson") }}
            </button>
          </template>
          <template v-else-if="item.type === 'conflict'">
            <button type="button" class="btn mem-btn-small" data-testid="inbox-keep-new" @click="decide(item, 'new')">{{ t("memory.inbox.keepNew") }}</button>
            <button type="button" class="btn mem-btn-small" @click="decide(item, 'old')">{{ t("memory.inbox.keepOld") }}</button>
            <button type="button" class="btn mem-btn-small" @click="decide(item, 'both')">{{ t("memory.inbox.keepBoth") }}</button>
          </template>
          <template v-else-if="item.type === 'sensitive'">
            <button type="button" class="btn mem-btn-small" data-testid="inbox-approve" @click="decide(item, 'approve')">{{ t("memory.inbox.approve") }}</button>
            <button type="button" class="btn mem-btn-small" data-testid="inbox-reject" @click="decide(item, 'reject')">{{ t("memory.inbox.reject") }}</button>
          </template>
          <template v-else-if="item.type === 'destructive'">
            <button type="button" class="btn mem-btn-small" @click="decide(item, 'approve')">{{ t("memory.inbox.confirmDelete") }}</button>
          </template>
          <button type="button" class="mem-link" :disabled="busy === item.id" @click="decide(item, 'dismiss')">{{ t("memory.inbox.dismiss") }}</button>
        </div>
      </li>
    </ul>
  </section>
</template>
