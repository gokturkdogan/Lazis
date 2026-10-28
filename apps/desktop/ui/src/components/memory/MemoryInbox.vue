<script setup lang="ts">
/** Decisions LAZIS does not take alone: which person, contradictions, sensitive facts,
 * deleting everything about someone. */
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import type { MemoryInboxItem, QualityFinding } from "@/api/client";
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
// Phase 9: suggestions from the quality checks, most important first; hidden on request.
const findings = ref<QualityFinding[]>([]);

function client() {
  const c = currentApiClient();
  if (c === null) throw new ApiError(0, "backend_unreachable", "", true);
  return c;
}

async function load() {
  loading.value = true;
  try {
    items.value = await client().memoryInbox();
    try {
      findings.value = await client().memoryQuality();
    } catch {
      findings.value = [];
    }
  } catch (e) {
    error.value = t(errorKey(e instanceof ApiError ? e.code : null));
  } finally {
    loading.value = false;
  }
}

onMounted(load);

async function hide(f: QualityFinding) {
  busy.value = f.id;
  try {
    findings.value = await client().dismissQuality(f.id, f.kind);
  } catch (e) {
    error.value = t(errorKey(e instanceof ApiError ? e.code : null));
  } finally {
    busy.value = null;
  }
}

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
    <p v-else-if="items.length === 0 && findings.length === 0" class="muted mem-small" data-testid="inbox-empty">{{ t("memory.inbox.empty") }}</p>
    <ul class="mem-list">
      <li v-for="item in items" :key="item.id" class="mem-item" data-testid="inbox-item">
        <div class="mem-meta">
          <span class="mem-badge warn">{{ item.about === "merge" ? t("memory.inbox.merge") : t(`memory.inbox.type.${item.type}`) }}</span>
          <span v-if="item.about === 'relationship'" class="mem-badge" data-testid="inbox-relationship">{{ t("memory.inbox.relationship") }}</span>
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
          <template v-else-if="item.type === 'destructive' && item.about === 'merge'">
            <button type="button" class="btn mem-btn-small" data-testid="inbox-merge" @click="decide(item, 'approve')">{{ t("memory.inbox.confirmMerge") }}</button>
            <button type="button" class="btn mem-btn-small" @click="decide(item, 'reject')">{{ t("memory.inbox.rejectMerge") }}</button>
          </template>
          <template v-else-if="item.type === 'destructive'">
            <button type="button" class="btn mem-btn-small" @click="decide(item, 'approve')">{{ t("memory.inbox.confirmDelete") }}</button>
          </template>
          <button type="button" class="mem-link" :disabled="busy === item.id" @click="decide(item, 'dismiss')">{{ t("memory.inbox.dismiss") }}</button>
        </div>
      </li>
    </ul>
    <template v-if="findings.length">
      <h3 class="mem-heading">{{ t("memory.quality.title") }}</h3>
      <p class="muted mem-small">{{ t("memory.quality.note") }}</p>
      <ul class="mem-list">
        <li v-for="f in findings" :key="f.id" class="mem-item" data-testid="quality-finding">
          <div class="mem-meta">
            <span class="mem-badge" :class="{ warn: f.kind === 'conflict' || f.kind === 'ambiguous_person' }">{{ t(`memory.quality.kind.${f.kind}`) }}</span>
            <span>{{ f.subject }}</span>
          </div>
          <span class="mem-text">{{ f.title }}</span>
          <span v-if="f.values.length" class="mem-small muted">{{ f.values.join(" · ") }}</span>
          <div class="mem-actions">
            <button type="button" class="mem-link" :disabled="busy === f.id" data-testid="quality-hide" @click="hide(f)">{{ t("memory.quality.hide") }}</button>
          </div>
        </li>
      </ul>
    </template>
  </section>
</template>
