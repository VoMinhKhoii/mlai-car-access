/* Field-only shell cache. Never cache authenticated API responses or the main app. */
const CACHE = 'ngo-ngach-field-v1'
self.addEventListener('install', event => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE)
    const response = await fetch('/field', { cache: 'reload' })
    if (!response.ok) throw new Error('Field build missing')
    await cache.put('/field', response.clone())
    const html = await response.text()
    const assets = [...html.matchAll(/(?:src|href)="(\/assets\/[^"?]+\.(?:js|css))"/g)].map(m => m[1])
    // Follow shared module imports so split React bundles work on an offline reload.
    const seen = new Set()
    async function save(url) {
      if (seen.has(url)) return
      seen.add(url)
      const asset = await fetch(url)
      if (!asset.ok) throw new Error('Asset missing')
      await cache.put(url, asset.clone())
      if (url.endsWith('.js')) {
        const source = await asset.text()
        const imports = [...source.matchAll(/(?:from|import)\s*["'](\.\/[^"']+\.js)["']/g)]
        await Promise.all(imports.map(m => save(new URL(m[1], self.location.origin+url).pathname)))
      }
    }
    await Promise.all(assets.map(save))
    await self.skipWaiting()
  })())
})
self.addEventListener('activate', event => event.waitUntil(self.clients.claim()))
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url)
  if (event.request.method !== 'GET' || url.origin !== self.location.origin) return
  if (url.pathname === '/field' || url.pathname === '/field/') {
    event.respondWith(fetch(event.request).catch(() => caches.match('/field')))
  } else if (url.pathname.startsWith('/assets/')) {
    event.respondWith(caches.match(event.request).then(cached => cached || fetch(event.request)))
  }
})
