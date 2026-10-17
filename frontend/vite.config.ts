import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Dev only: the browser talks to Vite, Vite forwards /api to the backend. BACKEND_ORIGIN is read by the dev server,
// never bundled into the app. Production serves frontend/dist from the backend itself (same origin).
const backend = process.env.BACKEND_ORIGIN ?? 'http://127.0.0.1:8787'

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { '/api': backend } },
})
