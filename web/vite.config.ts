import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
  // assetsInlineLimit 0: fonts stay separate files, so the CSP can keep font-src 'self' (no data: URIs).
  build: { outDir: "dist", sourcemap: false, chunkSizeWarningLimit: 600, assetsInlineLimit: 0 },
});
