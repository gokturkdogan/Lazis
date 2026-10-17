/**
 * Desktop preferences (window, menu bar, motion). The shell stores them in its desktop state
 * file (no secrets, no conversation data); this store mirrors them and applies the motion
 * preference to the document.
 */
import { defineStore } from "pinia";
import { platformErrorCode, type Preferences } from "@/platform/tauri";
import { currentPlatform } from "@/stores/connection";

const DEFAULTS: Preferences = { closeToMenuBar: true, startHidden: false, reduceMotion: "system" };

export function applyMotion(preferences: Preferences): void {
  if (typeof document === "undefined") return;
  // "system" relies on the global prefers-reduced-motion rule in theme.css.
  document.documentElement.classList.toggle("reduce-motion", preferences.reduceMotion === "on");
}

export const usePreferencesStore = defineStore("preferences", {
  state: () => ({
    values: { ...DEFAULTS } as Preferences,
    loaded: false,
    saving: false,
    errorCode: null as string | null,
  }),

  actions: {
    async load() {
      const platform = currentPlatform();
      if (platform === null) return;
      try {
        this.values = await platform.getPreferences();
        this.loaded = true;
      } catch (error) {
        this.errorCode = platformErrorCode(error);
      }
      applyMotion(this.values);
    },

    async update(change: Partial<Preferences>) {
      const platform = currentPlatform();
      if (platform === null) return;
      const previous = this.values;
      this.values = { ...previous, ...change };
      applyMotion(this.values);
      this.saving = true;
      this.errorCode = null;
      try {
        this.values = await platform.setPreferences(this.values);
      } catch (error) {
        this.values = previous; // not saved: show what is really in effect
        this.errorCode = platformErrorCode(error);
      } finally {
        this.saving = false;
        applyMotion(this.values);
      }
    },
  },
});
