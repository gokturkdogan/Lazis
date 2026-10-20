<script setup lang="ts">
/** An entity's relationships (Phase 7): current and past, how each reads from this side, its
 * evidence and earlier versions; add, edit, delete (after confirmation); an optional map. */
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import type { MemoryEntity, Relationship, RelationshipDetail, RelationshipType } from "@/api/client";
import { ApiError } from "@/api/client";
import { errorKey } from "@/i18n";
import { currentApiClient } from "@/stores/connection";
import MemoryRelationMap from "./MemoryRelationMap.vue";

const props = defineProps<{ entityId: string; name: string; kind: string; entities: MemoryEntity[] }>();
const emit = defineEmits<{ changed: [] }>();
const { t } = useI18n();

const items = ref<Relationship[]>([]);
const types = ref<RelationshipType[]>([]);
const error = ref<string | null>(null);
const notice = ref<string | null>(null);
const openId = ref<string | null>(null);
const detail = ref<RelationshipDetail | null>(null);
const editing = ref<string | null>(null);
const confirming = ref<string | null>(null);
const showMap = ref(false);
const adding = ref(false);
const form = ref({ other: "", type: "", status: "active" as "active" | "ended" | "planned", time: "" });
const edit = ref({ type: "", status: "active" as "active" | "ended" | "planned", time: "" });

const CURRENT = new Set(["active", "planned", "unverified"]);
const current = computed(() => items.value.filter((r) => CURRENT.has(r.status)));
const past = computed(() => items.value.filter((r) => !CURRENT.has(r.status)));

function client() {
  const c = currentApiClient();
  if (c === null) throw new ApiError(0, "backend_unreachable", "", true);
  return c;
}

async function load() {
  error.value = null;
  try {
    items.value = await client().entityRelationships(props.entityId);
    if (types.value.length === 0) types.value = await client().relationshipTypes();
  } catch (e) {
    error.value = t(errorKey(e instanceof ApiError ? e.code : null));
  }
}

onMounted(load);
watch(() => props.entityId, load);

function line(r: Relationship): string {
  if (r.reading && r.other) return t("memory.relations.reading", { other: r.other.name, label: r.reading });
  return r.text;
}

function badges(r: Relationship): string[] {
  const out: string[] = [];
  const s = t(`memory.relations.status.${r.status}`);
  if (s) out.push(s);
  if (r.time_text) out.push(r.time_text);
  if (r.conflict_state === "pending") out.push(t("memory.relations.conflict"));
  if (r.sensitivity === "sensitive") out.push(t("memory.badge.sensitive"));
  return out;
}

/** Types that fit "‹other› is ‹this›'s ‹label›" for the chosen other entity. */
const otherKind = computed(() => {
  if (form.value.other === "user") return "person";
  return props.entities.find((e) => e.id === form.value.other)?.kind ?? "";
});
const fitting = computed(() =>
  types.value.filter((x) => x.source_kinds.includes(props.kind) && (!otherKind.value || x.target_kinds.includes(otherKind.value))),
);
const editTypes = computed(() => {
  const r = items.value.find((x) => x.id === editing.value);
  if (!r) return [];
  return types.value.filter((x) => x.source_kinds.includes(r.source.kind) && x.target_kinds.includes(r.target.kind));
});
const others = computed(() => props.entities.filter((e) => e.id !== props.entityId));
const chosenLabel = computed(() => types.value.find((x) => x.key === form.value.type)?.label ?? "…");
const otherName = computed(() =>
  form.value.other === "user" ? t("memory.entities.me") : (props.entities.find((e) => e.id === form.value.other)?.name ?? "…"),
);

async function act(fn: () => Promise<string | null>) {
  error.value = null;
  notice.value = null;
  try {
    notice.value = await fn();
    await load();
    emit("changed");
  } catch (e) {
    const code = e instanceof ApiError ? e.code : null;
    error.value = code === "memory_invalid" ? t("memory.relations.notAllowed") : t(errorKey(code));
  }
}

