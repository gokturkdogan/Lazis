<script setup lang="ts">
/** Memory records: search, filter, source and history, edit, forget (confirmed), add. */
import { computed, onMounted, reactive, ref } from "vue";
import { useI18n } from "vue-i18n";
import type { MemoryEntity, MemoryPredicate, MemoryRecord, MemoryRecordDetail } from "@/api/client";
import { ApiError } from "@/api/client";
import { errorKey } from "@/i18n";
import { currentApiClient } from "@/stores/connection";
import "./memory.css";

const emit = defineEmits<{ changed: [] }>();
const { t } = useI18n();

const PAGE = 50;
const query = ref("");
const filter = ref<"all" | "me" | "new">("all");
const showHistory = ref(false);
const records = ref<MemoryRecord[]>([]);
const hasMore = ref(false);
const loading = ref(false);
const error = ref<string | null>(null);
const notice = ref<string | null>(null);
const searched = ref(false);

const detailFor = ref<string | null>(null);
const detail = ref<MemoryRecordDetail | null>(null);
const editing = ref<string | null>(null);
const editValue = ref("");
const editStatement = ref("");
const confirming = ref<string | null>(null);

const predicates = ref<MemoryPredicate[]>([]);
const entities = ref<MemoryEntity[]>([]);
const adding = ref(false);
const form = reactive({ predicate: "", value: "", statement: "", subject: "me", name: "", relation: "" });

function client() {
  const c = currentApiClient();
  if (c === null) throw new ApiError(0, "backend_unreachable", "", true);
  return c;
}

function fail(e: unknown) {
  error.value = t(errorKey(e instanceof ApiError ? e.code : null));
}

async function load(append = false) {
  loading.value = true;
  error.value = null;
  try {
    const page = await client().memoryRecords({
      q: query.value.trim() || undefined,
      user_only: filter.value === "me" || undefined,
      new_days: filter.value === "new" ? 7 : undefined,
      status: showHistory.value ? "all" : "active",
      limit: PAGE,
      offset: append ? records.value.length : 0,
    });
    records.value = append ? [...records.value, ...page.records] : page.records;
    hasMore.value = page.has_more;
    searched.value = query.value.trim() !== "";
  } catch (e) {
    fail(e);
  } finally {
    loading.value = false;
  }
}

onMounted(async () => {
  await load();
  try {
    predicates.value = await client().memoryPredicates();
  } catch {
    predicates.value = [];
  }
});

function subjectLabel(r: MemoryRecord): string {
  if (!r.subject) return t("memory.filterMe");
  return r.subject.relation ? `${r.subject.name} (${r.subject.relation})` : r.subject.name;
}

function day(iso: string): string {
  return iso.slice(0, 10);
}

async function toggleDetail(r: MemoryRecord) {
  if (detailFor.value === r.id) {
    detailFor.value = null;
    return;
  }
  detailFor.value = r.id;
  detail.value = null;
  try {
    detail.value = await client().memoryRecord(r.id);
  } catch (e) {
    fail(e);
  }
}

function startEdit(r: MemoryRecord) {
  editing.value = r.id;
  editValue.value = r.value;
  editStatement.value = r.content;
}

async function saveEdit(r: MemoryRecord) {
  try {
    const updated = await client().editMemory(r.id, editValue.value.trim(), editStatement.value.trim());
    records.value = records.value.map((x) => (x.id === r.id ? updated : x));
    editing.value = null;
  } catch (e) {
    fail(e);
  }
}

async function forget(r: MemoryRecord) {
  try {
    await client().forgetMemory(r.id);
    records.value = records.value.filter((x) => x.id !== r.id);
    confirming.value = null;
    notice.value = t("memory.forgotten");
    emit("changed");
  } catch (e) {
    fail(e);
  }
}

async function openAdd() {
  adding.value = !adding.value;
  if (adding.value) {
    try {
      entities.value = await client().memoryEntities();
    } catch {
      entities.value = [];
    }
  }
}

const addable = computed(() => form.predicate !== "" && form.value.trim() !== "" && (form.subject !== "new" || form.name.trim() !== ""));

