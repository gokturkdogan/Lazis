import { createI18n } from "vue-i18n";
import { tr } from "./tr";

export function createAppI18n() {
  return createI18n({
    legacy: false,
    locale: "tr",
    fallbackLocale: "tr",
    messages: { tr },
    missingWarn: false,
    fallbackWarn: false,
  });
}

/** i18n key for a backend/shell error code, with a safe fallback. */
export function errorKey(code: string | null | undefined): string {
  const known = code && code in tr.errors ? code : "internal_error";
  return `errors.${known}`;
}
