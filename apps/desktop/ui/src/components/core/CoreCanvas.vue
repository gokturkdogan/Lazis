<script setup lang="ts">
/**
 * The living core's canvas (Phase 14). Rendering happens outside Vue: one requestAnimationFrame
 * loop reads the core state and the live audio level and draws; nothing re-renders per frame.
 *
 * * Quality adapts: below ~50 fps the pixel ratio drops, then the scene's detail; above ~58 fps
 *   it climbs back (at most three changes, like LAZOS's PerformanceMonitor).
 * * In the background the load drops: no frames while the window is hidden, ~24 fps while it
 *   is visible but not focused.
 * * Reduced motion (macOS setting or LAZIS preference) slows everything and calms the level.
 * * Without WebGL a still CSS glow stands in; the rest of the app is unaffected.
 */
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import type { Quality } from "@/core/scene";
import { useCore } from "@/core/useCore";
import { micLevel, speechLevel } from "@/voice/levels";

const host = ref<HTMLDivElement | null>(null);
const canvas = ref<HTMLCanvasElement | null>(null);
const fallback = ref(false);
const core = useCore();

let raf = 0;
let stop: (() => void) | null = null;

function levelFor(state: string): number {
  if (state === "listening") return micLevel();
  if (state === "speaking") return speechLevel();
  return 0;
}

onMounted(async () => {
  const el = canvas.value;
  const box = host.value;
  if (!el || !box) return;
  let renderer: import("@/core/scene").CoreRenderer;
  try {
    const { CoreRenderer } = await import("@/core/scene");
    renderer = new CoreRenderer(el, { quality: "high", dpr: Math.min(1.5, window.devicePixelRatio || 1), reducedMotion: core.reducedMotion.value });
  } catch {
    fallback.value = true; // no WebGL (or it failed): a still glow, nothing else changes
    return;
  }
  const resize = () => renderer.resize(box.clientWidth, box.clientHeight);
  const observer = new ResizeObserver(resize);
  observer.observe(box);
  resize();
  const onPointer = (e: PointerEvent) => {
    const r = box.getBoundingClientRect();
    renderer.pointer.set(((e.clientX - r.left) / r.width) * 2 - 1, -(((e.clientY - r.top) / r.height) * 2 - 1));
  };
  window.addEventListener("pointermove", onPointer, { passive: true });
  const offMotion = watch(core.reducedMotion, (v) => (renderer.reducedMotion = v));

  // Performance monitor: 2 s windows, at most three changes.
  let frames = 0;
  let windowStart = performance.now();
  let changes = 0;
  let last = performance.now();
  const loop = (now: number) => {
    raf = requestAnimationFrame(loop);
    if (document.hidden) return;
    const minGap = document.hasFocus() ? 0 : 1000 / 24;
    if (now - last < minGap) return;
    const dt = (now - last) / 1000;
    last = now;
    renderer.frame(dt, { state: core.state.value, level: levelFor(core.state.value) });
    frames++;
    if (now - windowStart >= 2000 && document.hasFocus()) {
      const fps = (frames * 1000) / (now - windowStart);
      frames = 0;
      windowStart = now;
      if (changes < 3 && fps < 50) {
        changes++;
        if (renderer.dpr > 1) renderer.setPixelRatio(1);
        else renderer.setQuality("low" as Quality);
        resize();
      } else if (changes < 3 && fps > 58 && renderer.quality === "high" && renderer.dpr < 1.75 && (window.devicePixelRatio || 1) > renderer.dpr) {
        changes++;
        renderer.setPixelRatio(Math.min(1.75, renderer.dpr + 0.25));
        resize();
      }
    } else if (!document.hasFocus()) {
      frames = 0;
      windowStart = now;
    }
  };
  raf = requestAnimationFrame(loop);
  stop = () => {
    cancelAnimationFrame(raf);
    observer.disconnect();
    window.removeEventListener("pointermove", onPointer);
    offMotion();
    renderer.dispose();
  };
});

onBeforeUnmount(() => stop?.());
</script>

<template>
  <div ref="host" class="core" data-testid="core" :data-state="core.state.value" aria-hidden="true">
    <canvas ref="canvas" />
    <div v-if="fallback" class="fallback" data-testid="core-fallback" />
  </div>
</template>

<style scoped>
.core {
  position: absolute;
  inset: 0;
  background: #02050b;
}
canvas {
  display: block;
  width: 100%;
  height: 100%;
}
.fallback {
  position: absolute;
  inset: 0;
  background:
    radial-gradient(circle at 50% 50%, color-mix(in srgb, var(--accent) 70%, white) 0, var(--accent) 4%, transparent 18%),
    radial-gradient(circle at 50% 50%, color-mix(in srgb, var(--accent) 22%, transparent) 0, transparent 45%),
    #02050b;
  transition: background 900ms;
}
</style>
