// v2: switched from cache-first to network-first for the app shell.
// The old cache-first strategy could serve stale JS/CSS forever once
// cached, since nothing ever told the browser a newer version existed -
// bumping this version string (and the activate handler below) clears
// out that old cache immediately on this update.
const CACHE = "facetally-shell-v2";
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

// Network-first for the app shell: always try to fetch the latest
// deployed version first, and only fall back to the cached copy if the
// network request fails (e.g. genuinely offline). Every deploy is picked
// up on the next online visit instead of being masked by an old cache.
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (SHELL.some((path) => url.pathname === path)) {
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          const copy = response.clone();
          caches.open(CACHE).then((cache) => cache.put(event.request, copy));
          return response;
        })
        .catch(() => caches.match(event.request))
    );
  }
});
