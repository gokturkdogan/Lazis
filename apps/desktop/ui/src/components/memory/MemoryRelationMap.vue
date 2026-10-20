<script setup lang="ts">
/** A simple 2D relation map: the entity in the middle, direct relationships on an inner ring,
 * two-step ones outside. Bounded by the backend (sensitive relationships never appear). */
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import type { GraphNeighbourhood } from "@/api/client";
import { ApiError } from "@/api/client";
import { errorKey } from "@/i18n";
import { currentApiClient } from "@/stores/connection";

const props = defineProps<{ entityId: string }>();
const { t } = useI18n();
const depth = ref("1");
const past = ref(false);
const data = ref<GraphNeighbourhood | null>(null);
const error = ref<string | null>(null);

const W = 560;
const H = 360;

async function load() {
  error.value = null;
  const c = currentApiClient();
  if (c === null) return;
  try {
    data.value = await c.graphNeighbourhood(props.entityId, Number(depth.value), past.value);
  } catch (e) {
    error.value = t(errorKey(e instanceof ApiError ? e.code : null));
  }
}

onMounted(load);
watch([depth, past, () => props.entityId], load);

interface Placed {
  id: string;
  name: string;
  x: number;
  y: number;
  depth: number;
  isUser: boolean;
}

const placed = computed<Placed[]>(() => {
  const g = data.value;
  if (g === null) return [];
  const rings = [0, 0.3, 0.46].map((f) => f * Math.min(W, H) * 1.0);
  const out: Placed[] = [];
  const byDepth = [0, 1, 2].map((d) => g.nodes.filter((n) => n.depth === d));
  byDepth.forEach((nodes, d) => {
    nodes.forEach((n, i) => {
      const angle = (2 * Math.PI * i) / Math.max(1, nodes.length) - Math.PI / 2 + (d === 2 ? 0.25 : 0);
      const r = rings[d] ?? 0;
      out.push({ id: n.id, name: n.name, depth: d, isUser: n.is_user,
                 x: W / 2 + r * Math.cos(angle) * 1.35, y: H / 2 + r * Math.sin(angle) });
    });
  });
  return out;
});

const lines = computed(() => {
  const g = data.value;
  if (g === null) return [];
  const at = new Map(placed.value.map((p) => [p.id, p]));
  return g.edges.flatMap((e) => {
    const a = at.get(e.source_id);
    const b = at.get(e.target_id);
    if (!a || !b) return [];
    const title = `${b.name}: ${a.name} → ${e.label}`;
    return [{ id: e.id, x1: a.x, y1: a.y, x2: b.x, y2: b.y, ended: e.status === "ended", title,
              label: a.depth === 0 || b.depth === 0 ? e.label : "", mx: (a.x + b.x) / 2, my: (a.y + b.y) / 2 }];
  });
});
</script>

<template>
  <div class="mem-map" data-testid="relation-map">
    <div class="mem-row">
      <label class="mem-small">
        {{ t("memory.relations.depth") }}
        <select v-model="depth" class="mem-select" data-testid="relation-map-depth">
          <option value="1">{{ t("memory.relations.depthOne") }}</option>
          <option value="2">{{ t("memory.relations.depthTwo") }}</option>
        </select>
      </label>
      <label class="mem-small"><input v-model="past" type="checkbox" /> {{ t("memory.relations.showPast") }}</label>
    </div>
    <p v-if="error" class="mem-error" role="alert">{{ error }}</p>
    <svg v-if="data" :viewBox="`0 0 ${W} ${H}`" class="mem-map-svg" role="img" :aria-label="t('memory.relations.map')">
      <g v-for="l in lines" :key="l.id">
        <line :x1="l.x1" :y1="l.y1" :x2="l.x2" :y2="l.y2" class="mem-map-edge" :class="{ ended: l.ended }">
          <title>{{ l.title }}</title>
        </line>
        <text v-if="l.label" :x="l.mx" :y="l.my - 4" class="mem-map-label" text-anchor="middle">{{ l.label }}</text>
      </g>
      <g v-for="n in placed" :key="n.id" data-testid="relation-map-node">
        <circle :cx="n.x" :cy="n.y" :r="n.depth === 0 ? 9 : 6" class="mem-map-node" :class="{ centre: n.depth === 0, user: n.isUser }" />
        <text :x="n.x" :y="n.y + 20" text-anchor="middle" class="mem-map-name">{{ n.name }}</text>
      </g>
    </svg>
    <p v-if="data?.truncated" class="muted mem-small">{{ t("memory.relations.truncated", { n: data.nodes.length }) }}</p>
    <p class="muted mem-small">{{ t("memory.relations.mapNote") }}</p>
  </div>
</template>
