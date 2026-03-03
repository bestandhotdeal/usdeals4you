self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    // clear caches
    const keys = await caches.keys();
    await Promise.all(keys.map(k => caches.delete(k)));
    // unregister this service worker
    await self.registration.unregister();
    // refresh open tabs
    const clients = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const c of clients) {
      try { c.navigate(c.url); } catch (e) {}
    }
  })());
});
