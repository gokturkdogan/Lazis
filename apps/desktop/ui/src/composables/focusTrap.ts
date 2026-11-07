/**
 * Keyboard handling for modal surfaces (Phase 14.1): focus moves in on open, Tab stays inside,
 * Escape closes, and focus returns to what opened it.
 */
import { nextTick, onBeforeUnmount, type Ref, watch } from "vue";

const FOCUSABLE =
  'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function useFocusTrap(container: Ref<HTMLElement | null>, active: Ref<boolean>, onEscape: () => void): void {
  let returnTo: HTMLElement | null = null;

  const onKey = (event: KeyboardEvent) => {
    const el = container.value;
    if (!active.value || !el) return;
    if (event.key === "Escape") {
      event.preventDefault();
      onEscape();
      return;
    }
    if (event.key !== "Tab") return;
    const items = [...el.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((x) => x.offsetParent !== null || x === document.activeElement);
    if (items.length === 0) {
      event.preventDefault();
      return;
    }
    const first = items[0]!;
    const last = items[items.length - 1]!;
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  watch(
    active,
    async (on) => {
      if (on) {
        returnTo = document.activeElement as HTMLElement | null;
        document.addEventListener("keydown", onKey);
        await nextTick();
        const el = container.value;
        (el?.querySelector<HTMLElement>("[data-autofocus]") ?? el?.querySelector<HTMLElement>(FOCUSABLE) ?? el)?.focus();
      } else {
        document.removeEventListener("keydown", onKey);
        returnTo?.focus?.();
        returnTo = null;
      }
    },
    { immediate: true },
  );

  onBeforeUnmount(() => document.removeEventListener("keydown", onKey));
}
