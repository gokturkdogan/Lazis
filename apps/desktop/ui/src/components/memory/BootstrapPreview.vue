<script setup lang="ts">
/**
 * The import preview (Phase 8): every item the file gave, by category, with its source, how it
 * relates to what is stored, and the user's decision; the people and who they are; the
 * conflicts. Nothing starts approved and there is no "approve all": each decision is one click
 * on one item, sent to the backend at once (which checks it again).
 */
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import type { BootstrapDecisions, BootstrapItem, BootstrapPerson, BootstrapPreview } from "@/api/client";

const props = defineProps<{ preview: BootstrapPreview; working: boolean }>();
const emit = defineEmits<{ decide: [body: BootstrapDecisions] }>();
const { t } = useI18n();

type Tab = "items" | "people" | "conflicts";
const tab = ref<Tab>("items");
const editing = ref<string | null>(null);
const editValue = ref("");
const linkChoice = ref<Record<string, string>>({});

const CATEGORY_ORDER = ["profile", "person", "relationship", "project", "preference", "habit", "goal", "event", "fact"];
const NEEDS_RESOLUTION = new Set(["conflict", "temporal_update", "possible_duplicate"]);

const byCategory = computed(() => {
  const groups = new Map<string, BootstrapItem[]>();
  for (const it of props.preview.items) {
    const list = groups.get(it.category) ?? [];
    list.push(it);
    groups.set(it.category, list);
  }
  return CATEGORY_ORDER.filter((c) => groups.has(c)).map((c) => ({ category: c, items: groups.get(c) ?? [] }));
});
const conflicts = computed(() => props.preview.items.filter((i) => NEEDS_RESOLUTION.has(i.classification)));
const people = computed(() => props.preview.people.filter((p) => p.kind === "person" || p.kind === "project"));

function needsResolution(it: BootstrapItem): boolean {
  return NEEDS_RESOLUTION.has(it.classification);
}

function decideItem(it: BootstrapItem, decision: BootstrapItem["decision"], resolution?: BootstrapItem["resolution"]) {
  emit("decide", { people: [], items: [{ id: it.id, decision, resolution: resolution ?? null }] });
}

function startEdit(it: BootstrapItem) {
  editing.value = it.id;
  editValue.value = it.edited_value ?? it.value;
}

function saveEdit(it: BootstrapItem) {
  const value = editValue.value.trim();
  if (value === "") return;
  emit("decide", {
    people: [],
    items: [{ id: it.id, decision: "approve", resolution: it.resolution, edited_value: value }],
  });
  editing.value = null;
}

function decidePerson(p: BootstrapPerson, decision: BootstrapPerson["decision"]) {
  if (decision === "link") {
    const target = linkChoice.value[p.id] ?? p.suggested_id ?? "";
    if (target === "") return;
    emit("decide", { people: [{ id: p.id, decision, link_id: target }], items: [] });
    return;
  }
  emit("decide", { people: [{ id: p.id, decision }], items: [] });
}

function noteOf(it: BootstrapItem): string | null {
  if (it.note === "rejected_before") return t("memory.bootstrap.rejectedBefore");
  if (it.note === "in_file") return t("memory.bootstrap.inFile");
  if (it.classification === "excluded" && it.note) {
    const key = `memory.bootstrap.excludedReason.${it.note}`;
    return t(key) === key ? t("memory.bootstrap.classification.excluded") : t(key);
  }
  return null;
}

function badgeClass(it: BootstrapItem) {
  return {
    warn: needsResolution(it) || it.classification === "ambiguous_entity" || it.classification === "insufficient_evidence",
    danger: it.classification === "excluded",
  };
}

const linkTargets = (p: BootstrapPerson) => [
  ...p.options,
  ...props.preview.people
    .filter((o) => o.id !== p.id && o.name === p.name && !p.options.some((x) => x.id === o.id))
    .map((o) => ({ id: o.id, label: o.relation ? `${o.name} (${o.relation})` : o.name, stored: false })),
];
</script>

