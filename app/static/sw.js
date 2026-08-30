const CACHE = "subtitle-web-v53";
const STATIC = [
  "/",
  "/static/index.html",
  "/static/styles.css",
  "/static/app.js",
  "/static/manifest.json",
  "/static/icons/icon-reference-192.png",
  "/static/icons/icon-reference-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(STATIC))
  );
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

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  // API requests are not cached.
  if (url.pathname.startsWith("/api/")) return;

  // HTML/CSS/JS use network-first so updates appear quickly.
  if (/\.(html|css|js)$/.test(url.pathname) || url.pathname === "/") {
    event.respondWith(
      fetch(event.request)
        .then((res) => {
          const clone = res.clone();
          caches.open(CACHE).then((c) => c.put(event.request, clone));
          return res;
        })
        .catch(() => caches.match(event.request))
    );
    return;
  }

  // Other static resources use cache-first.
  event.respondWith(
    caches.match(event.request).then((cached) => cached || fetch(event.request))
  );
});
