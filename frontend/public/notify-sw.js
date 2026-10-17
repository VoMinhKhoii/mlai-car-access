// Minimal service worker so parking-watch alerts can be shown as system notifications.
// Android Chrome refuses `new Notification()` from a page; it only allows
// ServiceWorkerRegistration.showNotification(). No caching, no push: the page still does the checks.
self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()))

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  event.waitUntil((async () => {
    const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
    const open = windows.find((client) => 'focus' in client)
    if (open) return open.focus()
    return self.clients.openWindow(self.registration.scope)
  })())
})
