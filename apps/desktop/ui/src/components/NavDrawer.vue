<script setup lang="ts">
/**
 * Navigation (Phase 14.1): a glass drawer that slides in from the left over a softly blurred
 * app, replacing the always-visible top tabs. Escape or a click outside closes it; focus stays
 * inside while open and returns to the menu button after. Not rendered while closed.
 */
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { EMBLEM } from "@/brand";
import Icon from "@/components/Icon.vue";
import { useFocusTrap } from "@/composables/focusTrap";
import { NAV_ITEMS as ITEMS } from "@/navigation";
import type { View } from "@/platform/tauri";

const props = defineProps<{ open: boolean; current: View }>();
const emit = defineEmits<{ close: []; go: [view: View] }>();
const { t } = useI18n();
const panel = ref<HTMLElement | null>(null);
const active = computed(() => props.open);

useFocusTrap(panel, active, () => emit("close"));

function go(view: View) {
  emit("go", view);
  emit("close");
}
</script>

<template>
  <Transition name="drawer">
    <div v-if="open" class="layer" data-testid="nav-drawer">
      <div class="scrim" data-testid="nav-scrim" @click="emit('close')" />
      <nav id="nav-panel" ref="panel" class="panel-nav glass" :aria-label="t('nav.title')" role="dialog" aria-modal="true">
        <div class="head">
          <span class="hud-label accent-text">{{ t("nav.title") }}</span>
          <button class="icon-btn" type="button" :aria-label="t('nav.close')" data-testid="nav-close" @click="emit('close')">
            <Icon name="x" />
          </button>
        </div>
        <ul>
          <li v-for="item in ITEMS" :key="item.view">
            <button
              type="button"
              class="item"
              :class="{ active: current === item.view }"
              :aria-current="current === item.view ? 'page' : undefined"
              :data-testid="`tab-${item.view}`"
              :data-autofocus="current === item.view ? '' : undefined"
              @click="go(item.view)"
            >
              <span class="glyph"><Icon :name="item.icon" /></span>
              <span>{{ t(`nav.${item.view}`) }}</span>
            </button>
          </li>
        </ul>
        <div class="foot muted">
          <img class="foot-logo" :src="EMBLEM" alt="" aria-hidden="true" width="22" height="22" draggable="false" />
          {{ t("nav.foot") }}
        </div>
      </nav>
    </div>
  </Transition>
</template>

<style scoped>
.layer {
  position: fixed;
  inset: 0;
  z-index: 50;
}
.scrim {
  position: absolute;
  inset: 0;
  background: rgb(2 5 11 / 0.4);
  backdrop-filter: blur(4px);
}
.panel-nav {
  position: absolute;
  top: 0;
  bottom: 0;
  left: 0;
  width: min(300px, 86vw);
  border-radius: 0 18px 18px 0;
  border-left: 0;
  padding: 16px 12px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  outline: none;
}
.panel-nav::after {
  /* a slow sweep of light along the edge as it opens */
  content: "";
  position: absolute;
  top: 0;
  right: -1px;
  width: 1px;
  height: 100%;
  background: linear-gradient(to bottom, transparent, var(--accent), transparent);
  opacity: 0.55;
}
.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 6px 8px;
}
ul {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.item {
  position: relative;
  width: 100%;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-muted);
  font-family: var(--font-display);
  font-size: 13px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  text-align: left;
  transition: background 180ms, color 180ms, border-color 180ms;
}
.item:hover {
  color: var(--text);
  background: rgb(255 255 255 / 0.04);
}
.item.active {
  color: #fff;
  border-color: color-mix(in srgb, var(--accent) 35%, transparent);
  background: linear-gradient(90deg, color-mix(in srgb, var(--accent) 18%, transparent), transparent);
}
.item.active::before {
  /* a small energy mark on the active section */
  content: "";
  position: absolute;
  left: -1px;
  top: 22%;
  bottom: 22%;
  width: 2px;
  border-radius: 2px;
  background: var(--accent);
  box-shadow: 0 0 12px var(--accent);
}
.glyph {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: 8px;
  background: rgb(255 255 255 / 0.03);
  border: 1px solid rgb(255 255 255 / 0.05);
}
.item.active .glyph {
  color: var(--accent);
  border-color: color-mix(in srgb, var(--accent) 35%, transparent);
}
.foot-logo {
  width: 22px;
  height: 22px;
  flex: none;
}
.foot {
  margin-top: auto;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 8px;
  font-size: 11px;
  letter-spacing: 0.2em;
  text-transform: uppercase;
}
.drawer-enter-active,
.drawer-leave-active {
  transition: opacity 260ms ease;
}
.drawer-enter-active .panel-nav,
.drawer-leave-active .panel-nav {
  transition: transform 320ms cubic-bezier(0.2, 0.8, 0.2, 1);
}
.drawer-enter-from,
.drawer-leave-to {
  opacity: 0;
}
.drawer-enter-from .panel-nav,
.drawer-leave-to .panel-nav {
  transform: translateX(-104%);
}
</style>
