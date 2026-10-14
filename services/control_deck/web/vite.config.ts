import { svelte } from '@sveltejs/vite-plugin-svelte'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [svelte()],
  server: {
    host: '127.0.0.1',
    proxy: { '/api': 'http://127.0.0.1:8765' },
  },
  build: { outDir: 'dist', emptyOutDir: true },
})
