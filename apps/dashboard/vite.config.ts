import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const API = process.env.PIDS_API_URL ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    // Same-origin in development: the API and WebSocket are proxied, exactly as
    // nginx does in the container, so no CORS and identical URLs everywhere.
    proxy: {
      "/api": { target: API, changeOrigin: true },
      "/ws": { target: API.replace(/^http/, "ws"), ws: true, changeOrigin: true },
    },
  },
  // MapLibre loads its web worker relative to its own module URL; pre-bundling
  // relocates the module and breaks that URL (GeoJSON layers silently fail).
  optimizeDeps: { exclude: ["maplibre-gl"] },
  build: { sourcemap: true, chunkSizeWarningLimit: 1600 },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["src/test/setup.ts"],
    css: false,
  },
});
