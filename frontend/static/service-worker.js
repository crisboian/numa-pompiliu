/* NUMA Capture — Service Worker for PWA offline support */
const CACHE_NAME = 'numa-capture-v1';
const PRECACHE_URLS = [
  '/capture',
  '/capture.html',
  '/static/styles.css',
  '/static/app.js',
  '/static/manifest.json',
];

/* Install: precache core files */
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(PRECACHE_URLS);
    })
  );
  self.skipWaiting();
});

/* Activate: clean old caches */
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys
          .filter((key) => key !== CACHE_NAME)
          .map((key) => caches.delete(key))
      );
    })
  );
  self.clients.claim();
});

/* Fetch: network-first for API, cache-first for static */
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  /* API calls: network-only, no cache */
  if (url.pathname.startsWith('/api/')) {
    return;
  }

  /* Static assets: cache-first */
  event.respondWith(
    caches.match(request).then((cached) => {
      return cached || fetch(request).then((response) => {
        /* Cache successful responses for static files */
        if (response.status === 200 && request.method === 'GET') {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => {
            cache.put(request, clone);
          });
        }
        return response;
      });
    })
  );
});
