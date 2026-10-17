import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { errorKey } from "@/i18n";
import { tr } from "@/i18n/tr";

// Tests run from apps/desktop (happy-dom rewrites import.meta.url, so use the cwd).
const BACKEND_I18N = resolve(process.cwd(), "../../core/src/lazis/i18n.py");

describe("translations", () => {
  it("cover every backend error code", () => {
    const source = readFileSync(BACKEND_I18N, "utf8");
    const codes = [...source.matchAll(/^\s{4}"([a-z_]+)":/gm)].map((m) => m[1]);
    expect(codes.length).toBeGreaterThan(10);
    for (const code of codes) {
      expect(tr.errors, `missing UI translation for ${code}`).toHaveProperty(code as string);
    }
  });

  it("falls back to the generic error for unknown codes", () => {
    expect(errorKey("something_new")).toBe("errors.internal_error");
    expect(errorKey(null)).toBe("errors.internal_error");
    expect(errorKey("unauthorized")).toBe("errors.unauthorized");
  });
});
