/** The app's sections, their icons and order (Phase 14.1): shared by the drawer and the page head. */
import type { IconName } from "@/components/Icon.vue";
import type { View } from "@/platform/tauri";

export const NAV_ITEMS: readonly { view: View; icon: IconName }[] = [
  { view: "conversation", icon: "message" },
  { view: "overview", icon: "dashboard" },
  { view: "memory", icon: "brain" },
  { view: "settings", icon: "settings" },
  { view: "diagnostics", icon: "activity" },
];

export function iconFor(view: View): IconName {
  return NAV_ITEMS.find((i) => i.view === view)?.icon ?? "dashboard";
}
