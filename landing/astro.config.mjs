import { defineConfig } from 'astro/config';
import react from '@astrojs/react';
import sitemap from '@astrojs/sitemap';

// https://astro.build/config
export default defineConfig({
  site: 'https://mysolaceclinic.com',
  output: 'static',
  integrations: [react(), sitemap()],
  build: {
    // Emit dist/about.html rather than dist/about/index.html so Vercel's
    // static handler serves clean URLs without a trailing-slash redirect.
    format: 'file',
  },
  vite: {
    build: {
      cssTarget: 'safari16',
    },
  },
});
