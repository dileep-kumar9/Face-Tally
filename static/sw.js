const CACHE = "facetally-shell-v1";
const SHELL = ["/static/style.css", "/static/app.js", "/static/manifest.json"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// Only cache-serve the static shell; every real request (uploads, analysis)
// always hits the network so results are never stale.
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (SHELL.some((path) => url.pathname === path)) {
    event.respondWith(
      caches.match(event.request).then((cached) => cached || fetch(event.request))
    );
  }
});
