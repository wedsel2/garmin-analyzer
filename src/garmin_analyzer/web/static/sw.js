// Service worker, served as /sw.js so that it covers the whole site. It shows a
// page when there is no connection. It keeps only the files listed here: never
// a page with someone's data and never an answer of the API.

const CACHE = "offline-v1";
const OFFLINE = "/offline";
const KEPT = [OFFLINE, "/static/app.css", "/static/icon.svg"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(KEPT)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((names) =>
        Promise.all(names.filter((name) => name !== CACHE).map((name) => caches.delete(name))),
      )
      .then(() => self.clients.claim()),
  );
});

// The network first, so a new release shows at once; the kept copy only when
// the network fails.
async function fresh(request) {
  const cache = await caches.open(CACHE);
  try {
    const response = await fetch(request);
    if (response.ok) await cache.put(request, response.clone());
    return response;
  } catch (error) {
    const kept = await cache.match(request, { ignoreSearch: true, ignoreVary: true });
    if (kept) return kept;
    throw error;
  }
}

async function pageOrOffline(request) {
  try {
    return await fetch(request);
  } catch (error) {
    const kept = await caches.match(OFFLINE, { ignoreVary: true });
    if (kept) return kept;
    throw error;
  }
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin) return;
  if (KEPT.includes(url.pathname)) {
    event.respondWith(fresh(request));
  } else if (request.mode === "navigate") {
    event.respondWith(pageOrOffline(request));
  }
});
