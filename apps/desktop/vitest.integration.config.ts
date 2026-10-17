import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vitest/config";

// Runs the real Python backend (core/.venv) and talks to it with the UI's API client.
export default defineConfig({
  resolve: {
    alias: { "@": fileURLToPath(new URL("./ui/src", import.meta.url)) },
  },
  test: {
    environment: "node",
    include: ["ui/tests/integration/**/*.spec.ts"],
    testTimeout: 30_000,
    hookTimeout: 30_000,
  },
});