async function submitAdd() {
  if (!addable.value) return;
  try {
    await client().addMemory({
      predicate: form.predicate,
      value: form.value.trim(),
      statement: form.statement.trim(),
      entity_id: form.subject !== "me" && form.subject !== "new" ? form.subject : null,
      new_entity: form.subject === "new" ? { name: form.name.trim(), relation: form.relation.trim() || null, kind: "person" } : null,
    });
    Object.assign(form, { predicate: "", value: "", statement: "", subject: "me", name: "", relation: "" });
    adding.value = false;
    notice.value = t("memory.add.done");
    emit("changed");
    await load();
  } catch (e) {
    fail(e);
  }
}
</script>

<template>
  <section class="panel mem-panel" data-testid="memory-records">
    <form class="mem-row" @submit.prevent="load()">
      <input v-model="query" class="mem-input" type="search" :placeholder="t('memory.search')" data-testid="memory-search" />
      <select v-model="filter" class="mem-select" data-testid="memory-filter" @change="load()">
        <option value="all">{{ t("memory.filterAll") }}</option>
        <option value="me">{{ t("memory.filterMe") }}</option>
        <option value="new">{{ t("memory.filterNew") }}</option>
      </select>
      <button type="submit" class="btn mem-btn-small">{{ t("memory.searchButton") }}</button>
      <button type="button" class="btn mem-btn-small" data-testid="memory-add-toggle" @click="openAdd">{{ t("memory.add.title") }}</button>
    </form>
    <label class="mem-row mem-small">
      <input v-model="showHistory" type="checkbox" data-testid="memory-history" @change="load()" />
      {{ t("memory.showHistory") }}
    </label>

    <form v-if="adding" class="mem-detail" data-testid="memory-add" @submit.prevent="submitAdd">
      <div class="mem-row">
        <select v-model="form.predicate" class="mem-select" :aria-label="t('memory.add.predicate')" data-testid="memory-add-predicate">
          <option value="" disabled>{{ t("memory.add.predicate") }}</option>
          <option v-for="p in predicates" :key="p.key" :value="p.key">{{ p.label }}</option>
        </select>
        <input v-model="form.value" class="mem-input" maxlength="200" :placeholder="t('memory.add.value')" data-testid="memory-add-value" />
      </div>
      <input v-model="form.statement" class="mem-input" maxlength="300" :placeholder="t('memory.add.statement')" />
      <div class="mem-row">
        <span class="mem-small muted">{{ t("memory.add.subject") }}</span>
        <select v-model="form.subject" class="mem-select" data-testid="memory-add-subject">
          <option value="me">{{ t("memory.add.me") }}</option>
          <option v-for="e in entities" :key="e.id" :value="e.id">{{ e.relation ? `${e.name} (${e.relation})` : e.name }}</option>
          <option value="new">{{ t("memory.add.newEntity") }}</option>
        </select>
        <template v-if="form.subject === 'new'">
          <input v-model="form.name" class="mem-input" maxlength="80" :placeholder="t('memory.add.name')" />
          <input v-model="form.relation" class="mem-input" maxlength="80" :placeholder="t('memory.add.relation')" />
        </template>
      </div>
      <div class="mem-actions">
        <button type="submit" class="btn mem-btn-small" :disabled="!addable" data-testid="memory-add-submit">{{ t("memory.add.submit") }}</button>
        <button type="button" class="btn mem-btn-small" @click="adding = false">{{ t("memory.cancel") }}</button>
      </div>
    </form>

    <p v-if="error" class="mem-error" role="alert">{{ error }}</p>
    <p v-if="notice" class="mem-ok" role="status">{{ notice }}</p>
    <p v-if="loading && records.length === 0" class="muted mem-small">{{ t("memory.loading") }}</p>
    <p v-else-if="!loading && records.length === 0" class="muted mem-small" data-testid="memory-empty">
      {{ searched ? t("memory.noResults") : t("memory.empty") }}
    </p>

    <ul class="mem-list">
      <li v-for="r in records" :key="r.id" class="mem-item" :class="{ old: r.status !== 'active' }" data-testid="memory-record">
        <template v-if="editing === r.id">
          <input v-model="editValue" class="mem-input" maxlength="200" :aria-label="t('memory.add.value')" data-testid="memory-edit-value" />
          <input v-model="editStatement" class="mem-input" maxlength="300" :aria-label="t('memory.add.statement')" data-testid="memory-edit-statement" />
          <div class="mem-actions">
            <button type="button" class="btn mem-btn-small" data-testid="memory-edit-save" @click="saveEdit(r)">{{ t("memory.save") }}</button>
            <button type="button" class="btn mem-btn-small" @click="editing = null">{{ t("memory.cancel") }}</button>
          </div>
        </template>
        <span v-else class="mem-text">{{ r.content }}</span>
        <div class="mem-meta">
          <span>{{ r.predicate_label }}</span>
          <span>· {{ subjectLabel(r) }}</span>
          <span>· {{ t(`memory.origin.${r.origin}`) }}</span>
          <span>· {{ day(r.updated_at) }}</span>
          <span v-if="r.status !== 'active'" class="mem-badge">{{ t("memory.badge.superseded") }}</span>
          <span v-if="r.conflict_state === 'pending'" class="mem-badge warn">{{ t("memory.badge.pending") }}</span>
          <span v-if="r.sensitivity === 'sensitive'" class="mem-badge danger">{{ t("memory.badge.sensitive") }}</span>
          <span v-if="r.confidence < 0.6" class="mem-badge">{{ t("memory.badge.uncertain") }}</span>
          <span v-if="r.status !== 'active' && !r.valid_from" class="mem-badge" data-testid="memory-past">{{ t("memory.badge.past") }}</span>
          <span v-if="r.tier === 'critical_personal' || r.tier === 'high'" class="mem-badge" data-testid="memory-tier">{{ t(`memory.tier.${r.tier}`) }}</span>
          <span v-if="r.sources > 1" class="mem-badge" data-testid="memory-sources">{{ t("memory.badge.sources", { n: r.sources }) }}</span>
        </div>
        <div v-if="editing !== r.id" class="mem-actions">
          <button type="button" class="mem-link" data-testid="memory-source" @click="toggleDetail(r)">
            {{ detailFor === r.id ? t("memory.hideSource") : t("memory.source") }}
          </button>
          <button v-if="r.status === 'active'" type="button" class="mem-link" data-testid="memory-edit" @click="startEdit(r)">{{ t("memory.edit") }}</button>
          <button type="button" class="mem-link danger" data-testid="memory-forget" @click="confirming = r.id">{{ t("memory.forget") }}</button>
        </div>
        <div v-if="confirming === r.id" class="mem-confirm" role="alertdialog">
          <span>{{ t("memory.forgetConfirm") }}</span>
          <div class="mem-actions">
            <button type="button" class="btn mem-btn-small" data-testid="memory-forget-confirm" @click="forget(r)">{{ t("memory.yesForget") }}</button>
            <button type="button" class="btn mem-btn-small" @click="confirming = null">{{ t("memory.cancel") }}</button>
          </div>
        </div>
        <div v-if="detailFor === r.id" class="mem-detail" data-testid="memory-detail">
          <template v-if="detail && detail.record.id === r.id">
            <span v-if="detail.evidence.length === 0" class="muted">{{ t("memory.noEvidence") }}</span>
            <span v-for="(e, i) in detail.evidence" :key="i">
              {{ t(`memory.evidence.${e.source_type}`) }} · {{ day(e.created_at) }}<template v-if="e.quote"> — “{{ e.quote }}”</template>
            </span>
            <template v-if="detail.previous.length">
              <strong class="muted">{{ t("memory.previous") }}</strong>
              <span v-for="p in detail.previous" :key="p.id">{{ p.value }} ({{ day(p.created_at) }} – {{ p.valid_to ? day(p.valid_to) : "" }})</span>
            </template>
          </template>
          <span v-else class="muted">{{ t("memory.loading") }}</span>
        </div>
      </li>
    </ul>
    <button v-if="hasMore" type="button" class="btn mem-btn-small" @click="load(true)">{{ t("memory.loadMore") }}</button>
  </section>
</template>
