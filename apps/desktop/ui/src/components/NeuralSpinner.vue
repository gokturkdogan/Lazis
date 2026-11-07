<script setup lang="ts">
/**
 * A small waiting mark in the core's language (Phase 14 polish): a hub and six nodes; pulses
 * of light travel out along the connections one after another and the nodes answer as they
 * arrive. SVG + CSS only, no library. Shown only while something real is being waited for;
 * under reduced motion it is still (the global rule stops the animations).
 */
withDefaults(defineProps<{ size?: number; label?: string }>(), { size: 44, label: "" });

const R = 34;
const nodes = Array.from({ length: 6 }, (_, k) => {
  const a = (Math.PI / 3) * k - Math.PI / 2;
  return { x: 50 + R * Math.cos(a), y: 50 + R * Math.sin(a), delay: `${(k * 0.27).toFixed(2)}s` };
});
</script>

<template>
  <svg
    class="neural"
    :width="size"
    :height="size"
    viewBox="0 0 100 100"
    :role="label ? 'img' : undefined"
    :aria-label="label || undefined"
    :aria-hidden="label ? undefined : 'true'"
    data-testid="neural-spinner"
  >
    <circle class="halo" cx="50" cy="50" r="46" />
    <g class="rim">
      <line v-for="(n, k) in nodes" :key="`r${k}`" :x1="n.x" :y1="n.y" :x2="nodes[(k + 1) % 6]!.x" :y2="nodes[(k + 1) % 6]!.y" />
    </g>
    <g class="spokes">
      <line v-for="(n, k) in nodes" :key="`s${k}`" x1="50" y1="50" :x2="n.x" :y2="n.y" />
    </g>
    <g class="pulses">
      <line v-for="(n, k) in nodes" :key="`p${k}`" x1="50" y1="50" :x2="n.x" :y2="n.y" pathLength="1" :style="{ animationDelay: n.delay }" />
    </g>
    <circle v-for="(n, k) in nodes" :key="`n${k}`" class="node" :cx="n.x" :cy="n.y" r="3.4" :style="{ animationDelay: n.delay }" />
    <circle class="hub" cx="50" cy="50" r="6" />
  </svg>
</template>

<style scoped>
.neural {
  --c: var(--brand-cyan, #3fd8ff);
  overflow: visible;
  flex: none;
}
.halo {
  fill: none;
  stroke: color-mix(in srgb, var(--c) 14%, transparent);
  stroke-width: 1;
}
.rim line {
  stroke: color-mix(in srgb, var(--c) 22%, transparent);
  stroke-width: 1;
}
.spokes line {
  stroke: color-mix(in srgb, var(--c) 30%, transparent);
  stroke-width: 1.2;
}
.pulses line {
  stroke: var(--c);
  stroke-width: 2.4;
  stroke-linecap: round;
  stroke-dasharray: 0.22 1;
  stroke-dashoffset: 0.22;
  filter: drop-shadow(0 0 3px var(--c));
  animation: travel 1.62s cubic-bezier(0.45, 0, 0.3, 1) infinite;
}
.node {
  fill: color-mix(in srgb, var(--c) 55%, #02101c);
  transform-box: fill-box;
  transform-origin: center;
  animation: answer 1.62s ease-out infinite;
}
.hub {
  fill: var(--c);
  filter: drop-shadow(0 0 6px var(--c));
  transform-box: fill-box;
  transform-origin: center;
  animation: breathe 3.2s ease-in-out infinite;
}
@keyframes travel {
  0% {
    stroke-dashoffset: 0.22;
    opacity: 0;
  }
  12% {
    opacity: 1;
  }
  70%,
  100% {
    stroke-dashoffset: -1;
    opacity: 0;
  }
}
@keyframes answer {
  0%,
  45% {
    fill: color-mix(in srgb, var(--c) 45%, #02101c);
    transform: scale(1);
  }
  58% {
    fill: var(--c);
    transform: scale(1.35);
  }
  100% {
    fill: color-mix(in srgb, var(--c) 45%, #02101c);
    transform: scale(1);
  }
}
@keyframes breathe {
  0%,
  100% {
    transform: scale(0.92);
    opacity: 0.85;
  }
  50% {
    transform: scale(1.08);
    opacity: 1;
  }
}
</style>