<template>
  <div class="mem-stack" data-testid="bootstrap-preview">
    <nav class="mem-row" role="tablist">
      <button
        v-for="item in (['items', 'people', 'conflicts'] as const)"
        :key="item"
        type="button"
        role="tab"
        class="mem-tab mem-btn-small"
        :class="{ active: tab === item }"
        :aria-selected="tab === item"
        :data-testid="`bootstrap-tab-${item}`"
        @click="tab = item"
      >
        {{ t(`memory.bootstrap.tabs.${item}`) }}
        <span v-if="item === 'conflicts' && conflicts.length" class="mem-badge warn">{{ conflicts.length }}</span>
        <span v-if="item === 'people' && preview.summary.people_pending" class="mem-badge warn">{{ preview.summary.people_pending }}</span>
      </button>
    </nav>
    <p class="muted mem-small">{{ t("memory.bootstrap.confidenceNote") }}</p>

    <!-- 3. Everything found, by category -->
    <template v-if="tab === 'items'">
      <p v-if="preview.items.length === 0" class="muted mem-small">{{ t("memory.bootstrap.nothing") }}</p>
      <section v-for="group in byCategory" :key="group.category" class="mem-group">
        <h3 class="mem-heading">{{ t(`memory.bootstrap.category.${group.category}`) }} · {{ group.items.length }}</h3>
        <ul class="mem-list">
          <li
            v-for="it in group.items"
            :key="it.id"
            class="mem-item"
            :class="{ old: it.classification === 'excluded' || it.decision === 'reject' }"
            data-testid="bootstrap-item"
            :data-decision="it.decision"
          >
            <span class="mem-text">
              <strong>{{ it.subject }}</strong> — {{ it.predicate_label }}: {{ it.edited_value ?? it.value }}
            </span>
            <div class="mem-meta">
              <span class="mem-badge" :class="badgeClass(it)">{{ t(`memory.bootstrap.classification.${it.classification}`) }}</span>
              <span class="mem-badge">{{ t(`memory.bootstrap.decision.${it.decision}`) }}</span>
              <span>{{ t("memory.bootstrap.source", { section: it.section }) }}</span>
              <span v-if="it.line">{{ t("memory.bootstrap.line", { n: it.line }) }}</span>
              <span>{{ t(`memory.bootstrap.method.${it.method}`) }}</span>
              <span>{{ t("memory.bootstrap.confidence", { n: Math.round(it.confidence * 100) + "%" }) }}</span>
              <span v-if="it.time">· {{ it.time }}</span>
            </div>
            <blockquote v-if="it.excerpt" class="mem-quote">“{{ it.excerpt }}”</blockquote>
            <div class="mem-meta">
              <span v-for="v in it.existing" :key="v">{{ t("memory.bootstrap.existing", { value: v }) }}</span>
              <span v-if="noteOf(it)">{{ noteOf(it) }}</span>
              <span v-if="it.blocked" class="mem-warn" data-testid="bootstrap-blocked">{{ t(`memory.bootstrap.blocked.${it.blocked}`) }}</span>
            </div>
            <div v-if="editing === it.id" class="mem-row">
              <input v-model="editValue" class="mem-input" maxlength="200" data-testid="bootstrap-edit-input" />
              <button type="button" class="btn mem-btn-small" :disabled="working" data-testid="bootstrap-edit-save" @click="saveEdit(it)">
                {{ t("memory.bootstrap.editSave") }}
              </button>
              <button type="button" class="btn mem-btn-small" @click="editing = null">{{ t("memory.bootstrap.editCancel") }}</button>
            </div>
            <div v-else-if="it.classification !== 'excluded'" class="mem-row">
              <template v-if="needsResolution(it)">
                <button
                  v-for="r in (['keep_old', 'update', 'keep_both'] as const)"
                  :key="r"
                  type="button"
                  class="btn mem-btn-small"
                  :class="{ chosen: it.decision === 'approve' && it.resolution === r }"
                  :disabled="working"
                  :data-testid="`bootstrap-resolve-${r}`"
                  @click="decideItem(it, 'approve', r)"
                >
                  {{ t(`memory.bootstrap.resolution.${r}`) }}
                </button>
              </template>
              <button
                v-else
                type="button"
                class="btn mem-btn-small"
                :class="{ chosen: it.decision === 'approve' }"
                :disabled="working"
                data-testid="bootstrap-approve"
                @click="decideItem(it, 'approve')"
              >
                {{ t("memory.bootstrap.approve") }}
              </button>
              <button type="button" class="btn mem-btn-small" :class="{ chosen: it.decision === 'reject' }" :disabled="working" data-testid="bootstrap-reject" @click="decideItem(it, 'reject')">
                {{ t("memory.bootstrap.reject") }}
              </button>
              <button type="button" class="btn mem-btn-small" :class="{ chosen: it.decision === 'hold' }" :disabled="working" data-testid="bootstrap-hold" @click="decideItem(it, 'hold')">
                {{ t("memory.bootstrap.hold") }}
              </button>
              <button v-if="it.kind === 'fact'" type="button" class="btn mem-btn-small" :disabled="working" data-testid="bootstrap-edit" @click="startEdit(it)">
                {{ t("memory.bootstrap.edit") }}
              </button>
              <button v-if="it.decision !== 'pending'" type="button" class="btn mem-btn-small" :disabled="working" @click="decideItem(it, 'pending')">
                {{ t("memory.bootstrap.undecide") }}
              </button>
            </div>
          </li>
        </ul>
      </section>
    </template>

    <!-- People: who each one is is the user's decision -->
    <template v-else-if="tab === 'people'">
      <ul class="mem-list">
        <li v-for="p in people" :key="p.id" class="mem-item" data-testid="bootstrap-person" :data-decision="p.decision">
          <span class="mem-text"><strong>{{ p.name }}</strong><span v-if="p.relation"> ({{ p.relation }})</span><span v-if="p.description" class="muted"> — {{ p.description }}</span></span>
          <div class="mem-meta">
            <span class="mem-badge" :class="{ warn: p.match !== 'new' }">{{ t(`memory.bootstrap.person.match.${p.match}`) }}</span>
            <span class="mem-badge">{{ t(`memory.bootstrap.person.decision.${p.decision}`) }}</span>
            <span>{{ t("memory.bootstrap.person.items", { n: p.items }) }}</span>
            <span>{{ t("memory.bootstrap.source", { section: p.section }) }}</span>
          </div>
          <p v-if="p.suggested_id" class="muted mem-small">
            {{ t("memory.bootstrap.person.suggested", { label: p.options.find((o) => o.id === p.suggested_id)?.label ?? p.name }) }}
          </p>
          <div class="mem-row">
            <button type="button" class="btn mem-btn-small" :class="{ chosen: p.decision === 'create' }" :disabled="working" data-testid="bootstrap-person-create" @click="decidePerson(p, 'create')">
              {{ t("memory.bootstrap.person.decision.create") }}
            </button>
            <template v-if="linkTargets(p).length">
              <select v-model="linkChoice[p.id]" class="mem-select" :aria-label="t('memory.bootstrap.person.linkTo')" data-testid="bootstrap-person-target">
                <option value="" disabled>{{ t("memory.bootstrap.person.linkTo") }}</option>
                <option v-for="o in linkTargets(p)" :key="o.id" :value="o.id">
                  {{ o.label }}<template v-if="!o.stored"> · {{ t("memory.bootstrap.person.fileNamesake") }}</template>
                </option>
              </select>
              <button type="button" class="btn mem-btn-small" :class="{ chosen: p.decision === 'link' }" :disabled="working || !(linkChoice[p.id] ?? p.suggested_id)" data-testid="bootstrap-person-link" @click="decidePerson(p, 'link')">
                {{ t("memory.bootstrap.person.decision.link") }}
              </button>
            </template>
            <button type="button" class="btn mem-btn-small" :class="{ chosen: p.decision === 'unresolved' }" :disabled="working" data-testid="bootstrap-person-unresolved" @click="decidePerson(p, 'unresolved')">
              {{ t("memory.bootstrap.person.decision.unresolved") }}
            </button>
            <button type="button" class="btn mem-btn-small" :class="{ chosen: p.decision === 'reject' }" :disabled="working" data-testid="bootstrap-person-reject" @click="decidePerson(p, 'reject')">
              {{ t("memory.bootstrap.person.decision.reject") }}
            </button>
          </div>
          <p v-if="p.decision === 'unresolved'" class="muted mem-small">{{ t("memory.bootstrap.person.unresolvedNote") }}</p>
        </li>
      </ul>
    </template>

    <!-- 4. Conflicts with what is stored -->
    <template v-else>
      <p v-if="conflicts.length === 0" class="muted mem-small">{{ t("memory.bootstrap.noConflicts") }}</p>
      <p v-else class="muted mem-small">{{ t("memory.bootstrap.deferHint") }}</p>
      <ul class="mem-list">
        <li v-for="it in conflicts" :key="it.id" class="mem-item" data-testid="bootstrap-conflict">
          <span class="mem-text"><strong>{{ it.subject }}</strong> — {{ it.predicate_label }}</span>
          <div class="mem-compare">
            <span>{{ t("memory.bootstrap.existing", { value: it.existing.join(", ") }) }}</span>
            <span>→ {{ it.edited_value ?? it.value }}<template v-if="it.time"> ({{ it.time }})</template></span>
          </div>
          <div class="mem-meta">
            <span class="mem-badge warn">{{ t(`memory.bootstrap.classification.${it.classification}`) }}</span>
            <span v-if="it.excerpt">“{{ it.excerpt }}”</span>
          </div>
          <div class="mem-row">
            <button
              v-for="r in (['keep_old', 'update', 'keep_both'] as const)"
              :key="r"
              type="button"
              class="btn mem-btn-small"
              :class="{ chosen: it.decision === 'approve' && it.resolution === r }"
              :disabled="working"
              @click="decideItem(it, 'approve', r)"
            >
              {{ t(`memory.bootstrap.resolution.${r}`) }}
            </button>
            <button type="button" class="btn mem-btn-small" :class="{ chosen: it.decision === 'hold' }" :disabled="working" @click="decideItem(it, 'hold')">
              {{ t("memory.bootstrap.hold") }}
            </button>
          </div>
        </li>
      </ul>
    </template>
  </div>
</template>
