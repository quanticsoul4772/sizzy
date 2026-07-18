import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

// The sidecar address is injected at build/dev time from DEVHARNESS_SIDECAR_ADDR
// (default http://localhost:8080) as the compile-time constant __SIDECAR_ADDR__.
export default defineConfig({
  plugins: [svelte()],
  define: {
    __SIDECAR_ADDR__: JSON.stringify(
      process.env.DEVHARNESS_SIDECAR_ADDR || 'http://localhost:8080'
    ),
  },
});
