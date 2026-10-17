import { fileURLToPath, URL } from "node:url";
import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./ui/src", import.meta.url)) },
  },
  test: {
    environment: "happy-dom",
    include: ["ui/tests/unit/**/*.spec.ts"],
    restoreMocks: true,
  },
});
