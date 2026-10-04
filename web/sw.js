/*
 * sw.js - Lets the installed app open without network (metro, holidays).
 *
 * Network first, always: when online the site is exactly what was last
 * published (a push is visible at the next opening); the copy kept here is
 * only used when the network fails. tools/build_site.py stamps BUILD, so each
 * publication installs a fresh worker.
 */

const BUILD = "__BUILD__";
const CACHE = "revisions";
const CORE = [
  "./", "index.html", "style.css", "app.js", "engine.js", "answers.js", "store.js",
  "exercises.json", "manifest.webmanifest", "icons/icon.svg", "icons/icon-192.png",
];

// Cache key without the "?v=..." the build adds to the file names.
const keyOf = (url) => {
  const u = new URL(url, self.location.href);
  return u.origin + u.pathname;
};

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    await Promise.all(CORE.map(async (path) => {
      try {
        const response = await fetch(path, { cache: "no-cache" });
        if (response.ok) await cache.put(keyOf(path), response);
      } catch { /* offline during install: the next visit fills the cache */ }
    }));
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET" || new URL(request.url).origin !== self.location.origin) return;
  event.respondWith((async () => {
    const key = keyOf(request.url);
    try {
      // A page load must not receive a followed redirect: let the browser follow it.
      const response = await fetch(request.url, {
        cache: "no-cache", credentials: "same-origin",
        redirect: request.mode === "navigate" ? "manual" : "follow",
      });
      if (response.ok) {
        const copy = response.clone();
        caches.open(CACHE).then((cache) => cache.put(key, copy)).catch(() => {});
      }
      return response;
    } catch (error) {
      const cached = (await caches.match(key))
        ?? (request.mode === "navigate" ? await caches.match(keyOf("./")) : undefined);
      if (cached) return cached;
      throw error;
    }
  })());
});

console.debug(`Révisions ${BUILD}`);
