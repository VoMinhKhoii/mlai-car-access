import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Dev only: the browser talks to Vite, Vite forwards /api to the backend. BACKEND_ORIGIN is read by the dev server,
// never bundled into the app. Production serves frontend/dist from the backend itself (same origin).
const backend = process.env.BACKEND_ORIGIN ?? 'http://127.0.0.1:8787'
// The backend accepts browser writes only from its own origin, so the dev proxy presents the request as same-origin
// (needed when the dev server is opened through a tunnel or a non-default port).
const toBackend = {
  target: backend, changeOrigin: true,
  configure: (proxy: { on: (e: 'proxyReq', cb: (req: { getHeader: (n: string) => unknown; setHeader: (n: string, v: string) => void; removeHeader: (n: string) => void }) => void) => void }) =>
    proxy.on('proxyReq', (req) => {
      if (req.getHeader('origin')) req.setHeader('origin', backend)
      // A tunnel's x-forwarded-proto: https would make the backend see itself as https and reject the http origin.
      req.removeHeader('x-forwarded-proto')
    }),
}

export default defineConfig({
  plugins: [react(), {
    // `/welcome` serves the landing page entry (welcome.html) in dev and preview.
    name: 'welcome-route',
    configureServer(server) { server.middlewares.use((req, _res, next) => { if (req.url === '/welcome' || req.url?.startsWith('/welcome?')) req.url = req.url.replace('/welcome', '/welcome.html'); next() }) },
    configurePreviewServer(server) { server.middlewares.use((req, _res, next) => { if (req.url === '/welcome' || req.url?.startsWith('/welcome?')) req.url = req.url.replace('/welcome', '/welcome.html'); next() }) },
  }],
  build: { rollupOptions: { input: { main: "index.html", field: "field.html", welcome: "welcome.html" } } },
  server: { port: 5173, proxy: { '/api': toBackend, '/mcp': toBackend }, allowedHosts: ['.trycloudflare.com'] },
})
