import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  build: { rollupOptions: { input: { main: 'index.html', field: 'field.html' } } },
  server: { port: 5173, proxy: { '/api': 'http://localhost:8787' } },
})
