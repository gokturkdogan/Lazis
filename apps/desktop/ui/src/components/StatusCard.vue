<script setup lang="ts">
import type { StatusRow } from "./types";

defineProps<{ title: string; rows: StatusRow[]; testid?: string }>();
</script>

<template>
  <section class="card panel" :data-testid="testid">
    <h3>{{ title }}</h3>
    <dl>
      <template v-for="row in rows" :key="row.label">
        <dt>{{ row.label }}</dt>
        <dd :class="[row.tone ? `tone-${row.tone}` : '', { mono: row.mono }]">{{ row.value }}</dd>
      </template>
    </dl>
  </section>
</template>

<style scoped>
.card {
  padding: 16px 18px;
}
h3 {
  margin: 0 0 12px;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-muted);
}
dl {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 6px 14px;
  margin: 0;
}
dt {
  color: var(--text-faint);
}
dd {
  margin: 0;
  text-align: right;
  overflow-wrap: anywhere;
}
.tone-ok {
  color: var(--ok);
}
.tone-warn {
  color: var(--warn);
}
.tone-danger {
  color: var(--danger);
}
.tone-muted {
  color: var(--text-muted);
}
</style>
