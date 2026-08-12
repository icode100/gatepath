const CACHE_PREFIX = "gatepath-pwa-";
const PRECACHE_VERSION = `${CACHE_PREFIX}precache-v1`;
const RUNTIME_STATIC_VERSION = `${CACHE_PREFIX}next-static-v1`;
const CURRENT_CACHES = new Set([PRECACHE_VERSION, RUNTIME_STATIC_VERSION]);
const MAX_RUNTIME_STATIC_ENTRIES = 128;
const OFFLINE_URL = "/offline.html";
const STATIC_ASSETS = [
  OFFLINE_URL,
  "/icon.svg",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
  "/icons/icon-maskable-512.png",
  "/apple-touch-icon.png",
];

const NEVER_INTERCEPT = [
  "/api/",
  "/health",
  "/internal/",
  "/docs",
  "/redoc",
  "/openapi.json",
  "/__/auth/",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(PRECACHE_VERSION).then((cache) => cache.addAll(STATIC_ASSETS)));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key.startsWith(CACHE_PREFIX) && !CURRENT_CACHES.has(key))
            .map((key) => caches.delete(key)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("message", (event) => {
  if (event.data?.type === "SKIP_WAITING") self.skipWaiting();
});

const isPrivateRequest = (request, url) =>
  request.method !== "GET" ||
  url.origin !== self.location.origin ||
  request.cache === "no-store" ||
  request.headers.has("authorization") ||
  request.headers.has("range") ||
  request.headers.has("rsc") ||
  request.headers.has("next-router-prefetch") ||
  url.searchParams.has("_rsc") ||
  NEVER_INTERCEPT.some((prefix) => url.pathname === prefix || url.pathname.startsWith(prefix));

const cacheableStaticResponse = (response) => {
  if (!response.ok || response.redirected || response.type === "opaque") return false;
  const cacheControl = response.headers.get("cache-control") ?? "";
  if (/\b(?:private|no-store)\b/i.test(cacheControl)) return false;
  const contentType = response.headers.get("content-type") ?? "";
  return /javascript|text\/css|font|image\//i.test(contentType);
};

const trimRuntimeStaticCache = async (cache) => {
  const requests = await cache.keys();
  const overflow = requests.length - MAX_RUNTIME_STATIC_ENTRIES;
  if (overflow <= 0) return;
  await Promise.all(requests.slice(0, overflow).map((request) => cache.delete(request)));
};

self.addEventListener("fetch", (event) => {
  const { request } = event;
  const url = new URL(request.url);
  if (isPrivateRequest(request, url)) return;

  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request).catch(async () => {
        const cache = await caches.open(PRECACHE_VERSION);
        return (await cache.match(OFFLINE_URL)) ?? Response.error();
      }),
    );
    return;
  }

  const isNextStatic =
    url.pathname.startsWith("/_next/static/") && url.search === "";
  const isAllowedPublicAsset =
    STATIC_ASSETS.includes(url.pathname) && url.search === "";
  if (!isNextStatic && !isAllowedPublicAsset) return;

  event.respondWith(
    caches
      .open(isNextStatic ? RUNTIME_STATIC_VERSION : PRECACHE_VERSION)
      .then(async (cache) => {
        const cached = await cache.match(request);
        if (cached) return cached;
        const response = await fetch(request);
        if (cacheableStaticResponse(response)) {
          await cache.put(request, response.clone());
          if (isNextStatic) await trimRuntimeStaticCache(cache);
        }
        return response;
      }),
  );
});
