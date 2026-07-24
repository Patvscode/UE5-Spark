import { defineConfig } from "vite";

const upstream = process.env.ARDY_RIG_LAB_UPSTREAM || "http://127.0.0.1:8777";

export default defineConfig({
  server: {
    host: "127.0.0.1",
    port: 8488,
    strictPort: true,
    proxy: {
      "/v2/poses": {
        target: upstream,
        changeOrigin: false,
      },
      "/api/ardy-health": {
        target: upstream,
        changeOrigin: false,
        rewrite: () => "/healthz",
      },
    },
  },
  preview: {
    host: "127.0.0.1",
    port: 8488,
    strictPort: true,
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
