<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import type { UiPhase } from "@/stores/connection";

const props = defineProps<{ phase: UiPhase }>();
const { t } = useI18n();

const tone = computed(() =>
  props.phase === "connected" ? "ok" : props.phase === "starting" || props.phase === "initializing" ? "warn" : "danger",
);
</script>

<template>
  <span class="pill" :class="`pill--${tone}`" role="status" data-testid="status-pill">
    <span class="dot" />
    {{ t(`connection.${phase}`) }}
  </span>
</template>

<style scoped>
.pill {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 5px 12px;
  border-radius: 999px;
  font-size: 12.5px;
  border: 1px solid var(--panel-border);
  background: rgba(10, 18, 34, 0.8);
}
.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: currentColor;
  box-shadow: 0 0 10px currentColor;
}
.pill--ok {
  color: var(--ok);
}
.pill--warn {
  color: var(--warn);
}
.pill--danger {
  color: var(--danger);
}
</style>
