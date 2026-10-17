import { fileURLToPath, URL } from "node:url";
import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vite";

// The Tauri dev window loads http://localhost:1420 (see src-tauri/tauri.conf.json).
export default defineConfig({
  root: "ui",
  plugins: [vue()],
  clearScreen: false,
  resolve: {
    alias: { "@": fileURLToPath(new URL("./ui/src", import.meta.url)) },
  },
  server: {
    port: 1420,
    strictPort: true,
    host: "localhost",
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    target: "safari16",
    sourcemap: false,
  },
});
