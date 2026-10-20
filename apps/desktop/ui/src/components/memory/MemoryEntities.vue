<script setup lang="ts">
/** People and projects: what is known about each, their relationships, rename, merge two
 * records, forget one. The user's own relationships are the first row. */
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import type { MemoryEntity, MemoryEntityDetail } from "@/api/client";
import { ApiError } from "@/api/client";
import { errorKey } from "@/i18n";
import { currentApiClient } from "@/stores/connection";
import MemoryRelations from "./MemoryRelations.vue";
import "./memory.css";

const emit = defineEmits<{ changed: [] }>();
const { t } = useI18n();

const entities = ref<MemoryEntity[]>([]);
const loading = ref(true);
const error = ref<string | null>(null);
const notice = ref<string | null>(null);
const openId = ref<string | null>(null);
const detail = ref<MemoryEntityDetail | null>(null);
const editName = ref("");
const editRelation = ref("");
const mergeOther = ref("");
const confirm = ref<"merge" | "forget" | null>(null);
const mineOpen = ref(false);

function client() {
  const c = currentApiClient();
  if (c === null) throw new ApiError(0, "backend_unreachable", "", true);
  return c;
}

function label(e: { name: string; relation: string | null }): string {
  return e.relation ? `${e.name} (${e.relation})` : e.name;
}

async function load() {
  loading.value = true;
  error.value = null;
  try {
    entities.value = await client().memoryEntities();
  } catch (e) {
    error.value = t(errorKey(e instanceof ApiError ? e.code : null));
  } finally {
    loading.value = false;
  }
}

onMounted(load);

async function open(e: MemoryEntity) {
  confirm.value = null;
  if (openId.value === e.id) {
    openId.value = null;
    return;
  }
  openId.value = e.id;
  detail.value = null;
  editName.value = e.name;
  editRelation.value = e.relation ?? "";
  mergeOther.value = "";
  try {
    detail.value = await client().memoryEntity(e.id);
  } catch (err) {
    error.value = t(errorKey(err instanceof ApiError ? err.code : null));
  }
}

async function run(action: () => Promise<unknown>, message: string) {
  error.value = null;
  try {
    await action();
    notice.value = message;
    confirm.value = null;
    emit("changed");
    await load();
  } catch (e) {
    error.value = t(errorKey(e instanceof ApiError ? e.code : null));
  }
}

function save(e: MemoryEntity) {
  return run(
    () => client().editEntity(e.id, { name: editName.value.trim(), relation: editRelation.value.trim() || null }),
    t("memory.add.done"),
  );
}

function merge(e: MemoryEntity) {
  return run(async () => {
    await client().mergeEntities(e.id, mergeOther.value);
    detail.value = await client().memoryEntity(e.id);
  }, t("memory.entities.merged"));
}

function forget(e: MemoryEntity) {
  return run(async () => {
    await client().forgetEntity(e.id);
    openId.value = null;
  }, t("memory.forgotten"));
}

function otherName(): string {
  const o = entities.value.find((x) => x.id === mergeOther.value);
  return o ? label(o) : "";
}
</script>

<template>
  <section class="panel mem-panel" data-testid="memory-entities">
    <p v-if="error" class="mem-error" role="alert">{{ error }}</p>
    <p v-if="notice" class="mem-ok" role="status">{{ notice }}</p>
    <p v-if="loading" class="muted mem-small">{{ t("memory.loading") }}</p>
    <p v-else-if="entities.length === 0" class="muted mem-small">{{ t("memory.entities.empty") }}</p>
    <ul class="mem-list">
      <li class="mem-item" data-testid="memory-me">
        <button type="button" class="mem-link" data-testid="memory-me-toggle" @click="mineOpen = !mineOpen">
          <strong>{{ t("memory.entities.me") }}</strong>
        </button>
        <div v-if="mineOpen" class="mem-detail">
          <MemoryRelations entity-id="user" :name="t('memory.entities.meShort')" kind="person" :entities="entities" @changed="emit('changed')" />
        </div>
      </li>
      <li v-for="e in entities" :key="e.id" class="mem-item" data-testid="memory-entity">
        <button type="button" class="mem-link" @click="open(e)">
          <strong>{{ label(e) }}</strong>
        </button>
        <div class="mem-meta">
          <span>{{ t(`memory.kind.${e.kind}`) }}</span>
          <span>· {{ t("memory.entities.records", { n: e.records }) }}</span>
          <span v-if="e.aliases.length">· {{ t("memory.entities.aliases", { names: e.aliases.join(", ") }) }}</span>
        </div>
        <div v-if="openId === e.id" class="mem-detail" data-testid="memory-entity-detail">
          <template v-if="detail && detail.entity.id === e.id">
            <span v-for="r in detail.records" :key="r.id" :class="{ muted: r.status !== 'active' }">
              {{ r.content }}<template v-if="r.status !== 'active'"> ({{ t("memory.badge.superseded") }})</template>
            </span>
          </template>
          <MemoryRelations :entity-id="e.id" :name="e.name" :kind="e.kind" :entities="entities" @changed="emit('changed')" />
          <div class="mem-row">
            <input v-model="editName" class="mem-input" maxlength="80" :aria-label="t('memory.entities.name')" />
            <input v-model="editRelation" class="mem-input" maxlength="80" :placeholder="t('memory.entities.relation')" />
            <button type="button" class="btn mem-btn-small" data-testid="entity-save" @click="save(e)">{{ t("memory.save") }}</button>
          </div>
          <div class="mem-row">
            <select v-model="mergeOther" class="mem-select" :aria-label="t('memory.entities.mergeWith')" data-testid="entity-merge-select">
              <option value="" disabled>{{ t("memory.entities.mergeWith") }}</option>
              <option v-for="o in entities.filter((x) => x.id !== e.id && x.kind === e.kind)" :key="o.id" :value="o.id">{{ label(o) }}</option>
            </select>
            <button type="button" class="btn mem-btn-small" :disabled="!mergeOther" data-testid="entity-merge" @click="confirm = 'merge'">
              {{ t("memory.entities.merge") }}
            </button>
            <button type="button" class="mem-link danger" data-testid="entity-forget" @click="confirm = 'forget'">{{ t("memory.forget") }}</button>
          </div>
          <div v-if="confirm === 'merge'" class="mem-confirm" role="alertdialog">
            <span>{{ t("memory.entities.mergeConfirm", { other: otherName(), keep: label(e) }) }}</span>
            <div class="mem-actions">
              <button type="button" class="btn mem-btn-small" data-testid="entity-merge-confirm" @click="merge(e)">{{ t("memory.entities.merge") }}</button>
              <button type="button" class="btn mem-btn-small" @click="confirm = null">{{ t("memory.cancel") }}</button>
            </div>
          </div>
          <div v-if="confirm === 'forget'" class="mem-confirm" role="alertdialog">
            <span>{{ t("memory.entities.forgetConfirm", { name: label(e), n: e.records }) }}</span>
            <div class="mem-actions">
              <button type="button" class="btn mem-btn-small" data-testid="entity-forget-confirm" @click="forget(e)">{{ t("memory.yesForget") }}</button>
              <button type="button" class="btn mem-btn-small" @click="confirm = null">{{ t("memory.cancel") }}</button>
            </div>
          </div>
        </div>
      </li>
    </ul>
  </section>
</template>
