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
    // Same-origin proxy → no CORS. Points at the live prod API by default so a
    // bare `npm run dev` has a working backend (the prod API's CORS is locked to
    // the Amplify origin, so the browser can't call it directly from localhost —
    // but this server-side proxy forwards without a browser Origin, so it works).
    // To develop against a local backend instead, set VITE_DEV_API_TARGET=http://localhost:8010.
    proxy: {
      "/api": {
        target: process.env.VITE_DEV_API_TARGET || "https://djfjrel7b1ebi.cloudfront.net",
        changeOrigin: true,
        secure: true,
      },
      "/media": {
        target: process.env.VITE_DEV_API_TARGET || "https://djfjrel7b1ebi.cloudfront.net",
        changeOrigin: true,
        secure: true,
      },
    },
  },
});
