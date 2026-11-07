/**
 * First setup state (Phase 10D, a modal since Phase 14.1). Where the user is stays in this
 * window's local storage, as before ("lazis.intake.v1": open | paused | done, and the step), so
 * no earlier choice is lost and nothing personal is kept here: answers go to memory only through
 * the explicit "Hafızaya kaydet" buttons.
 *
 * It opens by itself only while not done: "Sonra devam et" closes it for this run of the app
 * (it comes back next time, at the same step); "Bir daha gösterme" and finishing close it for
 * good. Settings can always open it again.
 */
import { defineStore } from "pinia";

export type IntakeStatus = "open" | "paused" | "done";
const KEY = "lazis.intake.v1";
const LATER = "lazis.intake.later";
export const LAST_STEP = 4;

function read(): { status: IntakeStatus; step: number } {
  try {
    const raw = JSON.parse(globalThis.localStorage?.getItem(KEY) ?? "null") as { status?: IntakeStatus; step?: number } | null;
    if (raw?.status && typeof raw.step === "number") return { status: raw.status, step: raw.step };
  } catch {
    // Unreadable: start over; nothing was lost, the answers are saved apart.
  }
  return { status: "open", step: 0 };
}

function laterThisRun(): boolean {
  try {
    return globalThis.sessionStorage?.getItem(LATER) === "1";
  } catch {
    return false;
  }
}

export const useOnboardingStore = defineStore("onboarding", {
  state: () => ({ ...read(), laterRun: laterThisRun() }),

  getters: {
    visible: (s) => s.status === "open" || (s.status === "paused" && !s.laterRun),
    finished: (s) => s.step >= LAST_STEP,
  },

  actions: {
    persist() {
      try {
        globalThis.localStorage?.setItem(KEY, JSON.stringify({ status: this.status, step: this.step }));
      } catch {
        // Not stored: the setup opens again next time. Nothing else depends on it.
      }
    },
    next() {
      this.step = Math.min(LAST_STEP, this.step + 1);
      this.persist();
    },
    /** "Sonra devam et": closed for this run, back next launch at the same step. */
    later() {
      this.status = "paused";
      this.laterRun = true;
      try {
        globalThis.sessionStorage?.setItem(LATER, "1");
      } catch {
        // fine: it only reappears sooner
      }
      this.persist();
    },
    /** "Bir daha gösterme", or the last step's "Tamam". */
    close() {
      this.status = "done";
      this.persist();
    },
    /** Settings → "İlk kurulumu aç". */
    reopen() {
      if (this.step >= LAST_STEP) this.step = 0;
      this.status = "open";
      this.laterRun = false;
      try {
        globalThis.sessionStorage?.removeItem(LATER);
      } catch {
        // nothing to clear
      }
      this.persist();
    },
  },
});