async function toggleEvidence(r: Relationship) {
  if (openId.value === r.id) {
    openId.value = null;
    return;
  }
  openId.value = r.id;
  detail.value = null;
  try {
    detail.value = await client().relationship(r.id);
  } catch (e) {
    error.value = t(errorKey(e instanceof ApiError ? e.code : null));
  }
}

function startEdit(r: Relationship) {
  editing.value = r.id;
  confirming.value = null;
  const status = r.status === "ended" || r.status === "planned" ? r.status : "active";
  edit.value = { type: r.type, status, time: r.time_text ?? "" };
}

function saveEdit(r: Relationship) {
  return act(async () => {
    await client().editRelationship(r.id, { type: edit.value.type, status: edit.value.status,
                                            time_text: edit.value.time.trim() || null, qualifier: r.qualifier });
    editing.value = null;
    return t("memory.relations.saved");
  });
}

function forget(r: Relationship) {
  return act(async () => {
    await client().forgetRelationship(r.id);
    confirming.value = null;
    return t("memory.relations.forgotten");
  });
}

function add() {
  return act(async () => {
    const res = await client().addRelationship({
      source_id: props.entityId, type: form.value.type, target_id: form.value.other,
      status: form.value.status, time_text: form.value.time.trim() || null, qualifier: null,
    });
    form.value = { other: "", type: "", status: "active", time: "" };
    adding.value = false;
    return res.inbox > 0 ? t("memory.relations.waiting") : t("memory.relations.added");
  });
}
</script>

