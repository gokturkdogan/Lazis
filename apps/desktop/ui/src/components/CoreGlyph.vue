<script setup lang="ts">
/**
 * Lightweight CSS identity mark (not the P14 neural core). Color follows connection health:
 * blue = ready/idle, yellow = starting, red = error. No WebGL, negligible GPU cost.
 */
import { computed } from "vue";
import type { UiPhase } from "@/stores/connection";

const props = defineProps<{ phase: UiPhase }>();

const tone = computed(() => {
  switch (props.phase) {
    case "connected":
      return "idle";
    case "initializing":
    case "starting":
      return "thinking";
    default:
      return "error";
  }
});
</script>

<template>
  <div class="glyph" :class="`glyph--${tone}`" aria-hidden="true">
    <div class="ring ring--outer" />
    <div class="ring ring--inner" />
    <div class="core" />
  </div>
</template>

<style scoped>
.glyph {
  --tone: var(--state-idle);
  position: relative;
  width: 44px;
  height: 44px;
  flex: none;
}
.glyph--thinking {
  --tone: var(--state-thinking);
}
.glyph--error {
  --tone: var(--state-error);
}
.ring {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  border: 1.5px solid color-mix(in srgb, var(--tone) 55%, transparent);
  transition: border-color 500ms ease;
}
.ring--outer {
  border-style: dashed;
  animation: spin 24s linear infinite;
}
.ring--inner {
  inset: 7px;
  border-color: color-mix(in srgb, var(--tone) 35%, transparent);
  animation: spin 16s linear infinite reverse;
}
.core {
  position: absolute;
  inset: 14px;
  border-radius: 50%;
  background: radial-gradient(circle at 40% 35%, #fff, var(--tone) 45%, transparent 75%);
  box-shadow: 0 0 18px color-mix(in srgb, var(--tone) 70%, transparent);
  animation: breathe 6s ease-in-out infinite;
  transition: background 500ms ease, box-shadow 500ms ease;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
@keyframes breathe {
  0%,
  100% {
    opacity: 0.85;
    transform: scale(0.94);
  }
  50% {
    opacity: 1;
    transform: scale(1);
  }
}
</style>
