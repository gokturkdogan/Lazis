<script setup lang="ts">
/**
 * The assistant's state as a small CSS mark plus a text label (never colour alone).
 * Not the P14 neural core. Animation runs only while thinking or speaking (idle is still,
 * so an open window costs nothing), uses transform/opacity only, and stops under macOS
 * Reduce Motion or the app's own "reduce motion" preference (`html.reduce-motion`).
 */
import { useI18n } from "vue-i18n";
import type { PresenceState } from "@/stores/presence";

defineProps<{ state: PresenceState; label: string; params?: Record<string, number>; compact?: boolean }>();
const { t } = useI18n();
</script>

<template>
  <div class="presence" :class="`presence--${state}`" data-testid="presence" :data-state="state">
    <div class="glyph" aria-hidden="true">
      <div class="ring ring--outer" />
      <div class="ring ring--inner" />
      <div class="core" />
    </div>
    <span v-if="!compact" class="label" role="status" aria-live="polite" data-testid="presence-label">
      {{ t(`presence.${label}`, params ?? {}) }}
    </span>
  </div>
</template>

<style scoped>
.presence {
  --tone: var(--state-idle);
  display: inline-flex;
  align-items: center;
  gap: 10px;
}
.presence--thinking {
  --tone: var(--state-thinking);
}
.presence--speaking {
  --tone: var(--state-speaking);
}
.presence--listening {
  --tone: var(--state-listening);
}
.presence--error {
  --tone: var(--state-error);
}
.glyph {
  position: relative;
  width: 44px;
  height: 44px;
  flex: none;
}
.ring {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  border: 1.5px solid color-mix(in srgb, var(--tone) 55%, transparent);
  transition: border-color 300ms ease;
}
.ring--outer {
  border-style: dashed;
}
.ring--inner {
  inset: 7px;
  border-color: color-mix(in srgb, var(--tone) 35%, transparent);
}
.core {
  position: absolute;
  inset: 14px;
  border-radius: 50%;
  background: radial-gradient(circle at 40% 35%, #fff, var(--tone) 45%, transparent 75%);
  box-shadow: 0 0 14px color-mix(in srgb, var(--tone) 60%, transparent);
  transition: background 300ms ease, box-shadow 300ms ease;
}
.presence--thinking .ring--outer {
  animation: spin 3s linear infinite;
}
.presence--thinking .ring--inner {
  animation: spin 2.2s linear infinite reverse;
}
.presence--speaking .core {
  animation: pulse 0.9s ease-in-out infinite;
}
.label {
  font-size: 12.5px;
  color: var(--tone);
  white-space: nowrap;
}
:global(html.reduce-motion) .ring,
:global(html.reduce-motion) .core {
  animation: none !important;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
@keyframes pulse {
  0%,
  100% {
    transform: scale(0.88);
    opacity: 0.8;
  }
  50% {
    transform: scale(1.06);
    opacity: 1;
  }
}
</style>