<template>
  <div class="mem-relations" data-testid="memory-relations">
    <div class="mem-row">
      <strong class="mem-small">{{ t("memory.relations.title") }}</strong>
      <button type="button" class="mem-link" data-testid="relation-add-toggle" @click="adding = !adding">{{ t("memory.relations.add") }}</button>
      <button type="button" class="mem-link" data-testid="relation-map-toggle" @click="showMap = !showMap">
        {{ showMap ? t("memory.relations.hideMap") : t("memory.relations.map") }}
      </button>
    </div>
    <p v-if="error" class="mem-error" role="alert">{{ error }}</p>
    <p v-if="notice" class="mem-ok" role="status">{{ notice }}</p>
    <p v-if="items.length === 0" class="muted mem-small" data-testid="relations-empty">{{ t("memory.relations.empty") }}</p>

    <form v-if="adding" class="mem-row mem-wrap" data-testid="relation-add" @submit.prevent="add">
      <select v-model="form.other" class="mem-select" :aria-label="t('memory.relations.other')" data-testid="relation-add-other">
        <option value="" disabled>{{ t("memory.relations.other") }}</option>
        <option v-if="entityId !== 'user'" value="user">{{ t("memory.entities.me") }}</option>
        <option v-for="o in others" :key="o.id" :value="o.id">{{ o.relation ? `${o.name} (${o.relation})` : o.name }}</option>
      </select>
      <select v-model="form.type" class="mem-select" :aria-label="t('memory.relations.type')" data-testid="relation-add-type">
        <option value="" disabled>{{ t("memory.relations.type") }}</option>
        <option v-for="x in fitting" :key="x.key" :value="x.key">{{ x.label }} · {{ t(`memory.relations.category.${x.category}`) }}</option>
      </select>
      <select v-model="form.status" class="mem-select" :aria-label="t('memory.relations.statusLabel')">
        <option value="active">{{ t("memory.relations.statusOption.active") }}</option>
        <option value="planned">{{ t("memory.relations.statusOption.planned") }}</option>
        <option value="ended">{{ t("memory.relations.statusOption.ended") }}</option>
      </select>
      <input v-model="form.time" class="mem-input" maxlength="80" :placeholder="t('memory.relations.time')" />
      <span class="muted mem-small" data-testid="relation-add-preview">{{ t("memory.relations.direction", { other: otherName, name, label: chosenLabel }) }}</span>
      <button type="submit" class="btn mem-btn-small" :disabled="!form.other || !form.type" data-testid="relation-add-submit">{{ t("memory.save") }}</button>
    </form>

    <ul class="mem-list">
      <li v-for="r in [...current, ...past]" :key="r.id" class="mem-rel" :class="{ muted: !CURRENT.has(r.status) }" data-testid="relation">
        <template v-if="r === past[0]"><span class="mem-small muted">{{ t("memory.relations.past") }}</span></template>
        <div class="mem-row mem-wrap">
          <span data-testid="relation-text">{{ line(r) }}</span>
          <span v-for="b in badges(r)" :key="b" class="mem-badge">{{ b }}</span>
          <span class="mem-small muted">{{ t(`memory.origin.${r.origin === "migrated" ? "imported" : r.origin}`) }}</span>
          <button type="button" class="mem-link" data-testid="relation-evidence" @click="toggleEvidence(r)">
            {{ openId === r.id ? t("memory.relations.hideEvidence") : t("memory.relations.evidence") }}
          </button>
          <button type="button" class="mem-link" data-testid="relation-edit" @click="startEdit(r)">{{ t("memory.relations.edit") }}</button>
          <button type="button" class="mem-link danger" data-testid="relation-forget" @click="confirming = r.id">{{ t("memory.relations.forget") }}</button>
        </div>
        <div v-if="openId === r.id && detail && detail.relationship.id === r.id" class="mem-detail" data-testid="relation-detail">
          <span v-for="(e, i) in detail.evidence" :key="i" class="mem-small">
            {{ t(`memory.evidence.${e.source_type}`) }}<template v-if="e.quote"> — “{{ e.quote }}”</template>
          </span>
          <span v-if="detail.evidence.length === 0" class="mem-small muted">{{ t("memory.noEvidence") }}</span>
          <template v-if="detail.previous.length">
            <span class="mem-small muted">{{ t("memory.relations.previous") }}</span>
            <span v-for="p in detail.previous" :key="p.id" class="mem-small muted">{{ p.text }}</span>
          </template>
        </div>
        <div v-if="editing === r.id" class="mem-row mem-wrap" data-testid="relation-edit-form">
          <select v-model="edit.type" class="mem-select" :aria-label="t('memory.relations.type')" data-testid="relation-edit-type">
            <option v-for="x in editTypes" :key="x.key" :value="x.key">{{ x.label }}</option>
          </select>
          <select v-model="edit.status" class="mem-select" :aria-label="t('memory.relations.statusLabel')" data-testid="relation-edit-status">
            <option value="active">{{ t("memory.relations.statusOption.active") }}</option>
            <option value="planned">{{ t("memory.relations.statusOption.planned") }}</option>
            <option value="ended">{{ t("memory.relations.statusOption.ended") }}</option>
          </select>
          <input v-model="edit.time" class="mem-input" maxlength="80" :placeholder="t('memory.relations.time')" />
          <button type="button" class="btn mem-btn-small" data-testid="relation-edit-save" @click="saveEdit(r)">{{ t("memory.save") }}</button>
          <button type="button" class="btn mem-btn-small" @click="editing = null">{{ t("memory.cancel") }}</button>
        </div>
        <div v-if="confirming === r.id" class="mem-confirm" role="alertdialog">
          <span>{{ t("memory.relations.forgetConfirm") }}</span>
          <div class="mem-actions">
            <button type="button" class="btn mem-btn-small" data-testid="relation-forget-confirm" @click="forget(r)">{{ t("memory.yesForget") }}</button>
            <button type="button" class="btn mem-btn-small" @click="confirming = null">{{ t("memory.cancel") }}</button>
          </div>
        </div>
      </li>
    </ul>
    <MemoryRelationMap v-if="showMap" :entity-id="entityId" />
  </div>
</template>
