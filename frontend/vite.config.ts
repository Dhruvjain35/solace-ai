import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  server: {
    port: 5173,
    host: true,
    // Accept any host — we front the dev server through HTTPS tunnels on demo day.
    allowedHosts: true,
    // Same-origin proxy → no CORS + single tunnel covers both frontend and API.
    proxy: {
      "/api": {
        target: "http://localhost:8010",
        changeOrigin: true,
      },
      "/media": {
        target: "http://localhost:8010",
        changeOrigin: true,
      },
    },
  },
});
