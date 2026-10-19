/* Strongman Coach – Service Worker
 *
 * Caches the app shell (HTML, JS, CSS, manifest, icons) on install.
 * Uses cache-first for app shell, network-first for API calls.
 * Stale-while-revalidate for exercise library and settings.
 */

const CACHE_NAME = 'strongman-coach-v1';
const APP_SHELL = [
  '/log.html',
  '/static/log.js',
  '/static/manifest.json',
];

/* ------------------------------------------------------------------ */
/* Install: cache the app shell                                       */
/* ------------------------------------------------------------------ */
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(APP_SHELL))
      .then(() => self.skipWaiting()),
  );
});

/* ------------------------------------------------------------------ */
/* Activate: clean old caches                                         */
/* ------------------------------------------------------------------ */
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)),
      ),
    ).then(() => self.clients.claim()),
  );
});

/* ------------------------------------------------------------------ */
/* Fetch: strategy per request type                                   */
/* ------------------------------------------------------------------ */
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  /* API calls – network-first, fall back to cached response */
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(networkFirst(event.request));
    return;
  }

  /* Exercise library / settings – stale-while-revalidate */
  if (url.pathname.startsWith('/api/exercises') ||
      url.pathname.startsWith('/api/settings')) {
    event.respondWith(staleWhileRevalidate(event.request));
    return;
  }

  /* Everything else – cache-first (app shell) */
  event.respondWith(cacheFirst(event.request));
});

/* ------------------------------------------------------------------ */
/* Strategies                                                         */
/* ------------------------------------------------------------------ */

function cacheFirst(request) {
  return caches.match(request).then((cached) => {
    if (cached) return cached;
    return fetch(request).then((response) => {
      if (!response || response.status !== 200) return response;
      const clone = response.clone();
      caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
      return response;
    });
  });
}

function networkFirst(request) {
  return fetch(request)
    .then((response) => {
      if (response && response.status === 200) {
        const clone = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
      }
      return response;
    })
    .catch(() => caches.match(request));
}

function staleWhileRevalidate(request) {
  return caches.open(CACHE_NAME).then((cache) =>
    cache.match(request).then((cached) => {
      const fetchPromise = fetch(request).then((response) => {
        if (response && response.status === 200) {
          cache.put(request, response.clone());
        }
        return response;
      }).catch(() => cached);
      return cached || fetchPromise;
    }),
  );
}

/* ------------------------------------------------------------------ */
/* Background sync: flush IndexedDB queue when back online            */
/* ------------------------------------------------------------------ */
self.addEventListener('sync', (event) => {
  if (event.tag === 'sync-sets') {
    event.waitUntil(syncQueuedSets());
  }
});

async function syncQueuedSets() {
  /* This runs in the service worker context – we can't access IndexedDB
     directly from here in all browsers. Instead, we notify the page. */
  const clients = await self.clients.matchAll({ type: 'window' });
  clients.forEach((client) => {
    client.postMessage({ type: 'SYNC_QUEUE' });
  });
}
